"""The live progress of an evaluation (aops.dbx.progress): what the Job writes, what the server and the CLI show."""

import io
import json
from types import SimpleNamespace

import pytest

from aops.dbx import progress as progress_mod
from aops.dbx.progress import Progress


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


def test_the_percentage_follows_the_steps_and_their_weights():
    clock, written = Clock(), []
    p = Progress("r1", written.append, clock=clock)
    p.begin("load", "버전 zip을 읽는 중")
    p.kind("code")  # code: load · format · review · record
    p.end("load", "done", "파일 33개")
    assert [s["name"] for s in p.steps] == ["load", "format", "review", "record"] and p.steps[0]["state"] == "done"
    p.begin("format", "형식 검사")
    p.end("format", "done")
    p.begin("review", "내용 검토를 시작합니다")
    p.review_event("read", {"files_done": 10, "files_total": 31, "lines_read": 3000, "lines_total": 6000, "turn": 4, "max_turns": 24,
                            "files": [{"path": "agent/agent.py", "start": 1, "end": 120}]})
    middle = p.percent()
    assert 40 < middle < 60  # 7 of 100 done, half of the review's 91
    assert p.message == "읽는 중: agent/agent.py (1~120줄)" and p.document()["review"]["current"] == ["agent/agent.py"]
    p.review_event("submitted", {"files_done": 31, "files_total": 31, "lines_read": 6000, "lines_total": 6000, "items": 10})
    assert p.percent() > middle and p.percent() < 100
    p.finish("passed")
    doc = p.document()
    assert doc["status"] == "done" and doc["percent"] == 100 and doc["steps"][-1]["state"] == "skipped"  # record never begun
    assert doc["events"][0]["text"] == "평가가 끝났습니다"  # newest first


def test_writes_are_throttled_except_at_step_changes_and_a_failing_volume_is_given_up():
    clock, written = Clock(), []
    p = Progress("r1", written.append, clock=clock, every=1.0)
    p.begin("review", "내용 검토")  # a step change: written now
    for n in range(5):
        p.review_event("search", {"pattern": f"p{n}", "hits": n})  # within the same second: kept, not written
    assert len(written) == 1
    clock.t += 1.5
    p.review_event("search", {"pattern": "later", "hits": 1})
    assert len(written) == 2 and written[-1]["message"] == "키워드(later)를 검사하고 있습니다 (찾은 곳 1)"
    assert written[-1]["events"][0]["detail"] == "검색 패턴: later"  # the exact pattern stays with the activity

    def broken(document):
        raise OSError("no volume")

    q = Progress("r2", broken, clock=clock)
    for _ in range(6):
        q.begin("load", "x")
    assert q.sink is None  # five failures: the evaluation goes on without it


def test_the_activity_keeps_the_latest_and_the_quality_counts():
    p = Progress("r1", clock=Clock())
    p.begin("evaluate", "평가셋 채점을 시작합니다")
    for n in range(progress_mod.EVENTS + 5):
        p.quality_event(n, 50, f"평가셋 {n + 1}/50")
    doc = p.document()
    assert len(doc["events"]) == progress_mod.EVENTS and doc["events"][0]["text"] == f"평가셋 {progress_mod.EVENTS + 5}/50"
    assert doc["quality"] == {"done": progress_mod.EVENTS + 4, "total": 50, "label": f"평가셋 {progress_mod.EVENTS + 5}/50"}


def test_the_review_reports_each_model_call_and_tool_call():
    from test_review import FILES, ITEMS, prompts, scripted, submit, tool_call

    from aops.dbx import review

    heard = []
    call = scripted([tool_call("list_files", {})],
                    [tool_call("read_files", {"files": [{"path": "SPEC.md"}, {"path": "agent/instructions.md", "end_line": 1}]}),
                     tool_call("search", {"pattern": "사번"})],
                    [submit(ITEMS)])
    review.review(None, FILES, "skill", prompts(), {}, "a", call=call, on_event=lambda event, info: heard.append((event, info)))
    assert [e for e, _ in heard] == ["turn", "list_files", "turn", "read", "search", "turn", "submitted"]
    read = dict(heard)["read"]
    assert read["files"] == [{"path": "SPEC.md", "start": 1, "end": 0}, {"path": "agent/instructions.md", "start": 1, "end": 1}]
    assert read["files_done"] == 2 and read["files_total"] == 2 and read["lines_read"] == read["lines_total"] == 5
    assert dict(heard)["search"]["hits"] == 1 and heard[-1][1]["items"] == 3

    def loud(event, info):
        raise RuntimeError("the screen is gone")

    assert review.review(None, FILES, "skill", prompts(), {}, "a", call=scripted(
        [tool_call("read_files", {"files": [{"path": "SPEC.md"}, {"path": "agent/instructions.md"}]})], [submit(ITEMS)]), on_event=loud)["verdict"]


def test_the_job_writes_the_document_as_it_goes(monkeypatch):
    from test_gate import REVIEW, gate_service, skill_files

    from aops.dbx import gate_eval, review

    svc = gate_service(skill_files())
    written = []
    svc.w.files.upload = lambda path, data, overwrite=False: written.append((path, json.loads(data.read())))

    def reviewing(*a, on_event=None, **k):
        on_event("read", {"files_done": 1, "files_total": 3, "lines_read": 10, "lines_total": 30, "turn": 2, "max_turns": 24,
                          "files": [{"path": "agent/instructions.md", "start": 1, "end": 10}]})
        return dict(REVIEW)

    def scoring(w, files, spec, policy, on_progress=None):
        on_progress(0, 2, "평가셋 1/2: 질문")
        return {"name": "evaluate", "status": "passed", "detail": "정확도 100%"}, []

    monkeypatch.setattr(review, "review", reviewing)
    monkeypatch.setattr(gate_eval, "evaluate_skill", scoring)
    report = svc.run_evaluation("r1")
    assert report["status"] == "passed"
    assert {path for path, _ in written} == {"/Volumes/c/s/aops_runs/r1.json"}
    messages = [doc["message"] for _, doc in written]
    assert messages[0] == "버전 zip을 읽는 중" and "읽는 중: agent/instructions.md (1~10줄)" in messages
    assert "평가셋 1/2: 질문" in messages
    last = written[-1][1]
    assert last["status"] == "done" and last["percent"] == 100
    assert [(s["name"], s["state"]) for s in last["steps"]] == [("load", "done"), ("format", "done"), ("review", "done"),
                                                                ("evaluate", "done"), ("record", "done")]
    assert any("CREATE VOLUME IF NOT EXISTS c.s.aops_runs" in stmt for stmt, _ in svc.sql.statements)


def test_the_server_reads_the_document_or_tells_the_job_state():
    from test_gate import gate_service, skill_files

    svc = gate_service(skill_files())
    doc = {"run_id": "r1", "status": "running", "stage": "review", "percent": 40, "message": "읽는 중: a.py", "steps": [], "events": []}
    svc.w.files.download = lambda path: SimpleNamespace(contents=io.BytesIO(json.dumps(doc).encode()))
    got = svc.evaluation_progress("r1")
    assert got["percent"] == 40 and got["message"] == "읽는 중: a.py" and "run_status" in got

    def missing(path):
        raise FileNotFoundError(path)

    svc.w.files.download = missing
    svc.evaluation = lambda run_id, results=False: {"validation_run_id": "r1", "status": "queued", "job_run_id": 77, "started_at": "2026-11-20T00:00:00Z"}
    life = SimpleNamespace(value="PENDING")
    svc.w.jobs = SimpleNamespace(get_run=lambda run_id: SimpleNamespace(state=SimpleNamespace(life_cycle_state=life), run_page_url="https://ws/jobs/1/runs/77"))
    waiting = svc.evaluation_progress("r1")
    assert waiting["stage"] == "queued" and waiting["percent"] == 0 and "준비하는 중" in waiting["message"]
    assert waiting["job"] == {"state": "PENDING", "url": "https://ws/jobs/1/runs/77"}
    svc.evaluation = lambda run_id, results=False: {"validation_run_id": "r1", "status": "passed", "job_run_id": None, "started_at": None}
    assert svc.evaluation_progress("r1")["status"] == "done"


def test_the_progress_route(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from aops.dbx.service import Caller
    from aops.server import create_app
    from aops.server.api import lifecycle as routes

    doc = {"run_id": "r1", "status": "running", "run_status": "running", "stage": "review", "percent": 42, "message": "검색: 사번 → 1곳",
           "since": "2026-11-20T00:00:00Z", "steps": [{"name": "review", "title": "내용 검토", "state": "running", "fraction": 0.4, "detail": None}],
           "review": {"turn": 5, "max_turns": 24, "files_done": 3, "files_total": 9, "lines_read": 100, "lines_total": 400, "current": []},
           "quality": None, "events": [{"at": "2026-11-20T00:00:01Z", "text": "검색: 사번 → 1곳"}]}
    monkeypatch.setattr(routes, "service_for", lambda command: SimpleNamespace(evaluation_progress=lambda run_id: doc))
    monkeypatch.setattr(routes, "caller_of", lambda request, svc: Caller("dev@x.com"))
    answer = TestClient(create_app(edition="dbx")).get("/api/v1/evaluations/r1/progress")
    assert answer.status_code == 200 and answer.json()["percent"] == 42 and answer.json()["review"]["turn"] == 5


def test_the_cli_prints_a_line_when_what_the_job_does_changes(monkeypatch, capsys):
    from aops import lifecycle

    states = iter(["running", "running", "running", "passed"])
    messages = iter(["모델이 다음 할 일을 정하는 중 (호출 1/24)", "읽는 중: a.py", "읽는 중: a.py"])

    class Server:
        def request(self, method, path, **k):
            if path.endswith("/progress"):
                return {"percent": 30, "message": next(messages)}
            return {"status": next(states)}

    monkeypatch.setattr(lifecycle, "_poll", lambda server, path: server.request("GET", path))
    monkeypatch.setattr(lifecycle.time, "sleep", lambda s: None)
    assert lifecycle._wait_evaluation(Server(), "r1")["status"] == "passed"
    out = capsys.readouterr().out
    assert out.count("읽는 중: a.py") == 1 and "[ 30%] 모델이 다음 할 일을 정하는 중" in out


def test_a_search_is_told_in_words_from_its_own_pattern():
    from aops.dbx.progress import search_words

    assert search_words(r"(?i)url\(|https?://|TODO|FIXME|internal|@import") == "웹 링크 주소, 작업 메모(TODO·FIXME), 내부 도메인·호스트"
    assert search_words(r"[\w.+-]+@[\w-]+\.[\w.]+") == "이메일 주소"
    assert search_words(r"\b10\.\d+\.\d+\.\d+\b") == "IP 주소"  # regex escapes are not words
    assert search_words(r"010-\d{4}-\d{4}") == "전화번호"
    assert search_words(r"\d{4}-\d{4}-\d{4}-\d{4}") == "카드·주민번호"
    assert search_words(r"(?i)phoenix|aurora|피닉스|오로라|dapi[a-z0-9]{6,}|secret|password") == "비밀값(비밀번호·토큰·키), 키워드(phoenix, aurora, 피닉스 …)"
    assert search_words("") == "파일 내용"
    p = Progress("r1", clock=Clock())
    p.begin("review", "내용 검토")
    p.review_event("search", {"pattern": r"https?://", "hits": 0})
    assert p.message == "웹 링크 주소를 검사하고 있습니다 (찾은 곳 없음)"
