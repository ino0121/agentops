from aops import init
from aops.hashing import folder_sha256, skills_sha256
from aops.project import Project
from aops.sync import END, START, sync


def make(tmp_path):
    return init.create(tmp_path, "price-helper")


def test_init_writes_template_and_harness_settings(tmp_path):
    project = make(tmp_path)
    root = project.root
    assert project.name == "price-helper" and project.harness == "claude"
    for rel in ("aops.toml", "SPEC.md", "agent/instructions.md", "agent/skills/vat-calculator/SKILL.md"):
        assert (root / rel).is_file()
    for rel in (".claude/skills/vat-calculator/SKILL.md", ".agents/skills/vat-calculator/SKILL.md"):
        assert (root / rel).read_text() == (root / "agent/skills/vat-calculator/SKILL.md").read_text()
    for name in ("CLAUDE.md", "AGENTS.md"):
        text = (root / name).read_text()
        assert START in text and "vat-calculator" in text and END in text


def test_sync_keeps_text_outside_the_block_and_follows_changes(tmp_path):
    project = make(tmp_path)
    root = project.root
    (root / "CLAUDE.md").write_text("내가 쓴 메모\n\n" + (root / "CLAUDE.md").read_text())
    (root / "agent/instructions.md").write_text("새 지시")
    result = sync(Project.load(root))
    text = (root / "CLAUDE.md").read_text()
    assert text.startswith("내가 쓴 메모") and "새 지시" in text and "vat-calculator" not in text
    assert "CLAUDE.md" in result.written


def test_sync_updates_and_removes_only_its_own_skills(tmp_path):
    project = make(tmp_path)
    root = project.root
    (root / "agent/skills/vat-calculator/SKILL.md").write_text("---\nname: vat-calculator\ndescription: v2\n---\n")
    (root / ".claude/skills/mine").mkdir()
    (root / ".claude/skills/mine/SKILL.md").write_text("user skill")
    sync(Project.load(root))
    assert "v2" in (root / ".claude/skills/vat-calculator/SKILL.md").read_text()
    assert (root / ".claude/skills/mine/SKILL.md").is_file()

    import shutil
    shutil.rmtree(root / "agent/skills/vat-calculator")
    sync(Project.load(root))
    assert not (root / ".claude/skills/vat-calculator").exists()
    assert (root / ".claude/skills/mine").exists()


def test_sync_leaves_a_hand_edited_copy(tmp_path):
    project = make(tmp_path)
    root = project.root
    (root / ".agents/skills/vat-calculator/SKILL.md").write_text("edited by hand")
    (root / "agent/skills/vat-calculator/SKILL.md").write_text("---\nname: vat-calculator\ndescription: v3\n---\n")
    result = sync(Project.load(root))
    assert ".agents/skills/vat-calculator" in result.kept
    assert (root / ".agents/skills/vat-calculator/SKILL.md").read_text() == "edited by hand"


def test_hash_follows_the_reference_rule(tmp_path):
    folder = tmp_path / "s"
    (folder / "ref").mkdir(parents=True)
    (folder / "SKILL.md").write_text("a")
    (folder / "ref" / "x.md").write_text("bc")
    import hashlib
    expected = hashlib.sha256(b"SKILL.md\x001\x00a" + b"ref/x.md\x002\x00bc").hexdigest()
    assert folder_sha256(folder) == expected
    assert skills_sha256({"b": "2", "a": "1"}) == hashlib.sha256(b"a:1\nb:2").hexdigest()
