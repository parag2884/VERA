"""Passage / text signals shared by ingest and Ask (no connector imports)."""

from app.knowledge.signals.passage import (
    compute_passage_signals,
    signals_from_chunk,
    summarize_passage_readiness,
)
from app.knowledge.signals.text_terms import boilerplate_penalty, person_title_names

__all__ = [
    "boilerplate_penalty",
    "person_title_names",
    "compute_passage_signals",
    "signals_from_chunk",
    "summarize_passage_readiness",
]
