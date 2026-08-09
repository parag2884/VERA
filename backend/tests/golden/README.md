# Golden Ask test cases

Dedicated suites for **cross-checking the bot against the knowledge base** — not against model memory.

| Folder | Knowledge source | How to draft Q&A |
|--------|------------------|------------------|
| `web/` | Public URL crawl | Open the live page (`source_url`); expected phrases must appear on that page |
| `documents/` | PDF / txt / Office upload | Open the file (`source_document`); expected phrases must appear in that file |
| `refuse/` | Out-of-KB traps | Same for every agent — must **refuse**, never invent |

## Drafting rules (required)

1. **Pick the source first** — page URL or PDF/txt filename that is actually in the agent’s KB.
2. **Write the expected answer from that source** — quote or paraphrase only what the document says.
3. **`must_any`** — short phrases you can Ctrl+F in the website or file (case-insensitive).
4. **`kb_quote_hint`** (optional but recommended) — one literal snippet from the source for human review.
5. **Never invent officers, metrics, or product facts** that are not on the cited page/file.
6. **Refuse cases** — questions the KB cannot answer (weather, other companies’ secrets, exact invented finance).

## Suite JSON shape

See [`SCHEMA.md`](SCHEMA.md). Minimal case:

```json
{
  "id": "TW01",
  "question": "Who is the CEO of Thoughtworks?",
  "expect_decision": "answer",
  "expected_answer": "Mike Sutcliff is CEO (from leaders page).",
  "must_any": ["mike sutcliff", "sutcliff"],
  "source_url": "https://www.thoughtworks.com/about-us/leaders",
  "kb_quote_hint": "Mike Sutcliff"
}
```

Documents example:

```json
{
  "id": "PR01",
  "question": "What is the difference between SL2000 and SL3000?",
  "expect_decision": "answer",
  "must_any": ["sl2000", "sl3000"],
  "source_document": "PlayReady_SL3000_Playbook.pdf",
  "kb_quote_hint": "SL3000"
}
```

## Run

Inside `vera-api` (after suite files are in the image or mounted):

```bash
# One suite
python /app/scripts/ask_eval_golden.py --suite /app/tests/golden/web/thoughtworks_v2.json

# By agent name (loads matching suite from tests/golden)
python /app/scripts/ask_eval_golden.py --agent "Thoughtworks Assistant"

# Subset
python /app/scripts/ask_eval_golden.py --suite /app/tests/golden/web/thoughtworks_v2.json --ids TW01,TW14
```

Results write under `/app/data/ask_eval_<suite_id>_results.json`.

## Adding a new corpus

1. Connect the agent (crawl URL or upload PDFs).
2. Copy `_template_web.json` or `_template_documents.json`.
3. Fill cases only from pages/files you opened.
4. Run the eval; fix retrieval or the golden if the page truly says something else.

## Layout

```
tests/golden/                 ← edit here (canonical)
  web/                        ← URL-crawled agents
  documents/                  ← PDF / txt / Office agents
  refuse/                     ← out-of-KB refuse traps
  _template_*.json
  SCHEMA.md
```

`docker-compose` mounts this folder into `vera-api` at `/app/tests/golden`.  
`backend/tests/golden` is a build-time copy for the image when the mount is absent — keep it in sync after suite edits:

```powershell
Copy-Item -Recurse -Force tests/golden/* backend/tests/golden/
```

Eval runners live only under `backend/scripts/` (image path `/app/scripts/`).
