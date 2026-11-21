"""These tests launch distinct Python processes against the real LangGraph runtime."""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_workflow import PAYOUT, QUESTION


HAS_LANGGRAPH = importlib.util.find_spec("langgraph") is not None
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(HAS_LANGGRAPH, "Install project dependencies to run real LangGraph subprocess tests")
class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.env = dict(os.environ)
        self.env.pop("GROQ_API_KEY", None)
        self.env.pop("QWEN_API_KEY", None)
        self.env.pop("DASHSCOPE_API_KEY", None)
        self.env.pop("TAVILY_API_KEY", None)

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, "-m", "deluxe", "--home", str(self.home), *args],
                                cwd=ROOT, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def discover(self):
        output = self.cli("discover", "--offline")
        self.assertIn("Paused for the editor", output)
        self.assertIn("--select 1", output)
        return re.search(r"Created run: ([a-f0-9]+)", output).group(1)

    def test_article_after_process_restart_and_repeat_resume(self):
        run = self.discover()
        inspected = self.cli("resume", run)
        self.assertIn("What LoomCart", inspected)
        self.assertIn(run, self.cli("list-runs"))
        self.cli("resume", run, "--select", "1")
        folder = self.home / "outputs" / run
        self.assertTrue((folder / "article.md").is_file())
        audit = json.loads((folder / "audit.json").read_text())
        self.assertEqual(audit["approved_question"], QUESTION)
        article = (folder / "article.md").read_text()
        self.assertIn("complete", self.cli("resume", run))
        self.assertEqual((folder / "article.md").read_text(), article)
        self.assertIn("complete", self.cli("list-runs"))

    def test_revised_payout_angle_survives_processes_and_returns_brief(self):
        run = self.discover()
        self.cli("resume", run, "--select", "1", "--question", PAYOUT)
        folder = self.home / "outputs" / run
        brief = (folder / "reporting-brief.md").read_text()
        self.assertIn(PAYOUT, brief)
        self.assertFalse((folder / "article.md").exists())
        self.assertIn(PAYOUT, self.cli("resume", run))

    def test_duplicate_coverage_after_restart(self):
        self.discover()
        second = self.cli("discover", "--offline")
        self.assertIn("no_pitches", second)
        self.assertNotIn("Paused for the editor", second)

    def test_invalid_choice_does_not_consume_interrupt_and_dismiss_persists(self):
        run = self.discover()
        self.cli("resume", run, "--select", "99", expected=2)
        self.assertIn("Paused for the editor", self.cli("resume", run))
        self.cli("resume", run, "--dismiss")
        self.assertIn("dismissed", self.cli("resume", run))
        self.assertFalse((self.home / "outputs" / run).exists())

    def test_editor_choice_persisted_before_research_failure(self):
        run = self.discover()
        script = """
import sys
from deluxe.adapters import AdapterError
from deluxe.cli import main
from deluxe.workflow import EditorialWorkflow
def fail(self, state):
    raise AdapterError('Temporary research failure')
EditorialWorkflow.research_start = fail
main()
"""
        failed = subprocess.run([sys.executable, "-c", script, "--home", str(self.home),
                                 "resume", run, "--select", "1", "--question", PAYOUT],
                                cwd=ROOT, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(failed.returncode, 2, failed.stderr)
        self.assertIn("Work checkpointed", failed.stderr)
        # New process with normal adapters retries the failed node without a new choice.
        self.cli("resume", run)
        folder = self.home / "outputs" / run
        audit = json.loads((folder / "audit.json").read_text())
        self.assertEqual(audit["approved_question"], PAYOUT)
        self.assertEqual(audit["editor_decision"]["pitch_id"], "1")
        self.assertTrue((folder / "reporting-brief.md").exists())

    def test_live_credentials_required_no_silent_offline_fallback(self):
        output = self.cli("discover", expected=2)
        self.assertIn("GROQ_API_KEY", output)
        self.assertEqual(self.cli("list-runs"), "")


if __name__ == "__main__":
    unittest.main()
