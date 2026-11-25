import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
sys.path.insert(0, str(SKILLS_DIR / "setup-agystack" / "scripts"))
import setup_runtime

EXPECTED_MODEL_TIERS: dict[str, list[str]] = {
    "feature, refactoring": ["inherit"],
    "bug-fix": ["inherit"],
    "perf-issue": ["inherit"],
    "hillclimb": ["inherit"],
    "judgment and prose": ["inherit"],
    "hardest tasks": ["inherit"],
    "how explorer": ["flash"],
    "how explainer": ["inherit"],
    "why investigators": ["flash"],
    "why synthesizer": ["inherit"],
    "reflect tooling": ["inherit"],
    "reflect judgment, divergent, synthesizer": ["inherit"],
    "arena runners": ["inherit", "flash", "pro"],
    "arena cross-judge pool": ["inherit", "flash", "pro"],
    "swarm workers": ["flash"],
    "architect runners": ["inherit", "flash", "pro"],
    "interrogate reviewers": ["inherit", "flash", "pro"],
}

BANNED_CURSOR_RE = re.compile(
    r"\.cursor/rules"
    r"|pstack-models\.mdc"
    r"|cursor-team-kit"
    r"|api2\.cursor\.sh"
    r"|SendToUser"
    r"|SendSlackMessage"
    r"|update_state"
    r"|claude-opus-5-5"
    r"|-xhigh-fast"
    r"|\bStrReplace\b"
    r"|\bReadLints\b"
    r"|\bTodoWrite\b"
    r"|\bSemanticSearch\b"
)
DOT_CURSOR_RE = re.compile(r"\.cursor")
NEGATIVE_CURSOR_GLOB_RE = re.compile(r"(?:Do not|Don't) glob(?:\s+across)?\s+`?~/\.cursor/projects/\*/`?")
LEGACY_TOOL_ARG_RE = re.compile(r"\b(?:AskQuestion|subagent_type|generalPurpose|run_in_background)\b|readonly:\s*(?:true|false)")


def _read_repo_file(rel_path: str) -> str:
    path = REPO_ROOT / rel_path
    assert path.is_file(), f"Required file missing: {rel_path}"
    return path.read_text(encoding="utf-8")


def _parse_model_lines(text: str) -> dict[str, list[str]]:
    roles: dict[str, list[str]] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        role, tiers_raw = line.split(":", 1)
        role_key = role.strip()
        assert role_key not in roles, f"Duplicate role key {role_key!r} in model config"
        roles[role_key] = [tier.strip() for tier in tiers_raw.split(",") if tier.strip()]
    return roles


def _is_excluded_skill_doc(rel_path: Path) -> bool:
    parts = rel_path.parts
    if "node_modules" in parts:
        return True
    return any(parts[idx : idx + 2] == ("scripts", "test") for idx in range(len(parts) - 1))


def _is_allowed_legacy_mapping_row(rel_posix: str, line: str) -> bool:
    if rel_posix != "poteto-mode/references/antigravity-tools.md":
        return False
    stripped = line.strip()
    if not stripped.startswith("|"):
        return False
    return any(
        token in stripped
        for token in ("`TypeName:", "`ask_question`", "Default. Antigravity subagents")
    )


def find_cursor_leakage(root_dir: Path) -> list[str]:
    violations: list[str] = []
    for md_path in sorted(root_dir.rglob("*.md")):
        rel_path = md_path.relative_to(root_dir)
        if _is_excluded_skill_doc(rel_path):
            continue
        rel_posix = rel_path.as_posix()
        for lineno, line in enumerate(md_path.read_text(encoding="utf-8").splitlines(), 1):
            banned_match = BANNED_CURSOR_RE.search(line)
            if banned_match:
                violations.append(f"{rel_posix}:{lineno}: banned token {banned_match.group(0)!r}")
                continue
            sanitized_line = NEGATIVE_CURSOR_GLOB_RE.sub("", line)
            if DOT_CURSOR_RE.search(sanitized_line):
                violations.append(f"{rel_posix}:{lineno}: unguarded '.cursor' reference")
                continue
            legacy_match = LEGACY_TOOL_ARG_RE.search(line)
            if legacy_match and not _is_allowed_legacy_mapping_row(rel_posix, line):
                violations.append(f"{rel_posix}:{lineno}: banned legacy Cursor token {legacy_match.group(0)!r}")
    return violations


class TestAntigravityInvariants(unittest.TestCase):
    def test_brain_artifact_deliverables(self):
        for rel_path in (
            "skills/poteto-mode/SKILL.md",
            "skills/poteto-mode/references/antigravity-tools.md",
        ):
            content = _read_repo_file(rel_path)
            for token in (
                "<appDataDir>/brain/<conversation-id>/",
                "implementation_plan.md",
                "walkthrough.md",
                "decisions.tsv",
                "scratch/",
            ):
                self.assertIn(token, content, f"{rel_path} missing brain artifact token {token!r}")

        agents_md = _read_repo_file("rules/AGENTS.md")
        for token in (
            "implementation_plan.md",
            "walkthrough.md",
            "decision_trail.md",
            "scratch/",
        ):
            self.assertIn(token, agents_md, f"rules/AGENTS.md missing deliverable token {token!r}")

    def test_three_tier_parallel_routing(self):
        self.assertFalse(
            (SKILLS_DIR / "swarm").exists(),
            "skills/swarm must stay absent so Antigravity native /swarm is unshadowed",
        )
        tools_ref = _read_repo_file("skills/poteto-mode/references/antigravity-tools.md")
        for token in ("Local fan-out", "invoke_subagent", "8 or fewer", "/swarm", "/cloud-swarm", "Cloud Run"):
            self.assertIn(token, tools_ref, f"antigravity-tools.md missing routing token {token!r}")

        cloud_swarm = _read_repo_file("skills/cloud-swarm/SKILL.md")
        for token in ("invoke_subagent", "8 or fewer", "/swarm", "more than 8", "Cloud Run"):
            self.assertIn(
                token.lower(),
                cloud_swarm.lower(),
                f"cloud-swarm/SKILL.md missing routing token {token!r}",
            )

    def test_send_message_iterative_worker_loops(self):
        poteto_skill = _read_repo_file("skills/poteto-mode/SKILL.md")
        self.assertIn("send_message", poteto_skill)
        self.assertIn("iterate with an active worker", poteto_skill)

        tools_ref = _read_repo_file("skills/poteto-mode/references/antigravity-tools.md")
        self.assertIn("send_message", tools_ref)
        self.assertIn("Iterative Worker Loops", tools_ref)

    def test_browser_subagent_and_surface_precedence_hierarchy(self):
        for rel_path in ("rules/AGENTS.md", "skills/poteto-mode/references/antigravity-tools.md"):
            content = _read_repo_file(rel_path)
            self.assertIn("Surface Precedence Hierarchy", content, f"{rel_path} missing Surface Precedence Hierarchy")
            self.assertIn("browser_subagent", content, f"{rel_path} missing browser_subagent")

        verify_skill = _read_repo_file("skills/create-verification-skill/SKILL.md")
        self.assertIn("browser_subagent", verify_skill)

    def test_permissioned_github_recovery(self):
        tools_ref = _read_repo_file("skills/poteto-mode/references/antigravity-tools.md")
        for token in (
            "permissioned-github",
            "Recovery Invariant",
            "126/127",
            "Never apologize or retry the identical command in a loop",
            "git.read",
            "gh.read",
            "git.update",
            "gh.create",
        ):
            self.assertIn(token, tools_ref, f"antigravity-tools.md missing permissioned-github token {token!r}")

    def test_orchestrate_playbook_present(self):
        orchestrate_path = SKILLS_DIR / "poteto-mode" / "playbooks" / "orchestrate.md"
        self.assertTrue(orchestrate_path.is_file(), "skills/poteto-mode/playbooks/orchestrate.md missing")
        self.assertTrue(orchestrate_path.read_text(encoding="utf-8").strip())
        self.assertIn("playbooks/orchestrate.md", _read_repo_file("skills/poteto-mode/SKILL.md"))

    def test_zero_teamwork_preview_leakage(self):
        scan_paths = [REPO_ROOT / "README.md"]
        for d in (SKILLS_DIR, REPO_ROOT / "rules", REPO_ROOT / "agents", REPO_ROOT / "docs"):
            scan_paths.extend(sorted(d.rglob("*.md")))
        hits: list[str] = []
        for path in scan_paths:
            rel = path.relative_to(REPO_ROOT)
            if _is_excluded_skill_doc(rel):
                continue
            if "teamwork-preview" in path.read_text(encoding="utf-8"):
                hits.append(rel.as_posix())
        self.assertEqual(hits, [], f"Stale /teamwork-preview references found: {hits}")

    def test_official_antigravity_docs_and_models_alignment(self):
        tools_ref = _read_repo_file("skills/poteto-mode/references/antigravity-tools.md")
        for token in (
            "/run-workflow",
            "run_workflow",
            "Gemini 4 Neon",
            "Gemini 4 Carbon",
            "Gemini 4 Hydrogen",
            "Orchestrator",
            "/teamwork",
            "/boost",
            "LocalAgentConfig",
            "CapabilitiesConfig",
            "SubagentConfig",
            "skills_paths",
            "BuiltinTools",
        ):
            self.assertIn(token, tools_ref, f"antigravity-tools.md missing official docs token {token!r}")
        self.assertNotIn("Subagents: [", tools_ref, "antigravity-tools.md still has stale Subagents array schema")

    def test_worker_contract_and_ketchup_video_brain_paths(self):
        worker_md = _read_repo_file("skills/poteto-mode/worker.md")
        for token in (
            "invoke_subagent",
            "Read <path>/worker.md before anything else.",
            "Never call `ask_question`",
            "<appDataDir>/brain/<conversation-id>/",
            "`type(scope): subject`",
            "Parent delegate envelope tool and nesting rules always govern.",
        ):
            self.assertIn(token, worker_md, f"worker.md missing token {token!r}")

        poteto_skill = _read_repo_file("skills/poteto-mode/SKILL.md")
        self.assertIn("worker.md", poteto_skill)
        self.assertNotIn("Delegates never call `ask_question`", poteto_skill)

        poteto_agent = _read_repo_file("agents/poteto-agent.md")
        self.assertIn("skills/poteto-mode/worker.md", poteto_agent)
        self.assertNotIn("## Standing delegate rules", poteto_agent)
        self.assertNotIn("Bar discipline", poteto_agent)

        ketchup_video = _read_repo_file("skills/ketchup-video/SKILL.md")
        self.assertIn("<appDataDir>/brain/<conversation-id>/", ketchup_video)
        self.assertIn("<appDataDir>/brain/<conversation-id>/scratch/", ketchup_video)

        sharpen = _read_repo_file("skills/sharpen/SKILL.md")
        self.assertIn("prototype any choice an experiment can settle", sharpen)

    def test_active_role_keys_defined_and_consumed(self):
        models_path = REPO_ROOT / "agystack-models.md"
        root_models = _parse_model_lines(models_path.read_text(encoding="utf-8"))
        self.assertEqual(root_models, EXPECTED_MODEL_TIERS)

        parsed = setup_runtime.parse_model_config(config_path=str(models_path))
        self.assertTrue(parsed["ok"], f"setup_runtime.parse_model_config failed: {parsed.get('error')}")
        for role_key, expected_tiers in EXPECTED_MODEL_TIERS.items():
            self.assertEqual(parsed["roles"].get(role_key), expected_tiers)

        setup_skill = _read_repo_file("skills/setup-agystack/SKILL.md")
        step4_match = re.search(
            r"### 4\. Map and confirm(.*?)### 5\. Write the model rule",
            setup_skill,
            re.DOTALL,
        )
        self.assertIsNotNone(step4_match, "setup-agystack/SKILL.md missing Step 4 section")
        step4_roles = re.findall(r"`([^`]+)`", step4_match.group(1))
        self.assertEqual(len(step4_roles), len(set(step4_roles)), "Duplicate role in setup-agystack Step 4")
        self.assertEqual(set(step4_roles), set(EXPECTED_MODEL_TIERS))

        step5_match = re.search(
            r"### 5\. Write the model rule.*?```[^\n]*\n(.*?)```",
            setup_skill,
            re.DOTALL,
        )
        self.assertIsNotNone(step5_match, "setup-agystack/SKILL.md missing Step 5 config code block")
        setup_models = _parse_model_lines(step5_match.group(1))
        self.assertEqual(setup_models, EXPECTED_MODEL_TIERS)

        how_skill = _read_repo_file("skills/how/SKILL.md")
        self.assertRegex(how_skill, r"how[- ]explorer")
        self.assertRegex(how_skill, r"how[- ]explainer")

        why_skill = _read_repo_file("skills/why/SKILL.md")
        self.assertRegex(why_skill, r"why[- ]investigators")
        self.assertRegex(why_skill, r"why[- ]synthesizer")

        self.assertIn("architect runners", _read_repo_file("skills/architect/SKILL.md"))
        self.assertIn("interrogate reviewers", _read_repo_file("skills/interrogate/SKILL.md"))
        self.assertIn("arena runners", _read_repo_file("skills/arena/SKILL.md"))
        self.assertIn("swarm workers", _read_repo_file("skills/cloud-swarm/SKILL.md"))
        self.assertIn("swarm workers", _read_repo_file("skills/poteto-mode/references/antigravity-tools.md"))
        reflect_skill = _read_repo_file("skills/reflect/SKILL.md")
        self.assertRegex(reflect_skill, r"reflect[- ]tooling")
        self.assertRegex(reflect_skill, r"reflect[- ]judgment")

    def test_zero_cursor_leakage_across_skills(self):
        for target_dir in (SKILLS_DIR, REPO_ROOT / "rules", REPO_ROOT / "agents"):
            violations = find_cursor_leakage(target_dir)
            self.assertEqual(violations, [], f"Cursor leakage found in {target_dir.name}/: {violations}")

    def test_cursor_leakage_scanner_catches_injected_files_and_honors_allowances(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_skills = Path(tmp_dir) / "skills"
            (tmp_skills / "bad-skill").mkdir(parents=True)
            (tmp_skills / "bad-skill" / "SKILL.md").write_text(
                "Load `.cursor/rules/pstack-models.mdc` before editing.\n",
                encoding="utf-8",
            )
            (tmp_skills / "bad-ask").mkdir(parents=True)
            (tmp_skills / "bad-ask" / "SKILL.md").write_text(
                "Call `AskQuestion` when stuck.\n",
                encoding="utf-8",
            )
            (tmp_skills / "bad-bypass").mkdir(parents=True)
            (tmp_skills / "bad-bypass" / "SKILL.md").write_text(
                "Do not glob ~/.cursor/projects/*/; read ~/.cursor/skills/pstack.md\n"
                "Spawn subagent_type: generalPurpose with run_in_background: true\n"
                "Check .cursorrules too.\n",
                encoding="utf-8",
            )
            (tmp_skills / "recall").mkdir(parents=True)
            (tmp_skills / "recall" / "SKILL.md").write_text(
                "Do not glob `~/.cursor/projects/*/`.\n",
                encoding="utf-8",
            )
            (tmp_skills / "poteto-mode" / "references").mkdir(parents=True)
            (tmp_skills / "poteto-mode" / "references" / "antigravity-tools.md").write_text(
                "| `AskQuestion` | `ask_question` tool for interactive questions |\n"
                "| `subagent_type: generalPurpose` | `TypeName: \"self\"` |\n",
                encoding="utf-8",
            )
            (tmp_skills / "pkg" / "node_modules" / "dep").mkdir(parents=True)
            (tmp_skills / "pkg" / "node_modules" / "dep" / "README.md").write_text(
                ".cursor/rules/pstack-models.mdc\n",
                encoding="utf-8",
            )
            (tmp_skills / "pkg" / "scripts" / "test").mkdir(parents=True)
            (tmp_skills / "pkg" / "scripts" / "test" / "fixture.md").write_text(
                "SendToUser\n",
                encoding="utf-8",
            )

            violations = find_cursor_leakage(tmp_skills)
            self.assertEqual(len(violations), 5, f"Unexpected violations: {violations}")
            self.assertTrue(any("bad-skill/SKILL.md:1" in v for v in violations))
            self.assertTrue(any("bad-ask/SKILL.md:1" in v for v in violations))
            self.assertTrue(any("bad-bypass/SKILL.md:1" in v for v in violations))
            self.assertTrue(any("bad-bypass/SKILL.md:2" in v for v in violations))
            self.assertTrue(any("bad-bypass/SKILL.md:3" in v for v in violations))


if __name__ == "__main__":
    unittest.main()
