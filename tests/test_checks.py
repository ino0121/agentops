"""`aops validate`: the template checklist of the three kinds of agent (aops.validate)."""

from pathlib import Path

from aops import init, package, validate
from aops.dbx.jobs import print_validation
from aops.dbx.service import SKILL_NAME, check_skill_agent, find_secrets

SPEC = ("---\nagent_id: a\nname: a\nbuild_type: skill\nowner: dev@x.com\napprovers: boss@x.com, group:pricing-leads\n"
        "service_criticality: medium\ndata_sensitivity: internal\ndescription: 할인 합계\n---\n\n# a\n\n영업팀이 견적 낼 때 쓴다.\n")
QUESTIONS = "questions:\n  - id: q1\n    text: 10개면?\n    expected: 5%\n"


def skill(name, description, body="10개 이상 5% 할인"):
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n".encode()


def skill_agent(**extra):
    files = {"SPEC.md": SPEC.encode(), "aops.toml": b'[project]\nname = "a"\n', "agent/instructions.md": "할인 도우미입니다.".encode(),
             "agent/skills/k/SKILL.md": skill("k", "할인을 물을 때"), "evals/questions.yaml": QUESTIONS.encode()}
    return {**files, **extra}


def by_name(steps):
    return {s["name"]: s for s in steps}


def failed_rules(steps):
    return sorted(r["id"] for s in steps for r in s.get("rules") or [] if not r["passed"])


def test_a_complete_skill_agent_passes_every_rule():
    steps = validate.check(skill_agent())
    assert [s["name"] for s in steps] == ["format", "config", "instructions", "skills", "evals", "secrets"]
    assert validate.passed(steps) and failed_rules(steps) == []
    assert all(r["fix"] and r["level"] in ("ERROR", "WARN") for s in steps for r in s["rules"])


def test_untouched_init_template_fails_with_the_rules_to_fix(tmp_path):
    project = init.create(tmp_path, "fresh", edition="dbx")
    steps = validate.check(package.read(package.build(project).data))
    assert not validate.passed(steps)
    assert failed_rules(steps) == ["evals.questions", "instructions.template", "skills.body", "skills.template", "spec.approvers", "spec.body",
                                   "spec.description"]
    errors = sorted(r["id"] for s in steps for r in s["rules"] if not r["passed"] and r["level"] == "ERROR")
    assert errors == ["skills.template", "spec.description"]  # the rest are warnings
    assert "템플릿" in by_name(steps)["format"]["detail"] and "my-skill" in by_name(steps)["skills"]["detail"]


def test_skill_name_follows_agent_skills_rule():
    for good in ("a", "discount-policy", "a1-b2", "x" * 64):
        assert SKILL_NAME.match(good), good
    for bad in ("-a", "a-", "a--b", "A", "x" * 65, ""):
        assert not SKILL_NAME.match(bad), bad
    steps = validate.check(skill_agent(**{"agent/skills/Bad/SKILL.md": skill("other", "언제")}))
    assert "skills.name" in failed_rules(steps) and by_name(steps)["skills"]["status"] == "failed"


def test_description_is_counted_in_characters():
    assert by_name(check_skill_agent(skill_agent(**{"agent/skills/k/SKILL.md": skill("k", "가" * 1000)})))["skills"]["status"] == "passed"
    steps = check_skill_agent(skill_agent(**{"agent/skills/k/SKILL.md": skill("k", "가" * 1025)}))
    assert by_name(steps)["skills"]["status"] == "failed" and "skills.description" in failed_rules(steps)


def test_renamed_skill_with_template_description_is_rejected():
    steps = check_skill_agent(skill_agent(**{"agent/skills/k/SKILL.md": skill("k", init.SKILL_DESCRIPTION)}))
    assert by_name(steps)["skills"]["status"] == "failed"


def test_format_detail_names_only_the_problems():
    spec = SPEC.replace("service_criticality: medium", "service_criticality: huge")
    step = validate.check_spec({"SPEC.md": spec.encode()})
    assert step["status"] == "failed" and step["detail"] == "SPEC.md: 허용되지 않는 값 service_criticality='huge'"
    assert validate.check_spec({})["detail"].startswith("SPEC.md: SPEC.md가 없거나")


def test_security_level_follows_the_policy_list():
    spec = SPEC.replace("description:", "security_level: topsecret\ndescription:").encode()
    assert validate.check_spec({"SPEC.md": spec})["status"] == "failed"
    assert validate.check_spec({"SPEC.md": spec}, policy={"security_levels": ["general", "topsecret"]})["status"] == "passed"
    assert validate.check_spec({"SPEC.md": spec}, policy={"security_levels": [{"code": "topsecret", "label": "극비"}]})["status"] == "passed"


def test_config_belongs_to_the_agent_and_says_its_kind():
    steps = by_name(validate.check(skill_agent(**{"aops.toml": b'[project]\nname = "other"\n'})))
    assert steps["config"]["status"] == "failed" and "other" in steps["config"]["detail"]
    steps = by_name(validate.check(skill_agent(**{"aops.toml": b'[project]\nname = "a"\ntype = "code"\n'})))
    assert "config.type" in failed_rules(steps.values())
    assert validate.check_config({"SPEC.md": SPEC.encode()}, "skill")["status"] == "failed"  # no aops.toml


def test_eval_set_gaps_are_warnings():
    steps = validate.check({k: v for k, v in skill_agent().items() if k != "evals/questions.yaml"})
    assert validate.passed(steps) and failed_rules(steps) == ["evals.present"]
    unjudged = validate.check(skill_agent(**{"evals/questions.yaml": "questions:\n  - id: q1\n    text: 10개면?\n".encode()}))
    assert validate.passed(unjudged) and "채점할 수 있는 질문이 없습니다" in by_name(unjudged)["evals"]["detail"]


def test_code_agent_is_an_agent_bricks_project():
    files = {"SPEC.md": SPEC.replace("build_type: skill", "build_type: code").encode(), "aops.toml": b'[project]\nname = "a"\ntype = "code"\n',
             "agent.toml": b'[agent]\nframework = "openai"\nserver = "agentbricks"\n', "app.yaml": b'command: ["uv", "run", "start-server"]\n',
             "pyproject.toml": b"[project]\nname = 'a'\n", "agent/agent.py": b"agent = None\n", "uv.lock": b""}
    steps = validate.check(files)
    assert [s["name"] for s in steps] == ["format", "config", "project", "secrets"] and failed_rules(steps) == []
    leftovers = validate.check({**{k: v for k, v in files.items() if k != "uv.lock"}, validate.SAMPLE_TOOL: b"def tool(): ..."})
    assert validate.passed(leftovers) and failed_rules(leftovers) == ["project.lock", "project.sample"]
    broken = validate.check({**files, "agent.toml": b'[agent]\nframework = "crewai"\nserver = "custom"\n'})
    assert "project.agent_toml" in failed_rules(broken) and not validate.passed(broken)


def test_no_code_snapshot_checks_spec_definition_and_secrets():
    from aops.dbx import nocode

    spec = SPEC.replace("build_type: skill", "build_type: no_code")
    files = nocode.bundle("a", spec, nocode.initial_space(["main.s.t"], "질문"))
    steps = validate.check(files)
    assert [s["name"] for s in steps] == ["format", "definition", "secrets"]
    assert "nocode.consumer_group" in failed_rules(steps)  # a warning: only the owner would use it
    assert by_name(steps)["format"]["status"] == "passed" and by_name(steps)["definition"]["status"] == "failed"  # no examples, benchmarks


def test_env_templates_are_not_forbidden_but_their_content_is_scanned():
    assert find_secrets({".env": b"A=1", "app/.env.local": b"A=1", "key.pem": b"x"}) == [".env (금지 파일)", "app/.env.local (금지 파일)", "key.pem (금지 파일)"]
    assert find_secrets({".env.example": b"TOKEN=dapi" + b"0" * 32}) == [".env.example (Databricks 토큰)"]
    assert find_secrets({".env.example": b"TOKEN=<your token>", "app/.env.sample": b"x"}) == []
    steps = validate.check(skill_agent(**{".env": b"A=1"}))
    assert "secrets.files" in failed_rules(steps) and not validate.passed(steps)


def test_validation_report_shows_rules_and_files(capsys):
    steps = check_skill_agent(skill_agent())
    print_validation("r1", "cat.sch", {"agent_id": "a", "version": "1.0.0", "artifact_path": "/Volumes/c/s/a/1.0.0.zip",
                                       "sha256": "abc", "files": ["SPEC.md"], "steps": steps, "status": "passed"})
    out = capsys.readouterr().out
    assert "규칙: SPEC.md: spec.present" in out and "검사한 파일" in out and "cat.sch.validation_runs" in out


def test_validate_doc_is_current():
    doc = Path(__file__).resolve().parents[1] / "docs" / "validate.md"
    assert doc.read_text(encoding="utf-8") == validate.markdown(), "run scripts/validate_docs.py"
    for row in validate.catalog():
        assert f"`{row['id']}`" in doc.read_text(encoding="utf-8")


def test_approvers_are_people_or_groups_other_than_the_owner():
    def rules(approvers, policy=None, lookup=None):
        spec = SPEC.replace("approvers: boss@x.com, group:pricing-leads", f"approvers: {approvers}")
        return {r["id"]: r for r in validate.check_spec({"SPEC.md": spec.encode()}, policy=policy, lookup=lookup)["rules"]}

    assert validate.approvers_of({"approvers": "boss@x.com, user:lee@x.com, group:leads, boss@x.com"}) == ["boss@x.com", "lee@x.com", "group:leads"]
    assert rules("boss@x.com")["spec.approvers_other"]["passed"]
    assert not rules("dev@x.com")["spec.approvers_other"]["passed"]  # only the owner: nobody could approve
    assert not rules("boss, group:")["spec.approvers_format"]["passed"]
    empty = rules("")["spec.approvers"]
    assert not empty["passed"] and empty["level"] == "WARN"
    assert rules("", policy={"approvers_required": True})["spec.approvers"]["level"] == "ERROR"
    assert "spec.approvers_exist" not in rules("boss@x.com")  # a PC cannot look the workspace up
    known = {"boss@x.com": True, "group:leads": False, "lee@x.com": None}
    assert not rules("boss@x.com, group:leads", lookup=known.get)["spec.approvers_exist"]["passed"]
    unsure = rules("boss@x.com, lee@x.com", lookup=known.get)["spec.approvers_exist"]
    assert unsure["passed"] and unsure["level"] == "WARN"


def test_init_writes_the_approvers_into_spec(tmp_path):
    project = init.create(tmp_path, "priced", edition="dbx", approvers=["boss@x.com", "group:leads"])
    spec = package.front_matter((project.root / "SPEC.md").read_text(encoding="utf-8"))
    assert validate.approvers_of(spec) == ["boss@x.com", "group:leads"]
    assert init.render_spec({"agent_id": "a", "approvers": ["boss@x.com"], "build_type": "skill"}).count("approvers: boss@x.com") == 1
