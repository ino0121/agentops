# aops v2 아키텍처

AgentOps(`aops`)는 에이전트의 전 라이프사이클(만들기 → 실험 → 평가 → 가드레일 → 등록 → 배포 → 운영)을 관리하는 오픈소스 도구다. **실행 엔진은 만들지 않는다.** 기존 하네스(Claude Code, Codex 같은 코딩 어시스턴트, 에이전트 프레임워크)와 플랫폼 SDK를 감싸는 래퍼다.

**대상 사용자는 두 부류다.** 에이전트를 만들고 쓰는 **개발자**는 자기 에이전트를 기록하고 평가하고 싶어서 aops를 쓴다. **관리자**는 조직에 등록·배포되는 에이전트가 정한 형식을 지키는지 관리한다. 그래서 **개발은 자유, 등록부터 강제**다 ([원칙 10](#1-설계-원칙)).

- 작성일: 2026-10-30 · 상태: 구현 전 최종 설계 (독립 검토 1회 + 실현 가능성 검토 반영)
- v1(`v1.3.0` 태그)은 참고만 한다. 코드는 가져오지 않는다.
- 버전·기능 상태는 작성일 기준이다. 하네스 소스·패키지 내용·공식 문서와 Databricks 워크스페이스 조회로 확인했다 ([14장](#14-실현-가능성-검토와-제한)). 확인하지 못한 것은 **확인 필요**로 표시했다.

> **실현 가능성 요약.** 핵심 기능인 하네스 간 이어가기는 만들 수 있다. 다만 하네스 내부 상태를 그대로 옮기는 것이 아니라 **요약·인계 파일·기록 조회 도구로 이어가는 방식**이다. 터미널 직접 실행 기록과 hook 가드레일은 하네스의 신뢰 승인과 회사 관리 설정에 따라 막힐 수 있다. dbx 기능 다수가 Beta이고, `aops monitor`의 "실시간"은 Databricks가 앱 실행 상태까지만 준다. 기능별 판정은 [14장](#14-실현-가능성-검토와-제한).
>
> **dbx는 Databricks 기능 위에서 돈다.** 에이전트 서버는 Agent Bricks `DurableAgentServer`(legacy Responses 서버 미사용), 로컬 채팅은 `agentbricks dev`, 검증은 Lakeflow Job, 레지스트리·승인 기록은 UC Delta 테이블, 운영 화면은 Databricks App이다 ([4.3](#43-dbx에서-쓰는-databricks-기능)).

---

## 0. 결정 사항

| 주제 | 결정 |
| --- | --- |
| 강제 범위 | **개발 단계에서는 아무것도 강제하지 않는다.** hook·기록·가드레일·평가는 사용자가 원해서 켜는 기능이고 언제든 끌 수 있다. 끄면 그만큼 기록이 남지 않을 뿐이다. 강제는 dbx·omni의 `validate`·`register`·`deploy`(그리고 이어지는 `approve`·`promote`)에서 관리자 정책을 코드로 검사할 때만 한다. local 에디션에는 강제가 없다 |
| 개발 기록 위치 | aops로 실행하면 기록된다. 어디에 남길지는 사용자가 정한다. local은 프로젝트 폴더, dbx 기본값은 **본인 Experiment**(`/Users/<me>/aops/<project>`)이고, 공유 위치는 사용자가 고를 때만 쓴다 |
| 하네스 전환 시점 | **사용자가 정한다.** Claude 사용량이 떨어지면 Codex로 넘어가는 판단은 사용자 몫이다. aops는 자동 전환이나 사용량 한도 감지를 하지 않고, 전환이 일어나면 맥락을 이어 붙이는 일만 한다 |
| 로그인 | aops는 로그인을 제공하거나 제한하지 않는다. 사용자가 하네스에 설정한 로그인(구독 로그인, API 키 등)을 그대로 쓴다. 구독 로그인일 때는 **사용자가 설치한 하네스 실행 파일을 그대로 구동**하고, 자격 증명을 읽거나 옮기거나 저장하지 않는다 (약관, [14.2](#142-하네스-codex--claude-code)) |
| dbx의 모델 호출 | **Unity AI Gateway 경유를 권장한다** (강제 아님). Gateway를 거치면 사용량·예산·기록이 자연스럽게 남는다 |
| 평가 기록 | `aops evaluate`는 **MLflow에 기록한다.** local은 프로젝트의 MLflow, dbx는 Databricks MLflow Experiment |
| 세션 정본 | local·dbx는 aops. omni는 Omnigent가 세션을 갖고 aops는 인계·비교·평가를 맡는다 |
| 1차 지원 하네스 | Codex, Claude Code. 나머지는 어댑터 인터페이스만 두고 뒤로 미룬다 |
| 에이전트 서버 (dbx) | Agent Bricks **`DurableAgentServer`**(`server = "agentbricks"`, `/api/invocations`)만 쓴다. MLflow `AgentServer`·`LongRunningAgentServer`(`/responses`, `ResponsesAgent`)는 공식 문서상 legacy라 쓰지 않는다. 로컬 실행과 채팅 화면은 `agentbricks dev`를 그대로 쓴다 |
| 검증 실행 (dbx) | `aops validate`는 **Databricks Lakeflow Job(서버리스)** 으로 돈다. 결과는 MLflow와 Delta 테이블에 남고, 이 Job의 결과만 배포 승인 근거가 된다 |
| 레지스트리·승인 (dbx) | 에이전트 레지스트리, 배포 승인 요청, 승인·반려, 배포·운영 지정 이력은 **UC Delta 테이블이 정본**이다. UC registered model과 MLflow는 버전과 평가를 잇는 데 쓴다 |
| 운영 화면 (dbx) | 모니터링·레지스트리·승인 화면은 **Databricks App(console App)** 으로 띄운다. 배포 승인은 이 화면에서만 한다. CLI `aops monitor`는 같은 데이터를 읽는 보조 수단이다 |

---

## 1. 설계 원칙

1. **실행 엔진은 만들지 않는다.** 에이전트 실행은 하네스, 플랫폼 기능은 `databricks-sdk`·`mlflow`·`databricks-agentbricks`·`omnigent`가 맡는다. Agent Bricks 에이전트의 서버(`DurableAgentServer`)와 로컬 채팅 화면(`agentbricks dev`)은 다시 만들지 않는다. aops가 직접 만드는 것은 1.1의 목록뿐이다.
2. **에디션은 누적되고, 기능별로 섞을 수 있다.** `local ⊂ dbx ⊂ omni`. 에디션은 기능별 구현체(provider)의 기본 조합이다. Beta 기능이 없는 환경에서는 그 기능만 local 구현을 쓸 수 있다.
3. **하네스 버전에 종속된다. 그래서 버전 고정이 기능이다.** aops 릴리스 하나는 검증된 상위 버전 묶음이다 ([11장](#11-버전-관리)).
4. **폴더 하나가 프로젝트다.** `aops init`이 만든 폴더 안에서 모든 실험·비교·평가를 한다. 하네스는 이 폴더의 프로젝트 설정을 읽으므로, **터미널에서 `claude`·`codex`를 직접 실행해도 같은 지시·스킬·도구·기록이 적용된다.** 단, 사용자가 하네스에서 이 폴더와 hook을 신뢰로 승인해야 하고, 회사 관리 설정이 프로젝트 hook을 막지 않아야 한다. 사용자가 hook을 끄면 그 실행은 기록되지 않는다 ([2.1](#21-기록-범위)).
5. **정본은 `aops.toml` 하나다.** `AGENTS.md`, `CLAUDE.md`, `.codex/`, `.claude/` 같은 하네스 설정은 생성물이다 (`aops.toml`이 바뀌면 aops가 다시 만든다).
6. **원본을 쌓고, 정리는 나중에 한다.** 하네스 출력 원본을 그대로 쌓고, 화면과 집계에 쓰는 정리된 이벤트는 버전이 붙은 변환기로 만든다. 하네스 출력 형식이 바뀌어도 과거 기록을 다시 정리할 수 있다.
7. **모든 저장 형식에 버전을 붙인다.** 설정(`config_version`), 이벤트(`schema_version`), 세션 저장. 형식이 바뀌면 aops를 올린 뒤 처음 실행할 때 백업하고 옮긴다 (`aops doctor --fix migrate`).
8. **세션과 메모리는 aops가 갖는다 (가장 중요).** 하네스를 바꿔도 대화·작업 맥락·메모리가 이어지도록 정본을 aops에 둔다. 하네스 고유 세션은 aops 세션의 한 구간이다 ([2장](#2-핵심-기능-하네스를-바꿔도-이어지는-세션과-메모리)).
9. **uv 기반.** 설치·실행·버전 고정을 모두 uv로 한다.
10. **개발은 자유, 등록부터 강제.**
    - 개발자는 원해서 기록(trace)하고 원해서 평가(evaluate)한다. aops는 hook을 끄거나 기록을 끄는 것을 막지 않고, 끈 것을 몰래 되살리거나 뒤에서 채우지 않는다. aops를 통해 실행하면 기록되고, 하네스를 직접 쓰면서 hook을 끄면 기록되지 않는다.
    - 개발 중 가드레일은 시험 도구다. 켜고 끄고 비교해 보는 용도이고 개발자를 막는 장치가 아니다.
    - 강제는 dbx·omni에서 조직 레지스트리에 올리는 순간(`validate`·`register`)과 배포하는 순간(`deploy` 이후)에 시작된다. 관리자가 정한 정책(형식·가드레일·평가 기준·승인)을 **코드로** 검사한다.
    - 강제 검사는 개발 중 기록에 기대지 않는다. 필요한 증거(평가 결과, 가드레일 시험)는 validate Job이 등록된 소스로 직접 만든다. 그래서 개발 중 hook을 꺼 둔 사람도 등록·배포에서 불리하지 않다.

### 1.1 aops가 직접 만드는 것

| 기능 | 직접 만드는 이유 |
| --- | --- |
| 세션 저장과 하네스 간 인계 | 하네스끼리 공통 세션 형식이 없다. 핵심 기능이다 |
| 이벤트 변환 | 하네스마다 출력 형식이 다르다. 도구·스킬 사용 횟수를 세려면 하나로 맞춰야 한다 |
| 배치 실행과 비교 | 하네스·모델·가드레일을 바꿔 같은 질문을 나란히 비교하는 상위 도구가 없다 |
| 2층 규칙 검사 | 정규식·허용 목록 수준의 작은 규칙 모음이다. hook으로 하네스에 붙인다 |
| 개발 화면 (`aops dev`) | Databricks AI Playground의 에이전트 구성 방식은 공식 문서에서 legacy로 표기됐고, 여러 하네스를 비교하는 로컬 화면이 없다. 한 에이전트의 채팅 시험은 `agentbricks dev` 화면을 쓴다 |
| 레지스트리·승인 테이블과 console App | 코드·하네스·스킬 에이전트의 버전·검증·배포 승인·운영 지정을 한곳에서 관리하는 Databricks 기능이 없다 (UC model은 버전, Apps는 실행만 담당). 저장은 Delta, 화면은 Databricks App, 검증은 Lakeflow Job으로 **Databricks 기능 위에** 만든다 |

그 외(모델 호출, 평가 채점, 기록 저장소, 배포, 실행 격리, dbx 장기 메모리 저장소, 작업 실행, 화면 호스팅)는 모두 상위 도구를 호출한다.

---

## 2. 핵심 기능: 하네스를 바꿔도 이어지는 세션과 메모리

**문제:** Claude Code를 쓰다 사용량이 떨어지면 Codex로 옮겨 계속 일하는 경우가 많다. 하네스마다 세션과 메모리를 자기 형식으로 따로 저장해서, 바꾸는 순간 대화와 작업 맥락이 끊긴다.

**원칙:** 세션과 메모리의 정본을 aops가 갖는다. 전환 시점은 사용자가 정하고, aops는 전환할 때 맥락을 이어 붙인다.

```text
aops 세션 S-0142 ──────────────────────────────────────────────────────────▶
  구간 1  Claude Code (터미널에서 직접 사용, 기록됨)  턴 1~7
          └ 사용자가 Codex로 전환 ─────────────────────▶ 인계
  구간 2  Codex (개발 화면)                            턴 8~12
          └ 사용자가 다시 Claude로 전환 ───────────────▶ 고유 재개 + 구간 2 보충
  구간 3  Claude Code                                  턴 13~
```

### 2.1 기록 범위

| 경로 | 기록 방법 |
| --- | --- |
| aops로 실행 (`aops run`, 개발 화면) | 어댑터가 직접 기록 |
| **프로젝트 폴더에서 `claude`·`codex`를 직접 실행** | aops가 넣어 둔 프로젝트 hook(`SessionStart`·`UserPromptSubmit`·`PostToolUse`·`Stop`)이 턴마다 `runs/`에 기록 |
| 이미 끝난 하네스 세션 | `aops session import`로 하네스의 기존 기록을 가져와 aops 세션으로 만든다 |

터미널 직접 실행 기록이 동작하는 조건:

| 조건 | Codex | Claude Code |
| --- | --- | --- |
| 프로젝트 신뢰 | 프로젝트 `.codex/`는 신뢰한 프로젝트에서만 읽는다. git worktree는 원래 저장소 기준으로 판정한다 | 대화형은 처음에 신뢰 확인 창이 뜬다. `-p`·SDK 실행은 확인 없이 프로젝트 hook을 실행한다 |
| hook 승인 | **hook마다 내용 해시로 승인한다.** aops가 hook 내용을 바꾸면 사용자가 `/hooks`에서 다시 승인해야 한다. aops가 대신 승인할 수 없다 | 별도 승인 없음 |
| 회사 관리 설정 | 관리 계층의 `features.hooks = false`, MCP 허용 목록으로 막을 수 있다 | `allowManagedHooksOnly`, `allowManagedMcpServersOnly`로 막을 수 있다. 관리 hook이 없으면 사용자가 `disableAllHooks`로 끌 수 있다 |
| 기록 방법 | 턴 ID는 `UserPromptSubmit`·`Stop`에서 얻는다 (`SessionStart`에는 없다) | 기록 파일이 늦게 써지므로 마지막 답변은 `Stop`의 `last_assistant_message`를 쓴다 |

- **사용자가 끈 기록은 aops가 되살리지 않는다.** hook을 지우거나 끄거나 `capture_terminal = false`(개발 화면 스위치)로 끄면 그 구간은 기록되지 않는다. 의도한 동작이다. aops는 하네스 기록을 뒤에서 읽어 채우지 않고, 사용자가 원할 때 직접 `aops session import`를 실행해야 가져온다.
- `aops doctor`는 기록이 켜져 있는지, 신뢰·승인이 됐는지를 **알려만** 준다. 사용자가 일부러 끈 상태는 경고가 아니라 "기록 꺼짐"으로 표시한다.
- hook 내용을 자주 바꾸지 않도록, 프로젝트 hook은 `aops hook <이벤트>`를 부르는 고정된 한 줄만 둔다. 규칙이 바뀌어도 hook 해시는 그대로다.

### 2.2 이어 붙이는 것

| 대상 | 내용 | 정본 위치 | 전환할 때 |
| --- | --- | --- | --- |
| 대화 기록 | 질문·답변·도구 호출과 결과 | aops 세션 저장소 (원본 + 정리된 이벤트) | 요약 + 최근 턴을 넘기고, 나머지는 필요할 때 조회 |
| 작업 상태 | 프로젝트 파일, 변경 내역(git diff), 진행 중인 계획·할 일 | 프로젝트 폴더 (모든 하네스가 같은 폴더 사용) | 폴더는 그대로 두고 변경 요약만 넘김 |
| 요약 | 결정 사항, 남은 일, 주의점 | aops 세션 저장소 | 넘김 |
| 장기 메모리 | 사용자 선호, 프로젝트 사실, 과거 결정 | local: `memory/` · dbx: Agent memory store | 현재 일과 관련된 항목만 넘김 |

### 2.3 전환 흐름

1. 사용자가 하네스를 바꾼다 (개발 화면의 하네스 목록, `aops session switch --harness codex`, 또는 터미널에서 다른 하네스를 바로 실행).
2. aops가 이전 구간을 닫고, 하네스 고유 세션 ID와 상태 위치를 구간에 기록한다.
3. 마지막 턴이 끝나지 않았으면 그 턴에 바뀐 파일·실행된 명령을 인계 내용에 넣는다 (2.7).
4. 인계 내용을 만들어 새 하네스에 넣는다 (2.4).
5. 같은 하네스로 돌아갈 때는 하네스 고유 재개를 먼저 쓰고, 그 사이 다른 하네스에서 진행된 내용만 보충한다 (2.5).

### 2.4 인계 방법: 파일 + 짧은 안내 + 조회 도구

인계 내용을 hook 하나로 한꺼번에 넣지 않는다. hook이 모델에 넘기는 문맥에는 크기 기준이 있다. Codex는 약 2,500 토큰, Claude Code는 10,000자다. 이를 넘으면 두 하네스 모두 전체 내용을 파일로 빼고 미리보기만 넘긴다. Claude 문서는 이 경우 모델이 파일을 읽도록 유도하지 않는다고 적고 있다.

| 구성 | 내용 |
| --- | --- |
| 인계 파일 | `.aops/handoff/<session>.md`: 요약, 최근 턴, 작업 상태, 관련 메모리. 하네스별 토큰 예산(`[session] handoff_tokens`)에 맞춘다 |
| 짧은 안내 | `SessionStart` hook의 `additionalContext`로 "다른 하네스에서 이어받은 세션. 인계 파일과 기록 조회 도구를 먼저 확인하라"는 안내와 파일 경로만 넣는다 (크기 기준 안) |
| 기록 조회 도구 | aops MCP 서버(`aops-recall`): 이전 턴 원문, 도구 결과, 변경 내역을 검색해 돌려준다. 새 하네스가 필요할 때 직접 꺼내 본다 |
| Codex 기록 주입 (aops가 구동할 때) | Codex app-server의 `thread/inject_items`(안정 API)로 이전 대화를 Codex 대화 기록에 직접 넣는다. 턴을 시작하지 않고 기록에 남는다. 터미널 직접 실행에는 쓸 수 없다 |

- **이어가기의 한계:** 하네스 내부 상태(도구 실행 원본, 추론 내용, 프롬프트 캐시)는 다른 하네스로 옮길 수 없다. Claude Code에는 외부 대화를 세션에 넣는 공식 방법이 없다. 새 하네스는 요약과 조회 도구로 맥락을 다시 잡으므로, 전환 직후 파일을 다시 읽는 토큰이 든다.

### 2.5 하네스 고유 상태 보존과 재개

- 하네스 설정(생성물)과 하네스 고유 상태(세션 기록 등)를 나눈다. 고유 상태는 구간마다 `runs/state/<segment>/`에 보존한다.
- 같은 하네스·같은 버전으로 돌아오면 고유 재개(`claude --resume`, Codex thread resume)를 쓴다. 버전이 바뀌었거나 재개가 실패하면 인계 방식으로 시작한다.
- **두 하네스 모두 버전이 달라도 재개된다는 보장을 문서에 적지 않았다.** Claude는 세션 파일 형식이 내부용이고 버전마다 바뀐다고 명시했다. 그래서 aops는 구간마다 실행 파일 경로와 버전을 기록하고, 같을 때만 고유 재개를 시도한다.
- Claude는 세션 파일을 기본 30일 뒤 지운다(`cleanupPeriodDays`). Codex 기록은 `CODEX_HOME`에 묶이고 `.jsonl.zst`로 압축될 수 있다. 그래서 aops는 원본을 `runs/events/`에 따로 보관한다.

### 2.6 요약

- 기본은 **규칙 기반 축약**이다 (최근 턴 원문, 도구 결과 앞부분, 변경 파일 목록). 별도 모델 없이 동작한다.
- 요약은 전환할 때마다 **원본 기록에서 새로 만든다.** 요약을 다시 요약하지 않아 내용이 흐려지지 않는다.
- 선택 사항으로 요약 모델을 지정할 수 있다: 새로 시작하는 하네스 자신, 사용자가 지정한 모델, dbx에서는 Gateway Model Service.
- 하네스 자체의 대화 압축 이벤트(두 하네스 모두 `PreCompact`·`PostCompact`)를 기록해 aops 요약과 맞춘다.

### 2.7 끝나지 않은 턴

- 턴마다 체크포인트를 남긴다: 턴 시작 시점의 git 상태와 도구 실행 기록.
- 전환할 때 끝나지 않은 턴이 있으면, 이미 바뀐 파일·실행된 명령을 화면과 인계 파일에 보여준다. 이어서 할지, 되돌리고 다시 할지는 사용자가 고른다.

### 2.8 장기 메모리

- 하네스가 메모리를 바꾸려 하면 바로 쓰지 않고 **제안**으로 쌓는다. 사용자가 승인한 것만 `memory/`에 들어간다.
- 하네스 자체 메모리 기능은 사용자가 고른다(`[memory] harness_memory = "keep" | "import" | "off"`, 기본 `keep`). `import`는 하네스 메모리를 aops 메모리 제안으로 가져오고, `off`일 때만 aops가 프로젝트 설정에서 하네스 메모리를 끈다. 기본값으로는 끄지 않는다.
  - Claude 자동 메모리: 기본으로 켜져 있다. 프로젝트 설정 `autoMemoryEnabled: false` 또는 `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`로 끈다. SDK는 설정 파일을 읽지 않게 해도 메모리를 읽으므로 따로 꺼야 한다.
  - Codex 메모리: `features.memories`는 기본 꺼짐이다. 켜져 있으면 `aops doctor`가 알린다.

### 2.9 에디션별 저장

| | local | dbx | omni |
| --- | --- | --- | --- |
| 세션 | `runs/` (SQLite + 원본 이벤트) | Agent sessions (`session_stores`, Lakebase 기반, Beta). 다른 PC·Databricks Sandbox에서도 같은 세션을 이어감 | **Omnigent 세션이 정본.** aops는 Omnigent 세션 사이의 인계와 기록 조회만 맡음 |
| 장기 메모리 | `memory/` (Markdown 정본 + SQLite 검색) | Agent memory stores (Lakebase 기반, Beta) | dbx와 동일 |
| 작업 상태 | 프로젝트 폴더 + git | 동일. Sandbox에는 파일 동기화 API가 없어 aops가 git이나 명령 실행으로 옮긴다 | Omnigent 호스트·Sandbox |

- dbx 세션·메모리 제한: 항목 크기·보존 기간이 문서에 없고, 권한은 저장소 단위뿐이다(항목별 권한 없음). Beta 기간에는 바탕이 되는 Lakebase 비용이 나간다. 내 PC에서 목록 조회는 확인했고, 쓰기는 3단계 전에 확인한다.

### 2.10 지켜야 할 것

- **개인정보·기밀:** 저장 전에 2층 규칙으로 가린다(기본값, 사용자가 끌 수 있음). `[memory] store_raw = false`면 원문 대신 요약만 저장한다 (dbx 기본값 `false`).
- **하네스 간 내용 이동:** 인계는 한 회사의 모델에서 다른 회사의 모델로 대화 내용을 넘긴다. 프로젝트 단위로 끌 수 있게 하고, 전환할 때 화면에 알린다.
- **같은 규칙 유지:** 새 하네스에도 같은 지시·스킬·도구·가드레일이 적용된다. 모두 `aops.toml`에서 만들기 때문이다.
- **이어가기 품질 시험:** 하네스 A로 1~2단계, 하네스 B로 3단계를 시킨 뒤 앞 단계의 사실·결정을 기억하는지 채점한다 (`aops evaluate --scenario handoff`, 결과는 MLflow).

---

## 3. 가드레일

세 층으로 켜고 끄고, **시험하고, 에이전트와 함께 배포한다.** 개발 중 가드레일은 개발자가 켜고 끄는 시험 도구이고, 운영에서 지킬 가드레일은 배포 구성(`[release.guardrails]`)에 따로 적어 validate가 관리자 정책대로 검사한다.

| 층 | 판단 방식 | local | dbx | omni |
| --- | --- | --- | --- | --- |
| 1층 지시 | 모델이 공통 지시를 따른다 | ● | ● | ● |
| 2층 규칙 | 정해진 규칙(정규식·허용 목록)으로 검사한다 | ● hook | ● + Gateway 결정적 정책 (개인정보 가림, SQL 정책) | ● + Omnigent 정책 (개발 세션은 사용자가 켤 때만, 배포 에이전트는 배포 구성대로) |
| 3층 판정 | 별도 판정 모델이 의미를 판단한다 | 선택 (hook 판정) | ● Gateway LLM 정책 (탈옥·유해·기밀 판정) | ● Gateway |

- **시험:** `aops evaluate --suite redteam`이 레드팀 사례를 배치로 돌려 층별 차단·통과·오탐을 표로 낸다. 배포한 에이전트에도 `--target deployed`로 같은 시험을 한다.
- **비교:** `[[variants]]`로 가드레일을 켠 구성과 끈 구성을 같은 질문으로 나란히 비교한다 (개발 화면 Batch 탭).
- **배포:** `aops deploy`가 가드레일을 에이전트와 함께 배포한다. 배포 패키지에 들어가는 것은 개발 중 스위치(`[guardrails]`)가 아니라 배포 구성(`[release.guardrails]`)이다. 개발 중에 꺼 두었어도 배포 구성이 관리자 정책을 만족하면 된다. Gateway 정책은 공개 API로 붙이거나 확인할 수 없어(문서상 UI 전용), aops는 붙여야 할 정책 목록과 확인 방법을 점검표로 보여주고 시험 질문으로 실제 차단되는지 확인한다. omni는 Omnigent 정책으로 넣는다.
- 판정은 `GuardrailDecision` 이벤트로 남아 화면의 🛡 배지와 `aops monitor`의 차단 집계에 쓰인다.

**제한:**
- hook 가드레일은 **완전한 차단 경계가 아니다** (두 하네스 문서 모두 명시). Codex의 호스팅 웹 검색에는 hook이 걸리지 않는다. 개발 중에는 이것으로 충분하다. 시험 도구이고, 사용자가 hook을 끄는 것도 허용하기 때문이다.
- 운영에서 반드시 막아야 하는 규칙은 배포된 에이전트 쪽에 둔다: 배포 패키지의 규칙, 배포 에이전트가 쓰는 Model Service의 Gateway 정책. validate가 이것이 관리자 정책대로 들어갔는지 검사한다. 회사가 개발 PC 자체를 통제하려고 하네스 관리 설정을 쓰는 것은 aops의 범위 밖이다.
- Gateway 서비스 정책은 Beta다. 차단되어도 HTTP 200에 안내 문장이 오므로, aops는 응답의 정책 정보로 차단 여부를 판단한다. Gateway의 판정 값은 `ALLOW`·`DENY`·`ASK`이고 aops의 `pass`·`block`으로 바꿔 기록한다.
- 관리형 Omnigent 정책은 CEL만 지원한다(사용자 Python 정책 불가). aops 2층 규칙은 CEL로 바꿀 수 있는 것만 omni에서 서버 정책이 된다. 개발 세션에는 사용자가 켤 때만 넣고, 배포한 관리형 에이전트에는 배포 구성대로 넣는다.

---

## 4. 에디션

| | local | dbx | omni |
| --- | --- | --- | --- |
| 대상 | 개인·오프라인 실험 | Databricks를 쓰는 조직 | Omnigent를 쓰는 조직 |
| 실행 위치 | 내 PC | 내 PC 또는 Databricks Sandbox | Omnigent 세션 (Databricks Sandbox 등) |
| 모델 연결 | 사용자가 하네스에 설정한 그대로 | **Unity AI Gateway 경유 권장** | Omnigent → Unity AI Gateway |
| 기록·평가 | 원본 이벤트 + 프로젝트 MLflow | UC trace 테이블 + Databricks MLflow Experiment | dbx와 동일 + Omnigent 세션 |
| 화면 | 로컬 개발 화면(웹 UI) | 로컬: 개발 화면 + `agentbricks dev` 채팅 화면 · 운영: **Databricks App (console App)** | Omnigent UI 안의 aops 화면 |
| 검증·승인·레지스트리 | 로컬 검사, 프로젝트 MLflow | **Lakeflow Job**으로 검증, **UC Delta 테이블**에 레지스트리·승인 기록 | dbx와 동일 |
| 설치 | `uv tool install "aops[local]"` | `uv tool install "aops[dbx]"` | `uv tool install "aops[omni]"` |

- **dbx는 local의 모든 기능을 Databricks 기능으로 바꾸고 기능을 더한다.** 실행 기록 → UC trace 테이블, 평가 → Databricks MLflow, 스킬 → UC Skills, 가드레일 → Gateway 서비스 정책, 세션·메모리 → Lakebase 기반 Agent sessions·memory, 실행 격리 → Databricks Sandbox, 에이전트 서버 → Agent Bricks `DurableAgentServer`, 검증 → Lakeflow Job, 레지스트리·승인 → UC Delta 테이블, 운영 화면 → Databricks App. 쓰는 기능 전체는 [4.3](#43-dbx에서-쓰는-databricks-기능).
- **omni는 dbx 기능 전부를 Omnigent UI에서 쓴다.** aops는 Omnigent 에이전트 정의(YAML)·정책·스킬 묶음을 만들고, Omnigent에 없는 배치 비교·평가·질문별 사용량·하네스 간 인계를 더한다.

### 4.1 dbx에서 Gateway 경유를 권장하는 이유

- 사용량이 남는다: `system.ai_gateway.usage`에 요청자, Model Service, 토큰, MCP 도구 이름(`mcp_metadata.tool_name`), 코딩 에이전트 종류(`session_metadata.coding_agent`)가 기록된다 (워크스페이스 조회로 컬럼 확인). 사용량 추적은 Gateway의 과금 기능이다.
- 사용자별 한도(요청·토큰 속도)와 예산(USD 기준 알림·차단)을 걸 수 있다.
- Gateway 가드레일 정책(2층 결정적 + 3층 판정)이 같은 경로에서 적용된다.
- 연결 방법: Codex는 `https://<workspace>/ai-gateway/codex/v1`(Responses), Claude Code는 `https://<workspace>/ai-gateway/anthropic`. 공식 `ug` CLI(`ug codex`, `ug claude`)로 설정한다. 검증 워크스페이스의 사용량 테이블에서 최근 30일간 두 경로의 호출 기록을 확인했다.
- **주의:** Claude Code에 Gateway 주소만 넣고 Gateway 토큰을 넣지 않으면, 저장된 claude.ai 로그인이 그대로 자격 증명으로 쓰인다. aops는 주소와 토큰이 함께 설정됐는지 `aops doctor`로 점검한다.
- **앱이 부르면 앱 서비스 주체로 기록된다.** 배포한 에이전트의 최종 사용자별 사용량은 사용자 권한 전달(OBO)이나 요청 태그로 따로 남겨야 한다 ([9장 monitor](#aops-monitor---me----all---watch---web-dashboard)).
- 강제하지 않는다. Gateway를 쓰지 않으면 aops 원본 이벤트의 사용량만 집계된다.

### 4.2 기능별 조합

```toml
[providers]            # 생략하면 edition의 기본 조합
trace = "dbx"
memory = "local"       # 예: 워크스페이스에 Agent memory 프리뷰가 꺼져 있을 때
```

### 4.3 dbx에서 쓰는 Databricks 기능

라이프사이클 단계마다 Databricks 기능을 그대로 쓴다. aops는 이것들을 한 프로젝트 정의(`aops.toml`)로 묶고 순서(등록 → 검증 → 승인 → 배포 → 운영 지정)를 강제한다. 상태는 작성일 기준 공식 문서 표기이고, –는 확인한 문서에 프리뷰 표기가 없다는 뜻이다.

| 단계 | Databricks 기능 | 상태 | aops에서 |
| --- | --- | --- | --- |
| 만들기·로컬 실행 | Agent Bricks CLI `init`·`dev`, AgentKit `DurableAgentServer`, 채팅 화면 | CLI Beta | `aops init --edition dbx`, `aops dev` |
| 모델 호출 | Unity AI Gateway Model Service (`system.ai.*` 포함) | – | 모든 하네스·에이전트의 기본 경로 (권장) |
| 도구 | managed MCP(`system.ai.*`, 코드 실행용 `system.ai.sandbox`), UC MCP Service, UC function, Genie | – | `aops add tool` → `agentbricks tools add` |
| 스킬 | UC Skills | Beta | `aops register`가 게시 |
| 세션·메모리 | Agent sessions·memory stores (Lakebase), 메모리 파이프라인 | Beta | `aops session`·`aops memory` |
| 실행 격리 | Databricks Sandbox | Beta | 로컬 배치 분산, 배포 에이전트의 셸 실행 (`system.ai.sandbox` MCP) |
| 실행 기록 | MLflow 3 trace를 UC 테이블에 저장 (`<prefix>_otel_spans`) | – | `aops session show`, 개발 화면 기록 탭 |
| 평가 | `mlflow.genai.evaluate`, UC 평가 데이터셋, production monitoring | monitoring Beta | `aops evaluate`, `aops validate` 안의 평가 단계 |
| 검증 실행 | **Lakeflow Jobs (서버리스)**, 번들(`databricks.yml`)로 정의 | – | `aops validate` |
| 등록 | UC registered model + MLflow LoggedModel, UC Volume(소스 스냅샷) | – | `aops register` |
| 레지스트리·승인 기록 | **UC managed Delta 테이블**, multi-statement transaction(`BEGIN ATOMIC`), governed tags | – | `aops register`·`deploy`·`approve`·`promote` |
| 승인 흐름 연결 | MLflow **deployment jobs** (UC 모델 버전 → 평가·승인·배포 Job) | Public Preview, 승인 기능 experimental | 켜져 있으면 승인 단계를 이것으로 연결 (9장) |
| 가드레일 | Gateway 서비스 정책 | Beta | `aops evaluate --suite redteam`, `[release.guardrails]` |
| 배포 | `agentbricks deploy` → Agent Runtime on Apps, Runtime Store(Lakebase) | CLI Beta | `aops deploy` (승인 뒤 Job이 실행) |
| 운영 화면 | **Databricks Apps** (console App), AI/BI 대시보드 임베드 | – | `aops monitor --web` |
| 운영 데이터 | `system.ai_gateway.usage`, `system.billing.usage`, `system.access.audit`, **Apps telemetry**(`otel_*` UC 테이블), 예산 계정 API | telemetry Beta | `aops monitor`, console Monitor 화면 |
| 배포 자동화 | Declarative Automation Bundles (`databricks.yml`) | – | validate Job·console App·테이블 권한을 번들로 배포 |
| 코딩 에이전트 연결 | `ug` | – | `aops harness`, `aops register`(스킬) |

---

## 5. 전체 구조

```text
                 ┌────────────────────────────── aops ───────────────────────────────┐
  사용자 ──CLI──▶ │ 명령 라우터 │ aops.toml 모델 │ 세션·인계 │ 원본 이벤트 + 변환기     │
        ──UI───▶ │ 개발 화면 서버 (FastAPI, 버전 있는 REST + SSE) │ aops-recall MCP 서버│
  터미널 claude/codex ──프로젝트 hook──▶ 세션 기록                                         │
                 └───────────┬────────────────────────────────┬──────────────────────────┘
                             │ ① 하네스 어댑터                 │ ② provider (기능별)
                ┌────────────┼────────────┐       ┌───────────┼──────────────┬───────────┐
              Codex      Claude Code   (이후)    local        dbx             omni
          openai-codex  claude-agent-sdk          SQLite·      databricks-sdk  omnigent
          (CLI 포함)    (CLI 포함)                MLflow       mlflow·agentbricks·ug
```

### 5.1 기능별 provider

| 기능 | local | dbx | omni |
| --- | --- | --- | --- |
| `ModelProvider` 모델 연결 | 하네스 설정 그대로 | Gateway Model Service 권장 | Omnigent `auth` → Gateway |
| `Executor` 실행 격리 | 칸·세션별 작업 폴더 분리 | + Databricks Sandbox (`w.sandbox`, Beta. 4 vCPU·8GB 고정, 외부 네트워크 제한 설정 불가, 하네스 CLI는 사용자 이미지로 넣어야 함 **확인 필요**) | Omnigent 세션 |
| `SessionStore` 세션 | `runs/` SQLite + 원본 이벤트 | Agent sessions (Lakebase, Beta) | Omnigent 세션 (정본) |
| `MemoryProvider` 장기 메모리 | `memory/` | Agent memory stores (Lakebase, Beta) | dbx와 동일 |
| `TraceStore` 실행 기록 | 원본 이벤트 + 프로젝트 MLflow | MLflow UC trace 테이블 (`<prefix>_otel_spans`) | dbx와 동일 |
| `EvalRunner` 평가 | `mlflow.genai.evaluate` → 프로젝트 MLflow | `mlflow.genai.evaluate` → Databricks Experiment, UC 평가 데이터셋 | dbx와 동일 |
| `SkillStore` 스킬 | `SKILL.md` 폴더 | + UC Skills (`w.ai_gateway.create_skill`, Beta, 관리자 활성화 필요) | Omnigent YAML에 스킬 필드가 없어 하네스 스킬 폴더로 넣음 (**확인 필요**) |
| `ToolRegistry` 도구 | 로컬 MCP 서버 | + UC MCP Service, managed MCP(`system.ai.*`), UC function | Omnigent YAML tools |
| `GuardrailProvider` 가드레일 ([3장](#3-가드레일)) | 1층 지시 + 2층 hook 규칙 (+ 선택 3층 hook 판정) | + Gateway 정책 (2층 결정적 + 3층 판정, Beta, 부착은 UI) | + Omnigent 정책 (CEL로 바꾼 규칙만 서버에서 강제) |
| `DevServer` 로컬 실행 | 하네스 직접 구동 (개발 화면) | `agentbricks dev` (`DurableAgentServer`, 채팅 화면, 포트 8000) | Omnigent 로컬 |
| `Validator` 검증 | 로컬 프로세스 (기록용) | **Lakeflow Job (서버리스)** | dbx와 동일 |
| `Registry` 등록·승인 | `runs/aops.db` (로컬 기록만) | **UC Delta 레지스트리 테이블** + UC registered model + MLflow LoggedModel | + Omnigent 에이전트 |
| `Deployer` 배포 | 없음 | 승인 뒤 Job이 `agentbricks deploy` 실행 (Agent Runtime on Apps, `server = "agentbricks"`) | Omnigent 관리형 에이전트 |
| `Monitor` 운영 관측 | aops 이벤트 집계 | **console App (Databricks App)**: Apps 상태·telemetry, aops 상태 경로, `system.ai_gateway.usage`, 예산 계정 API, `system.billing.usage`, production monitoring | dbx + Omnigent 세션 |

---

## 6. 프로젝트 폴더 (`aops init`)

```text
my-agent/
├── pyproject.toml        aops 버전 고정 (uv 프로젝트)
├── uv.lock               aops + 하네스 + 상위 SDK의 정확한 버전
├── aops.toml             프로젝트 정의의 정본
├── agent/
│   ├── instructions.md   하네스 공통 지시
│   ├── skills/<name>/SKILL.md
│   └── tools.toml        MCP 서버·도구 선언
├── guardrails/
│   ├── rules.toml        2층 규칙
│   └── redteam.yaml      가드레일 시험 사례
├── evals/
│   ├── questions.yaml    배치 질문
│   └── datasets/         정답이 있는 평가 데이터
├── memory/               장기 메모리 (Markdown 정본, 승인된 항목만)
├── AGENTS.md  CLAUDE.md  .codex/  .claude/  .agents/skills/
│                         ↑ 하네스 프로젝트 설정 (생성물, aops가 자동 재생성). 터미널 직접 실행에도 적용
├── agent.toml            (dbx) Agent Bricks 프로젝트 선언: server = "agentbricks", 도구·세션·메모리·tracing
├── runtime/              (dbx) DurableAgentServer 진입점·adapter (agentbricks 템플릿, 생성물)
├── databricks.yml        (dbx) 번들: validate Job, 배포 Job 참조, 테이블 권한
├── runs/                 · git 제외
│   ├── aops.db           세션·구간·턴·배치 (SQLite)
│   ├── events/           하네스 원본 출력 (append-only)
│   ├── state/            구간별 하네스 고유 상태 (재개용)
│   └── mlflow.db         local 기록·평가 (MLflow)
└── .aops/                · git 제외: 인계 파일, 배치 칸 작업 폴더(worktree), 임시 파일
```

```toml
# aops.toml 예시
config_version = 1

[project]
name = "price-helper"
edition = "local"              # local | dbx | omni

[agent]
harness = "claude"             # 기본 하네스: claude | codex
model = "<model-name>"         # dbx에서는 UC Model Service 이름
instructions = "agent/instructions.md"
skills = ["agent/skills/*"]
tools = "agent/tools.toml"

[guardrails]                   # 개발 중 시험용 스위치. 언제든 끄고 켤 수 있다
instructions = true            # 1층
rules = "log"                  # 2층: off | log | enforce
gateway = false                # Gateway 정책 (dbx 이상)
judge = "off"                  # 3층 hook 판정 (Gateway를 쓰지 않을 때)

[session]
capture_terminal = true        # 터미널에서 직접 쓴 하네스 세션도 기록 (false면 기록 안 함, sync가 다시 켜지 않음)
handoff_tokens = { codex = 2000, claude = 4000 }   # 인계 안내·파일 크기 예산
summarizer = "rules"           # rules | next-harness | <model-name>

[memory]
long_term = true
store_raw = true               # dbx 기본값은 false
review_writes = true           # 메모리 변경은 사용자 승인 후 반영
harness_memory = "keep"        # 하네스 자체 메모리: keep | import | off

[[variants]]                    # 배치 비교용 구성. 지정하지 않은 값은 위 설정을 따름
name = "claude-guard-on"
rules = "enforce"

[[variants]]
name = "codex-guard-off"
harness = "codex"
rules = "off"

[release]                      # 등록·배포할 구성. dbx·omni에서 validate가 관리자 정책으로 검사한다
spec = "SPEC.md"               # 에이전트 정보는 SPEC.md 15개 필드 (agent_id·agent_version·owner·data_sensitivity 등)
evals = "evals/datasets/main"

[release.guardrails]           # 운영에서 켜 둘 가드레일. 개발 중 [guardrails]와 별개
instructions = true
rules = "enforce"
gateway_policies = ["kr-pii", "jailbreak"]

[dbx]
profile = "my-workspace"
catalog = "main"
schema = "agents"
experiment = "/Users/<me>/aops/price-helper"   # 개발 기록은 기본으로 본인 폴더. 공유는 사용자가 고를 때만
gateway = true                 # 모델 호출을 Gateway로 (권장)
registry = "main.aops"         # 레지스트리·승인 Delta 테이블 스키마 (조직 공통)
validate_job = "aops-validate" # aops validate가 실행하는 Lakeflow Job (번들로 배포)
console_app = "aops-console"   # 운영 화면 Databricks App
approvers = "group:agent-approvers"   # 배포 승인 그룹. 요청자 본인은 승인할 수 없음
```

- dbx 프로젝트는 그 자체로 Agent Bricks 프로젝트다. `agent.toml`·`runtime/`은 `agentbricks init`이 만든 형식을 그대로 따르고, aops는 `aops.toml`의 도구·세션·메모리 선언만 `agent.toml`에 반영한다.
- 레지스트리 스키마·validate Job·console App은 조직에 하나씩 둔다. 관리자가 `aops admin setup`으로 한 번 배포한다 ([9장](#aops-admin-setuppolicy-dbx-이상-관리자)).

---

## 7. 하네스 어댑터

### 7.1 어댑터가 하는 일

1. `aops.toml`에서 **하네스 프로젝트 설정**을 만든다 (지시 파일, 스킬 위치, 도구, 가드레일 hook, 세션 기록 hook).
2. 하네스를 구동하고, 출력 원본을 `runs/events/`에 쌓는다.
3. 원본을 aops 이벤트로 바꾼다 (버전 있는 변환기).
4. 세션 구간을 기록하고, 하네스 고유 상태를 구간별로 보존한다.
5. 인계 내용을 하네스 방식으로 넣는다 (2.4).
6. 시작할 때 하네스 지원 기능을 확인해(capability probe), 지원하지 않는 기능은 화면에서 끈다.
7. **로그인은 건드리지 않는다.** 사용자가 하네스에 설정한 로그인이나 환경 변수(API 키, dbx Gateway 토큰)를 그대로 쓴다.

### 7.2 하네스별 연결 방식 (1차)

| | Codex | Claude Code |
| --- | --- | --- |
| 구동 | `openai-codex` SDK → `codex app-server` (JSON-RPC, stdio). CLI에서 **experimental** 표기. 대체 경로 `codex exec --json` | 사용자가 설치한 `claude`를 `-p --output-format stream-json --verbose`로, 또는 `claude-agent-sdk`(`cli_path`로 실행 파일 지정) |
| 프로젝트 설정 | `AGENTS.md`, `.agents/skills/`, `.codex/config.toml`·`hooks.json` (신뢰한 프로젝트에서만) | `CLAUDE.md`, `.claude/settings.json` (hook, 권한, MCP), 스킬 폴더. `-p`에서는 신뢰 전 권한 허용 규칙이 무시되므로 `--allowedTools`로 넘김 |
| 도구 사용 추출 | `item/completed`의 `commandExecution`·`mcpToolCall`·`dynamicToolCall`·`fileChange`·`webSearch`, 하위 에이전트 `collabAgentToolCall` | `tool_use` 블록. 하위 에이전트는 `Agent` |
| 스킬 사용 추출 | **명시 이벤트 없음.** 대화에 들어간 `<skill>` 조각과 `SKILL.md` 읽기 명령으로 추정하고 화면에 "추정"으로 표시 | `tool_use`의 `name == "Skill"` |
| 세션 기록 hook | `SessionStart`·`UserPromptSubmit`·`PostToolUse`·`Stop` 등 12종 (0.166에서 2종 추가) | `SessionStart`·`UserPromptSubmit`·`PostToolUse`·`Stop`·`SessionEnd` 등 |
| 인계 | `SessionStart` 안내(약 2,500 토큰 기준) + aops가 구동할 때 `thread/inject_items` | `SessionStart` 안내(10,000자 기준). 외부 기록 주입 방법 없음 |
| 고유 재개 | thread resume (같은 `CODEX_HOME` 안에서) | `--resume <session>` |
| 사용량 | `thread/tokenUsage/updated`, `turn.completed` | `usage`, `modelUsage`(하위 에이전트 포함). `total_cost_usd`는 API 가격으로 계산한 추정치 |
| 버전 고정 | `openai-codex` 0.163.0 → `openai-codex-cli-bin==0.163.0` (macOS·Windows wheel에 실행 파일 포함 확인, Linux wheel은 **확인 필요**) | `claude-agent-sdk` 0.2.173 wheel에 CLI 2.1.309 포함 (macOS·Linux·Windows) |

- Codex는 `exec`(snake_case)와 `app-server`(camelCase)의 항목 이름이 달라 변환기에서 맞춘다. `exec --json`에는 hook 실행과 dynamic tool 이벤트가 없으므로 기본 경로는 app-server다.
- 구독 로그인 사용자는 직접 설치한 하네스(터미널에서 쓰는 것)를 구동하는 것이 기본이다. SDK에 든 CLI는 API 키·Gateway를 쓸 때와 CI에서 쓴다. 이 때문에 **터미널에서 쓰는 하네스 버전은 aops가 고정하지 못한다** (예: 작성 환경의 터미널 Claude 2.1.310, SDK 내장 2.1.309). aops는 실행마다 실제 실행 파일 경로와 버전을 기록하고 호환표와 다르면 경고한다.
- Codex의 OpenTelemetry 설정은 프로젝트 설정에서 무시된다. aops 실행 기록은 OTel이 아니라 어댑터 이벤트로 만든다.
- 이후 후보: OpenAI Agents SDK, LangGraph, Gemini CLI, OpenCode, Goose. 인터페이스는 1차부터 공통으로 둔다.

### 7.3 데이터 구조

```text
프로젝트 1 ─< 세션 1 ─< 구간(하네스 1개) 1 ─< 턴 1 ─< 이벤트
배치 1 ─< 칸(질문 × 구성 × 반복) ── 칸 하나 = 세션 하나
```

| 이벤트 | 주요 필드 | 용도 |
| --- | --- | --- |
| 공통 | `event_id`(중복 방지), `schema_version`, session·segment·turn ID, harness와 하네스 버전, 변환기 버전 | 모든 이벤트 |
| `TurnStarted` / `TurnFinished` | 질문, 상태(완료·중단), 체크포인트 | 턴 단위, 끝나지 않은 턴 판단 |
| `Message` | role, text | 채팅 표시 |
| `ToolCall` | kind(`tool`·`skill`·`mcp`·`subagent`), name, 시작·종료, 성공 여부, 감지 방식(`explicit`·`inferred`) | **사용 표시·횟수 집계** |
| `GuardrailDecision` | layer(1·2·3), location(`hook`·`session`·`gateway`), checkpoint(①~④), action(`pass`·`log`·`block`·`mask`), rule, 원래 판정 값(예: Gateway `DENY`) | 가드레일 표시·비교 |
| `Usage` | 토큰, 비용(가능하면), 지연 | 비교표 |
| `SegmentStarted` / `HarnessSwitched` | from, to, 이유(`manual`·`terminal`·`import`), 하네스 고유 세션 ID | 세션 구간 |
| `HandoffPrepared` | 인계 파일 크기, 포함 항목 수, 안내 크기 | 무엇을 넘겼는지 확인 |
| `MemoryProposed` / `MemoryAccepted` | 메모리 항목 | 메모리 변경 이력 |

- **저장:** 원본(`runs/events/`)이 1차 정본, 정리된 이벤트(`runs/aops.db`)는 변환기로 다시 만들 수 있다.
- **내보내기:** OpenTelemetry GenAI span(`invoke_agent`, `execute_tool {gen_ai.tool.name}`)으로 MLflow에 보낸다.
- **화면:** AG-UI 형태의 SSE로 흘린다. 화면 전송용일 뿐 정본이 아니다.

---

## 8. 명령어 × 에디션

● 지원 · △ 제한 있음 · – 미지원. 셀은 "어떻게 구현하나"다. 세부 사항은 [9장](#9-명령어-상세), 제한 근거는 [14장](#14-실현-가능성-검토와-제한).

명령은 **16개**다. 개발자가 매일 쓰는 것은 앞의 7개이고, 등록·배포는 dbx·omni에서만, `admin`은 관리자만 쓴다. 같은 일을 하는 명령을 따로 두지 않는다(아래 "합친 명령").

**개발 (모든 에디션, 강제 없음)**

| 명령 | 목적 | local | dbx | omni |
| --- | --- | --- | --- | --- |
| `aops init` | 프로젝트 폴더 생성 + 개발 화면 열기 | ● uv 프로젝트·템플릿·하네스 설정 생성, 하네스 설치 | ● + UC 이름·Gateway 기본값, Agent Bricks 프로젝트 | ● + Omnigent 에이전트 YAML |
| `aops dev` | 개발 화면 (Chat·Batch·Evaluate·기록·메모리, 가드레일 스위치) | ● 로컬 웹 UI | ● + Databricks 자원 조회, 실행 위치로 Sandbox 선택, Agent Bricks 프로젝트면 `agentbricks dev`도 띄움 | △ Omnigent 확장으로 화면 넣기 (OSS 확인, 관리형 확인 필요) |
| `aops run` | 질문 하나, 또는 질문 파일 × 구성 × 반복(배치) | ● 하네스 직접 구동, 칸별 작업 폴더, 비교표·사용률 | ● + Gateway 권장, 칸마다 MLflow trace, Sandbox 분산(**확인 필요**) | ● Omnigent 세션으로 실행 |
| `aops evaluate` | 원할 때 채점, `--suite redteam` 가드레일 시험 | ● `mlflow.genai.evaluate` → 프로젝트 MLflow | ● → Databricks Experiment, UC 평가 데이터셋, Gateway 정책 점검표 | ● + Omnigent 정책 (CEL) |
| **`aops session`** | **세션 보기·하네스 전환·가져오기·내보내기** | ● 수동 전환(같은 하네스면 고유 재개), 인계, 터미널 기록(신뢰 승인 필요), import | ● Agent sessions에 저장, 다른 PC·Sandbox에서 이어감 | △ Omnigent 세션 사이 인계 (세션 쓰기 공개 API 없음, 합의 필요) |
| `aops memory` | 장기 메모리 보기·승인·삭제 | ● `memory/` | ● Agent memory stores | ● dbx와 동일 |
| `aops add` · `remove` | 스킬·도구·MCP 추가·제거 | ● `SKILL.md` 폴더, 로컬 MCP | ● + UC MCP Service, managed MCP, UC function, Genie (`agentbricks tools add`) | ● YAML tools, 하네스 스킬 폴더 |

**등록·배포 (dbx·omni, 관리자 정책을 코드로 강제)**

| 명령 | 목적 | local | dbx | omni |
| --- | --- | --- | --- | --- |
| `aops configure` | Databricks 연결, 에디션 이전 | – | ● 프로필·카탈로그·Experiment·Gateway·프리뷰·내 권한 확인, local 데이터 이전 | ● + `omni login`, dbx → omni 이전 |
| **`aops validate`** | **등록 전 관리자 정책 검사 (강제 시작점)** | ● 로컬 실행 (참고용, 강제 없음) | ● 후보 소스 업로드 → **Lakeflow Job(서버리스)** → MLflow + Delta `validations` | ● dbx와 동일 |
| `aops register` | 버전 등록 | – | ● 통과한 검증이 있는 소스만 → UC Volume + UC registered model 버전 + Delta `agent_versions`, UC Skills 게시 | ● + Omnigent 에이전트 등록 |
| `aops deploy` | 배포 요청 (가드레일 포함) | – | ● Delta `deploy_requests` → console App 승인 → 배포 Job이 `agentbricks deploy`. `--dev`는 승인 없는 개인 시험 배포 / △ Codex·Claude 기반 에이전트는 확인 필요 | ● Omnigent 관리형 에이전트 + 정책 |
| `aops promote` | 운영 버전 지정 (이전 버전 지정 = 되돌리기) | – | ● Delta `production` + UC 모델 별칭을 한 번에 변경 | ● UI에서 동일 |

**운영·관리**

| 명령 | 목적 | local | dbx | omni |
| --- | --- | --- | --- | --- |
| **`aops monitor`** | **사용량·예산·활성 에이전트·MCP** (`--web`은 console App) | ● 내 사용량·도구 사용 집계 (aops 이벤트) | △ console Monitor 화면과 같은 데이터. 개인: 내 사용량·예산 소진율 / 관리자: 전체 사용량·비용, 실행 중인 앱과 MCP 호출. 사용량 1시간·비용 최대 12시간 지연 | ● + Omnigent 세션 현황 |
| `aops doctor` | 설치·버전·설정 점검, `--fix`로 설정 재생성·형식 이전 | ● 하네스 버전·호환표, 프로젝트·hook 신뢰 상태, hook·MCP를 막는 관리자 설정, 자체 메모리 (알림만) | ● + 인증·권한·프리뷰, Gateway 주소·토큰 짝 | ● + Omnigent 연결 |
| `aops harness` | 하네스 설치·버전 관리 | ● uv로 고정 버전 설치·전환 (터미널 하네스는 기록·경고만) | ● + `ug` | ● Omnigent 지원 하네스로 제한 |
| `aops admin` | 조직 공통 자원 준비(`setup`), 관리자 정책(`policy`) | – | ● 번들로 레지스트리 테이블·validate Job·배포 Job·console App·monitor 뷰 배포, 배포 형식 정책 버전 관리 | ● dbx와 동일 |

**합친 명령 (이전 설계 25개 → 16개)**

| 이전 | 지금 | 이유 |
| --- | --- | --- |
| `aops sandbox`·`aops dev` | `aops dev` | 둘 다 "로컬 개발 화면 열기"다. Agent Bricks 프로젝트면 `agentbricks dev`도 함께 띄운다. 이름은 Databricks Sandbox(실행 격리)와 겹치지 않게 `dev`로 한다 |
| `aops batch` | `aops run <질문 파일>` | 질문 하나와 여러 개는 같은 실행이다 |
| `aops guard on·off·status` | `aops.toml`·개발 화면 스위치 | 설정 값이라 명령이 필요 없다 |
| `aops guard test` | `aops evaluate --suite redteam` | 가드레일 시험도 채점이다 |
| `aops skill`·`aops tool` | `aops add`·`remove` | 둘 다 프로젝트에 구성 요소를 넣는 일이다. UC Skills 게시는 `register`가 한다 |
| `aops trace` | `aops session show`, 개발 화면 기록 탭, `aops monitor --me` | 기록 보기는 화면과 세션·모니터링에서 이미 한다 |
| `aops sync` | 자동 + `aops doctor --fix sync` | 사람이 기억해서 실행할 일이 아니다 |
| `aops migrate` | 자동(백업 후 확인) + `aops doctor --fix migrate`, 에디션 이전은 `aops configure` | 형식 이전은 올릴 때 한 번, 에디션 이전은 연결할 때 한 번이다 |
| `aops approve`·`reject` | console App 화면 | 승인은 사람의 판단이고, 승인자 신원·자기 승인 금지를 App 한곳에서 검사한다 |
| `aops rollback` | `aops promote <이전 버전>` | 되돌리기도 운영 버전 지정이다 |
| `aops console` | `aops monitor --web` | 화면을 여는 것뿐이다 |
| `aops session resume`·`capture` | `aops session switch`, `[session] capture_terminal` | 재개는 같은 하네스로의 전환이고, 기록 켜기는 설정 값이다 |

---

## 9. 명령어 상세

### `aops init <name> [--harness claude|codex] [--edition local|dbx|omni] [--no-ui]`
- 6장 구조의 폴더를 만들고 `uv sync`로 aops와 하네스를 설치한다.
- 하네스 프로젝트 설정을 만든다. 이후 이 폴더에서 `claude`·`codex`를 직접 실행해도 aops 설정과 기록이 적용된다.
- 예시 질문 3개와 기본 가드레일 규칙을 넣고, 마지막에 `aops dev`를 연다.
- omni: 같은 정의로 Omnigent 에이전트 YAML(`name`, `instructions`, `executor`(harness·model·auth), `tools`, `policies`, `os_env.sandbox`)도 만든다. YAML에 스킬 필드가 없어 스킬은 디렉터리 번들 안의 하네스 스킬 폴더로 넣는다 (확인 필요).
- **설정 재생성(sync):** 따로 명령이 없다. aops 명령을 실행할 때 `aops.toml`이 바뀌었으면 하네스 설정(`AGENTS.md`, `.codex/`, `.claude/`, dbx는 `agent.toml`)을 다시 만든다.
  - 사람이 하네스 설정 파일을 직접 고쳤으면 덮어쓰기 전에 차이를 보여주고 묻는다.
  - 다른 도구의 hook(예: `mlflow autolog claude`)은 지우지 않고 합친다.
  - **사용자가 지우거나 끈 hook은 다시 넣지 않는다.** 되살리지 않겠다고 하면 `aops.toml`에 꺼짐(`capture_terminal = false` 등)으로 기록해 다음에도 그대로 둔다.

### `aops dev [--port] [--host 127.0.0.1]`
- 로컬 개발 화면(Chat·Batch·Evaluate·기록·메모리)을 띄운다. 화면 구성은 [10장](#10-개발-화면-aops-dev).
- 가드레일 층별 스위치, 하네스·모델·스킬·도구 선택도 이 화면에서 한다. 바꾼 값은 `aops.toml`에 저장된다.
- **dbx의 Agent Bricks 프로젝트면 `agentbricks dev`도 함께 띄운다.** 배포 환경과 같은 명령·환경으로 `DurableAgentServer`를 포트 8000에 띄우고 Agent Bricks 채팅 화면을 연다(모델 선택·세션·메모리·trace·호출 방식 선택). aops는 이 화면을 다시 만들지 않고, 로컬 서버(`/api/invocations`)를 Batch·Evaluate 비교 대상으로 붙인다. 로컬에서는 세션·메모리 저장소가 연결되지 않는다(공식 문서).
- dbx: 모델 목록은 Gateway Model Service, 도구는 UC MCP Service·managed MCP, 스킬은 UC Skills, 기록은 UC trace 테이블에서 읽는다. 실행 위치로 "내 PC / Databricks Sandbox"를 고를 수 있다.

### `aops run "<질문>" | <questions.yaml> [--variants a,b] [--repeat N] [--concurrency N] [--harness ...] [--json]`
- **질문 하나:** 현재 세션에 이어 붙인다. 하네스를 바꿔 실행하면 2장의 인계가 일어난다.
- **질문 파일(배치):** **질문 × 구성 × 반복**의 모든 칸을 실행하고 비교표를 낸다. 칸마다 작업 폴더(git worktree)를 나눠 서로 파일을 덮어쓰지 않게 한다.
  - 결과: 칸별 답변, 도구·스킬 사용, 가드레일 판정, 토큰·지연.
  - **질문별 사용률:** 질문 q, 구성 v에서 도구 t의 사용률 = `t를 쓴 실행 수 / 반복 수`. 호출 횟수도 따로 센다.
- **동시 실행과 로그인:**
  - 하네스 홈(`CODEX_HOME`, `CLAUDE_CONFIG_DIR`)은 칸마다 나누지 않고 공유한다. Codex는 홈을 나눠 로그인 파일을 복사하면 ChatGPT 로그인 갱신 토큰이 서로 충돌하는 문제가 여러 건 보고돼 있다. Claude는 설정 폴더를 나누면 macOS 키체인 항목이 갈라져 칸마다 다시 로그인해야 한다. 같은 홈을 함께 쓸 때 Codex는 기록 쓰기를 프로세스 간 잠금으로 맞춘다.
  - 구독 로그인은 개인의 일반적인 사용을 전제로 한도가 정해져 있다. 구독 로그인 배치는 기본 동시 실행 수를 낮게 두고(예: 2), 큰 배치는 API 키나 Gateway를 권장한다.
  - Codex는 worktree를 원래 저장소 기준으로 신뢰 판정하므로 프로젝트 설정은 읽힌다. hook 승인이 worktree에서도 유지되는지는 0단계에서 확인한다. 칸마다 hook 실행 이벤트(app-server `hook/started`·`hook/completed`, Claude `--include-hook-events`)로 hook이 실제로 돌았는지 확인하고, 안 돈 칸은 결과에 표시한다.
- dbx: 칸 하나 = MLflow trace 하나 (`batch_id`·`variant`·`question_id` 태그). 칸을 Databricks Sandbox로 나눠 돌리려면 Sandbox에 하네스 CLI를 넣는 방법을 먼저 확인해야 한다 (사용자 이미지 필요 가능성, 사용자당 활성 Sandbox 200개).

### `aops evaluate [dataset] [--suite redteam|handoff] [--scorers ...] [--variants ...] [--target deployed]`
- 개발자가 원할 때 채점한다. `mlflow.genai.evaluate(data, predict_fn, scorers)`를 그대로 쓰고 **결과는 항상 MLflow에 남긴다.** `predict_fn`은 aops 하네스 실행 함수다.
- 하네스는 별도 프로세스라 MLflow trace가 자동으로 이어지지 않는다. `predict_fn` 안에서 aops가 trace를 직접 만들고, 하네스 이벤트를 도구 span으로 붙인다.
- `--suite redteam`: **가드레일 시험.** `guardrails/redteam.yaml`로 층별 차단·통과·오탐을 표로 낸다. `--variants`로 가드레일 켬·끔 구성을 나란히 비교한다. `--target deployed`면 배포한 에이전트로 시험한다.
  - dbx Gateway 정책: aops가 권장 구성(SQL 정책 함수, 판정 모델)과 붙일 정책 목록을 점검표로 보여준다. 부착은 Databricks UI에서 하고, 공개 SDK에 정책 조회 메서드가 없으므로 붙었는지는 이 시험의 실제 차단 여부로 확인한다. omni는 CEL 정책으로 바꿔 넣는다 (CEL로 못 바꾸는 규칙은 hook으로 남김).
- `--suite handoff`: 이어가기 품질 시험 (2.10).
- local: 프로젝트 MLflow(`runs/mlflow.db`). judge 모델은 사용자가 지정한다. 결과는 개발 화면 Evaluate 탭이나 `mlflow ui`로 본다.
- dbx: Databricks MLflow Experiment, UC 평가 데이터셋, Databricks judge. 구성별 `model_id`로 비교한다.

### `aops session [list|show|switch|import|export]`
- `list`·`show`: 세션과 구간(하네스·턴 범위), 전환 기록, 인계 내용, 턴별 도구 호출을 보여준다. 실행 기록 조회도 여기서 한다(화면은 개발 화면 기록 탭, dbx는 MLflow UI).
- `switch --harness <name>`: 지금 세션을 다른 하네스로 옮긴다. 같은 하네스·같은 버전으로 돌아가면 고유 재개, 아니면 인계로 이어간다.
- `import --from claude|codex [--session id]`: 하네스의 기존 세션 기록을 가져와 aops 세션으로 만든다. 사용자가 실행할 때만 가져온다.
- `export`: 하네스 중립 형식(JSON)으로 내보낸다.
- 터미널 직접 실행 기록은 `[session] capture_terminal`(개발 화면 스위치)로 켜고 끈다.
- dbx: 세션을 Agent sessions(`AgentKitClient(...).session_stores`, `append_items`)에 저장해 다른 PC나 Databricks Sandbox에서 이어간다.

### `aops memory [list|search|accept|forget]`
- `list --pending`·`accept`: 하네스가 제안한 메모리 변경을 보고 승인한다.
- local: `memory/` Markdown이 정본, SQLite로 검색한다. dbx: Agent memory stores(Lakebase 기반, Beta), 저장소 단위로 권한을 준다.

### `aops add|remove skill|tool|mcp <대상>`
- `skill`: 로컬 `SKILL.md` 폴더를 `agent/skills/`에 넣고 하네스별 위치로 배치한다. 형식은 추가할 때 검사한다.
- `tool`·`mcp`: local은 로컬 MCP 서버를 `agent/tools.toml`에 등록한다. dbx는 UC MCP Service, managed MCP(`system.ai.web_search`, `system.ai.dbsql`, 코드 실행 `system.ai.sandbox` 등), UC function, Genie Agent를 붙이고 Agent Bricks 프로젝트에는 `agentbricks tools add`로 반영한다.
- UC Skills 게시는 따로 하지 않는다. `aops register`가 등록할 때 함께 게시한다.

### `aops configure [--edition dbx|omni] [--dry-run]` (dbx 이상)
- Databricks CLI 프로필, 카탈로그·스키마·Experiment·Gateway Model Service·SQL Warehouse를 확인해 `aops.toml [dbx]`에 저장한다. 조직 공통 레지스트리 스키마·validate Job·console App이 있는지와 내 권한(읽기, 요청, 승인)도 확인한다.
- 프리뷰(Sandbox, UC Skills, Agent memory, 서비스 정책 등) 상태를 확인하고, 꺼진 기능은 local 구현으로 대신하도록 `[providers]`를 제안한다.
- **에디션 이전:** local 프로젝트에 처음 실행하면 데이터를 옮길지 묻는다. 세션 → Agent sessions, 메모리 → memory stores, 평가 기록 → Databricks Experiment, 평가 데이터 → UC 평가 데이터셋. `--dry-run`으로 항목별 이전 계획과 옮길 수 없는 항목을 먼저 보여준다. 옮기지 않아도 dbx 기능은 쓸 수 있다.

### `aops validate [--local]`
**강제가 시작되는 첫 단계다** (dbx·omni). 조직 레지스트리에 올릴 후보를 관리자 정책으로 검사한다.
- 커밋된 소스만 대상이다. 미커밋 변경이 있으면 거부한다. 후보 소스와 `uv.lock`을 묶어 UC Volume의 검증 대기 위치(`<registry>/staging/<agent>/<source-hash>`)에 올린다.
- `[dbx] validate_job` Lakeflow Job(서버리스, 서비스 주체 실행)을 `agent_id`·`source_hash` 매개변수로 실행하고, 끝날 때까지 진행 상황을 보여준다. 올린 소스를 대상으로 하므로 내 PC 상태와 무관하다.
- 단계 (검사 항목과 기준은 [관리자 정책](#관리자-정책-배포-형식)에서 온다):
  1. **형식 검사:** `aops.toml [release]` 필수 항목, `agent.toml`, 스킬 형식, 도구 권한(`auth = "user"|"app"`), 허용된 Model Service·MCP, 비밀값·금지 파일, 서버 종류(`agentbricks`인지)
  2. **평가:** `mlflow.genai.evaluate`로 `[release] evals` 데이터셋 채점, 정책의 최소 점수와 비교
  3. **가드레일 시험:** `[release.guardrails]`에 정책이 요구하는 층·규칙이 있는지, 레드팀 통과율. Gateway 정책이 붙어 있으면 실제 차단도 확인
  4. **호환 검사:** `uv.lock`의 하네스·SDK 버전이 정책의 허용 범위와 호환표에 있는지
  5. **기록:** MLflow run과 Delta `validations`에 단계별 결과, 소스 해시, 정책 버전을 남긴다
- **개발 중 기록에 기대지 않는다.** 개발 중 trace가 있는지, 개발 중 `aops evaluate`를 했는지는 보지 않는다. 필요한 증거는 이 Job이 직접 만든다.
- `--local`: 같은 단계를 내 PC에서 돌린다. 등록 전에 미리 확인하는 용도이고, 결과는 참고용이다. local 에디션에는 이 방식만 있고 강제는 없다.
- 코드 에이전트는 Job 안에서 `DurableAgentServer` 앱을 직접 띄워 시험한다. Codex·Claude 기반 에이전트를 서버리스 Job에서 실행할 수 있는지(실행 파일·네트워크)는 **확인 필요**다. 안 되면 Sandbox에서 실행하는 작업으로 바꾼다.

### `aops register [--version x.y.z]` (dbx 이상)
- **통과한 검증이 있는 소스만 등록한다.** 같은 소스 해시로 현재 정책 버전에서 통과한 `validations` 행이 없으면 거부한다.
- 검증 대기 위치의 스냅샷을 버전 위치로 옮기고, UC registered model 버전과 MLflow LoggedModel을 만든다. 평가·trace가 같은 `model_id`로 연결된다.
- 등록하면서 스킬을 UC Skills로 게시한다 (`w.ai_gateway.create_skill` → `PUT /api/2.0/fs/files/Skills/<catalog>/<schema>/<skill>/<file>`로 파일 업로드 → `finalize_skill`). 관리자가 UC Skills 프리뷰를 켜야 한다. 코딩 에이전트에는 `ug skills add`로 연결할 수 있다.
- 레지스트리 정본은 Delta `agents`·`agent_versions`다. 소스 해시, git 커밋, 하네스·SDK 버전, UC 모델 버전, LoggedModel ID, 근거 검증 ID를 한 행에 남긴다. 버전은 `[release] version`과 같아야 한다.
- UC 등록은 **UC registered model**로 한다 (AI 거버넌스 문서: "an agent is registered as a Unity Catalog model"). agent-services(Beta)는 호출 기능이 없고 SDK 메서드도 없어, 나오면 찾기용으로만 추가한다.

### `aops deploy [--version] [--target <workspace>] [--dev]` (dbx 이상)
조직 배포는 **요청 → 승인 → 배포 Job** 순서로만 한다. 사용자 PC에서 바로 조직 배포를 하지 않는다.

```text
aops validate         → 후보 소스 업로드 → Lakeflow Job(관리자 정책 검사) → validations (통과)
aops register 1.2.0   → 통과한 소스만 → agent_versions, UC 모델 버전
aops deploy 1.2.0     → deploy_requests (대기). 검증의 정책 버전이 현재 정책과 다르면 다시 validate 요구
승인자: console App [승인]·[반려]
                      → approvals + UC 모델 버전 승인 태그
배포 Job (서비스 주체) → 승인 기록 재확인 → agentbricks deploy → deployments
aops promote 1.2.0    → production
```

- **에이전트 서버:** 배포하는 모든 dbx 에이전트는 `server = "agentbricks"`(`DurableAgentServer`)다. 요청 ID로 중복 실행을 막고(같은 ID 재요청은 저장된 결과, 다른 내용이면 409), 동기·스트리밍·백그라운드 호출을 같은 실행으로 다룬다. 배포하면 Lakebase 기반 Runtime Store가 실행 상태·이벤트를 보관하고, 등록한 recovery handler가 중단된 실행을 복구한다. 사용자 권한으로 도구를 부르는 기능(`auth = "user"`)도 이 서버에서만 된다. **배포 뒤에는 서버 종류를 바꿀 수 없으므로** custom 서버와 legacy 서버(MLflow `AgentServer`, `LongRunningAgentServer`)는 처음부터 쓰지 않는다.
- **LangGraph·OpenAI Agents 기반:** `agentbricks init`의 Durable 템플릿을 그대로 쓰고 배포 Job이 `agentbricks deploy`를 부른다. Agent Bricks CLI는 Beta다.
- **Codex·Claude 기반 (확인 필요):**
  - `DurableAgentServer`의 invoke 처리 함수 안에서 하네스 SDK를 부르고, 진행 상황을 `context.emit`으로 흘린다. invoke 함수는 프레임워크와 무관하다는 것이 문서 서술이다.
  - 셸 실행은 앱 컨테이너가 아니라 `system.ai.sandbox` managed MCP로 보낸다 (`agentbricks tools add sandbox`, 권한 축소 설정 포함).
  - 남은 확인 사항: `agent.toml`의 `framework`가 `langgraph`·`openai`만 허용되는 점, 복구할 때 하네스를 다시 실행해도 되는지(멱등성), Linux용 codex 실행 파일, Apps 컨테이너 자원·시간 한도. 4단계 전에 실제 배포로 확인한다.
- **승인 규칙:**
  - 승인자는 `[dbx] approvers` 그룹이어야 하고 요청자 본인은 승인할 수 없다. console App과 배포 Job이 둘 다 검사한다.
  - UC 승인 태그는 governed tag 정책으로 승인 그룹만 붙일 수 있게 한다.
  - 승인 근거는 같은 버전·같은 소스 해시의 통과한 `validations` 행이다. 로컬 `--local` 검증은 근거가 되지 않는다.
- **MLflow deployment jobs 연결 (선택):** UC 모델에 배포 Job을 연결하면, 새 버전마다 평가 → 승인 → 배포 작업이 자동으로 돈다. 승인은 이름이 `approval`로 시작하는 작업이 UC 태그 `Approved`를 확인하는 방식이다. 이 기능은 Public Preview이고 승인 방식은 experimental이다. 문서 예시는 Model Serving 배포만 다룬다. 그래서 켤 경우에도 배포 작업은 `agentbricks deploy`를 부르는 aops 작업으로 두고, 정본은 Delta 승인 기록으로 유지한다. Job은 모델 소유자 권한으로 돌기 때문에 서비스 주체로 실행한다. 승인 작업은 재시도를 끄고, 동시 실행은 1로 둔다.
- **가드레일 포함:** 1·2층 설정(지시·hook 규칙)을 배포 패키지에 넣는다. Gateway 정책은 점검표와 시험 질문으로 확인하고 결과를 `deployments`에 남긴다.
- **운영 관측 준비:** 배포할 때 Apps telemetry를 켜고(`otel_*` UC 테이블), FastAPI 자동 계측으로 요청 수·지연·오류를 남긴다. `DurableAgentServer`는 FastAPI 앱이므로 진행 중인 실행·최근 도구 호출을 돌려주는 경로(`/aops/status`)를 추가한다.
- 배포 앱 이름은 `agent-bricks-<name>`이다. `agentbricks deployments list`가 이 접두사의 앱만 찾는다.
- **개인 시험 배포 (`aops deploy --dev`):** 세션·메모리·Runtime Store처럼 배포해야만 시험할 수 있는 기능이 있다(`agentbricks dev`는 로컬에서 저장소를 연결하지 않는다). 그래서 승인 없이 본인 이름이 붙은 앱(`agent-bricks-dev-<user>-<name>`)으로 배포할 수 있다. 개발 단계로 보고 강제하지 않는다. 대신 레지스트리에 운영 후보로 남지 않고, `promote` 대상이 아니며, console의 운영 목록에 나오지 않는다. 앱을 만들 수 있는지는 워크스페이스 권한이 정한다.
- omni: Omnigent 관리형 에이전트로 게시하고 정책을 함께 넣는다.

### `aops promote <version> [--expected-version <현재>]` (dbx 이상)
- 통과한 검증과 완료된 배포가 있는 버전만 운영으로 지정한다. 운영 포인터(`production`)와 UC 모델 별칭을 함께 바꾼다.
- `--expected-version`으로 현재 운영 버전을 확인한 뒤 바꾼다(동시 변경 방지).
- **되돌리기도 이 명령이다.** 이전 버전을 지정하면 된다. 과거에 운영이었던 버전만 허용한다.

### 레지스트리·승인 테이블 (dbx)

`[dbx] registry` 스키마의 UC managed Delta 테이블이다. 조직이 하나를 함께 쓰고, 코드·하네스·스킬 에이전트를 같은 표에서 관리한다. 정의는 `bundles/registry/tables.sql`이고, 모든 테이블·컬럼에 한글 설명이 있다. 값 형식은 현재 aops 코드를 따른다: 에이전트 정보는 SPEC.md 15개 필드와 허용 값(예: `data_sensitivity` 공개·내부·대외비·개인정보), ID는 `uuid4().hex`, 해시는 sha256, 소스 스냅샷은 `/Volumes/<catalog>/<schema>/agent_artifacts/agents/<agent_id>/<version>/<sha256>.tar.gz`. 허용 값은 CHECK 제약으로 막는다. 샘플 데이터는 `scripts/make_sample_registry.py`가 실제 에이전트 소스로 만든다. 워크스페이스·사람 정보는 `.env.e2e`에서 읽고, 생성된 SQL은 git에서 뺀다.

| 테이블 | 내용 | 쓰는 주체 |
| --- | --- | --- |
| `agents` | SPEC 정보(ID·이름·`agent_type` skill-based·code-based·genie, 담당자·조직, 중요도·민감도·보안 등급, UC 권한, 성공 기준, 모델), 생애 상태, 최근 등록 버전 | `register` |
| `agent_versions` | 버전, 소스 스냅샷 경로·해시·크기, 스킬 목록, git 커밋, `uv.lock` 해시, 하네스·SDK 버전, UC 모델 버전, LoggedModel ID, 근거 검증, SPEC 스냅샷(JSON) | `register` |
| `validations` | 후보 버전·소스 해시·대기 위치, 정책 버전, Job·실행 ID, MLflow run ID, 단계별 결과(JSON), 평가 점수(정답성·관련성·안전성·지연 p90)·레드팀 통과율, 통과 여부 | validate Job |
| `deploy_requests` | 요청 ID, 버전, 대상 워크스페이스·앱, 요청자, 근거 검증 ID, 상태(대기·승인·반려·배포됨·실패) | `deploy`, 배포 Job |
| `approvals` | 요청 ID, 승인자, 결정, 사유, 시각 (추가만 하는 이력) | console App |
| `deployments` | 배포 결과, 앱 이름·URL, 배포 ID, 가드레일 점검 결과 | 배포 Job |
| `production` | 에이전트별 운영 버전과 변경 이력 (`promote`·`rollback`, 현재 표시) | `promote` |
| `policies` | 관리자 정책(배포 형식)과 버전: 승인 그룹·수, 허용 서버·모델, 최소 점수, 민감도별 필수 가드레일, 정책 원문 | `aops admin policy` |
| `agent_status` (뷰) | 에이전트별 최신 등록 버전·운영 버전·최근 검증·승인 대기 수 (console 레지스트리 화면용) | – |

- **한 번에 바뀌어야 하는 것은 한 트랜잭션으로 묶는다.** 예: 요청 상태 변경 + 승인 이력 추가, 운영 포인터 변경 + 이력 추가. `BEGIN ATOMIC … END`(multi-statement transaction)를 쓰려면 테이블이 catalog commits를 켠 UC managed 테이블이어야 한다. DDL은 트랜잭션 안에서 못 쓴다.
- **쓰기 권한은 서비스 주체만 갖는다.** 사람 계정에는 `SELECT`만 준다. 쓰기는 console App·validate Job·배포 Job의 서비스 주체가 한다. CLI 명령도 요청을 App API로 보낸다.
- Delta에는 강제되는 기본 키가 없다. 요청 ID는 UUID로 만들고, 상태 변경은 현재 상태를 조건으로 건 `MERGE`로 한다.

### 관리자 정책 (배포 형식)

관리자가 정하는 "조직에 올리고 배포하려면 지켜야 할 형식"이다. `aops admin policy set <policy.toml>`로 올리면 Delta `policies`에 버전이 붙어 저장되고, validate Job·`register`·배포 Job이 같은 정책 버전을 읽는다. **정책은 코드로만 검사한다.** 사람의 판단이 들어가는 곳은 승인 하나다.

| 항목 | 예 | 검사 시점 |
| --- | --- | --- |
| 필수 정보 | `[release]`의 소유 팀·담당자·데이터 등급·설명, 이름 규칙 | validate |
| 소스 | 커밋된 소스, 금지 파일·비밀값 없음 | validate |
| 실행 구성 | `server = "agentbricks"`, 허용 하네스·SDK 버전 범위, 허용 Model Service·MCP, 도구 권한 방식 | validate |
| 가드레일 | 데이터 등급별 필수 층·규칙·Gateway 정책, 레드팀 최소 통과율 | validate, 배포 Job |
| 평가 | 필수 평가 데이터셋, 최소 점수 | validate |
| 운영 기록 | 배포 에이전트의 MLflow tracing·Apps telemetry 켬 | 배포 Job |
| 승인 | 승인 그룹, 필요한 승인 수, 자기 승인 금지 | deploy·approve |
| 재검증 | 정책이 바뀌면 이전 정책의 검증으로 배포할 수 있는지 | deploy |

- 개발 단계의 기록·가드레일·평가 여부는 정책 항목이 될 수 없다. 정책은 등록·배포되는 결과물만 본다.
- 배포된 에이전트의 운영 기록은 정책에 따라 켜지고, 그 에이전트를 쓰는 최종 사용자 쪽에서는 끌 수 없다. 이것은 조직이 운영하는 서비스의 기록이고, 개발자 개인의 개발 기록과 다르다.
- 정책 파일에도 버전(`policy_version`, `schema_version`)을 붙인다. 정책이 없으면 dbx 기본 정책(서버 종류, 커밋된 소스, 비밀값 검사, 승인 1명)을 쓴다.

### console App (dbx 이상)
- 조직 공통 **Databricks App**이다. 명령이 따로 없고, `aops admin setup`이 번들로 배포하며 `aops monitor --web`이 주소를 연다.
- **배포 승인·반려는 이 화면에서만 한다.** CLI 승인 명령을 두지 않는다. 승인은 사람의 판단이고, App이 승인자 신원(사용자 권한 전달)과 자기 승인 금지를 한곳에서 검사하기 위해서다.
- 화면:
  - **레지스트리:** 에이전트·버전·검증 결과·배포 위치
  - **배포 요청·승인:** 승인자에게만 [승인]·[반려] 버튼. 요청자 본인 버튼은 꺼짐
  - **모니터링:** `aops monitor`와 같은 데이터
  - **운영 지정 이력**
- 기술: FastAPI + React. 개발 화면과 같은 화면 구성 요소와 `/api/v1`을 쓴다. 테이블은 SQL warehouse로 읽고 쓴다. 관리자 현황 대시보드(AI/BI)는 화면에 임베드한다.
- 권한: 화면 접근은 Apps `CAN_USE`. "내 것" 보기는 사용자 권한 전달(OBO)로 조회해 동적 뷰가 본인 행만 돌려주게 한다. 관리자 보기는 App 서비스 주체 권한으로 읽고 관리자 그룹에만 보여준다. OBO에 필요한 권한 범위는 **확인 필요**.

### `aops admin setup|policy` (dbx 이상, 관리자)
- `setup`: 조직 공통 자원을 번들(`databricks.yml`)로 한 번 배포한다.
  - 레지스트리 스키마와 테이블 (catalog commits 켬)
  - validate Job, 배포 Job (서버리스, 서비스 주체 실행, 동시 실행 1)
  - console App과 Apps telemetry 대상 스키마
  - monitor용 동적 뷰 (`requester = session_user()`)
  - governed tag 정책 (승인 태그)
- 권한 부여는 미리 보여주고 `--apply`일 때만 실행한다.
- `policy set|show|diff`: 관리자 정책(배포 형식)을 올리고 버전을 관리한다 ([관리자 정책](#관리자-정책-배포-형식)).

### `aops monitor [--me | --all] [--watch] [--web] [dashboard]`
개인 사용자와 관리자가 사용량·예산과 운영 중인 에이전트를 한곳에서 본다. **주 화면은 console App의 Monitor 화면**이고(`--web`으로 연다), `aops monitor`는 같은 데이터를 CLI 표로 보여준다. 내 실행의 도구·스킬 사용 집계(`--me`)도 여기서 본다. 데이터는 Databricks 기능과, aops로 배포한 에이전트의 상태 경로에서 가져온다. 아래 출처·지연은 검증 워크스페이스에서 컬럼과 최신 행 시각을 직접 조회해 확인했다.

| 보기 | 개인 사용자 (`--me`, 기본) | 관리자 (`--all`) |
| --- | --- | --- |
| 사용량 | 내가 직접 부른 요청·토큰·MCP 도구 호출 | 전체·사용자별·에이전트(앱)별 사용량 |
| 예산 | 내 예산의 USD 소진율 (차단 기준이 걸린 Gateway 예산만) | 예산별 소진율, 차단·알림 기준 근접 |
| 비용 | 내가 만든 앱의 비용 | 앱·Model Service별 비용 |
| 에이전트 | 내가 배포한 에이전트의 상태 | **실행 중인 에이전트 전체와 각자 쓰는 MCP** |
| 품질·가드레일 | 내 에이전트 평가 점수, 내 개발 기록의 차단 건수 | **배포된** 에이전트별 점수, 정책별 차단 건수 |

| 정보 | 출처 | 갱신 | 제한 |
| --- | --- | --- | --- |
| 앱 실행 상태 | `w.apps.list`(컴퓨트 상태) + 앱마다 `w.apps.get`(앱 상태) | 조회 시점 | `RUNNING`은 앱 프로세스가 떠 있다는 뜻이지 요청을 처리 중이라는 뜻이 아니다. 앱 상태는 `get`에만 있어 앱 수만큼 호출한다 |
| **진행 중인 세션·방금 쓴 MCP** | aops로 배포한 에이전트의 상태 경로(`/aops/status`, `DurableAgentServer`에 추가) | 조회 시점 | aops로 배포한 에이전트만. Databricks에는 앱별 요청 수·활성 사용자 조회 API가 없다 |
| 앱 요청 수·지연·오류 | **Apps telemetry** (`<prefix>_otel_metrics`·`otel_spans`·`otel_logs` UC 테이블) + FastAPI 자동 계측 | 수집 지연 문서 없음 (**확인 필요**) | Beta. 지원 지역 14곳(ap-northeast-2 포함). 대상은 같은 지역의 managed Delta 테이블 |
| 연결된 MCP·도구 | 배포할 때 기록한 구성, UC MCP Service 목록 | 조회 시점 | 선언된 것이지 실제 호출이 아니다 |
| 실제 호출한 MCP·도구 | `system.ai_gateway.usage`의 `mcp_metadata.tool_name`, 감사 로그(`system.access.audit`의 `mcpService`·`managedMcp`) | **1시간 이내** (문서. 실측 20~26분 전 행까지) | Gateway를 거친 MCP만 남는다 |
| 사용량 (요청·토큰) | `system.ai_gateway.usage` | 1시간 이내, 365일 보존 | 앱이 부르면 요청자가 앱 서비스 주체로 남는다 |
| 예산 | **계정 API** `a.budgets.get_budget_spend_status`·`list_budget_spend_statuses` (SDK 0.158.0) | 거의 실시간 (차단은 "대략" 적용) | 계정 콘솔 로그인이 따로 필요하다. 모든 계정 사용자가 본인 소진액을 볼 수 있지만, 차단 기준이 있는 Gateway 예산만, USD 정가 기준이다. 공유 기준은 소진율만 온다. Gateway 밖 호출·provisioned throughput은 빠진다. 실제 호출은 **확인 필요** |
| 속도 한도 | Gateway rate limit 설정 | – | 남은 양 조회 API가 없다. 429 건수는 셀 수 있지만 Gateway 한도인지 상위 모델 한도인지 구분되지 않았다 |
| 비용 | `system.billing.usage` (앱은 `usage_metadata.app_id`, 모델은 `endpoint_name`) | **최대 12시간** (문서. 실측 약 2.4시간) | 최종 사용자별 비용은 없다. 개인 비용은 "내가 만든 앱" 단위 |
| 품질 | MLflow production monitoring (Beta, Experiment당 scorer 최대 20개) | 처음 15~20분, 이후 샘플링 | 표본 기반 |
| 가드레일 차단 | aops `GuardrailDecision` 이벤트 | 조회 시점 | `system.ai_gateway.usage`에 `service_policies` 칸은 있지만, 정책을 시험한 워크스페이스에서도 30일간 값이 비어 있었다. Gateway 쪽 차단 집계는 **확인 필요** |

- **관리자 보기의 범위:** 등록·배포된 에이전트(운영)와 Gateway·billing 같은 플랫폼 기록만 다룬다. 개발자의 개발 중 aops 기록은 그 사람이 고른 위치(기본 본인 Experiment)에 남고, aops는 그것을 관리자 보기에 모으지 않는다 (워크스페이스 관리자의 플랫폼 권한은 별개다). 관리자 보기의 "사용자별 사용량"은 Gateway가 남기는 플랫폼 기록이며 aops hook과 무관하다.
- **최종 사용자별 귀속:** 배포한 에이전트가 앱 권한으로 Gateway를 부르면 사용량·비용이 앱 서비스 주체로 남는다. 사용자별로 보려면 (a) 사용자 권한 전달(OBO)로 부르거나 (b) 에이전트가 요청 태그(`request_tags`)에 최종 사용자를 넣는다. OBO 호출이 Gateway에 누구로 기록되는지는 **확인 필요**.
- **개인 보기 준비:** system 테이블에는 행 단위 필터가 없다. 그래서 `aops admin setup`이 `requester = session_user()` 조건의 뷰를 만들고 사용자에게 권한을 준다. console App은 사용자 권한(OBO)으로 이 뷰를 읽는다 (조건 동작은 조회로 확인, 뷰 생성은 미실행).
- **`aops monitor dashboard`:** `w.lakeview.create`·`publish`로 AI/BI 대시보드를 만든다. 게시할 때 게시자 권한으로 조회하는 것이 기본이라 관리자 전체 현황용이다. 보는 사람 권한으로 조회하는 설정(`embed_credentials=false`)은 **확인 필요**.
- 화면: console App Monitor 화면(주), CLI 표(`--watch`로 주기 갱신). 항목마다 데이터 기준 시각을 함께 보여준다.
- local: aops 이벤트로 하네스별 토큰·세션 사용량만 보여준다 (예산·비용 없음). 구독 로그인의 남은 사용량(예: 5시간 한도)은 하네스가 출력하지 않아 보여줄 수 없다.
- omni: Omnigent 세션 현황(실행 중인 세션, 하네스)을 함께 보여준다.

### `aops harness list|install|use|upgrade` · `aops doctor [--fix <항목>]`
- `install`·`use`: 호환표의 고정 버전을 uv로 설치·전환한다. `use codex@<버전> --untested`로 검증 전 버전도 경고와 함께 쓸 수 있다.
- `upgrade`: 호환표의 다음 버전으로 올리고, 녹화된 출력 재생 시험을 통과하지 못하면 되돌린다.
- `doctor`: 설치 버전과 호환표, 인증 상태, 프리뷰, 하네스 설정을 덮어쓰는 관리자 설정을 점검한다.
  - Codex: `/etc/codex/managed_config.toml`·`requirements.toml`의 모델 공급자 고정, hook 끄기, MCP 허용 목록. 프로젝트 신뢰와 hook 승인 상태.
  - Claude: 관리 설정의 `allowManagedHooksOnly`·`allowManagedMcpServersOnly`·`allowedProviders`, 사용자 `disableAllHooks`, 자동 메모리, Gateway 주소와 토큰이 함께 설정됐는지.
  - 결과는 **알림**이다. 자동으로 고치지 않고, 사용자가 일부러 끈 것(hook, 기록, 가드레일)은 문제가 아니라 "꺼짐"으로 표시한다. 고치기는 사용자가 고른 항목만 `aops doctor --fix <항목>`으로 한다.
  - `--fix sync`: 하네스 설정을 지금 다시 만든다 (평소에는 aops 명령이 자동으로 한다).
  - `--fix migrate`: aops 형식(`config_version`·이벤트·세션 저장)을 새 버전으로 옮긴다. 평소에는 aops를 올린 뒤 처음 실행할 때 백업하고 묻는다. 원본 이벤트는 바꾸지 않고 정리된 이벤트를 다시 만든다.

---

## 10. 개발 화면 (`aops dev`)

Databricks AI Playground의 Agent 모드(모델·도구·스킬·지시·설명·trace)를 참고하되, **aops만의 기능**을 앞에 둔다.

```text
┌──────────────────┬───────────────────────────────────────────┬────────────────────────┐
│ 구성             │ [ Chat ]  [ Batch ]  [ Evaluate ]         │ [기록] [사용량] [메모리]│
│ 하네스  Codex  ▾ │                                           │ 세션 S-0142            │
│ 모델    <모델> ▾ │ 사용자: 부가세 규칙 파일 정리해줘         │  구간1 Claude  턴 1~7  │
│ 도구    + 추가   │ [Claude] 규칙 3개를 정리했어요 …          │   (터미널)             │
│ 스킬    ☑ vat    │                                           │  구간2 Codex   턴 8~   │
│         ☐ unit   │ ────── Claude → Codex (사용자 전환) ───── │                        │
│ 지시    편집     │   넘긴 것: 요약 · 최근 4턴 · 변경 파일 2  │ 이번 전환에 넘긴 것    │
│ 가드레일         │                                           │  인계 파일 1.8k 토큰   │
│  1층 지시   ●    │ 사용자: 이어서 예외 규칙도 추가해줘       │  변경: rules.md, …     │
│  2층 규칙 log ▾  │ [Codex] 🧩 vat-calculator  🔧 bash ×2     │  메모리 3개            │
│  3층 판정   ○    │   앞서 정리한 3개 규칙에 예외 1개 추가 …  │                        │
│ [구성 저장]      │   🛡 2층 ④ pass                           │ 승인 대기 메모리 1     │
│                  │ [ 질문 입력 …                        ▶ ]  │  · 절사 규칙 우선 [승인]│
└──────────────────┴───────────────────────────────────────────┴────────────────────────┘
```

- **dbx의 Agent Bricks 에이전트:** 한 에이전트의 채팅 시험은 `agentbricks dev`의 채팅 화면을 그대로 쓴다. aops 개발 화면은 그 로컬 서버(`/api/invocations`)를 하네스 구성과 나란히 놓는 배치 비교·평가 대상으로만 쓴다.
- **운영 화면은 따로다:** 레지스트리·승인·모니터링은 로컬 개발 화면이 아니라 Databricks App(console App)에 있다.

### 10.1 Playground와 같은 부분
- 모델 선택, 도구 추가(MCP·UC function), 스킬 폴더(`SKILL.md`), 지시, 설명, 채팅, trace 보기.

### 10.2 aops만의 부분

| 기능 | 화면 | 구현 |
| --- | --- | --- |
| **하네스를 바꿔도 이어지는 대화** | 대화 중 하네스를 바꾸면 같은 대화가 이어짐. 전환 지점 구분선, 메시지별 하네스 배지, 터미널에서 진행된 구간도 같은 타임라인에 표시 | 2장 |
| **메모리 패널** | 이번 전환에 넘긴 내용, 장기 메모리, 승인 대기 메모리 | `HandoffPrepared`·`MemoryProposed` 이벤트 |
| **가드레일 켜고 끄기** | 층별 스위치. 판정은 답변 옆 🛡 배지 (통과·기록·차단·가림) | 실행마다 하네스 설정에 반영 ([3장](#3-가드레일)) |
| **Monitor** (dbx) | 개인·관리자 보기: 사용량·예산, 실행 중인 에이전트와 사용 MCP | `aops monitor` ([9장](#9-명령어-상세)) |
| **배치 비교** | Batch 탭: 행 = 질문, 열 = 구성, 칸 = 답변 요약 + 사용 칩 + 지연·토큰 + 가드레일 배지. 두 열을 고르면 답변 차이 표시 | `aops run <질문 파일>` |
| **스킬·도구 사용 표시** | 답변 위 칩: 🧩 스킬, 🔧 도구, 🔌 MCP, 👥 하위 에이전트. 누르면 입력·결과. Codex 스킬은 "추정" 표시 | `ToolCall` 이벤트 |
| **질문별 사용률** | Batch 하단 히트맵: 스킬·도구 × 질문 (`사용한 실행 수 / 반복 수`) | 이벤트 집계 |
| **평가** | Evaluate 탭: 데이터셋 × 구성 점수표, 실패 사례. MLflow 실행으로 바로 이동 | MLflow |
| **하네스 선택** | 같은 지시·스킬·도구로 Codex·Claude 바꿔 실행 | 어댑터 교체 |
| **배포 버튼** (dbx) | 등록·배포 | `aops register` · `aops deploy` |

### 10.3 기술 구성
- 서버: FastAPI. 화면은 빌드한 정적 파일(React)을 패키지에 넣는다. 실시간 표시는 SSE.
- **화면과 서버 사이 API에 버전을 붙인다** (`/api/v1`). 같은 화면 구성 요소를 omni에서 Omnigent UI에 넣을 때도 이 API만 쓴다.
- 보안: `127.0.0.1`에만 열고, 실행마다 바뀌는 토큰을 헤더로만 받는다. 요청의 Host·Origin을 검사하고 다른 사이트의 접근(CORS)을 막는다. 셸을 실행할 수 있는 에이전트를 움직이는 서버이기 때문이다.

---

## 11. 버전 관리

### 11.1 상위 도구 버전
- **하네스는 CLI가 들어 있는 Python 패키지로 고정한다.** `openai-codex`(0.163.0 → `openai-codex-cli-bin==0.163.0`, `codex` 실행 파일 포함), `claude-agent-sdk`(0.2.173 → Claude Code CLI 2.1.309 포함). `uv.lock` 하나에 aops가 구동하는 하네스 버전까지 고정된다.
- **고정되지 않는 것:** 사용자가 터미널에서 쓰는 하네스(자동 업데이트되는 Claude, Homebrew Codex 등)와 구독 로그인 실행에서 구동하는 사용자 하네스. aops는 이 버전을 기록하고 호환표와 비교해 경고만 한다. Claude 자동 업데이트를 멈추려면 사용자가 `DISABLE_AUTOUPDATER=1`을 설정한다.
- **SDK가 CLI보다 늦게 나온다.** 작성일 기준 Codex CLI는 0.166.0, `openai-codex`는 0.163.0이다. 새 CLI를 바로 쓰려면 `codex_bin`·`cli_path`로 실행 파일을 지정하고 `--untested`로 표시한다.
- **호환표 `compat.toml`은 CI가 `uv.lock`에서 만든다.** 사람이 따로 쓰지 않는다.
- **aops 버전 = 검증된 상위 버전 묶음.** 상위 고정 버전이 바뀌면 minor, aops 형식이나 명령이 호환되지 않게 바뀌면 major를 올린다.
- 사용자는 `aops harness use <하네스>@<버전> --untested`로 aops 릴리스를 기다리지 않고 하네스를 올릴 수 있다. 실행할 때 기능 확인으로 차이를 흡수하고, 모르는 출력은 원본에 남겨 둔다.

작성일 기준 최신 공개 버전 (참고값, 실제 고정값은 `uv.lock`):

| 상위 도구 | 버전 |
| --- | --- |
| Codex CLI / `openai-codex` | 0.166.0 (GitHub 릴리스, 2026-10-29) / 0.163.0 (PyPI) |
| Claude Code / `claude-agent-sdk` | 2.1.314 (GitHub 릴리스) / 0.2.173 (PyPI wheel 확인, 내장 CLI 2.1.309) |
| `mlflow` | 3.17.2 |
| `databricks-sdk` / Databricks CLI | 0.158.0 / 1.23.0 (작성 환경 1.21.0) |
| `databricks-agentbricks` / `databricks-langchain` | 0.7.1 / 0.22.0 |
| `omnigent` | 0.20.0 (OSS, alpha). 패키지 미러에 따라 같은 이름의 빈 예약 패키지(0.0.1rc1)가 받아지는 경우가 있어 설치 경로 **확인 필요** |
| uv | 0.13.6 (작성 환경 0.8.3) |

### 11.2 상위 변경을 일찍 잡는 시험
- **녹화 재생 시험:** 하네스 버전별로 실제 출력을 녹화해 두고, 변환기를 그 녹화로 시험한다. 실호출 없이 CI에서 돈다.
- **매일 실호출 시험:** 최신 하네스로 짧은 실제 실행을 돌려 깨지는 변경을 일찍 찾는다.
- **Databricks Beta 기능:** 기능마다 사용 가능 여부를 확인하고, 안 되면 local 구현으로 대신한다 (4.2).

### 11.3 aops 자체 형식
| 형식 | 버전 표시 | 바뀌면 |
| --- | --- | --- |
| `aops.toml` | `config_version` | aops를 올린 뒤 처음 실행할 때 백업하고 새 형식으로 고쳐 쓴다 |
| 이벤트 | `schema_version`, 변환기 버전 | 원본에서 다시 정리 |
| 세션 저장 (SQLite, Agent sessions) | 저장 형식 버전 | 같은 방식 (`aops doctor --fix migrate`) |
| 화면 ↔ 서버 API | `/api/v1` | 이전 버전을 한동안 함께 제공 |

### 11.4 설치

```bash
uv tool install "aops[local]"            # Codex·Claude 어댑터 포함
uv tool install "aops[dbx]"              # + databricks-sdk, mlflow[databricks], databricks-agentbricks
uv tool install "aops[omni]"             # + omnigent[databricks] (Python 3.12+, Node.js 22+, tmux 필요)
uvx --from "aops[local]==2.0.0" aops init my-agent   # 설치 없이 실행
```

- Python 최소 버전: local·dbx 3.10 이상(`claude-agent-sdk` 기준), omni 3.12 이상(Omnigent 기준).

프로젝트 안에서는 `uv run aops ...`로 프로젝트에 고정된 버전을 쓴다.

---

## 12. 리포 구조 (uv workspace)

```text
agentops-v2/
├── pyproject.toml            workspace 루트 + 메타 패키지 (extras: local, dbx, omni, codex, claude)
├── uv.lock
├── compat.toml               CI가 uv.lock에서 생성
├── packages/
│   ├── aops-core/            CLI, aops.toml 모델, 세션·인계, 원본 이벤트·변환기, provider·adapter 인터페이스, 개발 화면 서버, aops-recall MCP
│   ├── aops-ui/              개발 화면·console App이 함께 쓰는 화면 소스와 빌드 결과
│   ├── aops-console/         Databricks App (레지스트리·승인·모니터링 API, FastAPI)
│   ├── aops-harness-codex/   의존: openai-codex
│   ├── aops-harness-claude/  의존: claude-agent-sdk
│   ├── aops-local/           local provider (SQLite, MLflow)
│   ├── aops-dbx/             dbx provider (databricks-sdk, mlflow[databricks], databricks-agentbricks, databricks-langchain)
│   └── aops-omni/            omni provider (omnigent)
├── templates/                aops init 템플릿 (dbx는 agentbricks init 결과 위에 aops 설정을 얹음)
├── bundles/                  admin setup 번들: 레지스트리 DDL, validate·배포 Job, console App, 동적 뷰
├── tests/
│   ├── fixtures/             하네스 버전별 녹화 출력
│   ├── contract/             어댑터·provider 계약 시험
│   └── e2e/
└── docs/
```

- 어댑터·provider는 entry point로 등록하고 core가 찾아 쓴다. 설치한 extras에 따라 기능이 켜진다.
- core는 상위 SDK를 import하지 않는다. 상위 의존은 어댑터·provider 패키지에만 둔다.
- 배포 패키지 이름은 공개 전에 정한다 (현재 골격의 `codex-agentops`는 특정 하네스 이름이 들어가 있어 바꾼다).

---

## 13. 개발 순서

| 단계 | 범위 | 끝나는 기준 |
| --- | --- | --- |
| 0 사전 실험 | ① Claude로 작업하다 Codex로 바꿔 인계 (넘어간 크기·기억 정도 측정, Codex는 `thread/inject_items`와 비교) ② Codex 스킬 사용 추정 방식의 정확도 ③ 터미널 직접 실행 세션이 프로젝트 hook으로 기록되는지 (신뢰·승인 절차 포함) ④ worktree 칸에서 Codex hook 승인이 유지되는지 ⑤ 구독 로그인으로 동시 2~3개 실행 시 hook·로그인 상태 | 다섯 가지 결과로 2장·7장·9장 batch 세부 확정 |
| 1 | core, `aops.toml`, 원본 이벤트·변환기, Codex·Claude 어댑터, 세션 저장·수동 전환·인계(파일 + 안내 + `aops-recall`), 터미널 세션 기록, 설정 자동 재생성, `init`·`run`(질문 하나)·`session`·`dev`(Chat)·`add`·`harness`·`doctor` | Claude로 시작한 대화를 Codex로 바꿔도 앞 내용을 기억하고, 사용 칩이 보임 |
| 1.5 | `session import`, 끝나지 않은 턴 체크포인트, 메모리 제안·승인, 이어가기 품질 시험 | 터미널에서 쓰던 Claude 세션을 개발 화면의 Codex로 이어감 |
| 2 | `run <질문 파일>`(배치, 칸별 작업 폴더), 사용률 집계, 가드레일 1·2층(선택 3층 hook 판정)과 개발 화면 스위치, `evaluate`(프로젝트 MLflow, `--suite redteam`), 형식 이전(`doctor --fix migrate`), `monitor --me` | 가드레일 켬·끔 × 하네스 2개 배치 비교, 평가 결과가 MLflow에 남음 |
| 3 | dbx: `configure`, `admin setup`(레지스트리 테이블·validate Job)·`admin policy`(배포 형식), Gateway 연결(권장), `aops dev`의 `agentbricks dev` 연동, UC trace, Databricks MLflow 평가, `validate`(Lakeflow Job), `register`(Delta, UC Skills 게시), Gateway 가드레일 정책, Agent sessions·memory, `configure`의 local → dbx 이전. 시작 전 확인: Agent sessions 쓰기·크기 한도 (`BEGIN ATOMIC`은 확인함) | local 기능 전체가 Databricks 기능으로 동작, 검증 Job 결과가 Delta에 남음, 다른 PC에서 같은 세션 이어감 |
| 4 | dbx: `deploy` 요청 → console App 승인 → 배포 Job(`agentbricks deploy`, `[release.guardrails]` 포함) → `promote`, `deploy --dev`(개인 시험 배포), console App(레지스트리·승인·모니터링), `monitor`(상태 경로, Apps telemetry, 동적 뷰, 사용량·예산), Databricks Sandbox 실행. 시작 전 확인: `DurableAgentServer`에서 하네스 기반 에이전트 실행, Sandbox에 하네스 CLI 넣기, OBO 사용량 기록과 App 권한 범위, 예산 계정 API, deployment jobs 연결 | 승인 없이는 배포되지 않고, 배포한 에이전트의 상태·MCP·사용량·예산을 console App에서 확인 |
| 5 | omni: Omnigent YAML, 세션 연동, aops 화면 통합 | Omnigent UI에서 인계·배치 비교·평가 |

**Omnigent 팀과의 연결 방식(세션·정책·스킬·도구 계약, 화면 삽입 방식)은 1단계 인터페이스를 확정하기 전에 합의한다.**

---

## 14. 실현 가능성 검토와 제한

2026-10-30에 "된다고 적은 것"을 하나씩 다시 확인했다. 2026-11-01부터 시험 워크스페이스를 새 워크스페이스로 옮겼고(사용량 테이블 지연 23분, 과금 테이블 약 1.8시간, Agent sessions·memory·Sandbox·UC Skills API 응답, 리전 ap-northeast-1), 이전 수치는 삭제 예정인 이전 워크스페이스에서 잰 값이다. 방법은 네 가지다. Codex 소스(`openai/codex` rust-v0.163.0)와 로컬 바이너리로 만든 app-server 스키마를 봤다. `openai-codex`·`claude-agent-sdk`·`databricks-sdk` 0.158.0·`databricks-agentbricks` 0.7.1·`omnigent` 0.20.0 패키지 내용을 열어 봤다. 공식 문서를 확인했다. Databricks 검증 워크스페이스에서는 조회만 했다. 모델을 부르는 실제 실행은 하지 않았다. 그래서 "실행해서 확인"이 필요한 항목은 13장의 0단계·3단계·4단계 사전 확인으로 넘겼다.

### 14.1 판정 요약

● 가능 · △ 제한 있음(설계로 대응) · ? 확인 필요(실행해 봐야 앎)

| 기능 | 판정 | 확인된 제한 | 설계 대응 |
| --- | --- | --- | --- |
| 하네스 전환 인계 | ● | 하네스 내부 상태(도구 원본, 추론, 캐시)는 못 옮긴다. Claude는 외부 대화를 세션에 넣는 방법이 없다 | 인계 파일 + 짧은 안내 + `aops-recall`. Codex는 `thread/inject_items`. 기억 정도는 0단계에서 측정 |
| 같은 하네스 고유 재개 | △ | 버전이 달라도 재개된다는 보장이 없다. Claude 세션 형식은 내부용이고 30일 뒤 지워진다. Codex는 `CODEX_HOME`에 묶인다 | 같은 실행 파일·버전일 때만 시도하고, 실패하면 인계. 원본은 aops가 보관 |
| 터미널 직접 실행 기록 | △ | Codex는 프로젝트 신뢰 + hook마다 승인이 필요하고, 내용이 바뀌면 다시 승인해야 한다. 회사 관리 설정이 hook을 막을 수 있다. 사용자가 끄면 기록되지 않는다(의도한 동작) | 내용이 바뀌지 않는 한 줄 hook, `aops doctor`는 상태만 알림, 가져오기는 사용자가 직접 `session import` |
| 도구·MCP 사용 표시 | ● | Codex app-server는 experimental 표기. `exec --json`에는 hook 이벤트가 없다 | app-server 기본, 하네스 버전별 녹화 재생 시험 |
| 스킬 사용 표시 | Claude ● · Codex △ | Codex에는 스킬 사용 이벤트가 없다 | `<skill>` 조각과 `SKILL.md` 읽기로 추정하고 "추정"으로 표시 |
| 하네스 버전 고정 | △ | aops가 구동하는 하네스만 고정된다. 터미널 하네스와 구독 로그인 실행은 사용자 설치본이다. SDK가 CLI보다 늦게 나온다 | 실제 실행 파일·버전 기록, 호환표와 다르면 경고 |
| 구독 로그인 | △ 불명확 | Anthropic은 제3자가 사용자 대신 구독 자격으로 요청을 보내는 것을 허용하지 않는다. 다만 본인이 수정하지 않은 Claude Code에 본인 구독으로 로그인하는 것은 막지 않는다 | 사용자 설치본 구동, 자격 증명 미취급, 구독 배치는 낮은 동시 실행. 공개 배포 전에 Anthropic에 확인 |
| 배치 동시 실행 | △ | 하네스 홈을 나누면 로그인이 깨질 수 있다(Codex 토큰 갱신 충돌 이슈, Claude 키체인 분리) | 홈은 공유하고 작업 폴더만 분리, hook 실행 이벤트로 확인 |
| 2층 hook 가드레일 (개발) | ● | 완전한 차단 경계가 아니다. Codex 웹 검색에는 걸리지 않는다. 사용자가 끌 수 있다(의도한 동작) | 개발 중에는 시험 도구. 운영 규칙은 `[release.guardrails]`로 배포 에이전트에 넣고 validate가 검사 |
| Gateway 가드레일 | △ | Beta. 부착은 UI 전용이고 공개 조회 API가 없다. 차단 응답도 HTTP 200이다 | 점검표 + 시험 질문으로 실제 차단 확인 |
| dbx 세션·메모리 | △ | Beta. 크기·보존 기간이 문서에 없고, 권한은 저장소 단위뿐이다. Lakebase 비용이 든다 | 3단계 전 쓰기 시험, 민감 정보는 2층 규칙으로 가린 뒤 저장 |
| Databricks Sandbox | △ | Beta. 4 vCPU·8GB 고정, 외부 네트워크 제한 설정 불가, 파일 동기화 API 없음, SDK와 실제 응답 필드가 다름 | git·명령 실행으로 파일 이동. 하네스 CLI를 넣는 방법은 4단계 전 확인 |
| UC Skills | ● | Beta, 관리자가 켜야 한다 | – |
| 등록 | ● | agent-services는 Beta이고 호출 기능이 없다 | UC registered model + Delta `agent_versions` |
| `agentbricks dev`·`DurableAgentServer` | ● | Agent Bricks CLI Beta. 로컬에서는 세션·메모리 미연결. 배포 뒤 서버 종류 변경 불가 | 처음부터 `server = "agentbricks"`, legacy·custom 서버 미사용 |
| `aops validate` Lakeflow Job | ● (하네스 실행은 ?) | 서버리스 Job에서 codex·claude 실행 파일을 돌릴 수 있는지 미확인 | 코드 에이전트부터, 안 되면 Sandbox 작업으로 |
| Delta 레지스트리·승인 기록 | ● | 기본 키 강제 없음. `BEGIN ATOMIC`은 catalog commits(`delta.feature.catalogManaged`)를 켠 UC managed 테이블만, 문서에 GA·프리뷰 표기 없음. **시험 워크스페이스에서 두 테이블 커밋·쓰기 후 실패 시 롤백을 확인함** (서버리스 SQL warehouse) | 상태 조건 `MERGE`, 쓰기는 서비스 주체만 |
| MLflow deployment jobs | △ | Public Preview, 승인 방식 experimental, 문서 예시는 Model Serving 배포 | 선택 연결. 정본은 Delta, 배포 작업은 `agentbricks deploy` |
| LangGraph·OpenAI 에이전트 배포 | ● | Agent Bricks CLI가 Beta다 | 승인 뒤 배포 Job이 `agentbricks deploy` |
| Codex·Claude 기반 에이전트 배포 | ? | `agent.toml` framework는 `langgraph`·`openai`만 허용. 복구 시 하네스 재실행. Apps 자원·시간 한도 미기재, Linux용 codex wheel 미확인 | `DurableAgentServer` invoke 안에서 하네스 호출, 셸은 `system.ai.sandbox`. 4단계 전 실제 배포로 확인 |
| console App | ● | "내 것" 보기는 OBO 권한 범위 확인 필요 | 관리자 보기는 App 서비스 주체 권한 |
| monitor: 지금 활성인 에이전트·MCP | △ | Databricks 조회 API는 앱 프로세스가 떠 있는지까지만 준다. Apps telemetry(Beta)로 요청 기록은 받을 수 있지만 수집 지연이 문서에 없다 | 배포 에이전트에 상태 경로 + Apps telemetry |
| monitor: 사용량·MCP 호출 | ● (지연) | 1시간 이내 지연. 앱이 부르면 앱 서비스 주체로 기록된다 | 기준 시각 표시, OBO·요청 태그 |
| monitor: 예산 | △ | 계정 API다. 차단 기준이 있는 Gateway 예산의 USD 소진만 조회되고, 속도 한도의 남은 양은 조회할 수 없다 | 소진율만 표시 |
| monitor: 비용 | △ (지연) | 최대 12시간 지연. 최종 사용자별 비용이 없다 | 앱·Model Service 단위로 표시 |
| monitor: 개인 보기 | △ | system 테이블에 행 단위 필터가 없다 | `aops admin setup`이 본인 행 뷰 생성, console은 OBO로 조회 |
| omni | △ | Omnigent Beta(OSS는 alpha). 관리형 정책은 CEL만 된다. YAML에 스킬 필드가 없다. 세션 쓰기 공개 API가 없다. 화면 확장은 OSS에서만 확인했다 | 1단계 인터페이스 확정 전에 Omnigent 팀과 계약 합의 |

### 14.2 하네스 (Codex · Claude Code)

**Codex (0.163.0 소스·스키마 기준, 0.166.0과 대조)**
- hook 이벤트는 12종이다. `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PreCompact`, `PostCompact`, `SubagentStart`, `SubagentStop`, `Stop`, `Interrupt`, `SessionEnd`. 0.166에서 모델 요청 전후 2종이 추가됐다.
- hook을 두는 곳은 프로젝트 `.codex/`, 사용자 `~/.codex/`, 플러그인, 관리 설정이다. 프로젝트 `.codex/`는 신뢰한 프로젝트에서만 읽는다.
- **hook 승인은 내용 해시로 한다.** 공식 문서 문구는 "new or changed hooks are marked for review and skipped until trusted"다. 승인 상태는 사용자 설정에 저장되므로 aops가 대신 승인할 수 없다. 승인을 건너뛰는 `--dangerously-bypass-hook-trust`가 있지만, 켜진 hook을 모두 승인 없이 실행하므로 aops는 쓰지 않는다.
- `additionalContext`는 약 2,500 토큰이 기준이다. 넘으면 전체를 `<temp>/hook_outputs/...`에 저장하고 앞뒤 미리보기와 경로를 넘긴다. hook마다 `additionalContextLimit`로 바꿀 수 있다.
- PostToolUse는 셸, 파일 수정, MCP, 로컬 도구에 걸린다. 호스팅 웹 검색에는 걸리지 않는다.
- app-server는 CLI 도움말에 `[experimental]`로 표기된다. 안정 메서드는 thread start·resume·fork·`inject_items`, turn start·steer·interrupt 등이다. 메모리·검색 메서드는 실험 단계다. `openai-codex` SDK도 app-server를 하위 프로세스로 띄워 쓴다.
- 기록은 `$CODEX_HOME/sessions/.../rollout-*.jsonl`(압축 `.jsonl.zst` 가능)과 SQLite에 남는다. 버전 간 재개 보장 문구는 없다.
- 같은 홈을 함께 쓰면 기록 쓰기는 프로세스 간 잠금으로 맞춘다. ChatGPT 로그인의 "refresh token was already used" 오류는 열린 이슈로 여러 건 보고돼 있다(openai/codex #24365, #17340, #12755 등).
- 자체 메모리 `features.memories`는 기본 꺼짐이다. OTel 설정은 프로젝트 설정에서 무시된다. 도구 호출 span이 있는지는 확인하지 못했다.
- 작성 환경의 관리 설정 `/etc/codex/managed_config.toml`은 모델 공급자를 실제로 고정하고 있다(키 이름만 확인). `requirements.toml`에는 기능 스위치 하나만 있다. hook·MCP를 막는 키는 지금은 없다.

**Claude Code (2.1.310, `claude-agent-sdk` 0.2.173 기준)**
- `additionalContext`는 10,000자가 기준이다. 넘으면 파일로 저장하고 2,000자 미리보기만 넘긴다. 문서 문구는 "Claude can read the file, but Claude Code doesn't ask it to"다.
- **`-p`와 SDK 실행은 신뢰 확인 없이 프로젝트 hook을 실행한다.** 대신 프로젝트의 권한 허용 규칙은 무시한다. 다른 사람이 만든 저장소에서 aops 배치를 돌리면 그 저장소의 hook도 실행되므로, aops는 실행 전에 프로젝트 hook 목록을 보여준다.
- 관리 설정 `allowManagedHooksOnly`가 켜지면 프로젝트·사용자·플러그인 hook이 모두 막힌다. `allowManagedMcpServersOnly`, `allowedProviders`도 aops 설정을 막을 수 있다. 관리 hook이 없으면 사용자가 `disableAllHooks`로 모든 hook을 끌 수 있다. aops는 이것을 막지 않는다 (원칙 10).
- 세션 파일 형식은 "internal to Claude Code and changes between versions"다. 외부 대화를 넣는 공식 방법은 없다. `claude import`는 다른 도구의 설정을 가져오는 명령이고 세션 가져오기가 아니다.
- `claude-agent-sdk` wheel에는 CLI 실행 파일(약 275MB)이 들어 있다. macOS arm64, Linux x86_64, Windows wheel을 확인했다. 따로 지정하지 않으면 SDK는 내장 CLI(2.1.309)를 먼저 쓰므로 터미널의 `claude`(2.1.310)와 버전이 달라진다.
- `total_cost_usd`는 "client-side estimates, not authoritative billing data"다. 구독 한도(5시간 한도 등)의 남은 양은 출력에 없다.
- **로그인 관련 공식 문구:**
  - Agent SDK 문서: "Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK."
  - 법률·준수 문서: "Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, or Max plan credentials on behalf of their users." 같은 문서는 "Nor does it prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription"이라고도 쓰고, 한도는 "ordinary, individual usage"를 전제로 한다고 쓴다.
  - 해석: 사용자가 자기 PC에서 자기 구독으로 로그인한 Claude Code를 aops가 그대로 구동하는 것은 "본인 로그인"에 가깝다. 하지만 이를 명시적으로 허용하는 문장은 없다. 그래서 0장의 결정(자격 증명을 다루지 않고 사용자 설치본을 구동)을 유지하고, 공개 배포 전에 Anthropic에 확인한다.
- Gateway 주소(`ANTHROPIC_BASE_URL`)만 넣고 토큰을 넣지 않으면, 저장된 claude.ai 로그인이 그대로 자격 증명으로 쓰인다.
- MLflow의 `mlflow autolog claude`는 세션이 끝난 뒤 trace를 만들고, `.claude/settings.json`에 hook을 쓴다.

### 14.3 Databricks (dbx)

| 항목 | 확인한 사실 | 근거 |
| --- | --- | --- |
| Agent sessions·memory | 두 기능 모두 Beta다. API 이름(`AgentKitClient`, `session_stores`, `append_items`)은 설계와 같다. 검증 워크스페이스에서 세션 저장소·메모리 저장소 목록을 내 PC로 조회했다. 항목 크기·보존 기간은 문서에 없고, 권한은 저장소 단위뿐이다 | 공식 문서, 패키지 소스, 조회 |
| Databricks Sandbox | Beta이고 프리뷰를 켜야 한다. 4 vCPU·8GB 고정이다. 홈 100GB는 유지되고 홈 밖은 중지 시 지워진다. 활성 Sandbox는 사용자당 200개, 워크스페이스당 400개다. 외부 네트워크 제한은 설정할 수 없다. 서버리스 egress 제어가 켜진 워크스페이스에서는 쓰지 말라는 안내가 있다. 명령 실행에는 `databricks-sdk[sandbox]`가 필요하다. 파일 읽기·쓰기 API는 없다 | 공식 문서, SDK 소스 |
| UC Skills | `create_skill`·`finalize_skill`이 SDK 0.158.0에 있다. 파일은 Files API로 올린다. Beta, 관리자 활성화 필요 | SDK 소스, 공식 문서 |
| `ug` CLI | 명령은 `ug claude`·`ug codex`·`ug skills add`다. 설치는 GitHub 저장소에서 `uv tool install`로 한다 | 로컬 `ug --help`, 공식 문서 |
| Agent Bricks CLI | 0.7.1. `init`·`dev`·`deploy`·`deployments`·`memory`·`sessions` 명령이 있다. 프레임워크 선택지는 `langgraph`·`openai`이고, 서버는 기본형과 custom(FastAPI)이 있다. CLI가 experimental이고 기반 API는 프리뷰다. `deployments list`는 `agent-bricks-` 접두사 앱만 찾는다 | 패키지 소스, 공식 문서 |
| 등록 | AI 거버넌스 문서는 UC model로 등록한다고 쓴다. agent-services(Beta)는 "Runtime invocation is not available"이고 SDK 메서드가 없다 | 공식 문서, SDK 소스 |
| MLflow trace in UC | `<prefix>_otel_spans` 등 테이블을 쓴다. MLflow 3.14 이상과 SQL warehouse가 필요하다. 워크스페이스당 200 trace/초로 제한된다. 수집 지연은 문서에 없다 | 공식 문서 |
| 서비스 정책 | 문서 문구는 "You select and attach them by name through the Unity Gateway UI"다. SDK 0.158.0에 정책 메서드가 없다 | 공식 문서, SDK 소스 |
| Gateway 경로 | 검증 워크스페이스 사용량 테이블에서 최근 30일간 `/ai-gateway/codex`·`/ai-gateway/anthropic` 두 경로의 호출 기록을 확인했다 | 조회 |
| AI Playground | 문서 문구는 "Building agents in AI Playground is a legacy approach"다 (설계 서술과 일치) | 공식 문서 |
| 에이전트 서버 | AgentKit `DurableAgentServer`(권장, `/api/invocations`, Runtime Store + recovery)와 legacy 두 종(`LongRunningAgentServer`, MLflow `AgentServer`: `/responses`, `ResponsesAgent`)을 문서가 비교한다. "You can't change the agent server of an existing deployment." Runtime Store는 배포마다 Databricks 관리 Lakebase에 만들어지고 직접 고를 수 없다. 사용자 권한 도구는 `server = "agentbricks"`에서만 된다. `AgentApp`은 `DurableAgentServer`의 deprecated 별칭이다 | 공식 문서, 패키지 소스 |
| `agentbricks dev` | 배포와 같은 명령·환경으로 포트 8000에 로컬 서버를 띄운다. LangGraph 템플릿은 채팅 화면을 기본 포함한다(`--disable-chat-app`로 제외). 로컬에서는 메모리·세션이 연결되지 않는다 | 공식 문서, 템플릿 |
| 코드 실행 MCP | `agentbricks tools add sandbox`가 `system.ai.sandbox` managed MCP를 권한 축소 설정과 함께 붙인다 | 패키지 소스 |
| MLflow deployment jobs | UC 모델 버전 생성 시 Lakeflow Job(평가·승인·배포)을 돌린다. 승인 작업은 UC 태그 `Approved`를 확인하고, 승인에는 모델 APPLY TAG와 Job CAN MANAGE RUN이 필요하다. governed tag 정책으로 승인 그룹 제한·자기 승인 차단이 된다. Public Preview, 승인 방식 experimental | 공식 문서 |
| multi-statement transaction | `BEGIN ATOMIC … END`(SQL warehouse·서버리스·DBR 18.0+), 최대 100개 테이블, catalog commits를 켠 UC managed Delta·Iceberg만(새 테이블은 `TBLPROPERTIES ('delta.feature.catalogManaged' = 'supported')`, 기본값 아님), DDL 불가, 48시간 제한. 시험 워크스페이스에서 두 테이블 동시 커밋과, 쓰기 뒤 `SIGNAL`로 실패시켰을 때 두 테이블 모두 되돌려지는 것을 확인했다 | 공식 문서, 실측 |
| Apps telemetry | trace·log·metric을 고른 스키마의 `otel_metrics`·`otel_spans`·`otel_logs`(접두사 가능)에 쓴다. FastAPI는 `opentelemetry-instrument`로 자동 계측한다. 지원 지역 14곳(ap-northeast-2 포함), 같은 지역 managed Delta 테이블만 | 공식 문서 |

monitor 데이터의 출처·지연·제한은 [9장 `aops monitor`](#aops-monitor---me----all---watch---web-dashboard) 표에 정리했다.

### 14.4 Omnigent (omni)

- 공식 문서는 "Omnigent is in Beta", GitHub README는 "Status: alpha"다. 라이선스는 Apache-2.0이다. Python 3.12 이상, Node.js 22 이상, tmux가 필요하다.
- 에이전트 YAML의 실제 필드는 `name`, `instructions`, `executor`(harness·model·auth), `tools`, `policies`, `os_env.sandbox`다. 스킬 필드는 없다. 설계의 이전 서술(`config.harness`, `skills`)을 고쳤다.
- 관리형 정책은 "built-in contextual policies and custom policies written in Common Expression Language (CEL)"만 된다. 사용자 Python 정책은 안 된다. OSS YAML은 Python 처리기를 쓰므로 관리형과 다르다.
- 화면 확장: OSS 0.20.0에는 `omnigent.extensions` 확장 지점이 있다. 페이지, 메뉴, 명령, JS·CSS를 넣을 수 있고, 권한 항목에 세션 읽기는 있지만 세션 쓰기는 없다. 관리형에서도 되는지는 확인하지 못했다.
- 세션 API: 세션 항목 조회와 스트림은 있다. 메시지를 넣는 경로는 내부용으로 공개 명세에서 빠져 있다. 그래서 omni의 "Omnigent 세션 사이 인계"는 Omnigent 팀과 합의해야 만들 수 있다.

### 14.5 그 밖의 위험

| 항목 | 내용 |
| --- | --- |
| 인계 품질 | 요약을 거치며 세부 맥락이 빠질 수 있다. 0단계 실험과 이어가기 품질 시험으로 측정하고 예산·요약 방식을 조정한다 |
| 고유 재개와 보충의 충돌 | 같은 하네스로 돌아갈 때 고유 세션에는 다른 하네스 구간이 없다. 보충 내용과 중복·모순이 없는지 확인해야 한다 |
| 회사 간 대화 이동 | 인계는 한 회사의 모델에서 다른 회사의 모델로 대화 내용을 넘긴다. 회사 보안 정책에 따라 막아야 할 수 있어 프로젝트 단위로 끌 수 있게 한다 |
| 회사 수집 설정 | 회사 PC에는 하네스 프롬프트를 회사 수집기로 보내는 설정이 이미 있을 수 있다(예: Codex OTel의 프롬프트 기록). aops는 이를 바꾸지 않고 `aops doctor`에 표시만 한다 |
| Beta 의존 | Sandbox, Agent memory·sessions, UC Skills, 서비스 정책, production monitoring, Agent Bricks CLI, Omnigent가 Beta·experimental이다. 기능별로 local 구현으로 대신할 수 있게 한다 (4.2) |
| 라이선스 | 재배포하는 코드에 Elastic License 2.0 도구(Arize Phoenix)를 넣지 않는다. MLflow 외 기록 도구는 선택적 내보내기 대상이다 |

---

## 15. 참고

공개 문서만 적었다 (2026-10-30 확인).

- Databricks
  - Agent Bricks CLI: https://docs.databricks.com/aws/en/agents/custom-agents/agent-bricks-cli
  - Agent 배포 (Agent Runtime on Apps): https://docs.databricks.com/aws/en/agents/deploy · Agent server(`DurableAgentServer`·legacy 비교): https://docs.databricks.com/aws/en/agents/deploy/agent-server · legacy 앱 방식: https://docs.databricks.com/aws/en/agents/custom-agents/author-agent
  - MLflow deployment jobs: https://docs.databricks.com/aws/en/mlflow/deployment-job · multi-statement transaction: https://docs.databricks.com/aws/en/transactions/ · Apps telemetry: https://docs.databricks.com/aws/en/dev-tools/databricks-apps/observability
  - Agent sessions / memory: https://docs.databricks.com/aws/en/agents/agent-memory/managed-sessions · https://docs.databricks.com/aws/en/agents/agent-memory/managed-memory
  - Databricks Sandbox: https://docs.databricks.com/aws/en/compute/serverless/sandbox · https://docs.databricks.com/aws/en/compute/serverless/sandbox-usage-guide
  - UC Skills: https://docs.databricks.com/aws/en/agents/uc-skills · https://docs.databricks.com/aws/en/ai-gateway/skill-reference
  - Unity AI Gateway: https://docs.databricks.com/aws/en/ai-gateway · 서비스 정책 https://docs.databricks.com/aws/en/data-governance/unity-catalog/service-policies/ · `ug` CLI https://docs.databricks.com/aws/en/ai-gateway/coding-agent-ug-cli · 코딩 에이전트 연결 https://docs.databricks.com/aws/en/ai-gateway/coding-agent-integration-model-services · 속도 한도 https://docs.databricks.com/aws/en/ai-gateway/rate-limits · 예산 https://docs.databricks.com/aws/en/ai-gateway/budgets
  - 모니터링: system 테이블 https://docs.databricks.com/aws/en/admin/system-tables/ · Apps 모니터링 https://docs.databricks.com/aws/en/dev-tools/databricks-apps/monitor · 동적 뷰 https://docs.databricks.com/aws/en/views/dynamic · production monitoring https://docs.databricks.com/aws/en/mlflow3/genai/eval-monitor/production-monitoring
  - MLflow trace를 UC에 저장: https://docs.databricks.com/aws/en/mlflow3/genai/tracing/trace-unity-catalog
  - AI Playground: https://docs.databricks.com/aws/en/large-language-models/ai-playground
  - Omnigent: https://docs.databricks.com/aws/en/omnigent · https://github.com/omnigent-ai/omnigent
- 하네스
  - Codex: https://github.com/openai/codex · hooks https://learn.chatgpt.com/docs/hooks · app-server https://learn.chatgpt.com/docs/app-server · 설정 https://learn.chatgpt.com/docs/config-file/config-reference
  - Claude Code: https://github.com/anthropics/claude-code · Agent SDK https://code.claude.com/docs/en/agent-sdk/overview · hooks https://code.claude.com/docs/en/hooks · 권한·신뢰 https://code.claude.com/docs/en/permissions · 세션 https://code.claude.com/docs/en/sessions · 메모리 https://code.claude.com/docs/en/memory · 법률·준수 https://code.claude.com/docs/en/legal-and-compliance · Gateway 연결 https://code.claude.com/docs/en/llm-gateway
  - MLflow Claude Code 기록: https://mlflow.org/docs/latest/genai/tracing/integrations/listing/claude_code
- 표준
  - MCP: https://modelcontextprotocol.io/specification/latest · AG-UI: https://docs.ag-ui.com · OpenTelemetry GenAI: https://github.com/open-telemetry/semantic-conventions-genai
- 도구
  - uv workspace: https://docs.astral.sh/uv/concepts/projects/workspaces/ · MLflow GenAI: https://mlflow.org/docs/latest/genai/ · promptfoo: https://github.com/promptfoo/promptfoo
