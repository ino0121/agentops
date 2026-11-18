"""Named approvers: picked when the agent is made, kept on each deploy request, and the only ones who approve it."""

from types import SimpleNamespace

import pytest

pytest.importorskip("databricks.sdk")  # the dbx extra

from aops.dbx.service import DEFAULT_POLICY, Caller, Service, ServiceError  # noqa: E402

GATE = {"gate_id": "g1", "agent_id": "a", "version": "1.0.0", "requester": "dev@x.com", "decision": "pending_approval",
        "approval_mode": "auto", "validation_run_id": "r1", "required_approvals": 1}


def service(policy=None):
    svc = object.__new__(Service)
    svc.policy = lambda: (1, {**DEFAULT_POLICY, **(policy or {})})
    return svc


def test_named_approvers_are_the_only_ones_and_groups_count():
    svc = service({"approver_group": "everyone-else"})
    gate = {**GATE, "approvers": ["boss@x.com", "group:pricing-leads"]}
    assert svc.can_approve(Caller("boss@x.com"), gate)
    assert svc.can_approve(Caller("lee@x.com", groups=["pricing-leads"]), gate)
    assert not svc.can_approve(Caller("lee@x.com", groups=["everyone-else"]), gate)  # the policy group does not apply
    assert not svc.can_approve(Caller("dev@x.com", groups=["pricing-leads"]), gate)  # never the requester
    with pytest.raises(ServiceError) as denied:
        svc._check_approver(Caller("lee@x.com"), gate, "approve")
    assert denied.value.code == "not_approver" and "boss@x.com" in denied.value.message


def test_without_named_approvers_the_policy_group_decides():
    gate = {**GATE, "approvers": []}
    assert service().can_approve(Caller("anyone@x.com"), gate)
    assert not service({"approver_group": "leads"}).can_approve(Caller("anyone@x.com"), gate)
    assert service({"approver_group": "leads"}).can_approve(Caller("anyone@x.com", groups=["leads"]), gate)


def test_named_approvers_stop_auto_approval_even_when_the_policy_is_auto():
    svc = service({"approval_mode": "auto"})
    gate = {**GATE, "decision": "validating", "approvers": ["boss@x.com"]}
    svc.gate = lambda gate_id: dict(gate)
    svc._flagged = lambda run_id: None
    moved = []
    svc.sql = SimpleNamespace(table=lambda n: n, update=lambda s, p: moved.append(p) or True,
                              run=lambda s, p=None: pytest.fail("auto-approved"))
    svc._approved = lambda g, actor: pytest.fail("auto-approved")
    svc._after_gate("g1", "r1")
    assert moved[0]["why"] == "지정 승인자 승인 필요: boss@x.com (리포트를 보고 승인)"


def test_the_approver_list_shows_only_requests_waiting_for_me():
    svc = service()
    rows = [{**GATE, "gate_id": "g1"}, {**GATE, "gate_id": "g2"}, {**GATE, "gate_id": "g3"}]
    named = [{"gate_id": "g1", "approvers": '["boss@x.com"]'}, {"gate_id": "g2", "approvers": '["group:leads"]'}]

    class Sql:
        def table(self, name):
            return name

        def run(self, statement, params=None):
            return named if "agent_events" in statement else [dict(r) for r in rows]

    svc.sql = Sql()
    mine = [r["gate_id"] for r in svc.gates(Caller("boss@x.com"), to_approve=True)]
    assert mine == ["g1", "g3"]  # g3 has no named approvers: anyone but the requester
    assert [r["gate_id"] for r in svc.gates(Caller("lee@x.com", groups=["leads"]), to_approve=True)] == ["g2", "g3"]


def test_directory_search_lists_users_and_groups():
    svc = service()
    users = [SimpleNamespace(user_name="lead.approver@x.com", display_name="Lead Approver", active=True),
             SimpleNamespace(user_name="gone@x.com", display_name="Gone", active=False)]
    groups = [SimpleNamespace(display_name="lead-approvers")]
    seen = {}
    svc.w = SimpleNamespace(users=SimpleNamespace(list=lambda **k: seen.setdefault("users", k) and users),
                            groups=SimpleNamespace(list=lambda **k: seen.setdefault("groups", k) and groups))
    out = svc.search_directory("lead")
    assert out == [{"principal": "lead.approver@x.com", "kind": "user", "name": "Lead Approver"},
                   {"principal": "group:lead-approvers", "kind": "group", "name": "lead-approvers"}]
    assert 'userName co "lead"' in seen["users"]["filter"] and svc.search_directory("j") == []


def test_principal_lookup_says_unknown_when_the_server_cannot_list():
    svc = service()

    def denied(**k):
        raise PermissionError("not allowed")

    svc.w = SimpleNamespace(users=SimpleNamespace(list=lambda **k: iter([SimpleNamespace(user_name="boss@x.com")])),
                            groups=SimpleNamespace(list=denied))
    assert svc.principal_exists("boss@x.com") is True and svc.principal_exists("group:leads") is None
    calls = []
    svc.w = SimpleNamespace(users=SimpleNamespace(list=lambda **k: calls.append(k) or iter([])),
                            groups=SimpleNamespace(list=lambda **k: calls.append(k) or iter([SimpleNamespace(display_name="leads")])))
    assert svc.principal_exists("group:leads") is True  # an unknown answer was not kept: asked again
    assert svc.principal_exists("group:leads") is True and len(calls) == 1  # a known one is kept for a while


def test_a_request_only_its_requester_could_approve_is_refused():
    from aops.dbx.service import ServiceError

    svc = service()
    with pytest.raises(ServiceError) as error:
        svc.check_someone_approves(Caller("dev@x.com"), ["DEV@x.com"], {})
    assert error.value.code == "no_other_approver"
    svc.check_someone_approves(Caller("dev@x.com"), ["dev@x.com", "lead@x.com"], {})
    svc.check_someone_approves(Caller("dev@x.com"), ["group:leads"], {})  # a group may hold others
    svc.check_someone_approves(Caller("dev@x.com"), ["dev@x.com"], {"dev_approvers": ["dev@x.com"]})  # the exception approves


def test_the_approver_list_is_filtered_before_it_is_cut():
    svc = service()
    rows = [{**GATE, "gate_id": f"other{i}"} for i in range(5)] + [{**GATE, "gate_id": "mine"}]
    named = [{"gate_id": f"other{i}", "approvers": '["someone@x.com"]'} for i in range(5)] + [{"gate_id": "mine", "approvers": '["boss@x.com"]'}]
    seen = []

    class Sql:
        def table(self, name):
            return name

        def run(self, statement, params=None):
            seen.append(statement)
            return named if "agent_events" in statement else [dict(r) for r in rows]

    svc.sql = Sql()
    assert [r["gate_id"] for r in svc.gates(Caller("boss@x.com"), to_approve=True, limit=2)] == ["mine"]
    assert "LIMIT 1000" in seen[0]


def test_the_development_exception_lets_one_person_approve_their_own_request():
    svc = service({"dev_approvers": ["dev@x.com"]})
    gate = {**GATE, "approvers": ["boss@x.com"]}
    me = Caller("dev@x.com")
    assert svc.can_approve(me, gate) and svc.approval_exception(me, gate)
    svc._check_approver(me, gate, "approve")  # no error: the exception
    assert svc.can_approve(Caller("boss@x.com"), gate) and not svc.approval_exception(Caller("boss@x.com"), gate)
    assert not svc.can_approve(Caller("other@x.com"), gate)
    with pytest.raises(ServiceError):
        service()._check_approver(me, gate, "approve")  # without it, never the requester


def test_an_exception_approval_is_recorded_as_one():
    svc = service({"dev_approvers": ["dev@x.com"]})
    gate = {**GATE, "approvers": ["boss@x.com"]}
    svc.gate = lambda gate_id: dict(gate)
    written, events = [], []

    class Sql:
        def table(self, name):
            return name

        def one(self, statement, params=None):
            return None if "SELECT 1" in statement else {"n": 1}

        def run(self, statement, params=None):
            written.append(params)

    svc.sql = Sql()
    svc._approved = lambda g, actor, exception=None: events.append((actor, exception))
    svc.approve(Caller("dev@x.com"), "g1", "혼자 시험", "r1")
    assert written[0]["c"].startswith("[개발 예외 승인: 정책 dev_approvers, 본인 요청] 혼자 시험")
    assert events == [("dev@x.com", "dev_approver")]


def test_the_exception_lists_my_own_waiting_requests_to_approve():
    svc = service({"dev_approvers": ["dev@x.com"]})
    rows = [{**GATE, "gate_id": "mine", "requester": "dev@x.com"}]

    class Sql:
        def table(self, name):
            return name

        def run(self, statement, params=None):
            return [{"gate_id": "mine", "approvers": '["boss@x.com"]'}] if "agent_events" in statement else [dict(r) for r in rows]

    svc.sql = Sql()
    assert [r["gate_id"] for r in svc.gates(Caller("dev@x.com"), to_approve=True)] == ["mine"]
    svc.policy = lambda: (1, {**DEFAULT_POLICY})
    assert svc.gates(Caller("dev@x.com"), to_approve=True) == []


def test_policy_keeps_console_keys_and_takes_the_exception_from_the_cli():
    import argparse

    from aops import admin
    from aops.dbx.service import dev_approver_list

    args = argparse.Namespace(validation_mode="mandatory", approval_mode="auto", approver_group="", dev_approver=None, no_git=False,
                              git_connection=None, git_owner=None)
    body = admin.policy_body(args, {"approvers_required": True, "dev_approvers": ["dev@x.com"], "git": {"connection": "c", "owner": "o"}})
    assert body["approvers_required"] is True and body["dev_approvers"] == ["dev@x.com"] and body["git"]["owner"] == "o"
    args.dev_approver = []
    assert admin.policy_body(args, {"dev_approvers": ["dev@x.com"]})["dev_approvers"] == []
    assert dev_approver_list("a@x.com, b@x.com, a@x.com") == ["a@x.com", "b@x.com"]
    with pytest.raises(ServiceError):
        dev_approver_list(["not-an-email"])
