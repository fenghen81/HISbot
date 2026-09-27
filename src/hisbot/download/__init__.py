"""下载捕获子系统（文档 3.3 M7 / 4.6，静默下载专项）。"""
from .coordinator import DownloadCoordinator, CaptureResult  # noqa
from .archiver import archive_file  # noqa
from .magic import check_magic, detect_ext_by_magic  # noqa
