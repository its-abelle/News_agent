import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from deluxe.adapters import AdapterError
from deluxe.cli import runtime
from deluxe.service import NewsAgent, ServiceError
from deluxe.web import Application
from tests.test_workflow import PAYOUT


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.service = NewsAgent(self.home)
        self.app = Application(self.service)
        self.headers = {"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765",
                        "X-News-Agent-Token": self.app.token}

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def request(self, method, path, payload=None, headers=None):
        body = json.dumps(payload).encode() if payload is not None else b""
        status, response_headers, content = self.app.handle(method, path, headers or self.headers, body)
        if response_headers["Content-Type"].startswith("application/json"):
            content = json.loads(content)
        return status, response_headers, content

    def wait(self, run_id):
        deadline = time.monotonic() + 15
        while self.service._active(run_id):
            if time.monotonic() > deadline:
                self.fail("Background graph job did not finish")
            time.sleep(.01)
        return self.service.detail(run_id)

    def discover(self):
        status, _, result = self.request("POST", "/api/runs", {"mode": "offline", "recent_days": 7, "search_budget": 3})
        self.assertEqual(status, 202, result)
        run = self.wait(result["id"])
        self.assertTrue(run["pending"], run)
        return result["id"]

    def complete(self, question=None):
        run_id = self.discover()
        decision = {"action": "select", "pitch_id": "1"}
        if question:
            decision["question"] = question
        status, _, result = self.request("POST", f"/api/runs/{run_id}/resume", decision)
        self.assertEqual(status, 202, result)
        return self.wait(run_id)

    def test_static_workspace_is_packaged_and_token_is_injected(self):
        status, headers, content = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"News Agent", content)
        self.assertIn(self.app.token.encode(), content)
        self.assertNotIn(b"__SESSION_TOKEN__", content)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        for asset in ("app.js", "style.css"):
            self.assertEqual(self.request("GET", f"/{asset}")[0], 200)

    def test_settings_never_expose_keys(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "groq-private", "QWEN_API_KEY": "qwen-private",
                                      "TAVILY_API_KEY": "tavily-private"}):
            status, _, result = self.request("GET", "/api/settings")
        self.assertEqual(status, 200)
        self.assertTrue(result["groq"] and result["qwen"] and result["search"])
        for value in ("groq-private", "qwen-private", "tavily-private"):
            self.assertNotIn(value, json.dumps(result))

    def test_wrong_host_origin_or_token_cannot_start_reporting(self):
        for changed in ({"Host": "evil.example"}, {"Origin": "https://evil.example"}, {"X-News-Agent-Token": "wrong"}):
            with self.subTest(headers=changed):
                status, _, _ = self.request("POST", "/api/runs", {"mode": "offline"}, headers=self.headers | changed)
                self.assertEqual(status, 403)
        self.assertEqual(self.service.list_runs(), [])

    def test_invalid_json_and_payload_are_rejected(self):
        status, _, _ = self.app.handle("POST", "/api/runs", self.headers, b"not JSON")
        self.assertEqual(status, 400)
        for payload in ([], {"mode": "unknown"}, {"mode": "offline", "search_budget": 100},
                        {"mode": "offline", "recent_days": True}):
            with self.subTest(payload=payload):
                self.assertEqual(self.request("POST", "/api/runs", payload)[0], 400)

    def test_path_traversal_and_secret_paths_are_not_served(self):
        for path in ("/.env", "/../.env", "/%2e%2e/.env", "/api/runs/../../.env", "/api/runs/not-a-run"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)

    def test_live_mode_requires_credentials_and_never_falls_back_to_sample(self):
        with patch.dict("os.environ", {}, clear=True):
            status, _, content = self.request("POST", "/api/runs", {"mode": "live"})
        self.assertEqual(status, 400)
        self.assertIn("GROQ_API_KEY", content["error"])
        self.assertEqual(self.service.list_runs(), [])

    def test_offline_article_through_http_application(self):
        run = self.complete()
        self.assertEqual(run["status"], "complete", run)
        names = {doc["name"] for doc in run["documents"]}
        self.assertEqual(names, {"article.md", "reporting-notes.md"})
        article = next(doc for doc in run["documents"] if doc["name"] == "article.md")
        self.assertIn("SAMPLE MATERIAL", article["content"])
        self.assertIn("[C1]", article["content"])
        self.assertTrue(run["evidence"])
        self.assertFalse(run["pending"])
        self.assertFalse(run["can_resume"])

    def test_revised_payout_question_returns_reporting_brief(self):
        run = self.complete(PAYOUT)
        self.assertEqual(run["approved_question"], PAYOUT)
        self.assertEqual(run["verification"]["outcome"], "reporting_brief")
        self.assertEqual([doc["name"] for doc in run["documents"]], ["reporting-brief.md"])
        self.assertIn("merchant-country eligibility", run["documents"][0]["content"])

    def test_edit_save_download_preserves_verified_original(self):
        run = self.complete()
        run_id = run["id"]
        original = (self.home / "outputs" / run_id / "article.md").read_text()
        edited = "# My edited article\n\nEditor’s own words.\n"
        status, _, result = self.request("PUT", f"/api/runs/{run_id}/documents/article.md", {"content": edited})
        self.assertEqual(status, 200, result)
        status, headers, download = self.request("GET", f"/api/runs/{run_id}/files/article.md")
        self.assertEqual(status, 200)
        self.assertEqual(download.decode(), edited)
        self.assertIn("article-edited.md", headers["Content-Disposition"])
        self.assertEqual((self.home / "outputs" / run_id / "article.md").read_text(), original)
        self.assertTrue(next(doc for doc in self.service.detail(run_id)["documents"] if doc["name"] == "article.md")["edited"])
        self.assertEqual(self.request("PUT", f"/api/runs/{run_id}/documents/audit.json", {"content": "bad"})[0], 404)

    def test_shortlist_and_documents_survive_service_restart(self):
        run_id = self.discover()
        self.service.close()
        self.service = NewsAgent(self.home)
        self.app = Application(self.service)
        self.headers["X-News-Agent-Token"] = self.app.token
        detail = self.service.detail(run_id)
        self.assertTrue(detail["pending"])
        self.assertEqual(len(detail["pitches"]), 1)
        self.assertEqual(self.request("POST", f"/api/runs/{run_id}/resume", {"action": "select", "pitch_id": "1"})[0], 202)
        self.assertEqual(self.wait(run_id)["status"], "complete")

    def test_duplicate_discovery_returns_no_pitches(self):
        self.discover()
        status, _, result = self.request("POST", "/api/runs", {"mode": "offline"})
        self.assertEqual(status, 202)
        self.assertEqual(self.wait(result["id"])["status"], "no_pitches")

    def test_invalid_selection_does_not_consume_interrupt_and_dismiss_works(self):
        run_id = self.discover()
        self.assertEqual(self.request("POST", f"/api/runs/{run_id}/resume", {"action": "select", "pitch_id": "99"})[0], 400)
        self.assertTrue(self.service.detail(run_id)["pending"])
        self.assertEqual(self.request("POST", f"/api/runs/{run_id}/resume", {"action": "dismiss"})[0], 202)
        self.assertEqual(self.wait(run_id)["status"], "dismissed")

    def test_background_failure_is_visible_and_retry_preserves_approval(self):
        run_id = self.discover()
        def failing_factory(store, mode, config):
            workflow = runtime(store, mode, config)
            def fail(state):
                raise AdapterError("Temporary provider outage", status=503)
            workflow.extract = fail
            return workflow
        self.service.workflow_factory = failing_factory
        self.assertEqual(self.request("POST", f"/api/runs/{run_id}/resume",
                                      {"action": "select", "pitch_id": "1", "question": PAYOUT})[0], 202)
        failed = self.wait(run_id)
        self.assertEqual(failed["status"], "error")
        self.assertTrue(failed["can_resume"])
        self.assertIn("Temporary provider outage", failed["error"])
        self.assertEqual(failed["approved_question"], PAYOUT)
        self.assertEqual(self.request("POST", f"/api/runs/{run_id}/resume", {"action": "select", "pitch_id": "1"})[0], 409)
        self.service.workflow_factory = runtime
        self.assertEqual(self.request("POST", f"/api/runs/{run_id}/resume", {"action": "resume"})[0], 202)
        result = self.wait(run_id)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["approved_question"], PAYOUT)
        self.assertEqual(result["verification"]["outcome"], "reporting_brief")

    def test_active_job_rejects_duplicate_resume(self):
        run_id = self.discover()
        with self.service.lock:
            self.service.jobs[run_id]["state"] = "running"
        try:
            with self.assertRaises(ServiceError) as raised:
                self.service.resume(run_id, {"action": "select", "pitch_id": "1"})
            self.assertEqual(raised.exception.status, 409)
        finally:
            with self.service.lock:
                self.service.jobs[run_id]["state"] = "done"


if __name__ == "__main__":
    unittest.main()
