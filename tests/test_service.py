from types import SimpleNamespace

import pytest

pytest.importorskip("databricks.sdk")  # the dbx extra

from aops.dbx.service import Caller, Service  # noqa: E402


def fake_service(calls):
    svc = object.__new__(Service)
    svc.w = SimpleNamespace(grants=SimpleNamespace(update=lambda kind, name, changes: calls.append((kind, name, changes))))
    svc._agent_or_404 = lambda agent_id: {"agent_id": agent_id, "owner": "me@x.com", "owner_group": None}
    svc._is_owner = lambda caller, agent: True
    svc.production = lambda agent_id: {"current_version": "1.0.1"}
    svc.version_skills = lambda agent_id, version: [{"uc_name": "c.s.a__k"}]
    svc.event = lambda *args: None
    return svc


def test_promote_sends_privileges_the_sdk_can_serialize():
    calls = []
    grants = fake_service(calls).promote(Caller("me@x.com", None, []), "a", ["group:team", "user:kim@x.com"])
    assert [g["principal"] for g in grants] == ["group:team", "user:kim@x.com"]
    kind, name, changes = calls[0]
    assert (kind, name) == ("skill", "c.s.a__k")
    assert changes[0].as_dict() == {"add": ["READ_VOLUME"], "principal": "team"}


def test_revoke_removes_the_same_privilege():
    calls = []
    fake_service(calls).promote(Caller("me@x.com", None, []), "a", ["group:team"], revoke=True)
    assert calls[0][2][0].as_dict() == {"remove": ["READ_VOLUME"], "principal": "team"}
