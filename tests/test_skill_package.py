from pathlib import Path


def test_aemeath_butler_skill_is_packaged_for_review():
    path = Path(__file__).parents[1] / "hermes_skills" / "productivity" / "aemeath-butler" / "SKILL.md"
    content = path.read_text(encoding="utf-8")

    assert content.startswith("---\nname: aemeath-butler")
    assert "confirmation buttons" in content
    assert "Never invent a task id" in content
