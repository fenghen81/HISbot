"""核心工具与脱敏/清洗纯函数测试。"""
import numpy as np

from hisbot.core import hashing
from hisbot.core.util import BooleanFlag, human_duration
from hisbot.parse import cleaner
from hisbot.store import masking


def test_sha256_known_vector():
    assert hashing.sha256_bytes(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


def test_phash_stability_and_distance():
    img = (np.random.RandomState(0).rand(64, 64) * 255).astype("uint8")
    h1 = hashing.phash_hex(img)
    h2 = hashing.phash_hex(img)
    assert h1 == h2
    assert hashing.phash_similarity(h1, h2) == 1.0
    other = (np.random.RandomState(99).rand(64, 64) * 255).astype("uint8")
    assert hashing.phash_similarity(h1, hashing.phash_hex(other)) < 1.0


def test_boolean_flag():
    f = BooleanFlag(False)
    assert f.get() is False
    f.set()
    assert f.wait(0.01) is True


def test_human_duration():
    assert human_duration(0) == "00:00"
    assert human_duration(125) == "02:05"
    assert human_duration(3725) == "01:02:05"


def test_mask_rules():
    assert masking.mask_name("张三") == "张*"
    assert masking.mask_name("欧阳修") == "欧**"
    assert masking.mask_id_card("110101199001011234") == "110101********1234"
    assert masking.mask_phone("13800005678") == "138****5678"
    assert masking.mask_value(None, "name") is None
    assert masking.mask_value("x", "unknown_rule") == "x"


def test_cleaner_transforms():
    assert cleaner.t_sbc2dbc("ＡＢＣ１２３") == "ABC123"
    assert cleaner.t_strip_unit("￥1,234.50元") == "1234.50"
    assert cleaner.t_to_date("2026/9/2") == "2026-09-02"
    assert cleaner.t_to_decimal("12.5") == 12.5
    assert cleaner.t_to_int("88") == 88
    assert cleaner.coerce("2026年09月02日", "date") == "2026-09-02"


def test_coerce_bool():
    assert cleaner.t_to_bool("是") == 1
    assert cleaner.t_to_bool("否") == 0
    assert cleaner.coerce("true", "bool") == 1
