"""防篡改日志哈希链、现场快照、看门狗心跳测试。"""
import json
import os
import threading
import time

import numpy as np

from hisbot.audit import StructuredLogger, Watchdog, save_snapshot, verify_chain


def test_hash_chain_append_and_reopen(tmp_path):
    p = str(tmp_path / "ops.jsonl")
    lg = StructuredLogger(p)
    lg.info("启动", "SYS-001", state="INIT")
    lg.action("click", "导出", "success", state="EXPORT")
    assert verify_chain(p)[0] is True
    StructuredLogger(p).info("跨实例续写", "SYS-001")
    ok, _, msg = verify_chain(p)
    assert ok, msg


def test_tamper_breaks_chain(tmp_path):
    p = str(tmp_path / "ops.jsonl")
    lg = StructuredLogger(p)
    for i in range(3):
        lg.info(f"msg{i}", "SYS-001")
    lines = open(p, encoding="utf-8").read().splitlines()
    rec = json.loads(lines[1])
    rec["message"] = "被篡改"
    lines[1] = json.dumps(rec, ensure_ascii=False)
    open(p, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    ok, line, _ = verify_chain(p)
    assert ok is False and line == 2


def test_snapshot_writes_screen_and_meta(tmp_path):
    folder = save_snapshot(str(tmp_path / "diag"),
                           frame=np.full((8, 8, 3), 0, np.uint8),
                           state="ABORTED", extra={"code": "SYS-002"})
    assert os.path.isfile(os.path.join(folder, "screen.png"))
    meta = json.load(open(os.path.join(folder, "meta.json"), encoding="utf-8"))
    assert meta["state"] == "ABORTED"


def test_watchdog_fires_on_stall_only():
    fired = threading.Event()
    wd = Watchdog(timeout_s=1, check_s=0.1, on_timeout=fired.set)
    wd.start()
    for _ in range(5):
        wd.beat(); time.sleep(0.1)
    time.sleep(1.4)
    assert fired.is_set()

    fired.clear()
    wd2 = Watchdog(timeout_s=1, check_s=0.1, on_timeout=fired.set)
    wd2.start()
    for _ in range(6):
        wd2.beat(); time.sleep(0.18)
    wd2.stop()
    assert not fired.is_set()
