"""Live progress of an evaluation, for the people waiting on it.

The evaluate Job keeps one small JSON document per run in the registry volume `aops_runs` and rewrites it about
once a second and at every step change; the server hands it out at `GET /evaluations/{id}/progress`. It carries
step states, a percentage, what is being done now (which file is read, what is searched, which question is asked)
and the recent activity. Paths and counts only, never file contents. It is best effort: if it cannot be written the
evaluation goes on, and the final report stays in `validation_runs` as before.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Callable

# kind → the steps in order: (name, title, weight). The weights make the percentage (the review is most of it).
STEPS: dict[str, list[tuple[str, str, int]]] = {
    "skill": [("load", "버전 읽기", 3), ("format", "형식 검사", 4), ("review", "내용 검토", 58), ("evaluate", "평가셋 채점", 33),
              ("record", "기록", 2)],
    "code": [("load", "버전 읽기", 3), ("format", "형식 검사", 4), ("review", "내용 검토", 91), ("record", "기록", 2)],
    "no_code": [("load", "버전 읽기", 3), ("format", "형식 검사", 4), ("review", "내용 검토", 48), ("evaluate", "벤치마크", 40),
                ("integrity", "무결성", 3), ("record", "기록", 2)],
}
GENERIC = [("load", "버전 읽기", 3), ("format", "형식 검사", 4), ("review", "내용 검토", 60), ("evaluate", "품질 평가", 31),
           ("record", "기록", 2)]
FINISHED = ("done", "warned", "failed", "skipped")

# What a search of the review looks for, in words (from the model's own pattern; nothing is made up). Order = shown order.
SEARCH_KINDS = [
    ("웹 링크 주소", re.compile(r"https?|url\\?\(|www", re.I)),
    ("이메일 주소", re.compile(r"@\[|@\\w|@\(|\]\+@|e-?mail", re.I)),
    ("IP 주소", re.compile(r"\\d\{1,3\}\\\.|\\d\+\\\.\\d|192\\\.168|\b10\\\.|\bip\b", re.I)),
    ("비밀값(비밀번호·토큰·키)", re.compile(r"pass(word|wd)?|pwd|secret|token|api[_\-\[ ]?key|apikey|dapi|ghp_|akia|private|bearer|credential", re.I)),
    ("작업 메모(TODO·FIXME)", re.compile(r"todo|fixme|xxx|hack", re.I)),
    ("전화번호", re.compile(r"010|phone|tel\b|전화|\\d\{3\}-\\d\{4\}", re.I)),
    ("카드·주민번호", re.compile(r"\\d\{4\}[^|]{0,8}\\d\{4\}[^|]{0,8}\\d\{4\}|\\d\{6\}-|card|카드|주민", re.I)),
    ("내부 도메인·호스트", re.compile(r"internal|corp|intranet|\\?\.local|localhost|사내", re.I)),
]
WORD = re.compile(r"[A-Za-z가-힣][A-Za-z가-힣0-9_]{2,}")
REGEX_WORDS = {"todo", "fixme", "xxx", "hack", "http", "https", "url", "www", "mail", "email", "password", "passwd", "pwd", "secret",
               "token", "apikey", "dapi", "ghp", "akia", "private", "bearer", "credential", "phone", "tel", "card", "internal", "corp",
               "intranet", "local", "localhost", "key", "import"}


def _particle(text: str) -> str:
    core = re.sub(r"\([^)]*\)$", "", text).strip()
    last = core[-1:] if core else ""
    return "을" if "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 else "를"


def search_words(pattern: str) -> str:
    """What a search pattern looks for, in words: kinds it matches, then the plain words it names."""
    labels = [label for label, kind in SEARCH_KINDS if kind.search(pattern)]
    plain = re.sub(r"\\[A-Za-z]|\[[^\]]*\]|\{[^}]*\}", " ", pattern)  # no regex escapes, classes or counts as words
    words = [w for w in dict.fromkeys(WORD.findall(plain)) if w.lower() not in REGEX_WORDS and not w.lower().startswith(("pass", "api"))]
    if words:
        labels.append("키워드(" + ", ".join(words[:3]) + (" …" if len(words) > 3 else "") + ")")
    if not labels:
        return "파일 내용"
    return ", ".join(labels[:3]) + (" 등" if len(labels) > 3 else "")
EVENTS = 40  # recent activity kept in the document


def iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Progress:
    def __init__(self, run_id: str, sink: Callable[[dict[str, Any]], None] | None = None,
                 clock: Callable[[], float] = time.time, every: float = 1.0):
        self.run_id, self.sink, self.clock, self.every = run_id, sink, clock, every
        self.started = self.since = clock()
        self.steps = [self._step(*s) for s in GENERIC]
        self.stage: str | None = None
        self.message = "평가를 시작합니다"
        self.status = "running"
        self.review: dict[str, Any] | None = None
        self.quality: dict[str, Any] | None = None
        self.events: list[dict[str, str]] = []
        self._written = 0.0
        self._failures = 0

    @staticmethod
    def _step(name: str, title: str, weight: int) -> dict[str, Any]:
        return {"name": name, "title": title, "weight": weight, "state": "wait", "fraction": 0.0, "detail": None}

    def _find(self, name: str) -> dict[str, Any] | None:
        return next((s for s in self.steps if s["name"] == name), None)

    # ── what happens ─────────────────────────────────────────────────────────

    def kind(self, kind: str) -> None:
        """The steps of this kind of agent (known once the version is read); finished steps keep their state."""
        known = {s["name"]: s for s in self.steps}
        self.steps = [{**self._step(*s), **{k: known[s[0]][k] for k in ("state", "fraction", "detail")}} if s[0] in known
                      else self._step(*s) for s in STEPS.get(kind, GENERIC)]

    def begin(self, name: str, message: str) -> None:
        step = self._find(name)
        if step:
            step["state"], step["fraction"] = "running", 0.0
        self.stage = name
        self.doing(message, force=True)

    def end(self, name: str, state: str, detail: str | None = None) -> None:
        step = self._find(name)
        if step:
            step["state"], step["fraction"], step["detail"] = state, 1.0, detail
        self.flush(force=True)

    def doing(self, message: str, fraction: float | None = None, event: bool = True, force: bool = False,
              detail: str | None = None) -> None:
        """What is being done now (and, for the step running, how far it is). `detail`: the exact thing (a search
        pattern) kept with the activity for whoever wants it."""
        if message != self.message:
            self.message, self.since = message, self.clock()
            if event:
                entry = {"at": iso(self.since), "text": message, **({"detail": detail[:300]} if detail else {})}
                self.events = (self.events + [entry])[-EVENTS:]
        step = self._find(self.stage) if self.stage else None
        if step and fraction is not None:
            step["fraction"] = max(step["fraction"], min(1.0, max(0.0, fraction)))
        self.flush(force=force)

    def finish(self, status: str, reason: str | None = None) -> None:
        for step in self.steps:
            if step["state"] not in FINISHED:
                step["state"] = "skipped" if status != "error" else ("failed" if step["state"] == "running" else "skipped")
        self.status, self.stage = "done", None
        word = {"passed": "평가가 끝났습니다", "failed": "평가가 끝났습니다 (실패한 단계가 있습니다)",
                "stale": "평가가 끝났습니다 (그 사이 개발용 정의가 바뀌었습니다)"}.get(status, f"평가를 끝내지 못했습니다: {reason or status}")
        self.doing(word, force=True)

    # ── the review and the quality evaluation report here ───────────────────

    def review_event(self, event: str, info: dict[str, Any]) -> None:
        """From aops.dbx.review: each model call and tool call, with how much has been read."""
        self.review = {k: info.get(k) for k in ("turn", "max_turns", "files_done", "files_total", "lines_read", "lines_total")}
        self.review["current"] = [f["path"] for f in info.get("files") or []][:5]
        share = (info.get("lines_read") or 0) / max(1, info.get("lines_total") or 0)
        if event == "turn":
            text = f"모델이 다음 할 일을 정하는 중 (호출 {info.get('turn')}/{info.get('max_turns')})"
        elif event == "list_files":
            text = "파일 목록을 확인합니다"
        elif event == "read":
            names = [f"{f['path']} ({f['start']}~{f['end']}줄)" if f.get("end") else f["path"] for f in info.get("files") or []]
            text = "읽는 중: " + ", ".join(names[:2]) + (f" 외 {len(names) - 2}개" if len(names) > 2 else "")
        elif event == "search":
            what = search_words(str(info.get("pattern") or ""))
            hits = int(info.get("hits") or 0)
            text = f"{what}{_particle(what)} 검사하고 있습니다 (찾은 곳 {hits if hits else '없음'})"
        elif event == "refused":
            parts = [f"끝까지 읽지 않은 파일 {info['unread']}개" if info.get("unread") else "",
                     f"빠진 항목 {info['missing']}개" if info.get("missing") else ""]
            text = "리포트를 돌려보냈습니다: " + ", ".join(p for p in parts if p) + " (다시 읽게 함)"
        elif event == "submitted":
            text = f"체크리스트 {info.get('items', 0)}개 항목 판정을 받았습니다"
            share = 1.0
        else:
            text = event
        self.doing(text, fraction=share if event == "submitted" else min(0.95, share), event=event != "turn" or info.get("turn") == 1,
                   detail=f"검색 패턴: {info.get('pattern')}" if event == "search" else None)

    def quality_event(self, done: int, total: int, label: str) -> None:
        """From the eval set (a question at a time) or the Genie benchmarks (polled counts)."""
        self.quality = {"done": done, "total": total, "label": label}
        self.doing(label, fraction=done / max(1, total))

    # ── the document ────────────────────────────────────────────────────────

    def percent(self) -> int:
        total = sum(s["weight"] for s in self.steps) or 1
        got = sum(s["weight"] * (1.0 if s["state"] in FINISHED else s["fraction"]) for s in self.steps)
        return 100 if self.status == "done" else min(99, int(got * 100 / total))

    def document(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "status": self.status, "stage": self.stage, "percent": self.percent(),
                "message": self.message, "since": iso(self.since), "started_at": iso(self.started), "updated_at": iso(self.clock()),
                "steps": [{k: s[k] for k in ("name", "title", "state", "fraction", "detail")} for s in self.steps],
                "review": self.review, "quality": self.quality, "events": list(reversed(self.events))}

    def flush(self, force: bool = False) -> None:
        if self.sink is None:
            return
        now = self.clock()
        if not force and now - self._written < self.every:
            return
        self._written = now
        try:
            self.sink(self.document())
        except Exception:
            self._failures += 1
            if self._failures >= 5:  # the volume is not there or not writable: stop trying, the evaluation goes on
                self.sink = None
