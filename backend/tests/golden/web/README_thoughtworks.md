# Thoughtworks golden suites

| File | Role |
|------|------|
| `thoughtworks_kb_pages.json` | Inventory of **all 452 KB pages** (URL, section, Qs per page, snippet) |
| `thoughtworks_coverage.json` | Counts: cases / dense pages / per-section mix |
| `thoughtworks_v4.json` | **Full suite** — every page ≥1 Q; denser on leaders/services/about/partnerships |
| `thoughtworks_v4_core.json` | **Core slice** — same as v4 but **excludes news** (so accuracy isn’t drowned by press archive) |
| `thoughtworks_v3.json` | Earlier 1–2 Q/page generator |
| `thoughtworks_v2.json` | Small hand-tuned smoke suite |

## Why v4 + core

The KB is news-heavy (~289 press pages). Full coverage still has one Q per news page, but **leaders / what-we-do / about / partnerships** now get multiple fact questions each (people, partners, service claims).

Use **`thoughtworks_v4_core.json`** day-to-day to see if Ask is right on the pages that matter.  
Use **`thoughtworks_v4.json`** when you want the full KB certificate.

## Leaders examples (from live KB text)

| ID | Question | must_any |
|----|----------|----------|
| TW047 | Who is Chief Executive Officer… | mike sutcliff |
| TW048 | Who is Chief Financial Officer… | erin cummins |
| TW049 | Who is Chief Technology Officer… | rachel laycock |

## Cross-verify

Open `source_url` → Ctrl+F `must_any` / `kb_quote_hint` → compare bot answer.

## Regenerate after re-crawl

```powershell
docker cp backend/scripts/_gen_tw_goldens_from_kb.py vera-api:/app/scripts/
docker exec -e PYTHONPATH=/app vera-api python /app/scripts/_gen_tw_goldens_from_kb.py
docker cp vera-api:/app/data/thoughtworks_v4_from_kb.json tests/golden/web/thoughtworks_v4.json
docker cp vera-api:/app/data/thoughtworks_kb_pages.json tests/golden/web/thoughtworks_kb_pages.json
docker cp vera-api:/app/data/thoughtworks_coverage.json tests/golden/web/thoughtworks_coverage.json
```

Then rebuild the core slice (or re-run the small Python filter in repo history).

## Run

```bash
# Core accuracy (recommended)
docker exec -e PYTHONPATH=/app vera-api \
  python /app/scripts/ask_eval_golden.py \
  --suite /app/tests/golden/web/thoughtworks_v4_core.json

# Spot leaders
docker exec -e PYTHONPATH=/app vera-api \
  python /app/scripts/ask_eval_golden.py \
  --suite /app/tests/golden/web/thoughtworks_v4.json --ids TW047,TW048,TW049
```
