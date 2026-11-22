import json
import re
import shlex
import subprocess
import tempfile
import tomllib
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_plugin_manifest_structure():
    manifest_path = REPO_ROOT / "plugin.json"
    assert manifest_path.exists(), "plugin.json does not exist"

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data.get("name") == "agystack"
    assert data.get("displayName") == "agystack"
    assert "version" in data
    assert "description" in data
    assert len(data["description"]) > 10

    # Marketplace UI recommendation: exactly or up to 3 prompts
    prompts = data.get("suggestedPrompts", [])
    assert 1 <= len(prompts) <= 3, f"Expected 1 to 3 suggestedPrompts, found {len(prompts)}"

    # Author
    author = data.get("author")
    assert isinstance(author, dict), "author should be an object"
    assert "name" in author
    assert "url" in author

    # Logo asset
    logo_rel = data.get("logo")
    assert logo_rel, "logo path missing"
    logo_file = REPO_ROOT / logo_rel
    assert logo_file.exists(), f"Logo file does not exist at {logo_file}"

    # SVG validation
    tree = ET.parse(logo_file)
    root = tree.getroot()
    assert root.tag.endswith("svg"), "Logo must be a valid SVG root"
    width = int(root.attrib.get("width", 0))
    height = int(root.attrib.get("height", 0))
    assert width >= 128 and height >= 128, "Logo dimensions should be at least 128x128"


def test_version_parity_and_semver():
    plugin_data = json.loads((REPO_ROOT / "plugin.json").read_text(encoding="utf-8"))
    pyproject_data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    marketplace_data = json.loads((REPO_ROOT / "docs" / "marketplace-submission.json").read_text(encoding="utf-8"))

    plugin_version = plugin_data["version"]
    pyproject_version = pyproject_data["project"]["version"]
    marketplace_version = marketplace_data["version"]

    assert re.fullmatch(r"\d+\.\d+\.\d+", plugin_version), f"Invalid semver version: {plugin_version!r}"
    assert plugin_version == pyproject_version == marketplace_version, (
        f"Version mismatch across manifests: plugin.json={plugin_version!r}, "
        f"pyproject.toml={pyproject_version!r}, "
        f"docs/marketplace-submission.json={marketplace_version!r}"
    )


def test_example_configs_and_hook_paths():
    runtime_example = json.loads((REPO_ROOT / "agystack-runtime.json.example").read_text(encoding="utf-8"))
    assert isinstance(runtime_example, dict) and runtime_example

    hooks_example = json.loads((REPO_ROOT / "hooks.json.example").read_text(encoding="utf-8"))
    assert isinstance(hooks_example, dict)

    prefix = "~/.gemini/config/plugins/agystack/"
    referenced_scripts = []
    for hook_group in hooks_example.values():
        if not isinstance(hook_group, dict):
            continue
        for event_entries in hook_group.values():
            if not isinstance(event_entries, list):
                continue
            for entry in event_entries:
                for hook in entry.get("hooks", []):
                    cmd = hook.get("command", "")
                    tokens = shlex.split(cmd)
                    script_tokens = [tok for tok in tokens if tok.startswith(prefix)]
                    assert script_tokens, f"Hook command missing expected plugin prefix: {cmd!r}"
                    for tok in script_tokens:
                        rel_path = tok.removeprefix(prefix)
                        referenced_scripts.append(rel_path)
                        assert (REPO_ROOT / rel_path).is_file(), f"Referenced hook script missing: {rel_path}"

    assert len(referenced_scripts) > 0, "Expected at least one hook script in hooks.json.example"


def test_packaging_archive_invariants():
    manifest = json.loads((REPO_ROOT / "plugin.json").read_text(encoding="utf-8"))
    expected_name = f"{manifest['name']}-{manifest['version']}.zip"

    with tempfile.TemporaryDirectory() as tmp_dir:
        proc = subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "package-plugin.sh"), "--output-dir", tmp_dir],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"package-plugin.sh failed:\n{proc.stdout}\n{proc.stderr}"

        archive_path = Path(tmp_dir) / expected_name
        assert archive_path.is_file(), f"Expected archive at {archive_path}"

        with zipfile.ZipFile(archive_path) as zf:
            assert zf.testzip() is None
            names = set(zf.namelist())

        required_root = {
            "plugin.json",
            "README.md",
            "LICENSE",
            "agystack-models.md",
            "agystack-runtime.json.example",
            "hooks.json.example",
        }
        missing = required_root - names
        assert not missing, f"Archive missing required root files: {sorted(missing)}"

        forbidden = [
            name for name in names
            if name.endswith(".test.ts")
            or name.endswith(".test-helper.ts")
            or "__pycache__" in Path(name).parts
            or "node_modules" in Path(name).parts
        ]
        assert not forbidden, f"Archive contains forbidden entries: {forbidden}"
