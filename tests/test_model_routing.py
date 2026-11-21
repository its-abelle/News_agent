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


if __name__ == "__main__":
    unittest.main()
