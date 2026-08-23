# Knowledge + assistant connector roadmap

VERA keeps **one agent · one graph**. New sources plug in as `SourceConnector.acquire() → AcquiredFile[] → ingest_pipeline`. Ask never imports connectors.

## Live today

| Kind | Package |
|------|---------|
| documents | `sources/documents` |
| web | `sources/web` |
| sharepoint | `sources/sharepoint` |
| blob | `sources/blob` (needs Azure config) |
| sample | `sources/documents/sample` |

- Hybrid retrieval (lexical + vector + graph) + page trust ranking (core/people vs news)
- Website crawl: chrome strip, heading/list structure, page PART_OF hierarchy

## Knowledge next (realistic)

| Kind | Why | Typical auth |
|------|-----|----------------|
| outlook | Email & calendar → Ask briefs (mail, meetings, summaries) | Graph `Mail.Read` + `Calendars.Read` |
| onedrive | Personal / work files | Graph `Files.Read.All` |
| teams | Channel posts + attached files | Graph channel + files scopes |
| onelake | Fabric lakehouse files | Workspace identity / ADLS |
| azure_sql | Structured facts (allowlisted views) | SQL connection |
| confluence | Wiki spaces | Atlassian API token |
| gdrive | Shared drives / Docs | Google OAuth |

Stubs live in `sources/planned.py` and appear on `GET /api/sources/connectors` → `catalog`.

## Email & calendar (personal assistant via Ask)

Not separate action tiles. When **Email & calendar** is connected, mail/meeting
content feeds the same ingest → Ask path so the chatbot can brief important
mail, upcoming meetings, and answer follow-up questions — same pattern as
Website or Files.

## Adding a new knowledge connector

1. Create `sources/<kind>/client.py` + `connector.py`.
2. Register in `registry.py`.
3. Add optional `POST /api/sources/<kind>` thin route.
4. Wire Connect UI tab when `state` becomes `configured` / `live`.
