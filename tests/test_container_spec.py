import os
import re
import unittest
from pathlib import Path


class TestContainerSpec(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project_root = Path(__file__).resolve().parent.parent
        cls.dockerfile_path = cls.project_root / "skills" / "swarm" / "scripts" / "Dockerfile"
        cls.setup_script_path = cls.project_root / "skills" / "swarm" / "scripts" / "setup-rust-worker.sh"
        cls.installed_plugin_dir = Path(os.path.expanduser("~/.gemini/config/plugins/agystack/skills/swarm/scripts"))

        if not cls.dockerfile_path.is_file():
            raise FileNotFoundError(f"Dockerfile not found at {cls.dockerfile_path}")
        cls.dockerfile_content = cls.dockerfile_path.read_text(encoding="utf-8")

    def test_base_image(self):
        self.assertRegex(
            self.dockerfile_content,
            r"FROM\s+python:3\.11-slim",
            "Base image must be python:3.11-slim",
        )

    def test_environment_variables(self):
        required_env_vars = [
            r"RUSTUP_HOME=/usr/local/rustup",
            r"CARGO_HOME=/usr/local/cargo",
            r"PATH=/usr/local/cargo/bin:\$PATH",
            r"PYTHONUNBUFFERED=1",
            r"DEBIAN_FRONTEND=noninteractive",
        ]
        for env_var in required_env_vars:
            self.assertTrue(
                re.search(env_var, self.dockerfile_content),
                f"Missing required environment variable definition: {env_var}",
            )

    def test_system_packages(self):
        required_packages = [
            "git",
            "git-lfs",
            "curl",
            "ca-certificates",
            "gnupg",
            "build-essential",
            "pkg-config",
            "libssl-dev",
            "bubblewrap",
            "util-linux",
            "nodejs",
        ]
        for pkg in required_packages:
            pattern = rf"\b{re.escape(pkg)}\b"
            self.assertTrue(
                re.search(pattern, self.dockerfile_content),
                f"Missing required system package in Dockerfile: {pkg}",
            )
        self.assertIn("setup_20.x", self.dockerfile_content)

    def test_rust_toolchain(self):
        self.assertIn("https://sh.rustup.rs", self.dockerfile_content)
        self.assertIn("--default-toolchain stable", self.dockerfile_content)
        self.assertIn("--profile minimal", self.dockerfile_content)
        self.assertRegex(
            self.dockerfile_content,
            r"chmod\s+-R\s+a\+w\s+/usr/local/cargo",
            "Cargo directory must be writable by all users",
        )

    def test_worker_user(self):
        self.assertRegex(
            self.dockerfile_content,
            r"useradd\s+-m\s+-u\s+1000\s+-s\s+/bin/bash\s+worker",
            "Non-root worker user with UID 1000 must be created",
        )
        self.assertRegex(
            self.dockerfile_content,
            r"\bUSER\s+worker\b",
            "Dockerfile should switch to worker user",
        )

    def test_git_lfs(self):
        self.assertIn("git lfs install --system", self.dockerfile_content)

    def test_antigravity_and_entrypoint(self):
        self.assertIn("pip install --no-cache-dir google-antigravity", self.dockerfile_content)
        self.assertIn('ENTRYPOINT ["python", "/app/cloud_worker.py"]', self.dockerfile_content)

    def test_setup_rust_worker_script_exists_and_matches_spec(self):
        self.assertTrue(
            self.setup_script_path.is_file(),
            f"setup-rust-worker.sh must exist at {self.setup_script_path}",
        )
        content = self.setup_script_path.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("#!/usr/bin/env bash"))
        self.assertIn("1000", content)
        self.assertIn("--default-toolchain 1.80.0", content)
        self.assertIn("git-lfs", content)
        self.assertIn("bubblewrap", content)
        self.assertIn("util-linux", content)

    def test_installed_plugin_dockerfile_sync(self):
        installed_dockerfile = self.installed_plugin_dir / "Dockerfile"
        if installed_dockerfile.is_file():
            installed_content = installed_dockerfile.read_text(encoding="utf-8")
            self.assertEqual(
                self.dockerfile_content,
                installed_content,
                "Installed agystack plugin Dockerfile must match project Dockerfile",
            )


if __name__ == "__main__":
    unittest.main()
