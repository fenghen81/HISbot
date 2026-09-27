#!/usr/bin/env python3
"""数据库初始化 / 迁移工具（文档 9.x / 附录 A）。

用法：
    python tools/migrate.py --root .            # 初始化或升级到最新版本
    python tools/migrate.py --root . --vacuum   # 迁移后执行 VACUUM（每月维护）
    python tools/migrate.py --db data/app.db --sql sql/schema_sqlite.sql

幂等：可重复执行；当前为初始版本 v1，后续版本在此追加迁移分支。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hisbot.store.database import Database  # noqa: E402
from hisbot.store.schema_sql import SCHEMA_VERSION  # noqa: E402


def migrate(db_path: str, vacuum: bool = False) -> int:
    db = Database(db_path)
    before = db.current_version()
    # 当前仅 v1：init_schema 幂等建表并登记版本。
    # 未来升级：在此按 before 分支执行 ALTER/数据迁移，再更新 t_schema_version。
    db.init_schema()
    after = db.current_version()
    if vacuum:
        db.conn.isolation_level = None
        db.execute("VACUUM")
    db.close()
    print(f"数据库：{db_path}")
    print(f"迁移前版本：{before}  →  当前版本：{after}（最新 {SCHEMA_VERSION}）")
    if after != SCHEMA_VERSION:
        print("警告：未达到最新 schema 版本，请检查迁移脚本。", file=sys.stderr)
        return 1
    print("迁移完成。")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="HISBot 数据库初始化/迁移")
    ap.add_argument("--root", default=".", help="程序根目录")
    ap.add_argument("--db", help="显式指定数据库路径（优先于 --root）")
    ap.add_argument("--vacuum", action="store_true", help="迁移后 VACUUM")
    args = ap.parse_args(argv)
    db_path = args.db or os.path.join(args.root, "data", "app.db")
    return migrate(os.path.abspath(db_path), args.vacuum)


if __name__ == "__main__":
    raise SystemExit(main())
