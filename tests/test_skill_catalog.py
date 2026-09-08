import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def get_principle_skills():
    skills_dir = REPO_ROOT / "skills"
    return sorted(skills_dir.glob("principle-*/SKILL.md"))


def test_principle_count():
    skills = get_principle_skills()
    assert len(skills) == 23, f"Expected 23 principle skills, found {len(skills)}"


def test_principle_frontmatter():
    skills = get_principle_skills()
    for skill_file in skills:
        content = skill_file.read_text(encoding="utf-8")
        assert content.startswith("---"), f"{skill_file} missing frontmatter delimiter"

        parts = content.split("---", 2)
        assert len(parts) >= 3, f"{skill_file} invalid frontmatter structure"
        frontmatter = parts[1]

        name_match = re.search(r"^name:\s*(.+)$", frontmatter, re.MULTILINE)
        desc_match = re.search(r"^description:\s*(.+)$", frontmatter, re.MULTILINE)

        assert name_match, f"{skill_file} missing 'name:' in frontmatter"
        assert desc_match, f"{skill_file} missing 'description:' in frontmatter"

        dir_name = skill_file.parent.name
        principle_name = name_match.group(1).strip().strip("'\"")
        assert principle_name == dir_name, f"{skill_file} name '{principle_name}' does not match dir '{dir_name}'"


def test_poteto_mode_indexes_all_principles():
    poteto_mode = (REPO_ROOT / "skills" / "poteto-mode" / "SKILL.md").read_text(encoding="utf-8")
    for skill_file in get_principle_skills():
        principle_name = skill_file.parent.name
        assert principle_name in poteto_mode, f"poteto-mode SKILL.md missing reference to {principle_name}"


def test_readme_indexes_all_principles():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for skill_file in get_principle_skills():
        slug = skill_file.parent.name.replace("principle-", "")
        assert (f"./skills/{skill_file.parent.name}/SKILL.md" in readme or 
                f"skills/{skill_file.parent.name}" in readme or 
                slug in readme), f"README.md missing reference to {skill_file.parent.name}"


def test_guide_indexes_all_principles():
    guide_principles = (REPO_ROOT / "docs" / "guide" / "08-principles.md").read_text(encoding="utf-8")
    for skill_file in get_principle_skills():
        slug = skill_file.parent.name.replace("principle-", "")
        assert (skill_file.parent.name in guide_principles or 
                f"skills/{skill_file.parent.name}" in guide_principles or 
                slug in guide_principles), f"08-principles.md missing reference to {skill_file.parent.name}"
