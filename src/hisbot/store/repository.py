"""仓储层（文档 4.8.1）：统一数据访问，封装加密、脱敏、审计、事务。

业务代码不直接写业务表 SQL；所有敏感列在写入前由本层加密并生成脱敏列。
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from ..core.util import now_iso
from .crypto import CryptoService
from .database import Database
from .masking import mask_value


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:16]}"


class Repository:
    def __init__(self, db: Database, crypto: CryptoService | None = None):
        self.db = db
        self.crypto = crypto

    # ------------------------------------------------------------------ #
    # 敏感列处理（文档 4.8.1 encrypt_row / 4.8.2）
    # ------------------------------------------------------------------ #
    @staticmethod
    def _columns_for(table: str) -> set[str]:
        cur = Repository._col_cache.get(table)
        return cur or set()  # populated lazily

    _col_cache: dict[str, set[str]] = {}

    def _table_columns(self, table: str) -> set[str]:
        if table not in self._col_cache:
            rows = self.db.execute(f"PRAGMA table_info({table})").fetchall()
            self._col_cache[table] = {r["name"] for r in rows}
        return self._col_cache[table]

    def encrypt_row(self, table: str, row: dict,
                    sensitive_specs: list[dict]) -> dict:
        """逻辑敏感字段 -> 物理 _enc/_mask/_hmac 列。

        逻辑名 target 与物理列命名约定：patient_name -> patient_name_enc、
        patient_name_mask；id_card -> id_card_enc、id_card_hmac。
        """
        out = dict(row)
        if not self.crypto:
            return out
        cols = self._table_columns(table)
        for spec in sensitive_specs:
            name = spec["target"]
            if name not in out:
                continue
            value = out.pop(name)
            if value is None or value == "":
                continue
            if spec.get("encrypt"):
                enc_col = f"{name}_enc"
                if enc_col in cols:
                    out[enc_col] = self.crypto.encrypt(str(value))
            rule = spec.get("mask_rule")
            if rule:
                mask_col = f"{name}_mask"
                if mask_col in cols:
                    out[mask_col] = mask_value(value, rule)
            if spec.get("index_mode") == "hmac":
                hmac_col = f"{name}_hmac"
                if hmac_col in cols:
                    out[hmac_col] = self.crypto.hmac_index(str(value))
        return out

    # ------------------------------------------------------------------ #
    # 幂等批量写入（文档 4.8.1 / 2.3.8）
    # ------------------------------------------------------------------ #
    def upsert_batch(self, table: str, rows: list[dict],
                     key_cols: list[str], *, batch_size: int = 1000,
                     sensitive_specs: list[dict] | None = None
                     ) -> dict:
        """按 key_cols 做 INSERT ... ON CONFLICT DO UPDATE，幂等。

        返回 {total, inserted, updated, failed, errors}。单批失败回滚该批。
        """
        sensitive_specs = sensitive_specs or []
        result: dict[str, Any] = {"total": len(rows), "inserted": 0, "updated": 0,
                  "failed": 0, "errors": []}
        if not rows:
            return result
        cols = self._table_columns(table)
        # 物理列：先加密再过滤掉表中不存在的键
        phys: list[dict] = []
        for logical in rows:
            pr = self.encrypt_row(table, logical, sensitive_specs)
            pr = {k: v for k, v in pr.items() if k in cols}
            phys.append(pr)
        # 保证所有行键齐全
        for i in range(0, len(phys), batch_size):
            batch = phys[i:i + batch_size]
            try:
                inserted, updated, errs = self._upsert_one_batch(
                    table, batch, key_cols)
                result["inserted"] += inserted
                result["updated"] += updated
                result["errors"].extend(errs)
                result["failed"] += len(errs)
                self.db.commit()
            except Exception as e:
                self.db.conn.rollback()
                result["failed"] += len(batch)
                result["errors"].append(f"批次回滚: {e}")
        return result

    def _upsert_one_batch(self, table, batch, key_cols):
        inserted = updated = 0
        errors = []
        # 预快照业务键，用于区分 insert / update（单文件事务，无并发写）
        existing = self._existing_keys(table, key_cols, batch)
        # 所有出现列的并集（以第一行为准并补齐），统一列集
        all_cols = set()
        for r in batch:
            all_cols.update(r.keys())
        all_cols |= set(key_cols)
        ordered = sorted(all_cols)
        col_list = ", ".join(ordered)
        ph = ", ".join("?" for _ in ordered)
        update_cols = [c for c in ordered if c not in key_cols
                       and c != "created_at"]
        set_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)
        conflict = ", ".join(key_cols)
        sql = (f"INSERT INTO {table} ({col_list}) VALUES ({ph}) "
               f"ON CONFLICT({conflict}) DO UPDATE SET {set_clause}")
        for r in batch:
            key = tuple(str(r.get(k)) for k in key_cols)
            is_insert = key not in existing
            try:
                self.db.execute(sql, tuple(r.get(c) for c in ordered))
                if is_insert:
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                errors.append(f"{dict(zip(key_cols, key, strict=False))}: {e}")
        return inserted, updated, errors

    def _existing_keys(self, table, key_cols, batch):
        keys = set()
        # 分批 IN 查询，避免 SQL 过长
        rows_of_keys = [tuple(r.get(k) for k in key_cols) for r in batch]
        if len(key_cols) == 1:
            vals = [k[0] for k in rows_of_keys]
            for i in range(0, len(vals), 500):
                chunk = vals[i:i + 500]
                qm = ",".join("?" for _ in chunk)
                cur = self.db.execute(
                    f"SELECT {key_cols[0]} k FROM {table} "
                    f"WHERE {key_cols[0]} IN ({qm})", chunk)
                keys |= {(str(r["k"]),) for r in cur}
        else:
            # 复合键：直接全量相关扫描（批量通常单文件，量可控）
            cur = self.db.execute(
                f"SELECT {', '.join(key_cols)} FROM {table}")
            keys = {tuple(str(r[k]) for k in key_cols) for r in cur}
        return keys

    # ------------------------------------------------------------------ #
    # 导入批次
    # ------------------------------------------------------------------ #
    def start_batch(self, file_id: str, target_table: str) -> str:
        bid = new_id("bat_")
        self.db.execute(
            "INSERT INTO t_import_batch(batch_id,file_id,target_table,"
            "started_at,status) VALUES(?,?,?,?, 'running')",
            (bid, file_id, target_table, now_iso()))
        self.db.commit()
        return bid

    def finish_batch(self, batch_id: str, total: int, inserted: int,
                     updated: int, failed: int, status: str = "success"):
        self.db.execute(
            "UPDATE t_import_batch SET finished_at=?, total_rows=?, "
            "inserted_rows=?, updated_rows=?, failed_rows=?, status=? "
            "WHERE batch_id=?",
            (now_iso(), total, inserted, updated, failed, status, batch_id))
        self.db.commit()

    # ------------------------------------------------------------------ #
    # 导出文件 / 解析报告（血缘）
    # ------------------------------------------------------------------ #
    def register_export_file(self, info: dict) -> str:
        fid = info.get("file_id") or new_id("file_")
        self.db.execute(
            "INSERT INTO t_export_file(file_id,job_run_id,origin_name,"
            "archived_path,file_ext,file_size,sha256,download_started_at,"
            "download_finished_at,signal_prompt,signal_stable,parse_status,"
            "created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (fid, info.get("job_run_id"), info.get("origin_name"),
             info.get("archived_path"), info.get("file_ext"),
             info.get("file_size"), info.get("sha256"),
             info.get("download_started_at"), info.get("download_finished_at"),
             int(info.get("signal_prompt", 0)),
             int(info.get("signal_stable", 0)),
             info.get("parse_status", "pending"), now_iso()))
        self.db.commit()
        return fid

    def update_export_file(self, file_id: str, **fields):
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(
            f"UPDATE t_export_file SET {cols} WHERE file_id=?",
            (*fields.values(), file_id))
        self.db.commit()

    def get_export_file(self, file_id: str):
        return self.db.execute(
            "SELECT * FROM t_export_file WHERE file_id=?",
            (file_id,)).fetchone()

    def add_parse_report(self, file_id: str, parser: str, header_row: int,
                         column_count: int, total: int, ok: int, fail: int,
                         fail_detail: str, confidence: float = 1.0):
        self.db.execute(
            "INSERT INTO t_parse_report(file_id,parser,header_row,column_count,"
            "total_rows,ok_rows,fail_rows,fail_detail,confidence,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (file_id, parser, header_row, column_count, total, ok, fail,
             fail_detail, confidence, now_iso()))
        self.db.commit()

    # ------------------------------------------------------------------ #
    # 作业 / 运行 / 步骤
    # ------------------------------------------------------------------ #
    def upsert_job(self, job: dict):
        now = now_iso()
        self.db.execute(
            "INSERT INTO t_job(job_id,job_name,site_id,graph_version,"
            "entry_page_id,target_page_id,path_element_ids,export_keywords,"
            "download_expect,schedule_cron,status,reviewed_by,reviewed_at,"
            "config_version,config_hash,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(job_id) DO UPDATE SET job_name=excluded.job_name,"
            "graph_version=excluded.graph_version,target_page_id=excluded."
            "target_page_id,path_element_ids=excluded.path_element_ids,"
            "export_keywords=excluded.export_keywords,download_expect=excluded"
            ".download_expect,schedule_cron=excluded.schedule_cron,status="
            "excluded.status,reviewed_by=excluded.reviewed_by,reviewed_at="
            "excluded.reviewed_at,config_version=excluded.config_version,"
            "config_hash=excluded.config_hash,updated_at=excluded.updated_at",
            (job["job_id"], job.get("job_name"), job.get("site_id"),
             job.get("graph_version"), job.get("entry_page_id"),
             job.get("target_page_id"),
             json.dumps(job.get("path_element_ids", []), ensure_ascii=False),
             json.dumps(job.get("export_keywords", []), ensure_ascii=False),
             int(job.get("download_expect", 1)), job.get("schedule_cron"),
             job.get("status", "draft"), job.get("reviewed_by"),
             job.get("reviewed_at"), int(job.get("config_version", 1)),
             job.get("config_hash"), now, now))
        self.db.commit()

    def start_run(self, job_id: str, total_steps: int, operator: str = ""
                  ) -> str:
        rid = new_id("run_")
        self.db.execute(
            "INSERT INTO t_job_run(run_id,job_id,started_at,status,"
            "current_state,current_step,total_steps,operator) "
            "VALUES(?,?,?, 'running','INIT',0,?,?)",
            (rid, job_id, now_iso(), total_steps, operator))
        self.db.commit()
        return rid

    def update_run(self, run_id: str, **fields):
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE t_job_run SET {cols} WHERE run_id=?",
                        (*fields.values(), run_id))
        self.db.commit()

    def finish_run(self, run_id: str, status: str, state: str,
                   files: int = 0, rows: int = 0, error_code: str | None = None):
        self.db.execute(
            "UPDATE t_job_run SET finished_at=?, status=?, current_state=?, "
            "files_downloaded=?, rows_imported=?, error_code=? WHERE run_id=?",
            (now_iso(), status, state, files, rows, error_code, run_id))
        self.db.commit()

    def add_step(self, run_id: str, seq: int, state: str, action: str,
                 target_desc: str, result: str, duration_ms: int,
                 page_id: str = "", snapshot: str = "",
                 resumed_from: int = 0):
        self.db.execute(
            "INSERT INTO t_job_step(run_id,seq,state,page_id,action,"
            "target_desc,result,duration_ms,snapshot,resumed_from) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (run_id, seq, state, page_id, action, target_desc, result,
             duration_ms, snapshot, resumed_from))
        self.db.commit()

    def last_finished_step_seq(self, run_id: str) -> int:
        row = self.db.execute(
            "SELECT COALESCE(MAX(seq),0) s FROM t_job_step "
            "WHERE run_id=? AND result='success'", (run_id,)).fetchone()
        return row["s"]

    # ------------------------------------------------------------------ #
    # 运行日志 / 告警 / 审计
    # ------------------------------------------------------------------ #
    def add_log(self, rec: dict):
        self.db.execute(
            "INSERT INTO t_operation_log(job_run_id,ts,level,state,page_id,"
            "action,target_desc,coords,result,duration_ms,snapshot_path,"
            "error_code) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (rec.get("job_run_id"), rec.get("ts", now_iso()),
             rec.get("level", "INFO"), rec.get("state"), rec.get("page_id"),
             rec.get("action"), rec.get("target_desc"), rec.get("coords"),
             rec.get("result"), rec.get("duration_ms"),
             rec.get("snapshot_path"), rec.get("error_code")))
        self.db.commit()

    def query_logs(self, *, job_run_id: str | None = None,
                   level: str | None = None, limit: int = 500):
        sql = "SELECT * FROM t_operation_log WHERE 1=1"
        params: list[Any] = []
        if job_run_id:
            sql += " AND job_run_id=?"
            params.append(job_run_id)
        if level:
            sql += " AND level=?"
            params.append(level)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.db.execute(sql, params).fetchall()]

    def add_alert(self, rec: dict) -> int:
        cur = self.db.execute(
            "INSERT INTO t_alert(job_run_id,ts,severity,error_code,message,"
            "snapshot) VALUES(?,?,?,?,?,?)",
            (rec.get("job_run_id"), rec.get("ts", now_iso()),
             rec.get("severity", "ERROR"), rec.get("error_code"),
             rec.get("message"), rec.get("snapshot")))
        self.db.commit()
        return int(cur.lastrowid)

    def query_alerts(self, limit: int = 200, acknowledged: int | None = None):
        sql = "SELECT * FROM t_alert"
        params: list[Any] = []
        if acknowledged is not None:
            sql += " WHERE acknowledged=?"
            params.append(acknowledged)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self.db.execute(sql, params).fetchall()]

    def audit(self, actor: str, event_type: str, *, object_type: str = "",
              object_id: str = "", detail: str = "", result: str = "success"):
        self.db.execute(
            "INSERT INTO t_audit_event(ts,actor,event_type,object_type,"
            "object_id,detail,result) VALUES(?,?,?,?,?,?,?)",
            (now_iso(), actor, event_type, object_type, object_id, detail,
             result))
        self.db.commit()

    def query_audit(self, limit: int = 200):
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM t_audit_event ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()]

    # ------------------------------------------------------------------ #
    # 业务数据查询（默认脱敏列；解密需额外授权，文档 4.8.1 / 7.4）
    # ------------------------------------------------------------------ #
    def query_records(self, table: str = "t_report_record", limit: int = 200,
                      decrypt: bool = False) -> list[dict]:
        rows = [dict(r) for r in self.db.execute(
            f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()]
        if decrypt and self.crypto:
            for r in rows:
                if r.get("patient_name_enc"):
                    r["patient_name"] = self.crypto.decrypt(
                        r["patient_name_enc"])
                if r.get("phone_enc"):
                    r["phone"] = self.crypto.decrypt(r["phone_enc"])
                if r.get("id_card_enc"):
                    r["id_card"] = self.crypto.decrypt(r["id_card_enc"])
        return rows

    def count(self, table: str) -> int:
        return int(self.db.execute(f"SELECT COUNT(*) c FROM {table}")
                   .fetchone()["c"])
