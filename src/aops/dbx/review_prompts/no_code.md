# 노코드(Genie) 에이전트 검토 기준

노코드 에이전트는 Genie 스페이스입니다. `genie/space.json`이 정의입니다:
`data_sources`(테이블·메트릭 뷰와 컬럼 설정 `column_configs`: 설명·동의어·숨김), `instructions`(`text_instructions` 지침,
`example_question_sqls` 예제 질문·SQL, `sql_snippets`, `join_specs`), `benchmarks`(질문·정답 SQL), `config.sample_questions`(샘플 질문).
운영용 Genie는 이 정의 그대로 만들어지고, 공개 그룹이 질문합니다.

## 더 볼 것

- 지침·예제·샘플 질문에 사내 정보나 특정 사람·고객이 들어 있지 않은지
- 예제 SQL·벤치마크가 개인정보 컬럼을 그대로 조회하지 않는지
- 데이터 소스가 목적에 필요한 것만인지, 민감한 컬럼이 숨겨져 있는지

## 체크리스트

- genie_instructions: 지침(text_instructions)이 답의 범위·형식·주의할 점을 분명히 하고 사내 정보를 담지 않는다
- genie_examples: 예제 SQL·벤치마크가 실제 질문을 대표하고, 개인정보 컬럼을 그대로 조회하지 않는다
- genie_data_scope: 데이터 소스가 목적에 필요한 것만이고, 개인정보·민감 컬럼은 숨겨져 있다
- genie_public_text: 샘플 질문·설명·동의어가 공개 그룹에 보여도 되는 내용이다
