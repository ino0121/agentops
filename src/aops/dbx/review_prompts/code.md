# 코드 기반 에이전트 검토 기준

코드 기반 에이전트는 Agent Bricks 프로젝트입니다: `agent/agent.py`(에이전트), `agent/tools/`(도구), `agent/mcps.py`(MCP),
`runtime/`(서버), `agent.toml`·`app.yaml`·`pyproject.toml`(설정). 운영에서는 Databricks App으로 돌고 앱의 서비스 주체 권한을 씁니다.

## 더 볼 것

- 비밀값을 코드·설정에 두지 않고 Databricks secret이나 Unity Catalog 연결로 받는지
- 외부로 나가는 호출(HTTP, MCP, 도구)이 목적에 맞는 곳만 부르는지
- Agent Bricks 템플릿의 샘플 도구·예시 코드 중 쓰지 않는 것이 모델에 붙어 있는지 (`agent/tools/`의 `get_current_time`·`send_message` 같은 것)
- Agent Bricks가 만든 서버와 채팅 화면(`runtime/`, `ui/`), 템플릿 안내 문서(`README.md`, `CHAT_APP.md`, `AGENTKIT_CONTRACT.md`), 템플릿 테스트(`tests/`)는
  운영 앱의 일부이거나 무해한 안내입니다. 템플릿 그대로면 `unnecessary`·`code_template_leftovers`에서 문제로 보지 않습니다. 고쳤으면 다른 코드처럼 봅니다
- 도구·모델 호출이 실패할 때 처리하고, 오류 메시지에 내부 정보를 그대로 내보내지 않는지

## 체크리스트

- code_config: 설정·환경 변수가 비밀값을 코드에 두지 않고 Databricks secret·UC 연결을 쓴다
- code_external_calls: 외부로 나가는 호출(HTTP, MCP, 도구)이 목적에 맞고 필요한 곳만 부른다
- code_template_leftovers: 쓰지 않는 템플릿 샘플 도구·예시 코드가 모델에 붙어 있지 않다 (Agent Bricks 서버·채팅 화면·안내 문서는 템플릿 그대로면 괜찮다)
- code_error_handling: 도구·모델 호출 실패를 처리하고, 오류에 내부 정보를 그대로 내보내지 않는다
