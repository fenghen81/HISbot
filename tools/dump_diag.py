#!/usr/bin/env python3
"""一键诊断包（文档 F-18 / 9.5 故障处置）。

收集运行环境、配置（脱敏）、数据库概况、告警、操作日志哈希链校验、
目录占用，打包为单个 zip，便于提交运维排查。
注意：绝不打包 credentials.enc / master.key 的内容与任何口令明文。

用法：python tools/dump_diag.py --root . [--out diag]
"""
from __future__ import annotations

import argparse
import os
import platform
import sqlite3
import sys
import zipfile
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

SENSITIVE_MARK = ("password", "passwd", "secret", "master_key",
                  "credential")


def _safe_yaml(path):
    try:
        lines = []
        for ln in open(path, encoding="utf-8"):
            low = ln.lower()
            if any(k in low for k in SENSITIVE_MARK) and ":" in ln:
                key = ln.split(":", 1)[0]
                lines.append(f"{key}: <已脱敏，不导出>\n")
            else:
                lines.append(ln)
        return "".join(lines)
    except Exception as e:  # noqa: BLE001
        return f"<读取失败：{e}>"


def collect_system(root):
    info = [f"采集时间: {datetime.now().isoformat(timespec='seconds')}",
            f"程序根目录: {os.path.abspath(root)}",
            f"操作系统: {platform.platform()}",
            f"Python: {platform.python_version()} ({sys.executable})",
            f"DISPLAY={os.environ.get('DISPLAY','')}  "
            f"WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY','')}  "
            f"XDG_SESSION_TYPE={os.environ.get('XDG_SESSION_TYPE','')}"]
    for mod in ("PySide6", "cv2", "numpy", "onnxruntime", "watchdog",
                "apscheduler", "openpyxl", "pdfplumber", "cryptography"):
        try:
            m = __import__(mod)
            info.append(f"依赖 {mod}: {getattr(m, '__version__', '?')}")
        except Exception as e:  # noqa: BLE001
            info.append(f"依赖 {mod}: 未安装/不可用 ({e})")
    info.append(f"sqlite3 运行时: {sqlite3.sqlite_version}")
    try:
        from hisbot.platform import factory
        from hisbot.config.settings import load_yaml
        site = load_yaml(os.path.join(root, "config", "site.yaml"))
        scale = site.get("scale", {})
        res = scale.get("expected_resolution") or [1920, 1080]
        warns, allowed = factory.check_display_environment(
            float(scale.get("expected_ratio", 1.0)),
            (int(res[0]), int(res[1])), scale.get("mismatch_policy", "abort"))
        info.append(f"显示环境允许运行: {allowed}")
        for w in warns:
            info.append(f"  - {w}")
    except Exception as e:  # noqa: BLE001
        info.append(f"显示环境校验异常: {e}")
    return "\n".join(info) + "\n"


def collect_db(root):
    dbp = os.path.join(root, "data", "app.db")
    out = [f"数据库: {dbp}（存在：{os.path.isfile(dbp)}）"]
    if not os.path.isfile(dbp):
        return "\n".join(out) + "\n"
    conn = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        ver = conn.execute("SELECT MAX(version) v FROM t_schema_version"
                           ).fetchone()["v"]
        out.append(f"schema 版本: {ver}")
        tabs = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE 't_%' ORDER BY name")]
        for t in tabs:
            try:
                n = conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
                out.append(f"表 {t}: {n} 行")
            except Exception as e:  # noqa: BLE001
                out.append(f"表 {t}: 统计失败 {e}")
        out.append("\n-- 最近 20 条告警 --")
        for r in conn.execute(
                "SELECT ts,severity,error_code,message,acknowledged "
                "FROM t_alert ORDER BY id DESC LIMIT 20"):
            out.append(" | ".join(str(r[k]) for k in r.keys()))
        out.append("\n-- 最近 20 次作业运行 --")
        for r in conn.execute(
                "SELECT job_id,started_at,status,current_state,"
                "files_downloaded,rows_imported,error_code FROM t_job_run "
                "ORDER BY started_at DESC LIMIT 20"):
            out.append(" | ".join(str(r[k]) for k in r.keys()))
    finally:
        conn.close()
    return "\n".join(out) + "\n"


def collect_log_chain(root):
    from hisbot.audit import verify_chain
    logdir = os.path.join(root, "logs")
    out = []
    if os.path.isdir(logdir):
        for name in sorted(os.listdir(logdir)):
            if name.endswith(".jsonl"):
                p = os.path.join(logdir, name)
                ok, line, msg = verify_chain(p)
                out.append(f"{name}: {'完整' if ok else f'断裂@第{line}行'} "
                           f"({msg})")
    return "\n".join(out) + "\n" if out else "（暂无操作日志）\n"


def collect_tree(root):
    lines = []
    for sub in ("data", "logs", "snapshots", "config"):
        base = os.path.join(root, sub)
        if not os.path.isdir(base):
            continue
        for dirpath, dirs, files in os.walk(base):
            depth = dirpath.replace(base, "").count(os.sep)
            if depth > 3:
                continue
            for f in files:
                fp = os.path.join(dirpath, f)
                try:
                    size = os.path.getsize(fp)
                except OSError:
                    size = -1
                rel = os.path.relpath(fp, root)
                lines.append(f"{size:>12,}  {rel}")
    return "\n".join(sorted(lines)) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = args.out or os.path.join(root, "diag")
    os.makedirs(outdir, exist_ok=True)
    zpath = os.path.join(outdir, f"hisbot_diag_{stamp}.zip")

    parts = {
        "system.txt": collect_system(root),
        "db_info.txt": collect_db(root),
        "log_chain.txt": collect_log_chain(root),
        "file_tree.txt": collect_tree(root),
        "config/app.yaml": _safe_yaml(os.path.join(root, "config",
                                                    "app.yaml")),
        "config/site.yaml": _safe_yaml(os.path.join(root, "config",
                                                     "site.yaml")),
        "config/keywords.yaml": _safe_yaml(os.path.join(
            root, "config", "keywords.yaml")),
    }
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in parts.items():
            z.writestr(name, content)
    print("诊断包已生成：", zpath)
    print("（已脱敏：不含 credentials.enc / master.key 内容与口令明文）")
    print(parts["log_chain.txt"])
    return zpath


if __name__ == "__main__":
    main()
