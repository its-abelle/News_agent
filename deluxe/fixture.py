"""Deterministic, fictional adapters implementing the same interfaces as live mode."""
from datetime import datetime, timedelta

from .adapters import AdapterError

URL = "https://loomcart.example/news/ai-storefront"
PASSAGE = "LoomCart says its new AI builder generates a storefront draft from a product description and uploaded product photographs."
LIMIT = "The generated draft includes editable product descriptions and a preview that the merchant can revise before publishing."
QUESTION = "What can an AI-generated storefront draft do for a Kenyan clothing brand's first product page?"


class FixtureDiscovery:
    def discover(self, now):
        date = (datetime.fromisoformat(now) - timedelta(days=1)).date().isoformat()
        common = {"id": "", "published_at": date, "event_date": date,
                  "summary": f"SAMPLE MATERIAL. On {date}, fictional LoomCart launched its AI storefront builder. {PASSAGE} {LIMIT}",
                  "region": "International"}
        return [common | {"headline": "LoomCart launches AI storefront drafts", "publisher": "LoomCart (fictional vendor)", "url": URL},
                common | {"headline": "AI storefront drafts arrive from LoomCart", "publisher": "Sample Wire (syndicated)",
                          "url": "https://wire.example/loomcart-launch"},
                common | {"headline": "Remembering the old AI logo launch", "publisher": "Sample Archive",
                          "url": "https://archive.example/old-logo", "event_date": "2020-01-01",
                          "summary": "SAMPLE MATERIAL. This is a retrospective about a 2020 logo generator launch. No new development."}], []


class FixturePages:
    def fetch(self, url, publisher="", title=""):
        if url not in {URL, "https://wire.example/loomcart-launch"}:
            raise AdapterError(f"No fictional page for {url}")
        return {"id": "", "url": URL if url == URL else url,
                "publisher": publisher or "LoomCart (fictional vendor)", "title": title,
                "text": f"SAMPLE MATERIAL — FICTIONAL. {PASSAGE} {LIMIT}"}


class FixtureSearch:
    def search(self, query):
        # No invented corroboration or payments page, including for a payout query.
        return [{"url": URL, "title": "LoomCart AI builder announcement (fictional)",
                 "publisher": "LoomCart (fictional vendor)"}]


class FixtureModel:
    def ask(self, task, instructions, data):
        if task == "pitch":
            candidates = [c for c in data["candidates"] if "loomcart" in c["url"] or "ai-storefront" in c["url"]]
            if not candidates:
                return {"pitches": []}
            return {"pitches": [{"candidate_ids": [c["id"] for c in candidates],
                "event_key": "loomcart-ai-storefront-launch-" + candidates[0]["event_date"],
                "headline": "What LoomCart's AI storefront draft actually promises a clothing brand",
                "primary_reader": "Kenyan clothing brand owner", "what_changed": PASSAGE,
                "why_kenya": "A clothing brand preparing product pages can evaluate the draft's editing workflow before committing staff time to a storefront trial.",
                "question": QUESTION, "timely_reason": "The fictional builder was announced yesterday in this sample run.",
                "strongest_source": URL, "reporting_gap": "Kenyan merchant eligibility and payout routes are undocumented.",
                "ranking_reason": "Ranked first because the vendor describes a concrete new drafting workflow, while payments remain unverified.",
                "event_date": candidates[0]["event_date"], "fresh_development": True,
                "freshness_passage": candidates[0]["summary"], "previous_event_key": None}]}
        if task == "plan_search":
            if data["searches_used"]:
                return {"query": None}
            return {"query": "LoomCart Kenyan merchant payouts eligibility official documentation"
                    if self.payments(data) else "LoomCart AI builder original announcement independent hands-on review"}
        if task == "extract":
            source = next((s for s in data["sources"] if s["url"] == URL), None)
            return {"claims": [] if source is None else [
                {"text": PASSAGE, "source_id": source["id"], "passage": PASSAGE,
                 "attribution": "LoomCart says", "kind": "vendor_assertion", "geographic_scope": "Unspecified"},
                {"text": "According to LoomCart, the generated draft includes editable product descriptions and a preview for revision.",
                 "source_id": source["id"], "passage": LIMIT, "attribution": "According to LoomCart",
                 "kind": "vendor_assertion", "geographic_scope": "Unspecified"}],
                "reporting_tasks": self.tasks(data)}
        if task == "draft":
            claims = data["evidence"]
            return {"title": "LoomCart promises a first storefront draft for clothing brands",
                    "blocks": [{"text": c["text"], "claim_ids": [c["id"]]} for c in claims]
                    + [{"text": "For a clothing brand preparing its first product page, use a draft as a starting point: check garment names, sizes and descriptions against your own catalogue before publishing.", "claim_ids": []}]}
        if task == "verify":
            allowed = data["approved_question"] == QUESTION or data["approved_question"] in {
                "What does LoomCart generate?", "What can this storefront builder generate?"}
            return {"central_supported": allowed, "supported_claim_ids": [c["id"] for c in data["evidence"]],
                    "safe_block_indices": list(range(len(data["draft"].get("blocks", [])))),
                    "title_supported": True,
                    "issues": [] if allowed else ["The supplied source does not establish the approved question's central premise."],
                    "reporting_tasks": self.tasks(data) if not allowed else [
                        "Hands-on test: generate a clothing product page and check editability, factual accuracy and image handling.",
                        "Seek an independent review; the current claims are attributed vendor assertions."]}
        raise ValueError(f"Unknown fixture model task: {task}")

    @staticmethod
    def payments(data):
        return any(w in data["approved_question"].lower() for w in ("payment", "payout", "m-pesa"))

    @staticmethod
    def tasks(data):
        if FixtureModel.payments(data):
            return ["Obtain official merchant-country eligibility and payout documentation explicitly covering Kenya.",
                    "Ask LoomCart which payment processors, settlement currencies, fees and Kenyan bank or M-Pesa payout routes are supported; request written confirmation.",
                    "With an eligible Kenyan merchant, test checkout and settlement and record the result before claiming payment support."]
        return ["Run a hands-on product-page generation test; no test results are available in these sources."]
