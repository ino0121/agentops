# aops v2

AgentOps(`aops`)는 에이전트의 전 라이프사이클을 관리하는 오픈소스 도구입니다. 자체 엔진 없이 기존 하네스(Codex, Claude Code, OpenAI Agents SDK, LangGraph 등)와 플랫폼 SDK를 감싸는 래퍼입니다.

- **하네스를 바꿔도 세션과 메모리가 이어집니다.** Claude Code 사용량이 다 떨어지면 Codex로 넘어가 같은 대화를 계속합니다. 세션·메모리의 정본은 aops가 갖습니다.
- 에디션: `local` → `dbx`(Databricks) → `omni`(Omnigent). 뒤 에디션이 앞 에디션의 기능을 모두 포함합니다.
- `aops init`으로 만든 폴더 하나에서 실험·배치 비교·평가·가드레일 시험을 합니다.
- uv 기반이며, 하네스 버전은 `uv.lock`과 호환표로 고정합니다.

설계: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (그림과 표로 본 판: `docs/ARCHITECTURE.html`)

상태: 설계 단계입니다. 코드는 골격과 레지스트리 테이블 정의(`bundles/registry/`)만 있습니다.

v1(마지막 버전 1.3.0)은 [`v1.3.0` 태그](https://github.com/jeeHwon/agentops/tree/v1.3.0)에 있습니다. v2는 v1 코드를 가져오지 않고 새로 만듭니다.
