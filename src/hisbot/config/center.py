"""配置中心（文档 M1 / 4.10）。

集中管理 app/site/keywords/mappings/jobs 等 YAML 配置与运行时目录，
支持路径解析、热加载（凭据与作业签名除外）、配置保存（留审计）。
"""
from __future__ import annotations

from pathlib import Path

from .settings import AttrDict, dump_yaml, load_yaml


class ConfigCenter:
    def __init__(self, root_dir: str | Path):
        self.root = Path(root_dir).resolve()
        self.config_dir = self.root / "config"
        self._mtimes: dict[Path, float] = {}
        self.reload()

    # ------------------------------------------------------------------ #
    # 路径
    # ------------------------------------------------------------------ #
    def resolve(self, p: str | Path) -> Path:
        """相对路径相对程序根解析；绝对路径原样返回；支持 $DATA_DIR。"""
        s = str(p)
        if s.startswith("$DATA_DIR"):
            s = s.replace("$DATA_DIR", str(self.data_dir), 1)
        path = Path(s)
        return path if path.is_absolute() else (self.root / path)

    @property
    def data_dir(self) -> Path:
        return self.resolve(self.app.get("app", {}).get("data_dir", "./data"))

    @property
    def template_dir(self) -> Path:
        return self.resolve(self.app.get("app", {}).get(
            "template_dir", "./templates"))

    @property
    def log_dir(self) -> Path:
        return self.resolve(self.app.get("app", {}).get("log_dir", "./logs"))

    @property
    def snapshot_dir(self) -> Path:
        return self.resolve(self.app.get("app", {}).get(
            "snapshot_dir", "./snapshots"))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def watch_dir(self) -> Path:
        return self.resolve(self.app["download"]["watch_dir"])

    @property
    def archive_dir(self) -> Path:
        return self.resolve(self.app["download"].get(
            "archive_dir", "./data/archive"))

    @property
    def quarantine_dir(self) -> Path:
        return self.resolve(self.app["download"].get(
            "quarantine_dir", "./data/quarantine"))

    def ensure_runtime_dirs(self) -> None:
        for d in (self.data_dir, self.template_dir, self.log_dir,
                  self.snapshot_dir, self.watch_dir, self.archive_dir,
                  self.quarantine_dir,
                  self.config_dir / "mappings", self.config_dir / "jobs",
                  self.config_dir / "graph"):
            Path(d).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # 加载 / 热加载
    # ------------------------------------------------------------------ #
    def reload(self) -> None:
        self.app = load_yaml(self.config_dir / "app.yaml")
        self.site = load_yaml(self.config_dir / "site.yaml")
        self.keywords = load_yaml(self.config_dir / "keywords.yaml")
        self._mtimes = {p: self._mtime(p) for p in (
            self.config_dir / "app.yaml",
            self.config_dir / "site.yaml",
            self.config_dir / "keywords.yaml")}

    @staticmethod
    def _mtime(p: Path) -> float:
        return p.stat().st_mtime if p.exists() else 0.0

    def maybe_reload(self) -> bool:
        """检测基础配置文件变化并热加载。返回是否发生重载。"""
        changed = False
        mapping = {
            self.config_dir / "app.yaml": "app",
            self.config_dir / "site.yaml": "site",
            self.config_dir / "keywords.yaml": "keywords",
        }
        for path, attr in mapping.items():
            mt = self._mtime(path)
            if mt != self._mtimes.get(path, 0):
                setattr(self, attr, load_yaml(path))
                self._mtimes[path] = mt
                changed = True
        return changed

    # ------------------------------------------------------------------ #
    # 作业 / 映射 / 导航图
    # ------------------------------------------------------------------ #
    def job_path(self, name_or_id: str) -> Path:
        name = name_or_id if name_or_id.endswith((".yaml", ".yml")) \
            else f"{name_or_id}.yaml"
        return self.config_dir / "jobs" / name

    def mapping_path(self, name: str) -> Path:
        if name.endswith((".yaml", ".yml")):
            return self.resolve(self.config_dir / "mappings" / name) \
                if not Path(name).is_absolute() else Path(name)
        return self.config_dir / "mappings" / f"{name}.yaml"

    def load_job(self, name_or_id: str) -> AttrDict:
        return load_yaml(self.job_path(name_or_id))

    def save_job(self, name_or_id: str, cfg: dict | AttrDict) -> Path:
        path = self.job_path(name_or_id)
        dump_yaml(cfg, path)
        return path

    def list_jobs(self) -> list[Path]:
        d = self.config_dir / "jobs"
        return sorted(d.glob("*.yaml")) if d.exists() else []

    def load_mapping(self, name: str) -> AttrDict:
        return load_yaml(self.mapping_path(name))

    def graph_path(self, version: str) -> Path:
        safe = version.replace("/", "_")
        return self.config_dir / "graph" / f"{safe}.json"

    def save_app(self) -> None:
        dump_yaml(self.app, self.config_dir / "app.yaml")

    def save_site(self) -> None:
        dump_yaml(self.site, self.config_dir / "site.yaml")

    def save_keywords(self) -> None:
        dump_yaml(self.keywords, self.config_dir / "keywords.yaml")

    # ------------------------------------------------------------------ #
    # 便捷读取
    # ------------------------------------------------------------------ #
    def get_list(self, section: str, key: str, default: list | None = None
                 ) -> list:
        """从 keywords.yaml 等读取列表。section 为顶层键。"""
        node = self.keywords.get(section, {})
        v = node.get(key, default if default is not None else [])
        return list(v) if v else []

    def timing_ms(self, key: str, default: int) -> int:
        return int(self.app.get("timing", {}).get(key, default))

    def download_cfg(self) -> AttrDict:
        return self.app.get("download", AttrDict())
