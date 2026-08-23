# VERA product scorecard

Living scores for the graph-primary evidence product. Update after hygiene / eval runs.

| Dimension | Was | Now | Notes |
|-----------|-----|-----|-------|
| Answer quality | 7 | **8** | Structured Markdown; comparison path; golden smoke eval (4/4 PASS) |
| Graph quality | 6 | **8** | Hygiene removed **954** bad aliases, retyped **37** junk Persons; backfilled **42** code/level nodes |
| UX polish | 7.5 | **8.5** | Studio Ask focus mode closer to chatbot (Options drawer, meta chips) |
| Production readiness | 5.5 | **6.5** | Public rate limit, optional require-Origin, `/hygiene` API, eval script |

**Overall: ~7.5 → ~8.1** for pilot / demo readiness (measured after PlayReady hygiene run).

## How to keep scores rising

```powershell
# Graph hygiene (PlayReady workspace)
Invoke-RestMethod -Method POST `
  -Uri "http://localhost:8080/api/workspaces/31509630-c427-40c4-b182-e1f63fe8c91b/hygiene"

# Ask smoke eval (in API container)
docker exec -e PYTHONPATH=/app vera-api python /app/scripts/eval_ask_smoke.py

# Trust Forge — climb golden fitness for one agent (isolated heal loop)
docker exec -e PYTHONPATH=/app vera-api `
  python -m app.trust_forge.cli --agent "PlayReady" --threshold 95 --poll
```

See [trust_forge/](trust_forge/README.md).

## Still to climb further

| Target | Work |
|--------|------|
| Answer → 9 | More asserted trails (`graph_primary` %) after re-weave |
| Graph → 9 | Human curation UI; unique aliases; split over-merged Products |
| Prod → 8 | AuthN for Studio, durable rate-limit store, billing meter, CI eval gate |

**Knowledge OS** (Insights): coverage by domain, numeric conflict scan, Ask 👍/👎, production weak-answer mining, source reliability in retrieval.
