"""SQLite 建表脚本（文档附录 A，权威单源）。

敏感列以 _enc 结尾存密文，以 _mask 结尾存脱敏值；
身份证等精确检索字段额外维护 _hmac 列。
"""
from __future__ import annotations

SCHEMA_VERSION = 1

SCHEMA_SQL = """
-- ============================================================
-- HIS 离线数据采集工具  数据库建表脚本
-- 目标：SQLite 3.35+（支持 ON CONFLICT 与 RETURNING）
-- ============================================================
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;
PRAGMA foreign_keys = ON;

-- ---------------- 元 ----------------
CREATE TABLE IF NOT EXISTS t_schema_version (
    version      INTEGER PRIMARY KEY,
    applied_at   TEXT NOT NULL,
    description  TEXT
);

CREATE TABLE IF NOT EXISTS t_template (
    template_id   TEXT PRIMARY KEY,
    site_id       TEXT NOT NULL,
    page_id       TEXT,
    element_name  TEXT,
    image_path    TEXT NOT NULL,
    scale_ratio   REAL NOT NULL DEFAULT 1.0,
    ref_width     INTEGER,
    ref_height    INTEGER,
    hit_count     INTEGER NOT NULL DEFAULT 0,
    miss_count    INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'active',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_template_site ON t_template(site_id, status);

-- ---------------- 导航图 ----------------
CREATE TABLE IF NOT EXISTS t_nav_page (
    page_id      TEXT PRIMARY KEY,
    graph_version TEXT NOT NULL,
    title        TEXT,
    fingerprint  TEXT NOT NULL,
    anchor_url   TEXT,
    snapshot     TEXT,
    depth        INTEGER NOT NULL DEFAULT 0,
    scanned_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_navpage_graph ON t_nav_page(graph_version);

CREATE TABLE IF NOT EXISTS t_nav_element (
    element_id   TEXT PRIMARY KEY,
    page_id      TEXT NOT NULL REFERENCES t_nav_page(page_id) ON DELETE CASCADE,
    text         TEXT,
    kind         TEXT,
    rel_x        REAL NOT NULL,
    rel_y        REAL NOT NULL,
    rel_w        REAL NOT NULL,
    rel_h        REAL NOT NULL,
    confidence   REAL,
    risk         TEXT NOT NULL DEFAULT 'safe',
    template_id  TEXT,
    fingerprint  TEXT,
    is_export_target INTEGER NOT NULL DEFAULT 0,
    keywords     TEXT
);
CREATE INDEX IF NOT EXISTS idx_navelem_page ON t_nav_element(page_id);

CREATE TABLE IF NOT EXISTS t_nav_edge (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    graph_version TEXT NOT NULL,
    from_page    TEXT NOT NULL,
    to_page      TEXT NOT NULL,
    via_element  TEXT NOT NULL,
    hits         INTEGER NOT NULL DEFAULT 1,
    approved     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_navedge_from ON t_nav_edge(from_page, to_page);

-- ---------------- 作业 ----------------
CREATE TABLE IF NOT EXISTS t_job (
    job_id          TEXT PRIMARY KEY,
    job_name        TEXT NOT NULL,
    site_id         TEXT NOT NULL,
    graph_version   TEXT,
    entry_page_id   TEXT,
    target_page_id  TEXT,
    path_element_ids TEXT,
    export_keywords TEXT,
    download_expect INTEGER NOT NULL DEFAULT 1,
    schedule_cron   TEXT,
    status          TEXT NOT NULL DEFAULT 'draft',
    reviewed_by     TEXT,
    reviewed_at     TEXT,
    config_version  INTEGER NOT NULL DEFAULT 1,
    config_hash     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_job_status ON t_job(status);

CREATE TABLE IF NOT EXISTS t_job_run (
    run_id        TEXT PRIMARY KEY,
    job_id        TEXT NOT NULL REFERENCES t_job(job_id),
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL DEFAULT 'running',
    current_state TEXT,
    current_step  INTEGER NOT NULL DEFAULT 0,
    total_steps   INTEGER NOT NULL DEFAULT 0,
    files_downloaded INTEGER NOT NULL DEFAULT 0,
    rows_imported INTEGER NOT NULL DEFAULT 0,
    error_code    TEXT,
    operator      TEXT
);
CREATE INDEX IF NOT EXISTS idx_run_job ON t_job_run(job_id, started_at);

CREATE TABLE IF NOT EXISTS t_job_step (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL REFERENCES t_job_run(run_id) ON DELETE CASCADE,
    seq           INTEGER NOT NULL DEFAULT 1,
    state         TEXT,
    page_id       TEXT,
    action        TEXT,
    target_desc   TEXT,
    result        TEXT,
    duration_ms   INTEGER,
    snapshot      TEXT,
    resumed_from  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_step_run ON t_job_step(run_id, seq);

-- ---------------- 文件（血缘核心） ----------------
CREATE TABLE IF NOT EXISTS t_export_file (
    file_id       TEXT PRIMARY KEY,
    job_run_id    TEXT REFERENCES t_job_run(run_id),
    origin_name   TEXT,
    archived_path TEXT,
    file_ext      TEXT,
    file_size     INTEGER,
    sha256        TEXT,
    download_started_at  TEXT,
    download_finished_at TEXT,
    signal_prompt INTEGER NOT NULL DEFAULT 0,
    signal_stable INTEGER NOT NULL DEFAULT 0,
    parse_status  TEXT NOT NULL DEFAULT 'pending',
    total_rows    INTEGER NOT NULL DEFAULT 0,
    ok_rows       INTEGER NOT NULL DEFAULT 0,
    fail_rows     INTEGER NOT NULL DEFAULT 0,
    batch_id      TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_file_run    ON t_export_file(job_run_id);
CREATE INDEX IF NOT EXISTS idx_file_status ON t_export_file(parse_status);
CREATE INDEX IF NOT EXISTS idx_file_sha    ON t_export_file(sha256);

CREATE TABLE IF NOT EXISTS t_parse_report (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id       TEXT NOT NULL REFERENCES t_export_file(file_id) ON DELETE CASCADE,
    parser        TEXT,
    header_row    INTEGER,
    column_count  INTEGER,
    total_rows    INTEGER,
    ok_rows       INTEGER,
    fail_rows     INTEGER,
    fail_detail   TEXT,
    confidence    REAL,
    created_at    TEXT NOT NULL
);

-- ---------------- 业务数据（示例表，按报表扩展） ----------------
CREATE TABLE IF NOT EXISTS t_report_record (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id           TEXT NOT NULL,
    batch_id          TEXT,
    source_row_no     INTEGER,
    report_date       TEXT NOT NULL,
    dept_code         TEXT NOT NULL,
    dept_name         TEXT,
    item_code         TEXT NOT NULL,
    item_name         TEXT,
    patient_name_enc  TEXT,
    patient_name_mask TEXT,
    id_card_enc       TEXT,
    id_card_hmac      TEXT,
    phone_enc         TEXT,
    phone_mask        TEXT,
    amount            NUMERIC,
    ext_data          TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    CONSTRAINT uq_report UNIQUE (report_date, dept_code, item_code)
);
CREATE INDEX IF NOT EXISTS idx_rec_date  ON t_report_record(report_date);
CREATE INDEX IF NOT EXISTS idx_rec_dept  ON t_report_record(dept_code);
CREATE INDEX IF NOT EXISTS idx_rec_batch ON t_report_record(batch_id);
CREATE INDEX IF NOT EXISTS idx_rec_hmac  ON t_report_record(id_card_hmac);

CREATE TABLE IF NOT EXISTS t_import_batch (
    batch_id      TEXT PRIMARY KEY,
    file_id       TEXT NOT NULL,
    target_table  TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    total_rows    INTEGER,
    inserted_rows INTEGER,
    updated_rows  INTEGER,
    failed_rows   INTEGER,
    status        TEXT NOT NULL DEFAULT 'running'
);

-- ---------------- 运行与审计 ----------------
CREATE TABLE IF NOT EXISTS t_operation_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_run_id    TEXT,
    ts            TEXT NOT NULL,
    level         TEXT NOT NULL,
    state         TEXT,
    page_id       TEXT,
    action        TEXT,
    target_desc   TEXT,
    coords        TEXT,
    result        TEXT,
    duration_ms   INTEGER,
    snapshot_path TEXT,
    error_code    TEXT
);
CREATE INDEX IF NOT EXISTS idx_log_run ON t_operation_log(job_run_id, ts);
CREATE INDEX IF NOT EXISTS idx_log_ts  ON t_operation_log(ts);

CREATE TABLE IF NOT EXISTS t_alert (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_run_id    TEXT,
    ts            TEXT NOT NULL,
    severity      TEXT NOT NULL,
    error_code    TEXT,
    message       TEXT,
    snapshot      TEXT,
    acknowledged  INTEGER NOT NULL DEFAULT 0,
    acknowledged_by TEXT,
    acknowledged_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_alert_ts ON t_alert(ts);

CREATE TABLE IF NOT EXISTS t_audit_event (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    actor         TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    object_type   TEXT,
    object_id     TEXT,
    detail        TEXT,
    source_ip     TEXT,
    result        TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON t_audit_event(ts);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON t_audit_event(actor, ts);
"""
