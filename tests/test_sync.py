from aops import init
from aops.hashing import folder_sha256, skills_sha256
from aops.project import Project
from aops.sync import sync


def make(tmp_path):
    return init.create(tmp_path, "price-helper")


def test_init_writes_template_and_harness_settings(tmp_path):
    project = make(tmp_path)
    root = project.root
    assert project.name == "price-helper" and project.harness == "claude"
    for rel in ("README.md", "aops.toml", "SPEC.md", "agent/instructions.md", "agent/skills/my-skill/SKILL.md"):
        assert (root / rel).is_file()
    for rel in (".claude/skills/my-skill/SKILL.md", ".agents/skills/my-skill/SKILL.md"):
        assert (root / rel).read_text() == (root / "agent/skills/my-skill/SKILL.md").read_text()
    for name in ("CLAUDE.md", "AGENTS.md"):
        assert (root / name).read_text() == (root / "agent/instructions.md").read_text().strip() + "\n"
        assert "<!--" not in (root / name).read_text()


def test_instruction_files_follow_the_source_unless_edited_by_hand(tmp_path):
    project = make(tmp_path)
    root = project.root
    (root / "agent/instructions.md").write_text("새 지시")
    result = sync(Project.load(root))
    assert (root / "CLAUDE.md").read_text() == "새 지시\n" and "CLAUDE.md" in result.written

    (root / "AGENTS.md").write_text("손으로 고침")
    (root / "agent/instructions.md").write_text("또 바뀐 지시")
    result = sync(Project.load(root))
    assert (root / "AGENTS.md").read_text() == "손으로 고침" and "AGENTS.md" in result.kept
    assert (root / "CLAUDE.md").read_text() == "또 바뀐 지시\n"


def test_instruction_file_not_made_by_aops_is_kept_and_old_block_form_is_rewritten(tmp_path):
    root = make(tmp_path).root
    (root / ".aops/sync.json").unlink()
    (root / "CLAUDE.md").write_text("팀이 쓴 CLAUDE.md")
    (root / "AGENTS.md").write_text("<!-- aops:start · made from aops.toml, aops rewrites this block -->\n옛 지시\n<!-- aops:end -->\n")
    result = sync(Project.load(root))
    assert "CLAUDE.md" in result.kept and (root / "CLAUDE.md").read_text() == "팀이 쓴 CLAUDE.md"
    assert (root / "AGENTS.md").read_text() == (root / "agent/instructions.md").read_text().strip() + "\n"


def test_sync_updates_and_removes_only_its_own_skills(tmp_path):
    project = make(tmp_path)
    root = project.root
    (root / "agent/skills/my-skill/SKILL.md").write_text("---\nname: my-skill\ndescription: v2\n---\n")
    (root / ".claude/skills/mine").mkdir()
    (root / ".claude/skills/mine/SKILL.md").write_text("user skill")
    sync(Project.load(root))
    assert "v2" in (root / ".claude/skills/my-skill/SKILL.md").read_text()
    assert (root / ".claude/skills/mine/SKILL.md").is_file()

    import shutil
    shutil.rmtree(root / "agent/skills/my-skill")
    sync(Project.load(root))
    assert not (root / ".claude/skills/my-skill").exists()
    assert (root / ".claude/skills/mine").exists()


def test_sync_leaves_a_hand_edited_copy(tmp_path):
    project = make(tmp_path)
    root = project.root
    (root / ".agents/skills/my-skill/SKILL.md").write_text("edited by hand")
    (root / "agent/skills/my-skill/SKILL.md").write_text("---\nname: my-skill\ndescription: v3\n---\n")
    result = sync(Project.load(root))
    assert ".agents/skills/my-skill" in result.kept
    assert (root / ".agents/skills/my-skill/SKILL.md").read_text() == "edited by hand"


def test_hash_follows_the_reference_rule(tmp_path):
    folder = tmp_path / "s"
    (folder / "ref").mkdir(parents=True)
    (folder / "SKILL.md").write_text("a")
    (folder / "ref" / "x.md").write_text("bc")
    import hashlib
    expected = hashlib.sha256(b"SKILL.md\x001\x00a" + b"ref/x.md\x002\x00bc").hexdigest()
    assert folder_sha256(folder) == expected
    assert skills_sha256({"b": "2", "a": "1"}) == hashlib.sha256(b"a:1\nb:2").hexdigest()
