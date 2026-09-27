"""PyInstaller 打包入口（等价于 python -m hisbot.app.main）。"""
from hisbot.app.main import main

if __name__ == "__main__":
    raise SystemExit(main())
