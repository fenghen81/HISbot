"""错误码表（文档附录 C）与统一异常体系。

错误码格式：模块前缀（3 位大写字母）+ 3 位序号。
日志、告警与界面提示统一使用本模块编码。
"""
from __future__ import annotations

import enum


class Severity(str, enum.Enum):
    WARNING = "WARNING"
    ERROR = "ERROR"
    FATAL = "FATAL"
    INFO = "INFO"


# 错误码 -> (含义, 级别)
ERROR_CODES: dict[str, tuple[str, Severity]] = {
    # 平台适配 AUT
    "AUT-001": ("窗口未找到 / 窗口已关闭", Severity.ERROR),
    "AUT-002": ("窗口置顶失败", Severity.WARNING),
    "AUT-003": ("键鼠注入失败", Severity.ERROR),
    "AUT-004": ("屏幕捕获失败", Severity.ERROR),
    # 扫描环境 SCA
    "SCA-001": ("显示缩放比与模板不匹配", Severity.FATAL),
    "SCA-002": ("分辨率与模板不匹配", Severity.FATAL),
    # 识别 DET
    "DET-001": ("元素定位失配（三级降级均失败）", Severity.ERROR),
    "DET-002": ("页面指纹不匹配", Severity.ERROR),
    "DET-003": ("OCR 置信度低于阈值", Severity.WARNING),
    # 扫描 SCN
    "SCN-001": ("扫描深度达上限", Severity.INFO),
    "SCN-002": ("回退失败，分支终止", Severity.WARNING),
    "SCN-003": ("命中危险元素并跳过", Severity.INFO),
    # 执行 EXE
    "EXE-001": ("路径未审核通过", Severity.FATAL),
    "EXE-002": ("配置签名校验失败", Severity.FATAL),
    "EXE-003": ("目标按钮未找到", Severity.ERROR),
    "EXE-004": ("导航超时", Severity.ERROR),
    # 登录 LOG
    "LOG-001": ("登录失败", Severity.ERROR),
    "LOG-002": ("登录态失效", Severity.WARNING),
    # 下载 DLD
    "DLD-001": ("下载超时（未完成落盘确认）", Severity.ERROR),
    "DLD-002": ("未捕获界面完成提示（信号 A 缺失）", Severity.WARNING),
    "DLD-003": ("文件未进入稳定态（信号 B 缺失）", Severity.WARNING),
    "DLD-004": ("文件魔数与扩展名不符", Severity.ERROR),
    "DLD-005": ("候选文件数量与预期不符", Severity.WARNING),
    "DLD-006": ("归档移动失败", Severity.ERROR),
    "DLD-007": ("下载目录不可访问", Severity.FATAL),
    # 解析 PRS
    "PRS-001": ("不支持的文件类型", Severity.ERROR),
    "PRS-002": ("PDF 无文本层", Severity.ERROR),
    "PRS-003": ("解析失败率超阈值", Severity.ERROR),
    "PRS-004": ("字段映射缺失必填列", Severity.ERROR),
    "PRS-005": ("编码识别失败", Severity.ERROR),
    # 数据库 DBS
    "DBS-001": ("数据库加锁超时", Severity.ERROR),
    "DBS-002": ("批次写入失败并回滚", Severity.ERROR),
    "DBS-003": ("密钥不可用 / 解密失败", Severity.FATAL),
    "DBS-004": ("密文认证失败（可能被篡改）", Severity.FATAL),
    # 系统 SYS
    "SYS-001": ("磁盘空间不足", Severity.FATAL),
    "SYS-002": ("执行线程无心跳（疑似卡死）", Severity.FATAL),
    "SYS-003": ("操作员急停", Severity.INFO),
}


class HisBotError(Exception):
    """所有业务异常基类，携带错误码。"""
    code = "SYS-000"

    def __init__(self, message: str = "", *, code: str | None = None,
                 detail: dict | None = None):
        self.code = code or self.code
        self.detail = detail or {}
        if not message:
            message = ERROR_CODES.get(self.code, ("未知错误",))[0]
        super().__init__(f"[{self.code}] {message}")

    @property
    def severity(self) -> Severity:
        return ERROR_CODES.get(self.code, ("", Severity.ERROR))[1]


# 具体异常（按模块）
class WindowNotFoundError(HisBotError):
    code = "AUT-001"


class FocusWindowError(HisBotError):
    code = "AUT-002"


class InputInjectError(HisBotError):
    code = "AUT-003"


class CaptureError(HisBotError):
    code = "AUT-004"


class ScaleMismatchError(HisBotError):
    code = "SCA-001"


class ResolutionMismatchError(HisBotError):
    code = "SCA-002"


class ElementNotFoundError(HisBotError):
    code = "DET-001"


class FingerprintMismatchError(HisBotError):
    code = "DET-002"


class BacktrackError(HisBotError):
    code = "SCN-002"


class UnapprovedPathError(HisBotError):
    code = "EXE-001"


class ConfigSignatureError(HisBotError):
    code = "EXE-002"


class TargetNotFoundError(HisBotError):
    code = "EXE-003"


class NavigationTimeoutError(HisBotError):
    code = "EXE-004"


class LoginError(HisBotError):
    code = "LOG-001"


class LoginExpiredError(HisBotError):
    code = "LOG-002"


class DownloadTimeoutError(HisBotError):
    code = "DLD-001"


class SignalAMissingError(HisBotError):
    code = "DLD-002"


class SignalBStableError(HisBotError):
    code = "DLD-003"


class MagicMismatchError(HisBotError):
    code = "DLD-004"


class CandidateCountError(HisBotError):
    code = "DLD-005"


class ArchiveMoveError(HisBotError):
    code = "DLD-006"


class WatchDirError(HisBotError):
    code = "DLD-007"


class UnsupportedFileTypeError(HisBotError):
    code = "PRS-001"


class PdfNoTextLayerError(HisBotError):
    code = "PRS-002"


class ParseRatioError(HisBotError):
    code = "PRS-003"


class MappingMissingColumnError(HisBotError):
    code = "PRS-004"


class EncodingDetectError(HisBotError):
    code = "PRS-005"


class DbLockError(HisBotError):
    code = "DBS-001"


class BatchRollbackError(HisBotError):
    code = "DBS-002"


class KeyUnavailableError(HisBotError):
    code = "DBS-003"


class CipherAuthError(HisBotError):
    code = "DBS-004"


class DiskFullError(HisBotError):
    code = "SYS-001"


class WatchdogTimeoutError(HisBotError):
    code = "SYS-002"


class AbortedByUser(HisBotError):
    code = "SYS-003"
