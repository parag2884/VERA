"""Build PlayReady golden cases from local normalised PDFs (+ optional live KB titles).

Usage (vera-api):
  python /app/scripts/_gen_playready_goldens.py --pdf-dir /app/data/playready_pdfs
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

from app.stores.sql import WorkspaceStore

try:
    from pypdf import PdfReader
except Exception:  # noqa: BLE001
    PdfReader = None  # type: ignore

OUT_SUITE = Path("/app/data/playready_v2_from_pdfs.json")
OUT_INV = Path("/app/data/playready_pdf_inventory.json")

WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-/]{2,}")
BAD = {
    "microsoft",
    "playready",
    "page",
    "table",
    "figure",
    "contents",
    "copyright",
    "reserved",
    "document",
    "version",
    "http",
    "https",
    "www",
}


def extract_pdf_text(path: Path, max_chars: int = 12000) -> str:
    if PdfReader is None:
        raise RuntimeError("pypdf not available")
    reader = PdfReader(str(path))
    parts: list[str] = []
    total = 0
    for page in reader.pages:
        try:
            t = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            t = ""
        if not t.strip():
            continue
        parts.append(t)
        total += len(t)
        if total >= max_chars:
            break
    return re.sub(r"[ \t]+", " ", "\n".join(parts))


def category_for(name: str) -> str:
    n = name.lower()
    if "sl3000" in n or "sl2000" in n:
        return "security_level"
    if "compliance" in n:
        return "compliance"
    if "robustness" in n:
        return "robustness"
    if "livetv" in n or "live_tv" in n or "live tv" in n:
        return "live_tv"
    if "whatsnew" in n or "whats_new" in n:
        return "whats_new"
    if "server" in n:
        return "server"
    if "client" in n or "dev_client" in n:
        return "client"
    if "license" in n or "ipla" in n or "agreement" in n:
        return "licensing"
    if "certificate" in n or "ev_" in n:
        return "certificates"
    if "whitepaper" in n or "protection" in n:
        return "protection"
    if "documentation" in n:
        return "documentation"
    if "overview" in n or "distribution" in n or "development" in n:
        return "overview"
    return "general"


def _clean_phrase(p: str) -> str:
    p = re.sub(r"\s+", " ", p).strip().lower()
    p = p.replace("microsoft corporation", "").strip(" -|")
    return p


def pick_must_any(text: str, filename: str) -> list[str]:
    candidates: list[str] = []
    low = text.lower()
    for tok in ("SL3000", "SL2000", "SL1500", "HDCP", "Secure Stop", "OPL", "PlayReady"):
        if tok.lower() in low:
            candidates.append(tok.lower())
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b", text[:2500]):
        phrase = _clean_phrase(m.group(1))
        if (
            not phrase
            or phrase in BAD
            or len(phrase) < 8
            or "microsoft" in phrase
            or "corporation" in phrase
        ):
            continue
        candidates.append(phrase)
    for w in WORD_RE.findall(filename.replace("_", " ").replace(".pdf", "")):
        wl = w.lower()
        if wl not in BAD and len(wl) > 3:
            candidates.append(wl)
    out: list[str] = []
    seen = set()
    for c in candidates:
        c = _clean_phrase(c)
        if not c or c in seen or c in BAD or "\n" in c:
            continue
        seen.add(c)
        out.append(c)
        if len(out) >= 4:
            break
    return out or ["playready"]


def draft_questions(filename: str, text: str, cat: str) -> list[tuple[str, str, list[str]]]:
    """Return list of (question, expected_answer, must_any overrides or [])."""
    stem = filename.replace(".pdf", "").replace("_", " ")
    low = text.lower()
    qs: list[tuple[str, str, list[str]]] = []

    # Always: what is this document about
    qs.append(
        (
            f"According to the PlayReady document “{stem}”, what topics does it cover?",
            f"Topics grounded in {filename}.",
            [],
        )
    )

    # Keep SL compare primarily on the playbook (avoid duplicating across every PDF that mentions SL*)
    if "sl3000_playbook" in filename.lower() or cat == "security_level":
        qs.append(
            (
                "What is the difference between PlayReady SL2000 and SL3000?",
                "Differences as stated in the SL3000 playbook.",
                ["sl2000", "sl3000"],
            )
        )
        qs.append(
            (
                "What does PlayReady SL3000 require or enable according to the playbook?",
                "SL3000 requirements / capabilities from the playbook.",
                ["sl3000"],
            )
        )
    elif ("sl3000" in low or "sl2000" in low) and cat in {"documentation", "whats_new", "overview"}:
        # one lighter mention Q only
        qs.append(
            (
                f"Does “{stem}” discuss PlayReady security levels (SL2000 / SL3000)?",
                "Yes — security levels are mentioned in this document.",
                ["sl2000", "sl3000"] if ("sl2000" in low and "sl3000" in low) else ["sl3000"] if "sl3000" in low else ["sl2000"],
            )
        )

    if "hdcp" in low:
        qs.append(
            (
                f"What does {stem} say about HDCP?",
                "HDCP-related requirements or guidance from the document.",
                ["hdcp"],
            )
        )
    if "output protection" in low or re.search(r"\bopl\b", low):
        qs.append(
            (
                "What are PlayReady output protection levels (OPL)?",
                "OPL / output protection wording from compliance docs.",
                ["output protection", "opl", "hdcp"],
            )
        )
    if "secure stop" in low:
        qs.append(
            (
                "What is PlayReady Secure Stop?",
                "Secure Stop definition from the documentation.",
                ["secure stop"],
            )
        )
    if "robust" in low:
        qs.append(
            (
                "What are the robustness rules for PlayReady products?",
                "Robustness rules from the robustness / compliance PDF.",
                ["robust"],
            )
        )
    if cat == "live_tv" or "live tv" in low or "livetv" in filename.lower():
        qs.append(
            (
                "How does PlayReady protect Live TV content?",
                "Live TV protection guidance from the LiveTV docs.",
                ["live"],
            )
        )
    if cat == "whats_new":
        ver = re.search(r"v(\d+\.\d+)", filename, re.I)
        v = ver.group(1) if ver else "this release"
        qs.append(
            (
                f"What is new in PlayReady {v}?",
                f"Release notes from {filename}.",
                [v] if ver else ["playready"],
            )
        )
    if cat == "certificates" or "certificate" in low:
        qs.append(
            (
                "What are the EV certificate instructions for PlayReady?",
                "Certificate enrollment / EV instructions from the PDF.",
                ["certificate"],
            )
        )
    if cat == "licensing" or "license" in low or "agreement" in low:
        qs.append(
            (
                f"What licensing or agreement terms are described in “{stem}”?",
                f"Licensing/agreement points from {filename}.",
                ["license", "agreement", "playready"],
            )
        )
    if cat == "server" or "server" in low:
        qs.append(
            (
                "What does the PlayReady Server documentation cover?",
                "Server overview / agreement points from the server PDFs.",
                ["server"],
            )
        )
    if cat in {"client", "overview", "documentation", "protection", "general"}:
        # second generic cross-check from a distinctive phrase in body
        m = re.search(r"([A-Z][a-z]+(?:\s+[a-z]+){3,12}\.)", text[:2000])
        if m:
            sentence = m.group(1).strip()
            qs.append(
                (
                    f"What does “{stem}” say about: {sentence[:90]}",
                    sentence[:220],
                    [],
                )
            )

    # Dedup by question text
    seen = set()
    uniq = []
    for q, a, must in qs:
        if q in seen:
            continue
        seen.add(q)
        uniq.append((q, a, must))
    return uniq[:4]  # cap per PDF


async def kb_titles() -> list[str]:
    try:
        async with WorkspaceStore() as store:
            agents = await store.list_agents()
            pr = next(
                (a for a in agents if (a.get("name") or "").strip().lower() in {"playready", "playready assistant"}
                 or "playready" in (a.get("name") or "").lower()),
                None,
            )
            if not pr:
                return []
            docs = await store.list_canonical_documents(pr["workspace_id"])
            return [d.get("title") or "" for d in docs]
    except Exception:  # noqa: BLE001
        return []


def match_kb_title(filename: str, titles: list[str]) -> str:
    stem = filename.lower().replace(".pdf", "")
    for t in titles:
        tl = t.lower()
        if stem in tl or tl.replace(" ", "_") in stem or filename.lower() in tl:
            return t
    # fuzzy token overlap
    tokens = [x for x in re.split(r"[_\s.-]+", stem) if len(x) > 3]
    best, score = filename, 0
    for t in titles:
        tl = t.lower()
        sc = sum(1 for tok in tokens if tok in tl)
        if sc > score:
            best, score = t, sc
    return best if score >= 2 else filename


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", required=True)
    args = ap.parse_args()
    pdf_dir = Path(args.pdf_dir)
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs in {pdf_dir}")

    titles = asyncio.run(kb_titles())
    inventory = []
    cases = []
    n = 0
    for pdf in pdfs:
        try:
            text = extract_pdf_text(pdf)
        except Exception as exc:  # noqa: BLE001
            inventory.append({"file": pdf.name, "error": str(exc)[:200], "chars": 0})
            continue
        cat = category_for(pdf.name)
        src_doc = match_kb_title(pdf.name, titles)
        inventory.append(
            {
                "file": pdf.name,
                "category": cat,
                "chars": len(text),
                "kb_title": src_doc,
                "snippet": re.sub(r"\s+", " ", text)[:280],
            }
        )
        for q, expected, must_override in draft_questions(pdf.name, text, cat):
            n += 1
            must = must_override or pick_must_any(text, pdf.name)
            cases.append(
                {
                    "id": f"PR{n:03d}",
                    "category": cat,
                    "question": q,
                    "expect_decision": "answer",
                    "expected_answer": expected,
                    "must_any": must,
                    "forbid_any": [],
                    "citation_any": [],
                    "source_document": src_doc,
                    "source_file": pdf.name,
                    "kb_quote_hint": re.sub(r"\s+", " ", text)[:200],
                    "map_check": f"PDF — {pdf.name}",
                }
            )

    # Refuse traps
    for q, expected in [
        (
            "What will Microsoft PlayReady stock price be next quarter?",
            "Refuse — finance / not in product PDFs.",
        ),
        (
            "What is the weather in Redmond tomorrow?",
            "Refuse — out of knowledge base.",
        ),
        (
            "What was PlayReady's exact revenue on 3 March 2011?",
            "Refuse — invented financial metric.",
        ),
    ]:
        n += 1
        cases.append(
            {
                "id": f"PR{n:03d}",
                "category": "refuse",
                "question": q,
                "expect_decision": "refuse",
                "expected_answer": expected,
                "must_any": [],
                "forbid_any": [],
                "citation_any": [],
                "source_document": None,
                "source_file": None,
                "kb_quote_hint": None,
                "map_check": "Refuse — OOD",
            }
        )

    suite = {
        "suite_id": "playready_docs_v2",
        "source_kind": "documents",
        "agent_name": "PlayReady Assistant",
        "kb_notes": [
            "Drafted from Prod Normalised PDFs; cross-verify must_any / kb_quote_hint inside source_file.",
            "source_document is best-match KB title when PlayReady agent already has the file uploaded.",
            "Re-run generator after adding/replacing PDFs.",
        ],
        "required_documents": [p.name for p in pdfs],
        "pdf_count": len(pdfs),
        "kb_title_count": len(titles),
        "cases": cases,
    }
    OUT_SUITE.write_text(json.dumps(suite, indent=2, ensure_ascii=False), encoding="utf-8")
    OUT_INV.write_text(json.dumps({"pdfs": inventory, "kb_titles": titles}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "pdfs": len(pdfs),
                "extracted": sum(1 for i in inventory if i.get("chars", 0) > 0),
                "cases": len(cases),
                "kb_titles": len(titles),
                "wrote": str(OUT_SUITE),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
