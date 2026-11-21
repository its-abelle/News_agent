import unittest
from unittest.mock import patch

from deluxe.adapters import AdapterError
from deluxe.context import context_budget, source_context


def source(source_id, text):
    return {"id": source_id, "url": f"https://example.com/{source_id}",
            "publisher": "Example", "title": "Launch", "text": text}


class ContextTests(unittest.TestCase):
    def test_small_sources_are_preserved(self):
        sources = [source("S1", "Vendor says it generates editable storefronts.")]
        result = source_context(sources, "What does it generate?", limit=2000)
        self.assertEqual(result[0]["text"], sources[0]["text"])
        self.assertFalse(result[0]["text_excerpted"])

    def test_large_source_packet_is_bounded_without_mutating_saved_pages(self):
        sources = [source(f"S{i}", f"Page {i}. " + "Source reporting. " * 2400) for i in range(11)]
        original = [s["text"] for s in sources]
        result = source_context(sources, "What is relevant to Kenyan SMEs?", limit=12000)
        self.assertLessEqual(sum(len(s["text"]) for s in result), 12000)
        self.assertEqual([s["id"] for s in result], [s["id"] for s in sources])
        self.assertTrue(all(s["text_excerpted"] for s in result))
        self.assertEqual([s["text"] for s in sources], original)

    def test_question_matching_text_and_closing_qualifiers_retained(self):
        text = "Launch announcement. " + "Unrelated detail. " * 2000
        text += " Kenyan merchant payouts require eligibility checks. "
        text += "Other details. " * 2000 + "Country restrictions still apply."
        result = source_context([source("S1", text)], "What are Kenyan merchant payouts?", limit=3000)[0]["text"]
        self.assertIn("Kenyan merchant payouts", result)
        self.assertIn("Country restrictions still apply.", result)
        self.assertIn("excerpt boundary", result)
        self.assertTrue(all(part in text for part in result.split("\n[... excerpt boundary ...]\n")))

    def test_small_sources_donate_budget_to_larger_sources(self):
        sources = [source("S1", "Small source."), source("S2", "Large source. " * 2000)]
        result = source_context(sources, "Large source", limit=2000)
        self.assertEqual(result[0]["text"], "Small source.")
        self.assertGreater(len(result[1]["text"]), 1000)
        self.assertLessEqual(sum(len(s["text"]) for s in result), 2000)

    def test_context_budget_validation(self):
        for value in ("not-a-number", "0", "48001"):
            with self.subTest(value=value), patch.dict("os.environ", {"DELUXE_SOURCE_CONTEXT_CHARS": value}):
                with self.assertRaisesRegex(AdapterError, "DELUXE_SOURCE_CONTEXT_CHARS"):
                    context_budget()

    def test_empty_sources(self):
        self.assertEqual(source_context([], "Question"), [])
