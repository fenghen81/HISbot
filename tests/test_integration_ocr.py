"""OCR 端到端集成测试（较慢，依赖 RapidOCR；用 -m 'not integration' 跳过）。"""
import os
import tempfile

import numpy as np
import pytest

from hisbot.config.settings import load_yaml
from hisbot.config.signing import sign_job
from hisbot.execute.context import RunControl
from hisbot.execute.engine import ExecEngine
from hisbot.perception import Locator, PageFingerprint, try_build_ocr
from hisbot.simulator.headless import SimHis
from hisbot.store.crypto import CryptoService
from hisbot.store.database import Database
from hisbot.store.repository import Repository

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.integration
def test_exec_engine_end_to_end():
    tmp = tempfile.mkdtemp()
    watch = os.path.join(tmp, "dl")
    ocr = try_build_ocr()
    ocr.recognize(np.full((80, 80, 3), 255, np.uint8))  # 预热
    his = SimHis(watch, write_seconds=0.3)
    app = load_yaml(os.path.join(ROOT, "config", "app.yaml"))
    kw = load_yaml(os.path.join(ROOT, "config", "keywords.yaml"))
    dl = dict(app["download"])
    dl["stable_sample_interval_ms"] = 150

    db = Database(os.path.join(tmp, "app.db")); db.init_schema()
    crypto = CryptoService(CryptoService.generate_master_key_b64())
    repo = Repository(db, crypto)

    eng = ExecEngine(
        operator=his, locator=Locator(ocr), fp=PageFingerprint(ocr),
        config_dir=os.path.join(ROOT, "config"), repo=repo, crypto=crypto,
        danger_words=kw["blacklist_keywords"],
        completion_keywords=dl["completion_keywords"], download_cfg=dl,
        control=RunControl(), settle_secs=0.05, nav_timeout_s=40.0)
    job = {"job": {
        "job_id": "inpatient_daily_report", "job_name": "住院日报",
        "site_id": "his-main", "graph_version": "v1", "config_version": 0,
        "path": [{"page": "home", "text": "住院报表",
                  "rel_bbox": [0, 0, 0, 0], "approved": True},
                 {"page": "rpt", "text": "住院日报",
                  "rel_bbox": [0, 0, 0, 0], "approved": True}],
        "target": {"page_id": "daily", "button_text": "导出Excel",
                   "button_keywords": ["导出Excel", "导出"],
                   "button_rel_bbox": [0, 0, 0, 0], "pre_actions": []},
        "download": {"expect_files": 1,
                     "expect_name_pattern": r"住院日报.*\.xlsx",
                     "timeout_ms": 40000, "on_timeout": "retry",
                     "max_retry": 2},
        "parse": {"mapping": "mappings/inpatient_daily.yaml",
                  "target_table": "t_report_record"},
        "schedule": {"enabled": False},
        "safety": {"allow_unapproved_path": False}}}
    sign_job(job, "集成测试")
    res = eng.run(job, username="ro", password="pw", biz_date="20260922",
                  watch_dir=watch, archive_dir=os.path.join(tmp, "arc"),
                  quarantine_dir=os.path.join(tmp, "q"))
    assert res.success, res.message
    assert res.state == "DONE"
    assert len(res.files) == 1
    assert repo.count("t_report_record") == 4
    f = db.execute(
        "SELECT signal_prompt,signal_stable,parse_status FROM t_export_file"
    ).fetchone()
    assert f["signal_prompt"] == 1 and f["signal_stable"] == 1
    assert f["parse_status"] == "success"


@pytest.mark.integration
def test_scan_builds_graph_with_danger():
    from hisbot.perception import ElementDetector
    from hisbot.scan.classifier import ElementClassifier
    from hisbot.scan.engine import ScanEngine

    tmp = tempfile.mkdtemp()
    watch = os.path.join(tmp, "dl")
    his = SimHis(watch)
    his.page = "home"          # 扫描从已登录首页开始
    ocr = try_build_ocr()
    ocr.recognize(np.full((80, 80, 3), 255, np.uint8))
    fp = PageFingerprint(ocr)
    kw = load_yaml(os.path.join(ROOT, "config", "keywords.yaml"))
    cls = ElementClassifier(kw["blacklist_keywords"], kw["export_keywords"],
                            kw["back_keywords"], kw["nav_safe_keywords"])
    eng = ScanEngine(detector=ElementDetector(ocr), ocr=ocr, fingerprint=fp,
                     classifier=cls, robot=his,
                     graph_path=os.path.join(tmp, "graph.json"),
                     max_depth=4, max_branch=30, settle_secs=0.05)
    result = eng.scan()
    assert result.status == "done"
    assert result.pages >= 3 and result.edges >= 2
    assert result.dangers >= 1
