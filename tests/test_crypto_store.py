"""加密、脱敏、HMAC、幂等入库与外键约束测试。"""
import os
import tempfile

import pytest

from hisbot.store.crypto import CryptoService
from hisbot.store.database import Database
from hisbot.store.repository import Repository

SPECS = [
    {"target": "patient_name", "encrypt": True, "mask_rule": "name"},
    {"target": "id_card", "encrypt": True, "index_mode": "hmac"},
    {"target": "phone", "encrypt": True, "mask_rule": "phone"},
]


def _row(dept="D01", item="I001", name="张三", idc="110101199001011234",
         phone="13800005678"):
    return {"file_id": "file_t1", "report_date": "2026-09-22",
            "dept_code": dept, "dept_name": "内科", "item_code": item,
            "item_name": "床位费", "patient_name": name, "id_card": idc,
            "phone": phone, "amount": 12.5,
            "created_at": "2026-09-22T08:00:00",
            "updated_at": "2026-09-22T08:00:00"}


@pytest.fixture()
def repo():
    d = tempfile.mkdtemp()
    db = Database(os.path.join(d, "app.db"))
    db.init_schema()
    crypto = CryptoService(CryptoService.generate_master_key_b64())
    yield Repository(db, crypto), crypto, db, d
    db.close()


def test_encrypt_roundtrip_and_hmac(repo):
    _, crypto, _, _ = repo
    token = crypto.encrypt("患者A")
    assert token is not None and token != "患者A"
    assert crypto.decrypt(token) == "患者A"
    # AES-GCM 非确定加密：同明文两次密文不同
    assert crypto.encrypt("患者A") != token
    # HMAC 确定性索引
    assert crypto.hmac_index("110101") == crypto.hmac_index("110101")
    assert crypto.hmac_index("110101") != crypto.hmac_index("110102")
    assert crypto.encrypt(None) is None


def test_wrong_master_key_fails_decrypt(repo):
    _, crypto, _, _ = repo
    token = crypto.encrypt("secret")
    other = CryptoService(CryptoService.generate_master_key_b64())
    with pytest.raises(Exception):
        other.decrypt(token)


def test_upsert_idempotent_and_physical_columns(repo):
    r, crypto, db, _ = repo
    u1 = r.upsert_batch("t_report_record", [_row(), _row("D02", "I002")],
                        ["report_date", "dept_code", "item_code"],
                        sensitive_specs=SPECS)
    assert u1["failed"] == 0 and u1["inserted"] == 2
    # 重复主键 -> update，不新增
    again = _row(name="张三丰", phone="13800009999")
    u2 = r.upsert_batch("t_report_record", [again],
                        ["report_date", "dept_code", "item_code"],
                        sensitive_specs=SPECS)
    assert u2["updated"] == 1 and u2["inserted"] == 0
    assert r.count("t_report_record") == 2

    rec = db.execute(
        "SELECT * FROM t_report_record WHERE dept_code='D01'").fetchone()
    assert rec["patient_name_mask"] == "张**"
    assert rec["phone_mask"] == "138****9999"
    assert rec["id_card_hmac"] == crypto.hmac_index("110101199001011234")
    assert rec["patient_name_enc"] and "张" not in rec["patient_name_enc"]
    # 物理表不含逻辑明文列
    cols = {r[1] for r in db.execute("PRAGMA table_info(t_report_record)")}
    assert "patient_name" not in cols and "id_card" not in cols
    # 明文凭据不出现在任何密文列
    assert "13800009999" not in (rec["phone_enc"] or "")


def test_run_requires_job_foreign_key(repo):
    r, _, db, _ = repo
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        r.start_run("not_exist_job", 5, "ro")
