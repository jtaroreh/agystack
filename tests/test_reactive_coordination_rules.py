"""Tests for Subagent Reactive Wakeup and Watchdog Architecture rules."""
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = REPO_ROOT / "rules"
SKILLS_DIR = REPO_ROOT / "skills"


class CoordinatorStateMachine:
    """Models coordinator state transitions during subagent fan-out and reactive wakeup."""

    def __init__(self, expected_workers: int, timeout_seconds: int = 300):
        self.expected_workers = expected_workers
        self.timeout_seconds = timeout_seconds
        self.state = "INIT"
        self.watchdog_armed = False
        self.watchdog_timer_id = None
        self.results = {}
        self.stragglers = []
        self.terminated_stragglers = []

    def dispatch(self, timer_task_id: str = "task-watchdog-1"):
        """Turn 1: Dispatch subagents and arm unconditional global watchdog timer."""
        self.state = "DISPATCHED"
        self.watchdog_armed = True
        self.watchdog_timer_id = timer_task_id
        # Turn 2: yield turn with zero tool calls
        self.state = "WAITING"
        yield_tool_calls = []  # ZERO tool calls
        return yield_tool_calls

    def on_worker_message(self, worker_id: str, findings: str):
        """Worker completion reactively wakes the coordinator."""
        assert self.state in ("WAITING", "PARTIAL_RECEIVED")
        self.results[worker_id] = findings

        if len(self.results) < self.expected_workers:
            self.state = "PARTIAL_RECEIVED"
            # Watchdog remains armed! Yield immediately with zero tool calls
            return {"action": "YIELD", "tool_calls": []}
        else:
            self.state = "COMPLETED"
            # Cancel watchdog timer and proceed to synthesis
            timer_to_kill = self.watchdog_timer_id
            self.watchdog_armed = False
            self.watchdog_timer_id = None
            return {
                "action": "CANCEL_WATCHDOG_AND_SYNTHESIZE",
                "tool_calls": [
                    {
                        "name": "manage_task",
                        "args": {"Action": "kill", "TaskId": timer_to_kill},
                    }
                ],
            }

    def on_watchdog_timeout(self, active_subagents_list: list):
        """Watchdog fires on timeout."""
        assert self.state in ("WAITING", "PARTIAL_RECEIVED")
        self.state = "TIMED_OUT"
        self.watchdog_armed = False

        # Timeout diagnosis: inspect manage_subagents(list)
        missing = [w for w in active_subagents_list if w["id"] not in self.results]
        self.stragglers = missing
        self.terminated_stragglers = [w["id"] for w in missing]

        # Kill stragglers and proceed with partial results
        kill_tool_calls = [
            {
                "name": "manage_subagents",
                "args": {"Action": "kill", "SubagentId": w["id"]},
            }
            for w in missing
        ]
        return {
            "action": "SYNTHESIZE_PARTIAL",
            "tool_calls": kill_tool_calls,
            "results": self.results,
        }


class TestReactiveCoordinationRules(unittest.TestCase):
    def test_agents_md_has_reactive_wakeup_invariant(self):
        agents_file = RULES_DIR / "AGENTS.md"
        content = agents_file.read_text(encoding="utf-8")
        self.assertIn("Subagent Reactive Wakeup and Watchdog Timeout Invariant", content)
        self.assertIn("ZERO tool calls", content)
        self.assertIn('TimerCondition: "never"', content)
        self.assertIn("Continuous Busy-Wait Prohibited", content)
        self.assertIn("manage_subagents(list)", content)

    def test_agents_md_scopes_cloud_swarm_liveness(self):
        agents_file = RULES_DIR / "AGENTS.md"
        content = agents_file.read_text(encoding="utf-8")
        self.assertIn(
            "Active Liveness & Non-Blocking Monitoring (Cloud Run Swarms Only):", content
        )
        self.assertIn(
            "NEVER applies to native local Antigravity subagents (`invoke_subagent`)",
            content,
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

    def test_coordinator_state_machine_logic(self):
        sm = CoordinatorStateMachine(expected_workers=3, timeout_seconds=300)

        tool_calls = sm.dispatch("task-wd-1")
        self.assertEqual(sm.state, "WAITING")
        self.assertTrue(sm.watchdog_armed)
        self.assertEqual(tool_calls, [])

        res1 = sm.on_worker_message("worker-1", "Finding 1: bug in parser")
        self.assertEqual(sm.state, "PARTIAL_RECEIVED")
        self.assertTrue(sm.watchdog_armed)
        self.assertEqual(res1["action"], "YIELD")
        self.assertEqual(res1["tool_calls"], [])

        res2 = sm.on_worker_message("worker-2", "Finding 2: race condition")
        self.assertEqual(sm.state, "PARTIAL_RECEIVED")
        self.assertTrue(sm.watchdog_armed)
        self.assertEqual(res2["action"], "YIELD")
        self.assertEqual(res2["tool_calls"], [])

        res3 = sm.on_worker_message("worker-3", "No findings.")
        self.assertEqual(sm.state, "COMPLETED")
        self.assertFalse(sm.watchdog_armed)
        self.assertEqual(res3["action"], "CANCEL_WATCHDOG_AND_SYNTHESIZE")
        self.assertEqual(len(res3["tool_calls"]), 1)
        self.assertEqual(res3["tool_calls"][0]["name"], "manage_task")
        self.assertEqual(res3["tool_calls"][0]["args"]["Action"], "kill")
        self.assertEqual(res3["tool_calls"][0]["args"]["TaskId"], "task-wd-1")

        sm2 = CoordinatorStateMachine(expected_workers=3, timeout_seconds=300)
        sm2.dispatch("task-wd-2")
        sm2.on_worker_message("worker-1", "Finding A")
        sm2.on_worker_message("worker-2", "Finding B")

        active_workers = [
            {"id": "worker-1", "status": "done"},
            {"id": "worker-2", "status": "done"},
            {"id": "worker-3", "status": "idle"},
        ]
        timeout_res = sm2.on_watchdog_timeout(active_workers)
        self.assertEqual(sm2.state, "TIMED_OUT")
        self.assertEqual(timeout_res["action"], "SYNTHESIZE_PARTIAL")
        self.assertEqual(sm2.terminated_stragglers, ["worker-3"])
        self.assertEqual(len(timeout_res["tool_calls"]), 1)
        self.assertEqual(timeout_res["tool_calls"][0]["name"], "manage_subagents")
        self.assertEqual(timeout_res["tool_calls"][0]["args"]["SubagentId"], "worker-3")
        self.assertEqual(len(timeout_res["results"]), 2)


if __name__ == "__main__":
    unittest.main()
