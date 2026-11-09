# aops

Databricks 위에서 AI 에이전트를 개발부터 운영까지 관리하는 오픈소스 도구입니다. Claude Code·Codex 같은 하네스로 에이전트를 만들고, Databricks 기능으로 기록·검증·배포·운영합니다.

![aops 아키텍처](docs/architecture.png)

## 주요 기능

목표로 하는 기능입니다. 지금 동작하는 범위는 [지금 되는 것](#지금-되는-것-스킬-기반)을 보세요.

- **에이전트 3종을 하나로:** 스킬 기반(누구나), 코드 기반(AI 개발자), 노코드(데이터 실무자, Genie Agent)를 같은 검증·레지스트리·배포·운영으로 관리합니다. 코드·노코드는 dbx 에디션부터 씁니다.
- **세션 이어가기:** 하네스를 바꿔도 대화와 메모리가 이어집니다.
- **구성별 비교:** 같은 질문을 하네스·모델·가드레일 구성별로 돌려 나란히 비교합니다.
- **평가·가드레일 시험:** MLflow로 채점하고, 레드팀 사례로 가드레일을 시험합니다.
- **검증 후 배포:** 등록·배포할 때만 관리자 정책을 검사하고, 승인된 버전만 배포합니다.
- **운영 모니터링:** 사용량·비용과 실행 중인 에이전트를 한 화면에서 봅니다.
- **Custom Front:** 조직의 웹·서비스가 aops 서버 API에 연결해 dbx 기능을 그대로 씁니다 (custom 에디션).

## 지금 되는 것 (스킬 기반)

지금은 **스킬 기반 에이전트**의 만들기부터 가져다 쓰기까지 dbx 에디션에서 동작합니다. 노코드(Genie Agent)는 연결 작업 중이고, 코드 기반(Agent Bricks)은 다음에 붙입니다.

| 단계 | 명령 | 도는 곳 | 쓰는 Databricks 기능 |
| --- | --- | --- | --- |
| 만들기 | `aops init my-agent --edition dbx` | 내 PC | 없음 (스킬 템플릿, `SPEC.md`, `aops.toml`) |
| 실행 | `aops run "<질문>"` | 내 PC (Claude Code·Codex) | MLflow trace (도구·스킬, 토큰·비용) |
| 하네스 바꾸기 | `aops session switch --harness codex` | 내 PC | 없음 (앞 대화를 넘겨 이어 감) |
| 등록 | `aops register` | aops 서버 | UC Volume(버전 zip), UC Skill, 레지스트리 Delta 테이블 |
| 검사·승인·배포 | `aops deploy` (검사만: `aops validate`) | aops 서버 | Lakeflow Jobs (서버리스, 서비스 주체) |
| 목록 | `aops list` | aops 서버 | 레지스트리 |
| 권한 | `aops promote my-agent --to group:<계정 그룹>` | aops 서버 | UC Skill 권한 (`READ VOLUME`) |
| 가져오기 | `aops load my-agent` | aops 서버 → 내 PC | 요청한 사람의 권한 확인, 해시 확인 |
| 준비 (관리자) | `aops admin setup --profile <프로필> --registry <catalog>.<schema> --warehouse <ID>` | 관리자 PC | Databricks App(aops 서버), Jobs, 레지스트리 |

- `aops run`은 내 PC에 설치된 `claude`·`codex` CLI를 SDK로 띄웁니다. 모델 호출은 하네스 설정을 따릅니다.
- 등록부터는 aops 서버가 서비스 주체로 레지스트리·Job·UC Skill을 씁니다. 사람은 요청만 합니다.
- aops 서버 API 중 지금 처리되는 경로는 [API](docs/api.md)의 "지금 상태"에 있습니다. 나머지는 형식만 있고 `501`을 돌려줍니다.

## 전체 명령어 (설계)

아래는 설계한 전체 명령입니다. `dev`, `run <질문 파일>`, `evaluate`, `monitor`는 아직 없습니다.

```bash
aops init my-agent         # 프로젝트 만들기
aops dev                   # 개발 화면
aops run questions.yaml    # 구성별 비교 실행
aops evaluate              # 평가
aops validate              # 관리자 정책 검사
aops register              # 버전 등록
aops deploy                # 배포 요청 → 승인 → 배포
aops monitor               # 운영 현황
aops serve                 # aops API 서버 (custom)
```

## 문서

- [개요](docs/overview.md): 단계별 Databricks 기능, 원칙, 에디션
- [명령어](docs/commands.md): 전체 명령과 옵션
- [프로젝트 폴더](docs/project.md): 폴더 구조와 `aops.toml`
- [레지스트리·승인](docs/registry.md): 관리자 정책, aops 서버, 테이블
- [API](docs/api.md): `aops serve`의 HTTP API와 명령 대응표

## 라이선스

[MIT](LICENSE)
