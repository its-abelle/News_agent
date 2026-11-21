import json
import unittest
from unittest.mock import Mock, patch

from deluxe.adapters import AdapterError, FallbackModel, GroqModel, QwenModel, live_model


class RecordingHTTP:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def request(self, url, body, headers):
        self.calls.append((url, body, headers))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response, url


def response(value):
    return json.dumps({"choices": [{"message": {"content": json.dumps(value)}}]})


class ModelRoutingTests(unittest.TestCase):
    def test_groq_request_uses_its_key_model_and_json_format(self):
        http = RecordingHTTP(response({"claims": []}))
        with patch.dict("os.environ", {"GROQ_API_KEY": "groq-test"}, clear=True):
            result = GroqModel(http).ask("extract", "Return JSON.", {"source": "source material"})
        url, body, headers = http.calls[0]
        self.assertEqual(result, {"claims": []})
        self.assertEqual(url, "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(body["model"], "openai/gpt-oss-20b")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertFalse(body["stream"])
        self.assertNotIn("enable_thinking", body)
        self.assertEqual(headers["Authorization"], "Bearer groq-test")

    def test_groq_endpoint_and_model_are_configurable(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "test", "GROQ_MODEL": "custom-model",
                                      "GROQ_BASE_URL": "https://example.com/v1/"}, clear=True):
            model = GroqModel()
        self.assertEqual(model.model, "custom-model")
        self.assertEqual(model.base_url, "https://example.com/v1")

    def test_success_does_not_construct_fallback(self):
        primary = Mock()
        primary.ask.return_value = {"pitches": []}
        fallback = Mock(side_effect=AssertionError("Fallback must remain unused"))
        model = FallbackModel(lambda: primary, fallback)
        self.assertEqual(model.ask("pitch", "instructions", {}), {"pitches": []})
        fallback.assert_not_called()

    def test_groq_works_without_qwen_key(self):
        http = RecordingHTTP(response({"pitches": []}))
        with patch.dict("os.environ", {"GROQ_API_KEY": "groq-test"}, clear=True):
            model = live_model()
            model.primary_factory = lambda: GroqModel(http)
            self.assertEqual(model.ask("pitch", "instructions", {}), {"pitches": []})

    def test_http_failure_replays_same_question_and_sources_with_qwen_key(self):
        http = RecordingHTTP(AdapterError("rate limit"), response({"central_supported": False}))
        data = {"approved_question": "Can a Kenyan brand receive payouts?", "sources": [{"text": "Launch"}]}
        with patch.dict("os.environ", {"GROQ_API_KEY": "groq-test", "QWEN_API_KEY": "qwen-test"}, clear=True):
            model = FallbackModel(lambda: GroqModel(http), lambda: QwenModel(http))
            with self.assertWarnsRegex(RuntimeWarning, "trying Qwen fallback"):
                result = model.ask("verify", "Verify JSON.", data)
        self.assertEqual(result, {"central_supported": False})
        self.assertEqual(len(http.calls), 2)
        first, second = http.calls
        self.assertEqual(first[1]["messages"], second[1]["messages"])
        self.assertEqual(first[2]["Authorization"], "Bearer groq-test")
        self.assertEqual(second[2]["Authorization"], "Bearer qwen-test")
        self.assertIn("api.groq.com", first[0])
        self.assertIn("dashscope-intl.aliyuncs.com", second[0])
        self.assertNotIn("enable_thinking", first[1])
        self.assertFalse(second[1]["enable_thinking"])

    def test_malformed_json_triggers_fallback(self):
        for malformed in ("not JSON", response([]), response("not an object"), '{"choices": []}'):
            with self.subTest(malformed=malformed):
                http = RecordingHTTP(malformed, response({"claims": []}))
                with patch.dict("os.environ", {"GROQ_API_KEY": "groq-test", "QWEN_API_KEY": "qwen-test"}, clear=True):
                    model = FallbackModel(lambda: GroqModel(http), lambda: QwenModel(http))
                    with self.assertWarns(RuntimeWarning):
                        self.assertEqual(model.ask("extract", "Return JSON.", {}), {"claims": []})

    def test_missing_groq_key_can_use_qwen(self):
        http = RecordingHTTP(response({"claims": []}))
        with patch.dict("os.environ", {"QWEN_API_KEY": "qwen-test"}, clear=True):
            model = live_model()
            model.fallback_factory = lambda: QwenModel(http)
            with self.assertWarns(RuntimeWarning):
                self.assertEqual(model.ask("extract", "Return JSON.", {}), {"claims": []})
        self.assertEqual(len(http.calls), 1)

    def test_unconfigured_fallback_error_is_explicit(self):
        primary = Mock()
        primary.ask.side_effect = AdapterError("timeout")
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(AdapterError, "Qwen fallback is unavailable.*QWEN_API_KEY"):
                FallbackModel(lambda: primary).ask("draft", "instructions", {})

    def test_both_fail_without_leaking_provider_error_content(self):
        http = RecordingHTTP(AdapterError("groq-secret"), AdapterError("qwen-secret"))
        with patch.dict("os.environ", {"GROQ_API_KEY": "groq-secret", "QWEN_API_KEY": "qwen-secret"}, clear=True):
            model = FallbackModel(lambda: GroqModel(http), lambda: QwenModel(http))
            with self.assertWarns(RuntimeWarning), self.assertRaises(AdapterError) as raised:
                model.ask("draft", "instructions", {})
        self.assertIn("Groq and Qwen both failed", str(raised.exception))
        self.assertNotIn("groq-secret", str(raised.exception))
        self.assertNotIn("qwen-secret", str(raised.exception))
        self.assertEqual(len(http.calls), 2)

    def test_programming_errors_do_not_trigger_fallback(self):
        primary = Mock()
        primary.ask.side_effect = TypeError("implementation bug")
        fallback = Mock()
        with self.assertRaises(TypeError):
            FallbackModel(lambda: primary, fallback).ask("pitch", "instructions", {})
        fallback.assert_not_called()

    def test_each_call_returns_to_groq_first(self):
        primary = Mock()
        primary.ask.side_effect = [AdapterError("outage"), {"from": "groq"}]
        fallback = Mock()
        fallback.ask.return_value = {"from": "qwen"}
        model = FallbackModel(lambda: primary, lambda: fallback)
        with self.assertWarns(RuntimeWarning):
            self.assertEqual(model.ask("pitch", "instructions", {}), {"from": "qwen"})
        self.assertEqual(model.ask("draft", "instructions", {}), {"from": "groq"})
        self.assertEqual(fallback.ask.call_count, 1)

    def test_no_provider_keys_fails_before_discovery(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(AdapterError, "GROQ_API_KEY"):
                live_model()

    def test_bad_primary_configuration_can_fall_back(self):
        http = RecordingHTTP(response({"claims": []}))
        with patch.dict("os.environ", {"GROQ_API_KEY": "groq-test", "GROQ_BASE_URL": "file:///bad",
                                      "QWEN_API_KEY": "qwen-test"}, clear=True):
            model = FallbackModel(GroqModel, lambda: QwenModel(http))
            with self.assertWarns(RuntimeWarning):
                self.assertEqual(model.ask("extract", "instructions", {}), {"claims": []})

    def test_both_provider_statuses_are_visible_without_response_body(self):
        http = RecordingHTTP(AdapterError("primary-secret", status=429), AdapterError("fallback-secret", status=401))
        with patch.dict("os.environ", {"GROQ_API_KEY": "groq-test", "QWEN_API_KEY": "qwen-test"}, clear=True):
            model = FallbackModel(lambda: GroqModel(http), lambda: QwenModel(http))
            with self.assertWarnsRegex(RuntimeWarning, "HTTP 429"), self.assertRaises(AdapterError) as raised:
                model.ask("extract", "Extract JSON.", {})
        message = str(raised.exception)
        self.assertIn("Groq: HTTP 429", message)
        self.assertIn("Qwen: HTTP 401", message)
        self.assertNotIn("primary-secret", message)
        self.assertNotIn("fallback-secret", message)

    def test_http_error_is_classified_without_reading_body(self):
        import urllib.error
        from deluxe.adapters import HTTP
        body = Mock()
        http = HTTP()
        http.opener = Mock()
        http.opener.open.side_effect = urllib.error.HTTPError(
            "https://api.groq.com/openai/v1/chat/completions", 413, "Too large", {}, body)
        with patch("deluxe.adapters.public_url"), self.assertRaises(AdapterError) as raised:
            http.request("https://api.groq.com/openai/v1/chat/completions", {})
        self.assertEqual(raised.exception.status, 413)
        self.assertIn("request too large", raised.exception.diagnostic())
        body.read.assert_not_called()
        body.close.assert_called_once()

    def test_truncated_response_is_distinguished_from_bad_json(self):
        http = RecordingHTTP(json.dumps({"choices": [{"finish_reason": "length", "message": {"content": "{"}}]}))
        with patch.dict("os.environ", {"GROQ_API_KEY": "groq-test"}, clear=True):
            with self.assertRaises(AdapterError) as raised:
                GroqModel(http).ask("extract", "Return JSON.", {})
        self.assertEqual(raised.exception.category, "truncated")
        self.assertIn("output token limit", raised.exception.diagnostic())


if __name__ == "__main__":
    unittest.main()
