# Public API

Base (local): `http://localhost:8080`

These routes are for **published** agents only. Studio Ask uses `/api/chat` with a workspace id instead.

Interactive OpenAPI: http://localhost:8080/docs

---

## GET `/api/public/agents/{embed_key}`

Agent shell config for embed UIs.

**200** — name, greeting, placeholder, accent, trail/citation flags, `published: true`  
**403** — not published or Origin not allowed  
**404** — unknown key  

---

## POST `/api/public/chat`

```json
{
  "embed_key": "<from publish>",
  "question": "…",
  "session_id": null
}
```

Returns a `ChatResponse`: `decision`, `answer` / clarify fields, `trust_score`, `retrieval_mode`, `session_id`, etc.

| `decision` | Meaning |
|------------|---------|
| `answer` | Use `answer` |
| `clarify` | Use `clarification_prompt` |
| `refuse` | Insufficient evidence |

### PowerShell smoke test

```powershell
$key = "<embed_key>"
Invoke-RestMethod "http://localhost:8080/api/public/agents/$key"

$body = @{ embed_key = $key; question = "What is PlayReady?" } | ConvertTo-Json
Invoke-RestMethod -Method POST -Uri "http://localhost:8080/api/public/chat" `
  -ContentType "application/json" -Body $body
```

---

## Publish (Studio API)

```http
POST /api/agents/{agent_id}/publish
```

Returns embed key plus endpoint hints (`embed_url`, `widget_snippet`, `public_chat_url`, …).

Unpublish:

```http
POST /api/agents/{agent_id}/unpublish
```

---

## CORS vs agent origins

1. **Platform CORS** (`VERA_CORS_ORIGINS`) — browser may call the API at all.  
2. **Agent `allowed_origins`** — which sites may use *this* embed key (`*` allowed for demos).

Both must pass for public chat from a browser.

---

## Example integrators

- Studio embed page: `{VERA_WIDGET_PUBLIC_ORIGIN}/embed/{embed_key}`
- Widget script: see publish response `widget_snippet`
- Standalone chatbot: `C:\Parag-Personal\Vera_PlayReady_Chatbot`
