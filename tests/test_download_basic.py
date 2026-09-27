"""下载捕获的魔数、稳定判定与归档重命名测试（不依赖 OCR）。"""
import os
import tempfile

from hisbot.core.hashing import sha256_file
from hisbot.download import archiver, magic
from hisbot.download.stable import file_size, try_exclusive_open


def _w(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def test_magic_xlsx_pdf_csv(tmp_path):
    xlsx = _w(str(tmp_path / "a.xlsx"), b"PK\x03\x04rest-of-zip")
    pdf = _w(str(tmp_path / "a.pdf"), b"%PDF-1.7\nhello")
    csv = _w(str(tmp_path / "a.csv"), "科室,金额\n内科,12.5".encode("gbk"))
    assert magic.check_magic(xlsx, ".xlsx")
    assert magic.check_magic(pdf, ".pdf")
    assert magic.check_magic(csv, ".csv")
    # 纯文本伪装成 xlsx -> 魔数不符
    fake = _w(str(tmp_path / "fake.xlsx"), b"this is plain text only")
    assert not magic.check_magic(fake, ".xlsx")
    # 二进制 NUL 伪装 csv -> 拒绝
    bincsv = _w(str(tmp_path / "b.csv"), b"\x00\x01\x02binary")
    assert not magic.check_magic(bincsv, ".csv")


def test_detect_ext_by_magic(tmp_path):
    pdf = _w(str(tmp_path / "mystery"), b"%PDF-1.4\n")
    assert magic.detect_ext_by_magic(pdf) == ".pdf"


def test_stable_helpers(tmp_path):
    p = _w(str(tmp_path / "f.bin"), b"hello")
    assert file_size(p) == 5
    assert try_exclusive_open(p) is True


def test_archive_seq_no_overwrite(tmp_path):
    src_root = tmp_path / "dl"
    arc_root = tmp_path / "arc"
    src1 = str(src_root / "住院日报.xlsx")
    p1 = _w(src1, b"PK" + b"1" * 100)
    a1 = archiver.archive_file(str(p1), str(arc_root), "住院日报", "20260922")
    # 浏览器再次下载同名文件到同一路径
    p2 = _w(src1, b"PK" + b"2" * 200)
    a2 = archiver.archive_file(str(p2), str(arc_root), "住院日报", "20260922")
    assert a1.name.endswith("_001.xlsx")
    assert a2.name.endswith("_002.xlsx")
    assert os.path.isfile(a1.path) and os.path.isfile(a2.path)
    assert not os.path.exists(p1)
    assert a1.sha256 == sha256_file(a1.path)
    assert a1.size != a2.size
