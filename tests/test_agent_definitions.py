import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "agents"


def parse_frontmatter(content: str) -> dict:
    assert content.startswith("---"), "Missing frontmatter delimiter"
    parts = content.split("---", 2)
    assert len(parts) >= 3, "Invalid frontmatter structure"
    frontmatter_text = parts[1]

    data = {}
    for line in frontmatter_text.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            if val.lower() == "true":
                val = True
            elif val.lower() == "false":
                val = False
            data[key] = val
    return data


class TestAgentDefinitions(unittest.TestCase):
    def test_agent_frontmatter_presence(self):
        agent_files = sorted(AGENTS_DIR.glob("*.md"))
        self.assertGreaterEqual(
            len(agent_files), 2, f"Expected at least 2 agent definitions, found {len(agent_files)}"
        )

        for agent_file in agent_files:
            content = agent_file.read_text(encoding="utf-8")
            fm = parse_frontmatter(content)

            self.assertIn("name", fm, f"{agent_file.name} missing 'name' in frontmatter")
            self.assertIn("subagent", fm, f"{agent_file.name} missing 'subagent' in frontmatter")
            self.assertIn("model", fm, f"{agent_file.name} missing 'model' in frontmatter")
            self.assertIn(
                "commandExecutionPolicy",
                fm,
                f"{agent_file.name} missing 'commandExecutionPolicy' in frontmatter",
            )

    def test_inherit_customizations_is_false_on_all_agents(self):
        sicko_file = AGENTS_DIR / "comment-sicko.md"
        poteto_file = AGENTS_DIR / "poteto-agent.md"

        self.assertTrue(sicko_file.exists(), "comment-sicko.md not found")
        self.assertTrue(poteto_file.exists(), "poteto-agent.md not found")

        sicko_fm = parse_frontmatter(sicko_file.read_text(encoding="utf-8"))
        poteto_fm = parse_frontmatter(poteto_file.read_text(encoding="utf-8"))

        self.assertIn(
            "inheritCustomizations", sicko_fm, "comment-sicko.md missing 'inheritCustomizations'"
        )
        self.assertIs(
            sicko_fm["inheritCustomizations"],
            False,
            "comment-sicko.md must have 'inheritCustomizations: false'",
        )
        self.assertIs(poteto_fm.get("mainAgent"), True, "poteto-agent.md must have 'mainAgent: true'")

    def test_main_agent_flags(self):
        poteto_file = AGENTS_DIR / "poteto-agent.md"
        sicko_file = AGENTS_DIR / "comment-sicko.md"

        self.assertTrue(poteto_file.exists(), "poteto-agent.md not found")
        self.assertTrue(sicko_file.exists(), "comment-sicko.md not found")

        poteto_fm = parse_frontmatter(poteto_file.read_text(encoding="utf-8"))
        sicko_fm = parse_frontmatter(sicko_file.read_text(encoding="utf-8"))

        self.assertIs(poteto_fm.get("mainAgent"), True, "poteto-agent must have mainAgent: true")
        self.assertIs(sicko_fm.get("mainAgent"), False, "comment-sicko must have mainAgent: false")


if __name__ == "__main__":
    unittest.main()
