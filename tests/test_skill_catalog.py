import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def get_principle_skills():
    skills_dir = REPO_ROOT / "skills"
    return sorted(skills_dir.glob("principle-*/SKILL.md"))


def test_principle_count():
    skills = get_principle_skills()
    assert len(skills) == 24, f"Expected 24 principle skills, found {len(skills)}"


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


def test_all_skills_match_directory():
    skills_dir = REPO_ROOT / "skills"
    all_skills = sorted(skills_dir.glob("*/SKILL.md"))
    assert len(all_skills) > 0, "No skills found in skills/"
    for skill_file in all_skills:
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
        skill_name = name_match.group(1).strip().strip("'\"")
        assert skill_name == dir_name, f"{skill_file} name '{skill_name}' does not match dir '{dir_name}'"


def test_cloud_swarm_skill_name():
    cloud_swarm_file = REPO_ROOT / "skills" / "cloud-swarm" / "SKILL.md"
    assert cloud_swarm_file.exists()
    content = cloud_swarm_file.read_text(encoding="utf-8")
    parts = content.split("---", 2)
    name_match = re.search(r"^name:\s*(.+)$", parts[1], re.MULTILINE)
    assert name_match and name_match.group(1).strip().strip("'\"") == "cloud-swarm"


def test_no_swarm_skill_collision():
    skills_dir = REPO_ROOT / "skills"
    assert not (skills_dir / "swarm").exists(), "skills/swarm must not exist (shadows Antigravity built-in swarm skill)"
    for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
        content = skill_file.read_text(encoding="utf-8")
        parts = content.split("---", 2)
        assert len(parts) >= 3, f"{skill_file} invalid frontmatter structure"
        name_match = re.search(r"^name:\s*(.+)$", parts[1], re.MULTILINE)
        assert name_match, f"{skill_file} missing 'name:' in frontmatter"
        skill_name = name_match.group(1).strip().strip("'\"")
        assert skill_name != "swarm", f"{skill_file} declares 'name: swarm' and shadows Antigravity's built-in swarm skill"


def _extract_readme_details_section(summary: str) -> str:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(rf"<summary>{re.escape(summary)}</summary>(.*?)</details>", readme, re.DOTALL)
    assert match is not None, f"README.md missing '<summary>{summary}</summary>' section"
    return match.group(1)


def test_readme_indexes_all_non_principle_skills():
    all_skills_section = _extract_readme_details_section("all skills")
    skills_dir = REPO_ROOT / "skills"
    non_principle_skills = [
        skill_file
        for skill_file in sorted(skills_dir.glob("*/SKILL.md"))
        if not skill_file.parent.name.startswith("principle-")
    ]
    assert non_principle_skills, "No non-principle skills found in skills/"

    missing = []
    for skill_file in non_principle_skills:
        slug = skill_file.parent.name
        row_pattern = rf"^\|\s*\[`/{re.escape(slug)}`\]\((?:\./)?skills/{re.escape(slug)}/SKILL\.md\)\s*\|"
        if not re.search(row_pattern, all_skills_section, re.MULTILINE):
            missing.append(slug)

    assert not missing, f"README.md 'all skills' table missing skills: {missing}"


def test_readme_has_no_ghost_skills():
    all_skills_section = _extract_readme_details_section("all skills")
    table_rows = [
        line
        for line in all_skills_section.splitlines()
        if line.startswith("|") and not line.startswith("| skill |") and not line.startswith("|---")
    ]
    assert table_rows, "README.md 'all skills' table has no skill rows"

    seen_slugs: set[str] = set()
    ghosts: list[str] = []
    broken_links: list[str] = []
    duplicates: list[str] = []

    for row in table_rows:
        cells = row.split("|")
        assert len(cells) >= 3, f"Malformed skill table row in README.md: {row!r}"
        first_cell = cells[1]
        slugs = re.findall(r"`/([a-z0-9-]+)`", first_cell)
        assert slugs, f"README.md skill row missing `/<slug>` entry: {row!r}"
        link_targets = re.findall(r"\((?:\./)?skills/([a-z0-9-]+)/SKILL\.md\)", first_cell)
        if not link_targets or link_targets != slugs:
            broken_links.append(f"{row.strip()} -> {link_targets}")
        for slug in slugs:
            if slug in seen_slugs:
                duplicates.append(slug)
            seen_slugs.add(slug)
            if not (REPO_ROOT / "skills" / slug / "SKILL.md").is_file():
                ghosts.append(slug)

    examples_section = _extract_readme_details_section("all the examples")
    example_slugs = re.findall(r"(?:^|\s)/([a-z0-9-]+)(?=\s|$)", examples_section, re.MULTILINE)
    ghost_examples = sorted({slug for slug in example_slugs if not (REPO_ROOT / "skills" / slug / "SKILL.md").is_file()})

    playbooks_section = _extract_readme_details_section("the 23 playbooks")
    readme_playbooks = set(re.findall(r"\(\./skills/poteto-mode/playbooks/([^)]+)\)", playbooks_section))
    disk_playbooks = {p.name for p in (REPO_ROOT / "skills" / "poteto-mode" / "playbooks").glob("*.md")}
    playbook_drift = sorted(readme_playbooks ^ disk_playbooks)

    assert not ghosts, f"README.md 'all skills' table lists non-existent skills: {ghosts}"
    assert not broken_links, f"README.md 'all skills' table has invalid links: {broken_links}"
    assert not duplicates, f"README.md 'all skills' table has duplicate skills: {duplicates}"
    assert not ghost_examples, f"README.md 'all the examples' references non-existent skills: {ghost_examples}"
    assert not playbook_drift, f"README.md 'the 23 playbooks' out of sync with disk: {playbook_drift}"
