#!/usr/bin/env python3
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "swarm" / "scripts"))

import swarm_dashboard
from cloud_dispatch import (
    SwarmDashboardWriter,
    TaskDashboardState,
    colorize,
    format_cloud_logging_url,
    format_cloud_run_execution_url,
    format_cloud_run_url,
    format_elapsed_time,
    format_gcs_console_url,
    format_gcs_url,
    format_log_viewer_url,
    format_monitored_line,
    format_status_badge,
    format_tool_snippet,
)


class TestSwarmDashboardGeneration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp()).resolve()
        self.app_data_dir = self.temp_dir / "antigravity"
        self.session_id = f"test-sess-{int(time.time() * 1000)}"
        self._orig_env = os.environ.copy()
        os.environ.pop("CONVERSATION_ID", None)
        os.environ.pop("ANTIGRAVITY_CONVERSATION_ID", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)
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

    def test_reexported_symbols_match_between_modules(self):
        import cloud_dispatch

        self.assertIs(cloud_dispatch.SwarmDashboardWriter, swarm_dashboard.SwarmDashboardWriter)
        self.assertIs(cloud_dispatch.TaskDashboardState, swarm_dashboard.TaskDashboardState)
        self.assertIs(cloud_dispatch.format_status_badge, swarm_dashboard.format_status_badge)
        self.assertIs(cloud_dispatch.format_elapsed_time, swarm_dashboard.format_elapsed_time)
        self.assertIs(cloud_dispatch.format_tool_snippet, swarm_dashboard.format_tool_snippet)
        self.assertIs(cloud_dispatch.format_cloud_run_execution_url, swarm_dashboard.format_cloud_run_execution_url)
        self.assertIs(cloud_dispatch.format_cloud_logging_url, swarm_dashboard.format_cloud_logging_url)
        self.assertIs(cloud_dispatch.format_gcs_console_url, swarm_dashboard.format_gcs_console_url)
        self.assertIs(cloud_dispatch.format_monitored_line, swarm_dashboard.format_monitored_line)
        self.assertIs(cloud_dispatch.colorize, swarm_dashboard.colorize)
        self.assertIs(cloud_dispatch.format_cloud_run_url, swarm_dashboard.format_cloud_run_url)
        self.assertIs(cloud_dispatch.format_gcs_url, swarm_dashboard.format_gcs_url)
        self.assertIs(cloud_dispatch.format_log_viewer_url, swarm_dashboard.format_log_viewer_url)

    def test_conversation_id_resolution_precedence(self):
        # 1. Explicit argument takes top priority over environment variables and session_id
        with patch.dict(os.environ, {"CONVERSATION_ID": "env-conv-123", "ANTIGRAVITY_CONVERSATION_ID": "antigravity-conv-456"}):
            writer = SwarmDashboardWriter(
                session_id=self.session_id,
                conversation_id="explicit-conv-999",
                app_data_dir=self.app_data_dir,
            )
            self.assertEqual(writer.conversation_id, "explicit-conv-999")
            self.assertEqual(writer.dashboard_path, self.app_data_dir / "brain" / "explicit-conv-999" / "swarm_dashboard.md")

        # 2. CONVERSATION_ID from environment takes precedence over session_id
        with patch.dict(os.environ, {"CONVERSATION_ID": "env-conv-123"}):
            os.environ.pop("ANTIGRAVITY_CONVERSATION_ID", None)
            writer = SwarmDashboardWriter(
                session_id=self.session_id,
                app_data_dir=self.app_data_dir,
            )
            self.assertEqual(writer.conversation_id, "env-conv-123")
            self.assertEqual(writer.dashboard_path, self.app_data_dir / "brain" / "env-conv-123" / "swarm_dashboard.md")

        # 3. ANTIGRAVITY_CONVERSATION_ID takes precedence when CONVERSATION_ID is unset
        with patch.dict(os.environ, {"ANTIGRAVITY_CONVERSATION_ID": "antigravity-conv-456"}):
            os.environ.pop("CONVERSATION_ID", None)
            writer = SwarmDashboardWriter(
                session_id=self.session_id,
                app_data_dir=self.app_data_dir,
            )
            self.assertEqual(writer.conversation_id, "antigravity-conv-456")
            self.assertEqual(writer.dashboard_path, self.app_data_dir / "brain" / "antigravity-conv-456" / "swarm_dashboard.md")

        # 4. Fallback to session_id when no environment variables or explicit argument are set
        os.environ.pop("CONVERSATION_ID", None)
        os.environ.pop("ANTIGRAVITY_CONVERSATION_ID", None)
        writer = SwarmDashboardWriter(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
        )
        self.assertEqual(writer.conversation_id, self.session_id)
        self.assertEqual(writer.dashboard_path, self.app_data_dir / "brain" / self.session_id / "swarm_dashboard.md")

        # 5. Empty session_id falls back to "default"
        writer_default = SwarmDashboardWriter(
            session_id="",
            app_data_dir=self.app_data_dir,
        )
        self.assertEqual(writer_default.conversation_id, "default")

    def test_storage_url_formatting_uses_swarms_prefix(self):
        bucket = "my-test-bucket"
        sess = "sess-20261021"

        # Default prefix format in SwarmDashboardWriter uses swarms/<session_id>
        writer = SwarmDashboardWriter(
            session_id=sess,
            app_data_dir=self.app_data_dir,
            gcs_bucket=bucket,
        )
        expected_url = f"https://console.cloud.google.com/storage/browser/{bucket}/swarms/{sess}"
        self.assertEqual(writer.format_gcs_console_url(), expected_url)

        # Legacy prefix starting with swarm- is normalized to swarms/
        legacy_url = format_gcs_console_url(bucket=bucket, prefix=f"swarm-{sess}")
        self.assertEqual(legacy_url, expected_url)
        self.assertNotIn("swarm-", legacy_url)

        # Legacy prefix starting with swarm/ is normalized to swarms/
        slash_url = format_gcs_console_url(bucket=bucket, prefix=f"swarm/{sess}")
        self.assertEqual(slash_url, expected_url)

        # Task subpath formatting
        task_url = format_gcs_console_url(bucket=bucket, prefix=f"swarms/{sess}/tasks/task-3")
        self.assertEqual(task_url, f"https://console.cloud.google.com/storage/browser/{bucket}/swarms/{sess}/tasks/task-3")

        # format_gcs_url alias behaves identically
        alias_url = format_gcs_url(bucket=bucket, prefix=f"swarms/{sess}")
        self.assertEqual(alias_url, expected_url)

    def test_log_monitoring_timestamp_cursor_pagination_past_1000_entries(self):
        from cloud_dispatch import monitor_execution

        dashboard_writer = SwarmDashboardWriter(
            session_id=self.session_id,
            app_data_dir=self.app_data_dir,
            task_count=1,
        )

        poll_count = 0
        logged_commands = []

        # Generate 1,000 entries for batch 1
        batch_1_entries = []
        for i in range(1000):
            ts = f"2026-10-21T18:00:00.{i:06d}Z"
            batch_1_entries.append({
                "insertId": f"log-id-{i}",
                "timestamp": ts,
                "textPayload": f"[MILESTONE] [TASK 0] [PHASE: RUNNING_AGENT] Step {i}",
            })

        # Generate 200 entries for batch 2
        batch_2_entries = []
        for i in range(1000, 1200):
            ts = f"2026-10-21T18:00:01.{i - 1000:06d}Z"
            batch_2_entries.append({
                "insertId": f"log-id-{i}",
                "timestamp": ts,
                "textPayload": f"[MILESTONE] [TASK 0] [PHASE: RUNNING_AGENT] Step {i}",
            })
        # Add a duplicate from batch 1 to verify deduplication
        batch_2_entries.append(batch_1_entries[0])

        def fake_subprocess_run(cmd, capture_output=True, text=True, check=False):
            nonlocal poll_count
            cmd_str = " ".join(cmd)
            logged_commands.append(cmd)

            if "executions describe" in cmd_str:
                poll_count += 1
                if poll_count == 1:
                    return MagicMock(
                        returncode=0,
                        stdout=json.dumps({
                            "status": {
                                "runningCount": 1,
                                "succeededCount": 0,
                                "failedCount": 0,
                                "conditions": [{"type": "Completed", "status": "Unknown"}],
                            }
                        }),
                    )
                else:
                    return MagicMock(
                        returncode=0,
                        stdout=json.dumps({
                            "status": {
                                "runningCount": 0,
                                "succeededCount": 1,
                                "failedCount": 0,
                                "conditions": [{"type": "Completed", "status": "True"}],
                            }
                        }),
                    )

            if "logging read" in cmd_str:
                if poll_count == 1:
                    return MagicMock(returncode=0, stdout=json.dumps(batch_1_entries))
                else:
                    return MagicMock(returncode=0, stdout=json.dumps(batch_2_entries))

            return MagicMock(returncode=0, stdout="")

        with patch("subprocess.run", side_effect=fake_subprocess_run):
            with patch("time.sleep", return_value=None):
                result = monitor_execution(
                    execution_name="exec-cursor-test",
                    project="test-proj",
                    region="us-central1",
                    task_count=1,
                    poll_interval=0.01,
                    timeout=10.0,
                    session_id=self.session_id,
                    dashboard_writer=dashboard_writer,
                )

        self.assertTrue(result.succeeded)

        # Inspect the logging read commands across batches
        log_read_cmds = [
            c for c in logged_commands
            if len(c) > 2 and c[0] == "gcloud" and c[1] == "logging" and c[2] == "read"
        ]
        self.assertGreaterEqual(len(log_read_cmds), 2)

        # First read command has no cursor
        self.assertNotIn("timestamp >", log_read_cmds[0][3])

        # Second read command must have the timestamp cursor from the latest timestamp in batch 1
        expected_cursor = 'timestamp > "2026-10-21T18:00:00.000999Z"'
        self.assertIn(expected_cursor, log_read_cmds[1][3])


if __name__ == "__main__":
    unittest.main()
