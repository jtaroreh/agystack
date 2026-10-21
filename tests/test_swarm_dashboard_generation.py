#!/usr/bin/env python3
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "swarm" / "scripts"))

from cloud_dispatch import (
    SwarmDashboardWriter,
    TaskDashboardState,
    format_cloud_logging_url,
    format_cloud_run_execution_url,
    format_elapsed_time,
    format_gcs_console_url,
    format_status_badge,
    format_tool_snippet,
)


class TestSwarmDashboardGeneration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp()).resolve()
        self.app_data_dir = self.temp_dir / "antigravity"
        self.session_id = f"test-sess-{int(time.time() * 1000)}"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_initial_pending_table_rendering_all_tasks_queued(self):
        task_count = 4
        writer = SwarmDashboardWriter(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=task_count,
            model="gemini-3.8-flash",
        )
        dashboard_file = writer.write()

        self.assertTrue(dashboard_file.is_file())
        self.assertEqual(dashboard_file, self.app_data_dir / "brain" / self.session_id / "swarm_dashboard.md")

        content = dashboard_file.read_text(encoding="utf-8")

        self.assertIn("| Task Index | Model | Active Phase / Tool | Elapsed Time | Status Badge | Conversation Deep Link |", content)
        self.assertIn("**Total Tasks:** 4", content)
        self.assertIn("**Queued:** 4", content)
        self.assertIn("**Running:** 0", content)

        for i in range(task_count):
            self.assertEqual(writer.get_task_status(i), "Queued")
            self.assertEqual(writer.get_task_badge(i), "⏳ Queued")
            expected_conv_url = f"conversation://cloud-{self.session_id}-task-{i}"
            self.assertIn(f"| {i} | gemini-3.8-flash | - | 0s | ⏳ Queued | [{expected_conv_url}]({expected_conv_url}) |", content)

    def test_phase_transition_to_running_agent_changing_status_badge(self):
        writer = SwarmDashboardWriter(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=2,
            model="gemini-3.8-flash",
        )
        writer.write()

        milestone_line = "[MILESTONE] [TASK 0] [PHASE: RUNNING_AGENT] Initializing subagent loop"
        processed = writer.process_log_line(milestone_line)
        self.assertTrue(processed)

        self.assertEqual(writer.get_task_status(0), "Running")
        self.assertEqual(writer.get_task_badge(0), "🔄 Running")
        self.assertEqual(writer.get_task_status(1), "Queued")
        self.assertEqual(writer.get_task_badge(1), "⏳ Queued")

        content = writer.render()
        self.assertIn("| 0 | gemini-3.8-flash | RUNNING_AGENT |", content)
        self.assertIn("🔄 Running", content)
        self.assertIn("| 1 | gemini-3.8-flash | - | 0s | ⏳ Queued |", content)

    def test_active_tool_name_and_arguments_snippet_updating_in_real_time(self):
        writer = SwarmDashboardWriter(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=2,
            model="gemini-3.8-flash",
        )
        writer.update_task_phase(0, "RUNNING_AGENT")

        telemetry_line = (
            f'[TELEMETRY] [TASK 0] {{"timestamp": {time.time()}, "event": "tool_call", '
            f'"tool_name": "run_command", "args": {{"CommandLine": "cargo test --release", "timeout": 300}}}}'
        )
        processed = writer.process_log_line(telemetry_line)
        self.assertTrue(processed)

        content = writer.render()
        self.assertIn("run_command(CommandLine='cargo test --release')", content)
        self.assertIn("🔄 Running", content)

        # Test edge case with pipes and newlines to ensure markdown table structure is preserved
        writer.update_task_tool(
            0,
            tool_name="view_file",
            args={"AbsolutePath": "/tmp/test|file\nname.py", "StartLine": 1},
        )
        content_sanitized = writer.render()
        self.assertNotIn("\nname.py", content_sanitized.splitlines()[8])  # Check table row line does not break
        self.assertIn("view_file", content_sanitized)
        self.assertIn("\\|", content_sanitized)

    def test_elapsed_timer_column_incrementing_accurately(self):
        writer = SwarmDashboardWriter(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=1,
            model="gemini-3.8-flash",
        )
        writer.update_task_phase(0, "RUNNING_AGENT")
        state = writer.get_task_state(0)
        self.assertIsNotNone(state)
        t0 = 1000.0
        state.start_time = t0

        content_15s = writer.render(now=t0 + 15.0)
        self.assertIn("| 0 | gemini-3.8-flash | RUNNING_AGENT | 15s | 🔄 Running |", content_15s)

        content_75s = writer.render(now=t0 + 75.0)
        self.assertIn("| 0 | gemini-3.8-flash | RUNNING_AGENT | 1m 15s | 🔄 Running |", content_75s)

        content_3665s = writer.render(now=t0 + 3665.0)
        self.assertIn("| 0 | gemini-3.8-flash | RUNNING_AGENT | 1h 01m 05s | 🔄 Running |", content_3665s)

    def test_green_pass_badge_on_task_completion(self):
        writer = SwarmDashboardWriter(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=1,
            model="gemini-3.8-flash",
        )
        writer.update_task_phase(0, "RUNNING_AGENT")

        status_line = "[TASK 0] [STATUS: PASS] All 42 tests verified successfully."
        processed = writer.process_log_line(status_line)
        self.assertTrue(processed)

        self.assertEqual(writer.get_task_status(0), "PASS")
        self.assertEqual(writer.get_task_badge(0), "🟢 PASS")

        content = writer.render()
        self.assertIn("🟢 PASS", content)
        self.assertIn("**PASS:** 1", content)

        state = writer.get_task_state(0)
        self.assertIsNotNone(state.end_time)

    def test_warning_issues_badge_on_test_failure(self):
        writer = SwarmDashboardWriter(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=2,
            model="gemini-3.8-flash",
        )
        writer.update_task_phase(0, "RUNNING_AGENT")
        writer.update_task_phase(1, "RUNNING_AGENT")

        issues_line = "[TASK 0] [STATUS: ISSUES] 2 assertions failed in test_suite.py"
        processed_issues = writer.process_log_line(issues_line)
        self.assertTrue(processed_issues)
        self.assertEqual(writer.get_task_status(0), "ISSUES")
        self.assertEqual(writer.get_task_badge(0), "⚠️ ISSUES")

        blocked_line = "[TASK 1] [STATUS: BLOCKED] Git authentication failure."
        processed_blocked = writer.process_log_line(blocked_line)
        self.assertTrue(processed_blocked)
        self.assertEqual(writer.get_task_status(1), "BLOCKED")
        self.assertEqual(writer.get_task_badge(1), "🔴 BLOCKED")

        content = writer.render()
        self.assertIn("⚠️ ISSUES", content)
        self.assertIn("🔴 BLOCKED", content)
        self.assertIn("**ISSUES:** 1", content)
        self.assertIn("**BLOCKED:** 1", content)

    def test_cloud_run_execution_console_link_formatting(self):
        exec_name = "swarm-job-exec-456"
        project_id = "test-gcp-project"
        region = "us-central1"

        url = format_cloud_run_execution_url(
            execution_name=exec_name,
            project=project_id,
            region=region,
        )
        expected = f"https://console.cloud.google.com/run/jobs/executions/details/{region}/{exec_name}?project={project_id}"
        self.assertEqual(url, expected)

        writer = SwarmDashboardWriter(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=1,
            project=project_id,
            region=region,
            execution_name=exec_name,
        )
        content = writer.render()
        self.assertIn(f"[{exec_name}]({expected})", content)

    def test_prefiltered_cloud_logging_console_link_formatting(self):
        exec_name = "swarm-job-exec-789"
        project_id = "test-gcp-project"

        url = format_cloud_logging_url(
            execution_name=exec_name,
            project=project_id,
        )
        self.assertTrue(url.startswith("https://console.cloud.google.com/logs/query;query="))
        self.assertIn(f"?project={project_id}", url)
        self.assertIn("run.googleapis.com", url)
        self.assertIn("swarm-job-exec-789", url)

        writer = SwarmDashboardWriter(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=1,
            project=project_id,
            execution_name=exec_name,
        )
        content = writer.render()
        self.assertIn(f"[Pre-filtered Logs]({url})", content)

    def test_gcs_artifact_folder_console_link_formatting(self):
        bucket_name = "swarm-artifacts-bucket"
        session_id = "session-20261021-alpha"
        project_id = "test-gcp-project"

        url = format_gcs_console_url(
            bucket=bucket_name,
            prefix=f"swarms/{session_id}",
            project=project_id,
        )
        expected = f"https://console.cloud.google.com/storage/browser/{bucket_name}/swarms/{session_id}?project={project_id}"
        self.assertEqual(url, expected)

        # Test resilient strip of gs:// prefix
        url_with_gs = format_gcs_console_url(
            bucket=f"gs://{bucket_name}",
            prefix=f"gs://{bucket_name}/swarms/{session_id}",
            project=project_id,
        )
        self.assertEqual(url_with_gs, expected)

        writer = SwarmDashboardWriter(
            session_id=session_id,
            app_data_dir=self.app_data_dir,
            task_count=1,
            project=project_id,
            gcs_bucket=bucket_name,
        )
        content = writer.render()
        self.assertIn(f"[gs://{bucket_name}/swarms/{session_id}]({expected})", content)

    def test_atomic_write_replacement_prevents_partial_reads(self):
        writer = SwarmDashboardWriter(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=3,
            model="gemini-3.8-flash",
        )
        target_path = writer.dashboard_path

        replace_calls = []
        original_replace = os.replace

        def spy_replace(src, dst):
            # Verify src is a temporary file in the target directory
            self.assertTrue(Path(src).parent == Path(dst).parent)
            self.assertTrue(Path(src).name.startswith(".swarm_dashboard_"))
            self.assertTrue(Path(src).is_file())
            # Content in temp file must be complete valid markdown
            temp_content = Path(src).read_text(encoding="utf-8")
            self.assertIn("| Task Index | Model |", temp_content)
            replace_calls.append((src, dst))
            return original_replace(src, dst)

        with patch("os.replace", side_effect=spy_replace):
            result_file = writer.write()

        self.assertEqual(len(replace_calls), 1)
        self.assertEqual(Path(result_file), target_path)
        self.assertTrue(target_path.is_file())

        # Second write: verify atomic replacement over existing file
        writer.update_task_phase(0, "RUNNING_AGENT")
        with patch("os.replace", side_effect=spy_replace):
            writer.write()

        self.assertEqual(len(replace_calls), 2)
        final_content = target_path.read_text(encoding="utf-8")
        self.assertIn("RUNNING_AGENT", final_content)

    def test_dashboard_write_performance_benchmark(self):
        task_count = 32
        writer = SwarmDashboardWriter(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=task_count,
            model="gemini-3.8-flash",
            project="test-proj",
            region="us-central1",
            execution_name="benchmark-exec",
            gcs_bucket="benchmark-bucket",
        )

        for i in range(task_count):
            if i % 4 == 0:
                writer.update_task_phase(i, "RUNNING_AGENT")
                writer.update_task_tool(i, "run_command", {"CommandLine": f"test_worker_{i}.sh"})
            elif i % 4 == 1:
                writer.update_task_status(i, "PASS")
            elif i % 4 == 2:
                writer.update_task_status(i, "ISSUES")
            else:
                pass

        iterations = 20
        durations = []
        for _ in range(iterations):
            t_start = time.perf_counter()
            writer.write()
            durations.append(time.perf_counter() - t_start)

        avg_duration_ms = (sum(durations) / len(durations)) * 1000.0
        max_duration_ms = max(durations) * 1000.0

        # Overhead must be bounded <= 25 milliseconds across 32 tasks (baseline 5ms)
        self.assertLessEqual(
            avg_duration_ms,
            25.0,
            f"Average dashboard write latency ({avg_duration_ms:.2f}ms) exceeded 25ms SLA.",
        )
        self.assertLessEqual(
            max_duration_ms,
            50.0,
            f"Max dashboard write latency ({max_duration_ms:.2f}ms) exceeded 50ms spike limit.",
        )


if __name__ == "__main__":
    unittest.main()
