"""Build Thoughtworks golden cases from pages actually in the KB.

Goal: know what's happening page-by-page —
  • every KB URL gets ≥1 cross-checkable Q&A
  • core / services / leaders / about get denser multi-fact questions
  • news stays 1× per page (KB is news-heavy) so it doesn't drown the suite
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from app.stores.sql import WorkspaceStore

OUT = Path("/app/data/thoughtworks_v4_from_kb.json")
INVENTORY = Path("/app/data/thoughtworks_kb_pages.json")
COVERAGE = Path("/app/data/thoughtworks_coverage.json")

SOURCE_RE = re.compile(r"Source:\s*(https://www\.thoughtworks\.com[^\s|]+)", re.I)
H1_RE = re.compile(r"^#\s+(.+?)(?:\s*\|\s*Thoughtworks)?\s*$", re.M)
# "Mike Sutcliff" ... "Chief Executive Officer" style
PERSON_TITLE_RE = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s*"
    r"(?:[–—\-|:,]|\bis\b|\bas\b){1,3}\s*"
    r"((?:Chief|Global|Head|Managing|Executive|Senior|Vice|Director|President|Partner)[^.\n]{3,60})",
    re.I,
)
SENT_RE = re.compile(r"([A-Z][^.!?\n]{40,180}[.!?])")

_BAD_MUST = {
    "thoughtworks",
    "thoughtworks source",
    "source",
    "news archive",
    "what we",
    "about us",
    "about back",
    "about back our",
    "back close",
    "insights back",
    "what we do",
    "global technology",
    "nasdaq",
    "cookie",
    "privacy",
}


def title_to_url(title: str) -> str:
    t = title.replace(".md", "")
    if t.startswith("www.thoughtworks.com"):
        path = t[len("www.thoughtworks.com") :].replace("_", "/")
        if not path.startswith("/"):
            path = "/" + path
        return "https://www.thoughtworks.com" + (path.rstrip("/") or "/")
    return ""


def path_of(url: str) -> str:
    return re.sub(r"^https://www\.thoughtworks\.com", "", url).rstrip("/") or "/"


def section(url: str) -> str:
    p = path_of(url)
    parts = [x for x in p.split("/") if x]
    if not parts:
        return "home"
    if parts[0] == "about-us":
        if len(parts) > 1 and parts[1] == "news":
            return "news"
        if len(parts) > 1 and parts[1] == "leaders":
            return "people"
        if len(parts) > 1 and parts[1] == "partnerships":
            return "partnerships"
        if len(parts) > 1 and "diversity" in parts[1]:
            return "dei"
        return "about"
    if parts[0] == "what-we-do":
        return "services"
    if parts[0] in {"insights", "radar", "careers"}:
        return parts[0]
    if re.match(r"^(en-gb|de-de|es-|pt-br|zh-cn)", parts[0]):
        return "locale"
    return parts[0]


def clean_text(text: str) -> str:
    t = SOURCE_RE.sub(" ", text)
    t = re.sub(
        r"\b(News archive|Back|Close|Insights|What we do|About us|Source:|Cookie|Accept all)\b",
        " ",
        t,
        flags=re.I,
    )
    return re.sub(r"\s+", " ", t).strip()


def pick_must_any(*texts: str) -> list[str]:
    blob = clean_text(" ".join(texts))
    candidates: list[str] = []
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b", blob[:1600]):
        phrase = m.group(1).strip().lower()
        if phrase in _BAD_MUST or len(phrase) < 8:
            continue
        candidates.append(phrase)
    for m in re.finditer(r"\b([A-Z]{3,}(?:/\w+)?)\b", blob[:900]):
        tok = m.group(1).lower()
        if tok not in _BAD_MUST and tok not in {"ceo", "cto", "cfo", "pdf", "url", "api", "html", "http"}:
            candidates.append(tok)
    out: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        if c in seen or c in _BAD_MUST:
            continue
        seen.add(c)
        out.append(c)
        if len(out) >= 4:
            break
    return out or ["thoughtworks"]


def extract_people(text: str) -> list[tuple[str, str]]:
    people: list[tuple[str, str]] = []
    seen: set[str] = set()
    # Common explicit patterns in leaders extracts
    for name, title in [
        ("Mike Sutcliff", "Chief Executive Officer"),
        ("Erin Cummins", "Chief Financial Officer"),
        ("Rachel Laycock", "Chief Technology Officer"),
        ("Rebecca Parsons", "Chief Technology Officer"),
    ]:
        if name.lower() in text.lower() and any(
            t in text.lower() for t in (title.lower(), title.split()[-1].lower(), "chief")
        ):
            key = name.lower()
            if key not in seen:
                seen.add(key)
                people.append((name, title))
    for m in PERSON_TITLE_RE.finditer(text):
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        title = re.sub(r"\s+", " ", m.group(2)).strip(" -–,|")
        if name.lower() in _BAD_MUST or len(name) < 5:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        people.append((name, title[:80]))
        if len(people) >= 10:
            break
    return people


def extract_sentences(text: str, limit: int = 6) -> list[str]:
    cleaned = clean_text(text)
    out: list[str] = []
    for m in SENT_RE.finditer(cleaned):
        s = m.group(1).strip()
        sl = s.lower()
        if any(b in sl for b in ("cookie", "subscribe", "sign up", "privacy policy", "all rights")):
            continue
        if "thoughtworks" not in sl and len(s) < 50:
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


def questions_for_page(url: str, h1: str, text: str) -> list[dict]:
    """Dense, fact-oriented questions for one page."""
    p = path_of(url)
    sec = section(url)
    h1_clean = re.sub(r"\s*\|\s*Thoughtworks\s*$", "", h1 or "").strip() or p
    h1_clean = h1_clean.replace("\u200b", "").strip()
    low = text.lower()
    qs: list[dict] = []

    def add(question: str, expected: str, category: str, must: list[str] | None = None) -> None:
        qs.append(
            {
                "question": question,
                "expected_answer": expected,
                "category": category,
                "must_any": must or pick_must_any(expected, h1_clean, text[:400]),
            }
        )

    # --- Leaders: dense people coverage ---
    if p.endswith("/leaders") or "/about-us/leaders" == p:
        people = extract_people(text)
        if not people and "sutcliff" in low:
            people = [("Mike Sutcliff", "Chief Executive Officer")]
        for name, title in people:
            add(
                f"Who is {title} at Thoughtworks?"
                if "chief" in title.lower() or "officer" in title.lower() or "head" in title.lower()
                else f"What role does {name} hold at Thoughtworks?",
                f"{name} — {title} (leaders page).",
                "people",
                [name.lower(), name.split()[-1].lower()],
            )
        add(
            "Who are the executive leaders of Thoughtworks?",
            "Leaders page lists the executive / global management team.",
            "people",
            ["leader", "executive"] if "executive" in low else pick_must_any(text, h1_clean),
        )
        return qs[:8]

    # --- Services: overview + details + sentence facts ---
    if p.startswith("/what-we-do"):
        topic = h1_clean or p.split("/")[-1].replace("-", " ")
        add(
            f"What does Thoughtworks offer for {topic}?",
            f"Service page describes {topic} offerings.",
            "services",
            pick_must_any(topic, text),
        )
        add(
            f"How does Thoughtworks describe {topic} on its website?",
            f"Description from the {topic} service page.",
            "services",
            pick_must_any(text, topic),
        )
        for sent in extract_sentences(text, limit=3):
            hint = sent[:100]
            add(
                f"According to Thoughtworks' {topic} page, is this accurate: “{hint}…”?",
                sent,
                "services",
                pick_must_any(sent),
            )
        if p == "/what-we-do":
            add(
                "What service areas does Thoughtworks list under What we do?",
                "Hub page lists major service offerings.",
                "services",
                pick_must_any(text, "what we do"),
            )
        return qs[:5]

    # --- About hubs ---
    if sec in {"about", "dei", "partnerships"} or p in {
        "/about-us",
        "/about-us/our-purpose",
        "/about-us/history",
        "/about-us/social-change",
        "/about-us/diversity-and-inclusion",
        "/about-us/partnerships",
    }:
        add(
            f"According to Thoughtworks' page “{h1_clean[:90]}”, what is it about?",
            f"Page summarizes: {h1_clean[:140]}.",
            sec if sec != "about" else "about",
            pick_must_any(h1_clean, text),
        )
        if "purpose" in p:
            add(
                "What is Thoughtworks' purpose according to its website?",
                "Purpose page states company purpose / mission framing.",
                "about",
                pick_must_any(text, "purpose"),
            )
        if "history" in p:
            add(
                "What milestones does Thoughtworks share in its history?",
                "History page covers company background / milestones.",
                "about",
                pick_must_any(text, "history"),
            )
        if "social-change" in p:
            add(
                "How does Thoughtworks describe its social change work?",
                "Social change page describes impact / community initiatives.",
                "about",
                pick_must_any(text, "social"),
            )
        if "partnerships" in p:
            for partner in ("AWS", "Amazon", "Google", "Microsoft", "Databricks", "Nvidia", "Snowflake"):
                if partner.lower() in low:
                    add(
                        f"Is Thoughtworks a partner with {partner}?",
                        f"Partnerships materials mention {partner}.",
                        "partnerships",
                        [partner.lower(), "partner"],
                    )
            add(
                f"What partnerships does Thoughtworks highlight on “{h1_clean[:80]}”?",
                "Partnership details from the partnerships page.",
                "partnerships",
                pick_must_any(text, "partner"),
            )
        if "diversity" in p or "inclusion" in p:
            add(
                f"What does Thoughtworks say about {h1_clean[:80]}?",
                f"DEI page content on {h1_clean[:100]}.",
                "dei",
                pick_must_any(text, h1_clean),
            )
        for sent in extract_sentences(text, limit=2):
            add(
                f"What does Thoughtworks state here: “{sent[:100]}…”?",
                sent,
                sec if sec in {"dei", "partnerships"} else "about",
                pick_must_any(sent),
            )
        return qs[:6]

    if "radar" in p:
        add(
            "What is the Thoughtworks Technology Radar?",
            "Technology Radar is Thoughtworks' opinionated guide to technology trends/tools.",
            "radar",
            ["radar", "technology"],
        )
        for sent in extract_sentences(text, limit=2):
            add(
                f"According to the Technology Radar page: “{sent[:100]}…” — what does it say?",
                sent,
                "radar",
                pick_must_any(sent),
            )
        return qs[:4]

    if "careers" in p:
        add(
            "What does Thoughtworks say about careers / working there?",
            "Careers page describes working at Thoughtworks.",
            "careers",
            pick_must_any(text, "career"),
        )
        for sent in extract_sentences(text, limit=2):
            add(
                f"What careers message appears on the site: “{sent[:100]}…”?",
                sent,
                "careers",
                pick_must_any(sent),
            )
        return qs[:3]

    if sec == "news":
        add(
            f"What is the Thoughtworks news item titled “{h1_clean[:90]}” about?",
            f"Summary grounded in the press page: {h1_clean[:120]}.",
            "news",
            pick_must_any(h1_clean, text),
        )
        return qs[:1]

    if p.startswith("/insights") or "looking-glass" in p:
        add(
            f"What insights does Thoughtworks publish under “{h1_clean[:80]}”?",
            f"Insights content from {h1_clean[:100]}.",
            "insights",
            pick_must_any(h1_clean, text),
        )
        if "looking-glass" in p or "looking glass" in low:
            add(
                "What is Thoughtworks Looking Glass?",
                "Looking Glass insights / trends publication.",
                "insights",
                ["looking glass", "looking-glass"] if "looking" in low else pick_must_any(text),
            )
        return qs[:2]

    # default: 1 overview (+ 1 sentence if meaty non-locale page)
    add(
        f"According to Thoughtworks' website page “{h1_clean[:90]}”, what is it about?",
        f"Page summarizes: {h1_clean[:140]}.",
        sec,
        pick_must_any(h1_clean, text),
    )
    if sec not in {"locale", "news"} and len(text) > 400:
        for sent in extract_sentences(text, limit=1):
            add(
                f"What key point appears on “{h1_clean[:70]}”: “{sent[:90]}…”?",
                sent,
                sec,
                pick_must_any(sent),
            )
    return qs[:2]


async def main() -> None:
    async with WorkspaceStore() as store:
        agents = await store.list_agents()
        tw = next((a for a in agents if "thoughtworks" in (a.get("name") or "").lower()), None)
        if not tw:
            raise SystemExit("Thoughtworks agent not found")
        ws = tw["workspace_id"]
        docs = await store.list_canonical_documents(ws)
        chunks = await store.list_chunks(ws)

    by_doc: dict[str, list[str]] = defaultdict(list)
    for ch in chunks:
        did = ch["canonical_document_id"]
        # More text for dense pages
        limit = 24 if any(
            k in ((ch.get("text") or "")[:120].lower())
            for k in ("leaders", "what we do", "partnership")
        ) else 12
        if len(by_doc[did]) < limit:
            by_doc[did].append(ch.get("text") or "")

    # Prefer deeper text for leaders/services by title
    pages = []
    for d in docs:
        title = d.get("title") or ""
        texts = by_doc.get(d["id"]) or []
        # If leaders/service title, pull more chunks already stored
        text = "\n".join(texts)
        m = SOURCE_RE.search(text) or SOURCE_RE.search(title)
        url = m.group(1).rstrip(").,]") if m else title_to_url(title)
        if not url.startswith("http"):
            continue
        h1m = H1_RE.search(text)
        h1 = (h1m.group(1).strip() if h1m else title.replace(".md", "").replace("_", " "))[:160]
        pages.append({"url": url, "title": title, "h1": h1, "text": text, "doc_id": d["id"]})

    uniq: dict[str, dict] = {}
    for p in pages:
        # keep longest text for duplicates
        prev = uniq.get(p["url"])
        if not prev or len(p["text"]) > len(prev["text"]):
            uniq[p["url"]] = p
    pages = sorted(uniq.values(), key=lambda x: x["url"])

    # Enrich leaders/services with ALL chunks for those docs
    async with WorkspaceStore() as store:
        all_chunks = await store.list_chunks(ws)
    full_by_doc: dict[str, list[str]] = defaultdict(list)
    for ch in all_chunks:
        full_by_doc[ch["canonical_document_id"]].append(ch.get("text") or "")
    for p in pages:
        path = path_of(p["url"])
        if path.endswith("/leaders") or path.startswith("/what-we-do") or path.startswith("/about-us"):
            full = "\n".join(full_by_doc.get(p["doc_id"]) or [])
            if len(full) > len(p["text"]):
                p["text"] = full

    cases = []
    covered = []
    per_page_counts: dict[str, int] = {}
    n = 0
    for page in pages:
        drafted = questions_for_page(page["url"], page["h1"], page["text"])
        if not drafted:
            continue
        covered.append(page["url"])
        per_page_counts[page["url"]] = len(drafted)
        for item in drafted:
            n += 1
            cases.append(
                {
                    "id": f"TW{n:03d}",
                    "category": item["category"],
                    "question": item["question"],
                    "expect_decision": "answer",
                    "expected_answer": item["expected_answer"],
                    "must_any": item["must_any"],
                    "forbid_any": [],
                    "citation_any": [],
                    "source_url": page["url"],
                    "kb_quote_hint": clean_text(page["text"])[:200],
                    "map_check": f"KB page — {path_of(page['url'])} ({len(drafted)} Qs on page)",
                }
            )

    refuse = [
        (
            "What will Thoughtworks stock price be next quarter?",
            "Refuse forward-looking finance not in KB.",
        ),
        ("What is the weather in Chicago tomorrow?", "Refuse — out of knowledge base."),
        (
            "What was Thoughtworks' exact employee count on 12 March 2019?",
            "Refuse precise invented historical headcount.",
        ),
    ]
    for q, expected in refuse:
        n += 1
        cases.append(
            {
                "id": f"TW{n:03d}",
                "category": "refuse",
                "question": q,
                "expect_decision": "refuse",
                "expected_answer": expected,
                "must_any": [],
                "forbid_any": [],
                "citation_any": [],
                "source_url": None,
                "kb_quote_hint": None,
                "map_check": "Refuse — OOD",
            }
        )

    cat_counts = Counter(c["category"] for c in cases)
    sec_page_counts = Counter(section(u) for u in covered)
    dense_pages = sum(1 for u, c in per_page_counts.items() if c >= 3)

    suite = {
        "suite_id": "thoughtworks_v4",
        "source_kind": "web",
        "agent_name": "Thoughtworks Assistant",
        "seed_url": "https://www.thoughtworks.com",
        "kb_notes": [
            "v4: every KB page ≥1 Q; denser multi-fact Qs on leaders / what-we-do / about / partnerships / DEI.",
            "News remains 1 Q/page (KB is news-heavy) so core accuracy is measurable.",
            "Cross-verify on source_url with Ctrl+F must_any / kb_quote_hint.",
        ],
        "kb_page_count": len(pages),
        "covered_page_count": len(set(covered)),
        "dense_page_count": dense_pages,
        "category_counts": dict(cat_counts),
        "section_page_counts": dict(sec_page_counts),
        "all_kb_urls": [p["url"] for p in pages],
        "cases": cases,
    }

    inventory = {
        "agent_name": "Thoughtworks Assistant",
        "workspace_id": ws,
        "page_count": len(pages),
        "pages": [
            {
                "url": p["url"],
                "h1": p["h1"],
                "section": section(p["url"]),
                "questions_on_page": per_page_counts.get(p["url"], 0),
                "snippet": clean_text(p["text"])[:240],
            }
            for p in pages
        ],
    }
    coverage = {
        "kb_pages": len(pages),
        "covered_pages": len(set(covered)),
        "cases": len(cases),
        "dense_pages_3plus_qs": dense_pages,
        "category_counts": dict(cat_counts),
        "section_page_counts": dict(sec_page_counts),
        "questions_per_section": dict(
            Counter(section(c["source_url"]) for c in cases if c.get("source_url"))
        ),
        "top_dense_pages": sorted(
            ((u, c) for u, c in per_page_counts.items()), key=lambda x: -x[1]
        )[:30],
    }

    for path, payload in ((OUT, suite), (INVENTORY, inventory), (COVERAGE, coverage)):
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(coverage, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
