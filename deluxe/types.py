from typing import Literal, TypedDict


class Candidate(TypedDict):
    id: str
    headline: str
    publisher: str
    url: str
    published_at: str | None
    event_date: str | None
    summary: str
    region: str


class Source(TypedDict):
    id: str
    url: str
    publisher: str
    title: str
    text: str


class Claim(TypedDict):
    id: str
    text: str
    source_id: str
    url: str
    publisher: str
    passage: str
    attribution: str
    kind: Literal["vendor_assertion", "independent", "documented"]
    geographic_scope: str


class Pitch(TypedDict):
    id: str
    event_key: str
    candidate_ids: list[str]
    headline: str
    primary_reader: str
    what_changed: str
    why_kenya: str
    question: str
    timely_reason: str
    strongest_source: str
    reporting_gap: str
    ranking_reason: str
    event_date: str | None


class EditorialState(TypedDict, total=False):
    run_id: str
    mode: str
    now: str
    config: dict
    candidates: list[Candidate]
    pitches: list[Pitch]
    editor_decision: dict
    approved_question: str
    selected_pitch: Pitch
    evidence: list[Claim]
    sources: list[Source]
    research_budget: int
    searches_used: int
    research_done: bool
    search_log: list[dict]
    reporting_tasks: list[str]
    draft: dict
    verification: dict
    errors: list[str]
    status: str
    outputs: list[str]
