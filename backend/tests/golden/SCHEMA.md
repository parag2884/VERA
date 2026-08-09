# Golden suite schema

Top-level object:

| Field | Required | Description |
|-------|----------|-------------|
| `suite_id` | yes | Stable id, e.g. `thoughtworks_v2`, `playready_docs_v1` |
| `source_kind` | yes | `web` \| `documents` \| `refuse` |
| `agent_name` | yes | Exact Fleet agent name to evaluate |
| `seed_url` | web | Homepage / crawl seed for the corpus |
| `kb_notes` | no | How this KB was connected |
| `required_pages` | web | URLs that should be crawled before the suite is meaningful |
| `required_documents` | documents | Filenames / titles that should be uploaded |
| `cases` | yes | Array of case objects |

Each **case**:

| Field | Required | Description |
|-------|----------|-------------|
| `id` | yes | Unique within suite (`TW01`, `PR01`, …) |
| `question` | yes | Ask text |
| `expect_decision` | yes | `answer` \| `refuse` \| `clarify` \| `either` |
| `expected_answer` | yes | Human-readable ground truth from the KB |
| `must_any` | for answer | ≥1 phrase must appear in the bot answer (normalized) |
| `forbid_any` | no | Fail if any phrase appears |
| `citation_any` | no | Soft check on citation document titles |
| `source_url` | web answers | Canonical page to cross-verify in a browser |
| `source_document` | documents answers | Filename / title in the KB |
| `kb_quote_hint` | recommended | Literal snippet from that page/file |
| `category` | no | e.g. people, services, refuse |
| `map_check` | no | Optional graph / map note |

Eval pass rules (runner):

1. `decision` matches `expect_decision` (unless `either`).
2. If `expect_decision=answer` and `must_any` set → at least one phrase in answer.
3. No `forbid_any` phrases in answer.
4. `citation_any` miss is soft (noted, does not fail).
