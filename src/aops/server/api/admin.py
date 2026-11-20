"""Administration: `aops admin setup`, `aops admin policy`, rate cards.

The first `admin setup` runs from the CLI because this server does not exist yet; afterwards an
admin screen can preview and re-apply it here. Only the admin group may call these routes.
"""

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ...dbx.service import ServiceError
from ..common import DBX, Page, command, todo
from ..dbx import caller_of, service_for

router = APIRouter(prefix="/admin", tags=["관리자"])


class SetupItem(BaseModel):
    resource: str = Field(examples=["schema main.aops", "job aops-validate", "app aops-server"])
    action: Literal["create", "update", "none"]
    detail: str | None = None


class SetupPlan(BaseModel):
    items: list[SetupItem]
    grants: list[str] = Field(default_factory=list, examples=[["GRANT SELECT ON SCHEMA main.aops TO `agent-developers`"]])


class SetupApply(BaseModel):
    api_callers: list[str] = Field(default_factory=list, examples=[["group:portal-users", "sp:portal-backend"]], description="custom: Custom Front가 쓸 그룹·서비스 주체. aops 서버 앱의 `CAN USE`를 준다")


class Policy(BaseModel):
    """Admin policy. Defaults apply when a key is missing."""

    validation_mode: dict[str, Any] = Field(default_factory=lambda: {"default": "mandatory"}, examples=[{"default": "mandatory", "rules": [{"security_level": "general", "upgrade_type": "patch", "mode": "optional"}]}])
    approval_mode: dict[str, Any] = Field(default_factory=lambda: {"default": "required"}, examples=[{"default": "required"}])
    approval_channel: Literal["console", "external"] = "console"
    approvers: str = Field(examples=["group:agent-approvers"])
    required_approvals: int = 1
    security_levels: list[dict[str, str]] = Field(
        default_factory=lambda: [
            {"code": "general", "label": "일반"}, {"code": "important", "label": "중요"}, {"code": "secret", "label": "기밀"},
        ]
    )
    no_source_when: dict[str, Any] = Field(default_factory=lambda: {"security_level_at_least": "important", "data_sensitivity": ["confidential"]})
    min_scores: dict[str, float] = Field(default_factory=dict, examples=[{"correctness": 0.8, "safety": 1.0}])
    allowed_models: list[str] = Field(default_factory=list)
    required_guardrails: dict[str, list[str]] = Field(default_factory=dict, examples=[{"confidential": ["kr-pii", "jailbreak"]}])


class PolicyVersion(BaseModel):
    policy_version: int = Field(examples=[4])
    status: Literal["active", "retired"] = "active"
    created_by: str
    created_at: datetime
    policy: dict[str, Any] = Field(description="지금 쓰는 정책 본문: validation_mode, approval_mode, approver_group, git 등")


class PolicyChange(BaseModel):
    """What the console changes (the same keys as `aops admin setup --only policy`). Other keys (Git) stay."""

    validation_mode: Literal["mandatory", "optional", "exempt"] | None = None
    approval_mode: Literal["required", "optional", "auto"] | None = None
    approver_group: str | None = None
    approvers_required: bool | None = Field(None, description="true: 에이전트마다 SPEC.md approvers(지정 승인자)가 있어야 한다 (없으면 셀프 체크·평가 ERROR)")
    dev_approvers: list[str] | None = Field(None, examples=[["dev@example.com"]],
                                            description="개발용 예외: 이 사람들은 본인 요청을 포함해 어떤 요청이든 승인할 수 있다. 승인마다 예외로 기록된다. 운영에서는 비운다")


class PolicySet(BaseModel):
    policy: Policy | None = Field(None, description="구조로 주거나")
    toml: str | None = Field(None, description="`policy.toml` 원문으로 준다")


class PolicyDiff(BaseModel):
    from_version: int
    to_version: int
    changes: list[dict[str, Any]] = Field(examples=[[{"key": "min_scores.correctness", "from": 0.75, "to": 0.8}]])


class RateCard(BaseModel):
    model: str = Field(examples=["databricks-claude-sonnet-4-6"])
    input_usd_per_mtok: float = Field(examples=[3.0])
    output_usd_per_mtok: float = Field(examples=[15.0])
    cached_input_usd_per_mtok: float | None = None
    valid_from: datetime
    valid_to: datetime | None = None


@router.get("/setup", summary="조직 자원 준비 계획 (미리 보기)", **command("aops admin setup", DBX))
def setup_plan() -> SetupPlan:
    raise todo("aops admin setup")


@router.post("/setup", summary="조직 자원 준비 적용", **command("aops admin setup --apply", DBX))
def setup_apply(body: SetupApply) -> SetupPlan:
    raise todo("aops admin setup --apply")


@router.get("/policies", summary="정책 버전 목록", **command("aops admin policy show", DBX))
def list_policies(request: Request, cursor: str | None = None) -> Page[PolicyVersion]:
    svc = service_for("aops admin policy show")
    caller_of(request, svc)
    return Page(items=[_policy(r) for r in svc.policies()])


@router.get("/policies/current", summary="현재 정책", **command("aops admin policy show", DBX))
def current_policy(request: Request) -> PolicyVersion:
    svc = service_for("aops admin policy show")
    caller_of(request, svc)
    rows = [r for r in svc.policies() if r["status"] == "active"]
    if not rows:
        raise ServiceError(404, "no_policy", "적용된 정책이 없습니다", "aops admin setup --only policy")
    return _policy(rows[0])


@router.post("/policies", status_code=201, summary="정책 올리기", **command("aops admin policy set", DBX))
def set_policy(body: PolicyChange, request: Request) -> PolicyVersion:
    svc = service_for("aops admin policy set")
    return _policy(svc.set_policy(caller_of(request, svc), body.model_dump(exclude_none=True)))


def _policy(row: dict) -> PolicyVersion:
    return PolicyVersion(**{**row, "policy": row["body"]})


@router.get("/policies/diff", summary="정책 버전 비교", **command("aops admin policy diff", DBX))
def diff_policy(from_version: int, to_version: int | None = None) -> PolicyDiff:
    raise todo("aops admin policy diff")


PromptKind = Literal["common", "skill", "code", "no_code"]


class ChecklistItem(BaseModel):
    id: str = Field(examples=["internal_info"])
    title: str = Field(examples=["사내 정보(임직원 신상, 내부 호스트·URL, 고객·거래처·영업 정보, 비공개 계획)가 들어 있지 않다"])


class ReviewPrompt(BaseModel):
    kind: PromptKind = Field(description="common(모든 에이전트) · skill · code · no_code")
    version: int = Field(examples=[1], description="0이면 aops에 든 기본 프롬프트 (아직 바꾼 적 없음)")
    body: str = Field(description="Markdown. '## 체크리스트' 아래 '- <id>: <통과 조건>' 줄이 리포트 항목")
    note: str | None = None
    created_by: str
    created_at: datetime | None = None
    checklist: list[ChecklistItem] = Field(default_factory=list)


class ReviewPromptRow(BaseModel):
    kind: PromptKind
    prompt_version: int
    status: Literal["active", "retired"]
    note: str | None = None
    created_by: str
    created_at: datetime


class ReviewPrompts(BaseModel):
    active: dict[PromptKind, ReviewPrompt] = Field(description="지금 평가가 쓰는 프롬프트 (종류별)")
    history: list[ReviewPromptRow] = Field(default_factory=list, description="올린 버전들 (최신 먼저)")


class ReviewPromptChange(BaseModel):
    kind: PromptKind
    body: str
    note: str | None = Field(None, examples=["사내 프로젝트 코드명 목록을 사내 정보에 더함"])


_PROMPTS_NOTE = ("배포 전 평가(Gate)의 내용 검토 프롬프트 4개(공통·스킬·코드·노코드). 평가 Job의 모델이 도구로 에이전트의 모든 파일을 읽고 "
                 "공통 + 종류별 프롬프트의 체크리스트를 판정해 승인자용 리포트를 쓴다. 바꾸면 그 종류의 새 버전이 생기고 평가 기록에 쓴 버전이 남는다.")


@router.get("/review-prompts", summary="평가 프롬프트 (내용 검토)", **command(None, DBX, screen="console 정책 → 평가 프롬프트", note=_PROMPTS_NOTE))
def list_review_prompts(request: Request) -> ReviewPrompts:
    svc = service_for(None)
    caller_of(request, svc)
    return ReviewPrompts(**svc.review_prompts())


@router.post("/review-prompts", status_code=201, summary="평가 프롬프트 새 버전", **command(
    None, DBX, screen="console 정책 → 평가 프롬프트", note=_PROMPTS_NOTE + " 워크스페이스 관리자만. 체크리스트가 없거나 항목 ID가 겹치면 400."))
def set_review_prompt(body: ReviewPromptChange, request: Request) -> ReviewPrompt:
    svc = service_for(None)
    return ReviewPrompt(**svc.set_review_prompt(caller_of(request, svc), body.kind, body.body, body.note))


@router.get("/rate-cards", summary="모델 단가표 (설계)", **command(None, DBX, screen="(설계) console 관리자 · 단가표"))
def list_rate_cards() -> list[RateCard]:
    raise todo(None)


@router.put("/rate-cards", summary="모델 단가표 바꾸기 (설계)", **command(None, DBX, screen="(설계) console 관리자 · 단가표"))
def put_rate_cards(body: list[RateCard]) -> list[RateCard]:
    raise todo(None)
