"""AlertManager：告警落库、未确认列表、确认动作、外部 sink 回调。"""
from hisbot.audit.alert import AlertManager


class _FakeRepo:
    """最小内存 repo，只实现 AlertManager 用到的接口。"""

    def __init__(self):
        self.rows = []
        self.next_id = 1
        self.updated = []

    def add_alert(self, rec):
        rid = self.next_id
        self.next_id += 1
        self.rows.append({"id": rid, **rec, "acknowledged": 0})
        return rid

    def query_alerts(self, acknowledged=0):
        return [r for r in self.rows if r["acknowledged"] == acknowledged]

    class _DB:
        def __init__(self, outer):
            self.outer = outer

        def execute(self, sql, params=()):
            self.outer.updated.append((sql, params))
            return self

        def fetchall(self):
            return []

        def commit(self):
            self.outer.committed = True

    @property
    def db(self):
        self.committed = False
        return self._DB(self)


def test_raise_alert_persists_and_calls_sink():
    repo = _FakeRepo()
    got = []
    am = AlertManager(repo=repo, logger=None, sink=lambda a: got.append(a))

    a = am.raise_alert("CRITICAL", "SYS-002", "执行线程无心跳",
                       job_run_id="r1", snapshot="snap.png")

    assert a.id == 1
    assert a.severity == "CRITICAL" and a.error_code == "SYS-002"
    assert len(got) == 1 and got[0] is a          # sink 收到同一对象
    assert len(repo.query_alerts(acknowledged=0)) == 1


def test_unacked_only_returns_unacknowledged():
    repo = _FakeRepo()
    am = AlertManager(repo=repo, logger=None)
    am.raise_alert("warning", "W1", "一")
    am.raise_alert("warning", "W2", "二")
    assert len(am.unacked()) == 2
    # 模拟运维确认了第一条
    repo.rows[0]["acknowledged"] = 1
    left = am.unacked()
    assert len(left) == 1 and left[0]["error_code"] == "W2"


def test_ack_writes_correct_sql():
    repo = _FakeRepo()
    am = AlertManager(repo=repo, logger=None)
    am.raise_alert("warning", "W", "x")
    am.ack(1, by="ops")
    sql, params = repo.updated[0]
    assert "UPDATE t_alert" in sql and "acknowledged=1" in sql
    assert params[0] == "ops" and params[-1] == 1


def test_raise_without_repo_still_returns_alert():
    """无 repo 时不应抛错，只返回告警对象本身。"""
    am = AlertManager(repo=None, logger=None)
    a = am.raise_alert("info", "I1", "无存储告警")
    assert a.id == 0 and a.error_code == "I1"
    assert am.unacked() == []
