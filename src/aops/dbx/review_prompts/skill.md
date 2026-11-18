# 스킬 기반 에이전트 검토 기준

스킬 기반 에이전트는 지시(`agent/instructions.md`)와 스킬(`agent/skills/<이름>/SKILL.md`)로 하네스(Claude Code·Codex)가 일합니다.
SKILL.md의 `description`을 보고 하네스가 스킬을 고르고, 본문의 규칙대로 답합니다. 평가셋(`evals/questions.yaml`)은 배포 전 품질 평가에 쓰입니다.

## 더 볼 것

- 지시와 스킬이 SPEC.md에 적은 일만 다루는지, 서로 모순되지 않는지
- 스킬 규칙(계산 순서, 예외, 답 형식)이 분명해서 같은 질문에 같은 답이 나오는지
- 평가셋의 질문과 정답이 스킬 규칙으로 계산한 값과 맞는지

## 체크리스트

- skill_scope: 지시와 스킬이 SPEC.md에 적은 일만 다루고 서로 모순되지 않는다
- skill_rules: 스킬 규칙(계산·절차·예외·답 형식)이 분명하고 빠진 경우가 없다
- eval_alignment: 평가셋의 질문·정답이 스킬 규칙과 맞다 (평가셋이 없으면 na)
