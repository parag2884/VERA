# Configuration

Copy `.env.example` → `.env` at the repo root. Docker Compose loads this file for `vera-api`.

**Never commit a filled `.env`.**

---

## Azure OpenAI

| Variable | Required | Notes |
|----------|----------|-------|
| `AZURE_OPENAI_ENDPOINT` | for live LLM | Resource endpoint URL |
| `AZURE_OPENAI_API_KEY` | for live LLM | Keep secret |
| `AZURE_OPENAI_DEPLOYMENT` | for live LLM | Chat deployment name |
| `AZURE_OPENAI_API_VERSION` | no | Default `2024-08-01-preview` |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | optional | Embedding deployment if used |

If keys are missing, the app can fall back to mock LLM when `VERA_MOCK_LLM=true` (or when Azure is not configured).

---

## Storage & vectors

| Variable | Default | Notes |
|----------|---------|-------|
| `VERA_DB` | `./data/vera.db` | SQLite path (inside API container volume) |
| `VERA_DATA_DIR` | `./data` | Uploads / working data |
| `VERA_VECTOR_BACKEND` | `chroma` | `chroma` or `none` |
| `VERA_CHROMA_DIR` | `./data/chroma` | Chroma persistence |

Docker maps named volume `vera_data` → `/app/data`.

---

## Retrieval & weave

| Variable | Default | Notes |
|----------|---------|-------|
| `VERA_RETRIEVAL_MODE` | `graph_primary` | Product preference (actual mode may be hybrid per question) |
| `VERA_GRAPH_HOPS` | `3` | Multi-hop graph walk depth |
| `VERA_QUOTE_TOP_K` | `8` | Quote pack size |
| `VERA_WEAVER_LLM_CHUNKS` | `16` | Max chunks for LLM entity extraction per weave |
| `VERA_REFUSE_THRESHOLD` | `0.35` | Evidence judge refuse floor |
| `VERA_NEAR_DUPE_THRESHOLD` | `0.85` | Soft entity-link similarity |

---

## Knowledge connectors (`app/knowledge/`)

VERA’s **AI that works** model: each connector acquires files into a shared ingest pipeline; Ask only answers from that knowledge (or refuses). Connectors are isolated so changing crawl code cannot break PDF parse, and Ask never imports connectors.

| Package | Owns |
|---------|------|
| `knowledge/sources/documents` | PDF / Word / txt / Office / zip / sample |
| `knowledge/sources/web` | Public URL crawl + HTML extract |
| `knowledge/sources/sharepoint` | Microsoft Graph / demo library |
| `knowledge/sources/blob` | Azure Blob (needs connection string) |
| `knowledge/sources/planned` | Roadmap slots: Outlook, OneDrive, Teams, OneLake, SQL, Confluence, Drive + assistant tools |
| `knowledge/pipeline` | Shared fingerprint → parse → weave → embed |
| `knowledge/signals` | Passage signals shared by ingest + Ask |

See [`backend/app/knowledge/ROADMAP.md`](../backend/app/knowledge/ROADMAP.md) for Microsoft mail / personal-assistant provisioning.

## Uploads & URL crawl

| Variable | Default |
|----------|---------|
| `VERA_MAX_UPLOAD_FILES` | `100` |
| `VERA_MAX_FILE_MB` | `100` |
| `VERA_URL_MAX_PAGES` | `500` |
| `VERA_URL_MAX_DEPTH` | `4` |
| `VERA_URL_HARD_MAX_PAGES` | `2000` |
| `VERA_CRAWL_SKIP_CHRONICLE` | `false` (Foundry-style default: keep news/blog in the index; Ask demotes them unless the question asks). Set `true` only if you must save page budget on huge sites. |

---

## SharePoint (optional)

| Variable | Notes |
|----------|-------|
| `VERA_MS_TENANT_ID` | Entra tenant |
| `VERA_MS_CLIENT_ID` | App registration |
| `VERA_MS_CLIENT_SECRET` | Secret — keep out of git |

Needs Graph permissions: `Sites.Read.All`, `Files.Read.All` (app or delegated as implemented).

---

## Azure Blob (optional)

| Variable | Notes |
|----------|-------|
| `VERA_AZURE_BLOB_CONNECTION_STRING` | Preferred — full connection string |
| `VERA_AZURE_STORAGE_ACCOUNT` | Alternative with key |
| `VERA_AZURE_STORAGE_KEY` | Pair with storage account |

Without these, `GET /api/sources/connectors` shows `blob.state: needs_config` and `POST /api/sources/blob` returns `501 BLOB_NOT_CONFIGURED`. See `backend/app/knowledge/sources/blob/README.md`.

After ingest, Ask readiness (`ask_readiness` on health) is the gate that the agent “works” for grounded Q&A.

---

## Public surface & CORS

| Variable | Default | Notes |
|----------|---------|-------|
| `VERA_CORS_ORIGINS` | Studio + API localhost | Comma-separated browser origins |
| `VERA_WIDGET_PUBLIC_ORIGIN` | Studio origin | Used for embed URL / widget snippet |
| `VERA_EMBED_PRICE_PER_1M_TOKENS` | `0.02` | Pricing display / metering hint |

For the PlayReady chatbot on port 5500, include:

```
http://localhost:5500,http://127.0.0.1:5500
```

Compose currently injects CORS including those origins — keep `.env` in sync if you rely on env_file alone for local uvicorn.

---

## Ops

| Variable | Default |
|----------|---------|
| `VERA_MOCK_LLM` | `false` |
| `VERA_LOG_LEVEL` | `INFO` |

---

## After changing env

```powershell
cd C:\Parag-Personal\Kite
docker compose up -d api
```

Full recreate if volumes/images must rebuild:

```powershell
docker compose up -d --build
```
