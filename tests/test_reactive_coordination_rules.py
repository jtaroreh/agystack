"""Tests for Subagent Reactive Wakeup and Watchdog Architecture rules."""

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = REPO_ROOT / "rules"
SKILLS_DIR = REPO_ROOT / "skills"


class TestReactiveCoordinationRules(unittest.TestCase):
    def test_agents_md_has_reactive_wakeup_invariant(self):
        agents_file = RULES_DIR / "AGENTS.md"
        content = agents_file.read_text(encoding="utf-8")
        self.assertIn(
            "Subagent Reactive Wakeup and Watchdog Timeout Invariant", content
        )
        self.assertIn("ZERO tool calls", content)
        self.assertIn('TimerCondition: "never"', content)
        self.assertIn("Continuous Busy-Wait Prohibited", content)
        self.assertIn("manage_subagents(list)", content)

    def test_agents_md_scopes_cloud_swarm_liveness(self):
        agents_file = RULES_DIR / "AGENTS.md"
        content = agents_file.read_text(encoding="utf-8")
        self.assertIn("Primitive Boundary:", content)
        self.assertIn(
            "Active heartbeat polling (every 60-120s) applies strictly to external CLI/Cloud Run subprocesses (`run_command`, `cloud_dispatch.py`), NEVER to local Antigravity subagents (`invoke_subagent`).",
            content,
        )

        swarm_file = SKILLS_DIR / "swarm" / "SKILL.md"
        swarm_content = swarm_file.read_text(encoding="utf-8")
        self.assertIn(
            "Active Liveness & Non-Blocking Monitoring (Cloud Run Swarms Only):",
            swarm_content,
        )
        self.assertIn(
            "NEVER applies to native local Antigravity subagents (`invoke_subagent`)",
            swarm_content,
        )

    def test_reviewer_prompt_has_send_message_contract(self):
        prompt_file = SKILLS_DIR / "interrogate" / "references" / "reviewer-prompt.md"
        content = prompt_file.read_text(encoding="utf-8")
        self.assertIn("send_message", content)
        self.assertIn("{PARENT_CONVERSATION_ID}", content)
        self.assertIn("Output & Handoff", content)

    def test_interrogate_skill_has_zero_tool_yield(self):
        skill_file = SKILLS_DIR / "interrogate" / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        self.assertIn('TimerCondition: "never"', content)
        self.assertTrue(
            "ZERO tools (`tool_calls: []`)" in content or "zero tool calls" in content
        )
        self.assertIn("{PARENT_CONVERSATION_ID}", content)

    def test_arena_and_swarm_skills_have_reactive_protocol(self):
        arena_content = (SKILLS_DIR / "arena" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn('TimerCondition: "never"', arena_content)
        self.assertIn("ZERO tool calls", arena_content)
        self.assertIn("send_message", arena_content)
        self.assertIn("{PARENT_CONVERSATION_ID}", arena_content)

        swarm_content = (SKILLS_DIR / "swarm" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn('TimerCondition: "never"', swarm_content)
        self.assertIn("ZERO tool calls", swarm_content)
        self.assertIn("send_message", swarm_content)
        self.assertIn("{PARENT_CONVERSATION_ID}", swarm_content)

    def test_agents_md_has_delegation_thresholds(self):
        agents_file = RULES_DIR / "AGENTS.md"
        content = agents_file.read_text(encoding="utf-8")
        self.assertIn("Non-Trivial Delegation Threshold", content)
        self.assertIn("<= 50 lines", content)
        self.assertIn("> 50 lines", content)
        self.assertIn("poteto-agent", content)
        self.assertIn("User override", content)

    def test_agents_md_has_artifact_scoping_matrix(self):
        agents_file = RULES_DIR / "AGENTS.md"
        content = agents_file.read_text(encoding="utf-8")
        self.assertIn("Planning and Deliverable Artifact Scoping Matrix", content)
        self.assertIn("Interactive State-Changing Playbooks", content)
        self.assertIn("implementation_plan.md", content)
        self.assertIn("RequestFeedback: true", content)
        self.assertIn("walkthrough.md", content)
        self.assertIn("Autonomous & Hillclimb Playbooks", content)
        self.assertIn("RequestFeedback: false", content)
        self.assertIn("decision_trail.md", content)
        self.assertIn("Read-Only Investigation Playbooks", content)
        self.assertIn("investigation_report.md", content)


if __name__ == "__main__":
    unittest.main()
