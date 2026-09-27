"""平台适配层 L1（文档 3.3 M2）。"""
from .base import (ScreenCapturer, InputInjector, FsWatcher,  # noqa
                   CredentialVault, ScaleProvider)
from . import factory  # noqa
