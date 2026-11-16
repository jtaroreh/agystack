import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / "agents"

FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL
)

VALID_ONEHARNESS_AGENT_TOOLS = frozenset(
    {
        "read_file",
        "edit_file",
        "write_file",
        "run_command",
        "manage_task",
        "send_message",
        "schedule",
        "invoke_subagent",
        "manage_subagents",
        "define_subagent",
        "ask_question",
        "search_web",
        "generate_image",
        "finish",
    }
)
DYNAMIC_CORTEX_MCP_TOOLS = frozenset(
    {"call_mcp_tool", "list_resources", "read_resource"}
)
REQUIRED_POTETO_AGENT_TOOLS = frozenset(
    {
        "read_file",
        "edit_file",
        "write_file",
        "run_command",
        "manage_task",
        "send_message",
        "schedule",
        "invoke_subagent",
        "manage_subagents",
        "define_subagent",
        "ask_question",
        "search_web",
        "generate_image",
    }
)


def _strip_inline_comment(line: str) -> str:
    in_single = False
    in_double = False
    for idx, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if idx == 0 or line[idx - 1].isspace():
                return line[:idx].rstrip()
    return line


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and (
        (value.startswith('"') and value.endswith('"'))
        or (value.startswith("'") and value.endswith("'"))
    ):
        return value[1:-1]
    return value


def _parse_flow_list(raw: str) -> list[str]:
    inner = raw[1:-1].strip()
    if not inner:
        return []
    items = []
    for piece in inner.split(","):
        cleaned = piece.strip()
        if cleaned:
            items.append(_strip_quotes(cleaned))
    return items


def parse_frontmatter(content: str) -> dict:
    match = FRONTMATTER_RE.match(content)
    assert match is not None, "Invalid or unclosed YAML frontmatter fence"
    frontmatter_text = match.group(1)

    data = {}
    current_list_key = None
    flow_key = None
    flow_buffer = []

    for raw_line in frontmatter_text.splitlines():
        line = _strip_inline_comment(raw_line)
        stripped = line.strip()
        if not stripped:
            continue

        if flow_key is not None:
            flow_buffer.append(stripped)
            joined = " ".join(flow_buffer)
            if joined.endswith("]"):
                data[flow_key] = _parse_flow_list(joined)
                flow_key = None
                flow_buffer = []
            continue

        if current_list_key is not None and (
            stripped == "-" or stripped.startswith("- ")
        ):
            item = _strip_quotes(stripped[1:])
            if item:
                data[current_list_key].append(item)
            continue

        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            current_list_key = None
            if val.startswith("["):
                if val.endswith("]"):
                    data[key] = _parse_flow_list(val)
                else:
                    flow_key = key
                    flow_buffer = [val]
            elif not val:
                data[key] = []
                current_list_key = key
            elif val.lower() == "true":
                data[key] = True
            elif val.lower() == "false":
                data[key] = False
            else:
                data[key] = _strip_quotes(val)
        else:
            current_list_key = None

    assert flow_key is None, f"Unclosed flow sequence for key '{flow_key}'"
    return data


class TestAgentDefinitions(unittest.TestCase):
    def test_parse_frontmatter_supports_inline_multiline_and_block_lists(self):
        inline_sample = """---
name: test-inline
description: Fast --- lightweight # inline comment
tools: [read_file, 'edit_file', "write_file",] # trailing comma and comment
enabled: true # boolean comment
---
body
"""
        multiline_flow_sample = """---
name: test-flow
tools: [
  read_file,
  edit_file,
]
---
body
"""
        block_sample = """---
name: test-block
tools: # block comment
  - read_file # item comment
  - 'edit_file'
  - "write_file"
enabled: false
---
body
"""
        inline_fm = parse_frontmatter(inline_sample)
        flow_fm = parse_frontmatter(multiline_flow_sample)
        block_fm = parse_frontmatter(block_sample)

        self.assertEqual(inline_fm.get("name"), "test-inline")
        self.assertEqual(inline_fm.get("description"), "Fast --- lightweight")
        self.assertIs(inline_fm.get("enabled"), True)
        self.assertEqual(
            inline_fm.get("tools"), ["read_file", "edit_file", "write_file"]
        )
        self.assertEqual(flow_fm.get("tools"), ["read_file", "edit_file"])
        self.assertEqual(block_fm.get("name"), "test-block")
        self.assertIs(block_fm.get("enabled"), False)
        self.assertEqual(
            block_fm.get("tools"), ["read_file", "edit_file", "write_file"]
        )
        self.assertEqual(_strip_quotes('"'), '"')

        with self.assertRaises(AssertionError):
            parse_frontmatter("---\nname: unclosed\nUsage: body\n")

    def test_agent_frontmatter_presence(self):
        agent_files = sorted(AGENTS_DIR.glob("*.md"))
        self.assertGreaterEqual(
            len(agent_files),
            2,
            f"Expected at least 2 agent definitions, found {len(agent_files)}",
        )

        for agent_file in agent_files:
            content = agent_file.read_text(encoding="utf-8")
            fm = parse_frontmatter(content)

            self.assertIn(
                "name", fm, f"{agent_file.name} missing 'name' in frontmatter"
            )
            self.assertIn(
                "subagent", fm, f"{agent_file.name} missing 'subagent' in frontmatter"
            )
            self.assertIn(
                "model", fm, f"{agent_file.name} missing 'model' in frontmatter"
            )
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
            "inheritCustomizations",
            sicko_fm,
            "comment-sicko.md missing 'inheritCustomizations'",
        )
        self.assertIs(
            sicko_fm["inheritCustomizations"],
            False,
            "comment-sicko.md must have 'inheritCustomizations: false'",
        )
        self.assertIn(
            "inheritCustomizations",
            poteto_fm,
            "poteto-agent.md missing 'inheritCustomizations'",
        )
        self.assertIs(
            poteto_fm["inheritCustomizations"],
            False,
            "poteto-agent.md must have 'inheritCustomizations: false'",
        )

    def test_main_agent_flags(self):
        poteto_file = AGENTS_DIR / "poteto-agent.md"
        sicko_file = AGENTS_DIR / "comment-sicko.md"

        self.assertTrue(poteto_file.exists(), "poteto-agent.md not found")
        self.assertTrue(sicko_file.exists(), "comment-sicko.md not found")

        poteto_fm = parse_frontmatter(poteto_file.read_text(encoding="utf-8"))
        sicko_fm = parse_frontmatter(sicko_file.read_text(encoding="utf-8"))

        self.assertIs(
            poteto_fm.get("mainAgent"), True, "poteto-agent must have mainAgent: true"
        )
        self.assertIs(
            sicko_fm.get("mainAgent"), False, "comment-sicko must have mainAgent: false"
        )

    def test_poteto_agent_grants_execution_and_mcp_capabilities(self):
        poteto_file = AGENTS_DIR / "poteto-agent.md"
        self.assertTrue(poteto_file.exists(), "poteto-agent.md not found")

        poteto_fm = parse_frontmatter(poteto_file.read_text(encoding="utf-8"))
        self.assertIs(
            poteto_fm.get("inheritMcp"),
            True,
            "poteto-agent.md must have 'inheritMcp: true'",
        )

        tools = poteto_fm.get("tools")
        self.assertIsInstance(
            tools,
            list,
            "poteto-agent.md must declare a 'tools' list in frontmatter",
        )
        tools_set = set(tools)
        self.assertEqual(
            len(tools),
            len(tools_set),
            f"poteto-agent.md contains duplicate tools: {tools}",
        )
        missing_tools = REQUIRED_POTETO_AGENT_TOOLS - tools_set
        self.assertFalse(
            missing_tools,
            f"poteto-agent.md missing required tools: {sorted(missing_tools)}",
        )

    def test_custom_agents_only_declare_registered_oneharness_tools(self):
        agent_files = sorted(AGENTS_DIR.glob("*.md"))
        for agent_file in agent_files:
            content = agent_file.read_text(encoding="utf-8")
            fm = parse_frontmatter(content)
            if "tools" in fm:
                tools = fm["tools"]
                self.assertIsInstance(
                    tools,
                    list,
                    f"{agent_file.name} 'tools' must be a list",
                )
                self.assertTrue(
                    tools,
                    f"{agent_file.name} 'tools' must be a non-empty list",
                )
                tools_set = set(tools)
                self.assertEqual(
                    len(tools),
                    len(tools_set),
                    f"{agent_file.name} contains duplicate tools: {tools}",
                )
                mcp_tools = tools_set & DYNAMIC_CORTEX_MCP_TOOLS
                self.assertFalse(
                    mcp_tools,
                    f"{agent_file.name} must not declare dynamic MCP tools directly in 'tools': {sorted(mcp_tools)}",
                )
                invalid_tools = tools_set - VALID_ONEHARNESS_AGENT_TOOLS
                self.assertFalse(
                    invalid_tools,
                    f"{agent_file.name} contains invalid oneharness tools: {sorted(invalid_tools)}",
                )


if __name__ == "__main__":
    unittest.main()
