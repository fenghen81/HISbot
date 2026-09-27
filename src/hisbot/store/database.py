"""SQLite 连接管理与 schema 初始化/迁移（文档 4.8 / 第 5 章）。"""
from __future__ import annotations

import logging

_log = logging.getLogger("hisbot")

import os
import sqlite3
from pathlib import Path

from ..core.util import now_iso
from .schema_sql import SCHEMA_SQL, SCHEMA_VERSION


class Database:
    def __init__(self, path: str | Path, *, timeout: float = 30.0):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=timeout,
                                    check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 30000")
        self._lock_file_perms()

    def _lock_file_perms(self) -> None:
        """数据库文件权限仅当前用户可读写（Linux 600，文档 4.8.3）。"""
        try:
            for suffix in ("", "-wal", "-shm"):
                p = Path(str(self.path) + suffix)
                if p.exists():
                    os.chmod(p, 0o600)
        except Exception:
            _log.warning("忽略异常 @%s", __name__, exc_info=True)

    def init_schema(self) -> int:
        self.conn.executescript(SCHEMA_SQL)
        row = self.conn.execute(
            "SELECT version FROM t_schema_version WHERE version=?",
            (SCHEMA_VERSION,)).fetchone()
        if not row:
            self.conn.execute(
                "INSERT INTO t_schema_version(version, applied_at, "
                "description) VALUES (?,?,?)",
                (SCHEMA_VERSION, now_iso(), "初始化建表（附录 A）"))
            self.conn.commit()
        self._lock_file_perms()
        return SCHEMA_VERSION

    def current_version(self) -> int | None:
        try:
            row = self.conn.execute(
                "SELECT MAX(version) v FROM t_schema_version").fetchone()
        except sqlite3.OperationalError:
            return None            # 全新库，尚未建表
        return row["v"] if row and row["v"] is not None else None

    def execute(self, sql: str, params=()):
        return self.conn.execute(sql, params)

    def commit(self):
        self.conn.commit()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            _log.warning("忽略异常 @%s", __name__, exc_info=True)
