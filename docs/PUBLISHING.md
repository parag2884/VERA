# Publishing an agent

Publishing turns a workspace-backed agent into a **billable public surface**: embed page, widget snippet, and `POST /api/public/chat`.

---

## Checklist

1. Agent has documents ingested (chunks + weave complete).
2. Studio **Ask** works for that agent’s workspace.
3. Open **Agents** → select agent → **Publish**.
4. Copy **embed key**.
5. Add consumer origins to `VERA_CORS_ORIGINS` if needed.
6. Smoke-test public chat (see [PUBLIC-API.md](PUBLIC-API.md)).

---

## API publish

```powershell
$agents = Invoke-RestMethod http://localhost:8080/api/agents
$agent = $agents | Where-Object { $_.name -eq "PlayReady Assistant" } | Select-Object -First 1
Invoke-RestMethod -Method POST -Uri "http://localhost:8080/api/agents/$($agent.id)/publish"
```

Response includes:

| Field | Use |
|-------|-----|
| `embed_key` | Public chat + embed URL |
| endpoints.embed_url | Full-page embed |
| endpoints.widget_snippet | Drop-in `<script>` |
| endpoints.public_chat_url | `/api/public/chat` |

---

## Surfaces

| Surface | URL pattern |
|---------|-------------|
| Studio embed | `http://localhost:5173/embed/{embed_key}` |
| Widget | `{origin}/widget.js` + `data-vera-key` |
| Custom UI | Any site calling public API with the key |

---

## Isolation

Public chat always runs against the agent’s **own** `workspace_id`.  
Customers never see other agents’ graphs or documents.

---

## Unpublish

```powershell
Invoke-RestMethod -Method POST -Uri "http://localhost:8080/api/agents/$($agent.id)/unpublish"
```

Public routes return `403 Agent is not published` until republished.

---

## Pricing hint

Studio dashboard may show embed pricing from `VERA_EMBED_PRICE_PER_1M_TOKENS`.  
Treat as product copy / metering hint unless you wire a real billing meter.
