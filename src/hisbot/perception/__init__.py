"""感知与识别层 L2（文档 3.3 M3）。"""
from .ocr import try_build_ocr, RapidOcrEngine, NullOcrEngine  # noqa
from .detector import ElementDetector  # noqa
from .template import TemplateLibrary, TemplateMatcher  # noqa
from .fingerprint import PageFingerprint  # noqa
from .download_signal import DownloadSignalDetector  # noqa
from .locator import Locator  # noqa
