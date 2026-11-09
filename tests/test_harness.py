from aops.harness import claude, codex


def item(kind, **fields):
    return {"method": "item/completed", "payload": {"item": {"type": kind, **fields}}}


def test_codex_read_picks_final_answer_tools_skills_and_usage():
    events = [
        item("commandExecution", command="cat .agents/skills/maple-sql-style/SKILL.md"),
        item("agentMessage", phase="commentary", text="looking"),
        item("mcpToolCall", server="dbsql", tool="query"),
        item("agentMessage", phase="final_answer", text="done"),
        {"method": "thread/tokenUsage/updated", "payload": {"tokenUsage": {"total": {"totalTokens": 10}}}},
    ]
    turn = codex.read(events, native_session="t1")
    assert turn.text == "done"
    assert turn.tools == ["shell", "skill:maple-sql-style", "dbsql.query"]
    assert turn.usage == {"total": {"totalTokens": 10}, "turn": {"totalTokens": 10}}
    assert turn.native_session == "t1" and turn.events is events


def test_codex_turn_usage_is_this_turn_only():
    def usage(total, last):
        return {"method": "thread/tokenUsage/updated", "payload": {"tokenUsage": {
            "total": {"inputTokens": total, "outputTokens": 1}, "last": {"inputTokens": last, "outputTokens": 1}}}}
    # the thread had 100 input tokens before; this turn made two model calls of 30 and 40
    turn = codex.read([usage(130, 30), usage(170, 40)], native_session="t1")
    assert turn.usage["turn"] == {"inputTokens": 70, "outputTokens": 1}


def test_codex_read_without_final_phase_uses_last_message():
    turn = codex.read([item("agentMessage", text="a"), item("agentMessage", text="b")], native_session=None)
    assert turn.text == "b" and turn.tools == []


def test_claude_skill_tool_is_recorded_by_skill_name():
    assert claude.tool_name("Skill", {"skill": "maple-sql-style"}) == "skill:maple-sql-style"
    assert claude.tool_name("Read", {"file_path": "x"}) == "Read"


def test_claude_reads_project_settings_unless_the_project_asks_for_user_settings(tmp_path):
    from aops import init
    from aops.harness.claude import ClaudeHarness
    from aops.project import Project

    project = init.create(tmp_path, "agent-y")
    assert project.user_settings is False
    assert ClaudeHarness(cli_path="claude").setting_sources == ["project"]
    toml = project.root / "aops.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace("user_settings = false", "user_settings = true"), encoding="utf-8")
    assert Project.load(project.root).user_settings is True
    assert ClaudeHarness(cli_path="claude", user_settings=True).setting_sources == ["user", "project"]
