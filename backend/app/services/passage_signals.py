"""Compatibility shim — implementation lives in app.knowledge.signals.passage."""

from app.knowledge.signals.passage import (
    DocKind,
    compute_passage_signals,
    infer_doc_kind,
    signals_from_chunk,
    summarize_passage_readiness,
)

__all__ = [
    "DocKind",
    "compute_passage_signals",
    "infer_doc_kind",
    "signals_from_chunk",
    "summarize_passage_readiness",
]
