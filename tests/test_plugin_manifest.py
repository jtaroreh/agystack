import json
from pathlib import Path
import xml.etree.ElementTree as ET

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
