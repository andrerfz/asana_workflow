"""Tests for stream-json parsing, infra error detection, and stale run recovery."""
import json
import tempfile
from pathlib import Path

from app.agent.stream_parser import (
    extract_text_from_stream,
    extract_result_from_stream_lines,
    detect_infra_error,
    recover_stale_runs,
)


# ═══════════════════════════════════════════════
# extract_text_from_stream
# ═══════════════════════════════════════════════

class TestExtractTextFromStream:
    """Tests for QA stream-json fallback extraction."""

    def test_plain_text_passthrough(self):
        """Non-JSON text should be returned as-is."""
        text = "## QA Report\nAll tests passed."
        assert extract_text_from_stream(text) == text

    def test_empty_input(self):
        """Empty string returns empty string."""
        assert extract_text_from_stream("") == ""

    def test_none_input(self):
        assert extract_text_from_stream(None) is None

    def test_assistant_message_extraction(self):
        """Extract text from assistant-type events."""
        events = [
            json.dumps({"type": "assistant", "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "## QA Report\nLooks good."}]
            }}),
            json.dumps({"type": "result", "result": "Final summary."}),
        ]
        raw = "\n".join(events)
        result = extract_text_from_stream(raw)
        assert "QA Report" in result
        assert "Looks good" in result
        assert "Final summary" in result

    def test_result_event_extraction(self):
        """Extract text from result-type events."""
        events = [
            json.dumps({"type": "system", "data": "init"}),
            json.dumps({"type": "result", "result": "Task completed successfully."}),
        ]
        raw = "\n".join(events)
        result = extract_text_from_stream(raw)
        assert result == "Task completed successfully."

    def test_content_block_delta_extraction(self):
        """Extract text from content_block_delta events (newer CLI format)."""
        events = [
            json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello "}}),
            json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "World"}}),
        ]
        raw = "\n".join(events)
        result = extract_text_from_stream(raw)
        assert "Hello" in result
        assert "World" in result

    def test_no_extractable_content_returns_none(self):
        """Events without text content should return None."""
        events = [
            json.dumps({"type": "system", "data": "init"}),
            json.dumps({"type": "tool_use", "name": "Read", "input": {}}),
        ]
        raw = "\n".join(events)
        assert extract_text_from_stream(raw) is None

    def test_mixed_json_and_plain_text(self):
        """Plain text lines mixed with JSON should include both."""
        lines = [
            json.dumps({"type": "assistant", "message": {
                "content": [{"type": "text", "text": "Analysis:"}]
            }}),
            "Some plain text here",
        ]
        raw = "\n".join(lines)
        result = extract_text_from_stream(raw)
        assert "Analysis:" in result
        assert "Some plain text here" in result

    def test_malformed_json_lines_skipped(self):
        """Invalid JSON lines should be skipped, not crash."""
        lines = [
            '{"type": "assistant", "message": {"content": [{"type": "text", "text": "Good report"}]}}',
            '{broken json...',
            '{"type": "result", "result": "Done"}',
        ]
        raw = "\n".join(lines)
        result = extract_text_from_stream(raw)
        assert "Good report" in result
        assert "Done" in result

    def test_assistant_with_empty_text_skipped(self):
        """Assistant messages with empty text blocks should be skipped."""
        events = [
            json.dumps({"type": "assistant", "message": {
                "content": [{"type": "text", "text": ""}]
            }}),
            json.dumps({"type": "assistant", "message": {
                "content": [{"type": "text", "text": "Real content"}]
            }}),
        ]
        raw = "\n".join(events)
        result = extract_text_from_stream(raw)
        assert result == "Real content"

    def test_assistant_with_tool_use_blocks(self):
        """Assistant messages with tool_use blocks (no text) should be handled."""
        events = [
            json.dumps({"type": "assistant", "message": {
                "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]
            }}),
            json.dumps({"type": "assistant", "message": {
                "content": [{"type": "text", "text": "Final answer"}]
            }}),
        ]
        raw = "\n".join(events)
        result = extract_text_from_stream(raw)
        assert result == "Final answer"


# ═══════════════════════════════════════════════
# extract_result_from_stream_lines
# ═══════════════════════════════════════════════

class TestExtractResultFromStreamLines:
    """Tests for the main CLI output parser."""

    def test_result_event_takes_priority(self):
        """A result event should be preferred over assistant messages."""
        lines = [
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Thinking..."}]}}),
            json.dumps({"type": "result", "result": "Final answer here"}),
        ]
        assert extract_result_from_stream_lines(lines) == "Final answer here"

    def test_last_assistant_message_fallback(self):
        """Without result event, use last assistant message."""
        lines = [
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "First thought"}]}}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Final thought"}]}}),
        ]
        assert extract_result_from_stream_lines(lines) == "Final thought"

    def test_longest_text_block_fallback(self):
        """When last assistant has no text, use longest block from any."""
        lines = [
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "This is a longer detailed analysis of the issue"}]}}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}}),
        ]
        result = extract_result_from_stream_lines(lines)
        assert "longer detailed analysis" in result

    def test_content_block_delta_fallback(self):
        """content_block_delta events should be used as last resort."""
        lines = [
            json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Delta text"}}),
        ]
        assert extract_result_from_stream_lines(lines) == "Delta text"

    def test_empty_lines(self):
        assert extract_result_from_stream_lines([]) == ""

    def test_only_system_events(self):
        """Non-text events should return empty string."""
        lines = [
            json.dumps({"type": "system", "data": "init"}),
        ]
        assert extract_result_from_stream_lines(lines) == ""

    def test_result_event_with_empty_result(self):
        """Result event with empty result field should fall through."""
        lines = [
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Fallback text"}]}}),
            json.dumps({"type": "result", "result": ""}),
        ]
        assert extract_result_from_stream_lines(lines) == "Fallback text"


# ═══════════════════════════════════════════════
# detect_infra_error
# ═══════════════════════════════════════════════

class TestDetectInfraError:
    """Tests for infrastructure error detection in test output."""

    def test_docker_daemon_not_running(self):
        output = "Cannot connect to the Docker daemon at unix:///var/run/docker.sock"
        assert detect_infra_error(output) is not None

    def test_unable_to_find_user(self):
        output = 'error: failed switching to "php": unable to find user php: no matching entries in passwd file'
        matched = detect_infra_error(output)
        assert matched is not None
        assert "unable to find user" in matched

    def test_no_such_container(self):
        output = "Error: No such container: laravel.test-abc123"
        assert detect_infra_error(output) is not None

    def test_network_not_found(self):
        output = 'Error response from daemon: network yurest_back_sail not found'
        assert detect_infra_error(output) is not None

    def test_error_response_from_daemon(self):
        output = "Error response from daemon: conflict: unable to delete"
        assert detect_infra_error(output) is not None

    def test_no_docker_binary(self):
        output = "No such file or directory: 'docker'"
        assert detect_infra_error(output) is not None

    # ── False positives that should NOT match ──

    def test_php_class_not_found_is_not_infra(self):
        """PHP 'class not found' is a code error, not infra."""
        output = "Error: Class 'App\\Models\\Invoice' not found in /var/www/html/app/Http/Controllers"
        assert detect_infra_error(output) is None

    def test_route_not_found_is_not_infra(self):
        """HTTP 404 in test output is not an infra error."""
        output = "Expected status 200 but got 404. Route not found."
        assert detect_infra_error(output) is None

    def test_method_not_found_is_not_infra(self):
        """PHP method errors are code bugs, not infra."""
        output = "BadMethodCallException: Method not found: calculateTotal"
        assert detect_infra_error(output) is None

    def test_file_not_found_assertion_is_not_infra(self):
        """Test assertion about a missing file is not infra."""
        output = "AssertionError: Expected file output.csv to exist but it was not found"
        assert detect_infra_error(output) is None

    def test_normal_test_failure_is_not_infra(self):
        """Standard test failure output should not match."""
        output = """
FAILURES!
Tests: 3293, Assertions: 15000, Failures: 2.
Failed asserting that 8.050 matches expected 8.3616.
"""
        assert detect_infra_error(output) is None

    def test_paratest_progress_is_not_infra(self):
        """Normal paratest progress should not match."""
        output = "  122 / 3293 ( 3%)"
        assert detect_infra_error(output) is None

    def test_empty_output(self):
        assert detect_infra_error("") is None


# ═══════════════════════════════════════════════
# recover_stale_runs
# ═══════════════════════════════════════════════

class TestRecoverStaleRuns:
    """Tests for startup recovery of interrupted agent runs."""

    def _make_run(self, tmpdir: Path, task_gid: str, phase: str, **extra) -> Path:
        data = {"task_gid": task_gid, "phase": phase, "task_name": f"Test {task_gid}", **extra}
        path = tmpdir / f"{task_gid}.json"
        path.write_text(json.dumps(data))
        return path

    def test_coding_phase_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            tmpdir = Path(d)
            self._make_run(tmpdir, "111", "coding")
            recovered = recover_stale_runs(tmpdir)
            assert len(recovered) == 1
            assert recovered[0]["old_phase"] == "coding"
            assert recovered[0]["new_phase"] == "error"
            # Verify file was updated
            data = json.loads((tmpdir / "111.json").read_text())
            assert data["phase"] == "error"
            assert "Interrupted" in data["error"]
            assert data["is_active"] is False

    def test_all_active_phases_recovered(self):
        with tempfile.TemporaryDirectory() as d:
            tmpdir = Path(d)
            for i, phase in enumerate(["coding", "testing", "qa_review", "planning", "init", "queued"]):
                self._make_run(tmpdir, str(i), phase)
            recovered = recover_stale_runs(tmpdir)
            assert len(recovered) == 6

    def test_done_phase_not_touched(self):
        with tempfile.TemporaryDirectory() as d:
            tmpdir = Path(d)
            self._make_run(tmpdir, "222", "done")
            recovered = recover_stale_runs(tmpdir)
            assert len(recovered) == 0
            data = json.loads((tmpdir / "222.json").read_text())
            assert data["phase"] == "done"

    def test_error_phase_not_touched(self):
        with tempfile.TemporaryDirectory() as d:
            tmpdir = Path(d)
            self._make_run(tmpdir, "333", "error")
            recovered = recover_stale_runs(tmpdir)
            assert len(recovered) == 0

    def test_cancelled_phase_not_touched(self):
        with tempfile.TemporaryDirectory() as d:
            tmpdir = Path(d)
            self._make_run(tmpdir, "444", "cancelled")
            recovered = recover_stale_runs(tmpdir)
            assert len(recovered) == 0

    def test_mixed_phases(self):
        with tempfile.TemporaryDirectory() as d:
            tmpdir = Path(d)
            self._make_run(tmpdir, "100", "done")
            self._make_run(tmpdir, "200", "coding")
            self._make_run(tmpdir, "300", "error")
            self._make_run(tmpdir, "400", "testing")
            recovered = recover_stale_runs(tmpdir)
            assert len(recovered) == 2
            gids = {r["task_gid"] for r in recovered}
            assert gids == {"200", "400"}

    def test_nonexistent_directory(self):
        recovered = recover_stale_runs(Path("/nonexistent/path"))
        assert recovered == []

    def test_non_json_files_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            tmpdir = Path(d)
            (tmpdir / "readme.txt").write_text("not json")
            (tmpdir / ".gitkeep").write_text("")
            recovered = recover_stale_runs(tmpdir)
            assert recovered == []

    def test_malformed_json_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            tmpdir = Path(d)
            (tmpdir / "bad.json").write_text("{broken json")
            self._make_run(tmpdir, "555", "coding")
            recovered = recover_stale_runs(tmpdir)
            assert len(recovered) == 1
            assert recovered[0]["task_gid"] == "555"

    def test_preserves_original_error_message(self):
        """Recovery error message should include the original phase."""
        with tempfile.TemporaryDirectory() as d:
            tmpdir = Path(d)
            self._make_run(tmpdir, "666", "qa_review")
            recover_stale_runs(tmpdir)
            data = json.loads((tmpdir / "666.json").read_text())
            assert "was: qa_review" in data["error"]
