# Trust Forge

Climb a workspace’s Ask accuracy toward a fitness **threshold** (default 95%, aim near 100%) by looping **eval → heal → re-eval**. Other workspaces are never written.

## Package layout

```
backend/app/trust_forge/
  eval.py       # golden suite runner + fitness
  heal.py       # hygiene + site hierarchy + failed-fact pins
  service.py    # climb loop, locks, generations
  router.py     # HTTP API
  cli.py        # python -m app.trust_forge.cli
  __init__.py

frontend/src/trust_forge/
  TrustForgePanel.tsx
  index.ts

docs/trust_forge/
  README.md     # this file
```

## What it does

1. Load a **golden suite** for the agent (or an explicit suite path).
2. **Baseline eval** — fitness \( F = 100 \times passed / N \).
3. While below threshold:
   - **Heal** this workspace only:
     - graph hygiene (bad aliases, junk Person nodes)
     - website **PART_OF** hierarchy (child page → parent page)
     - **pin failed facts** onto the golden `source_url` page when retrieval missed (phrase must already exist in a chunk)
   - Re-run the golden suite.

For **website** agents, auto-suite pick prefers `*_core` goldens (identity/services pages) over news-heavy full dumps — that archive mix is why many crawls sit near 55%.

Eval now records `retrieval_ok` (source page slug in citations/answer) separately from final `must_any` pass, so you can see retrieval vs wording failures.
4. Stop when:
   - \( F \ge \) threshold, or
   - **Plateau** (no improvement for `stall_generations`, default 3), or
   - `max_generations` (default 8), or
   - User **Stop**.

## Isolation

| Rule | How |
|------|-----|
| Pack scope | Every query/heal uses `workspace_id` |
| One job at a time | Reject start if a run is `queued`/`running` for that workspace |
| No cross-pack writes | Hygiene + eval never touch other workspace ids |
| Shared Chroma | Still filtered by `workspace_id` on every query (existing VectorStore contract) |

## API

| Method | Path |
|--------|------|
| `POST` | `/api/workspaces/{workspace_id}/trust-forge/runs` |
| `GET` | `/api/workspaces/{workspace_id}/trust-forge/runs` |
| `GET` | `/api/workspaces/{workspace_id}/trust-forge/runs/{run_id}` |
| `POST` | `/api/workspaces/{workspace_id}/trust-forge/runs/{run_id}/stop` |

Start body (JSON):

```json
{
  "agent_id": "optional",
  "suite_path": "optional — e.g. documents/playready_v1.json",
  "threshold": 95,
  "max_generations": 8,
  "stall_generations": 3
}
```

## CLI

```bash
docker exec -e PYTHONPATH=/app vera-api \
  python -m app.trust_forge.cli --agent "PlayReady" --threshold 95 --poll

# or thin wrapper
docker exec -e PYTHONPATH=/app vera-api \
  python /app/scripts/trust_forge_run.py --agent "PlayReady" --threshold 95 --poll
```

## Studio

Dedicated tab **Trust Forge** (`/trust-forge`):

- Climb controls + live activity
- Knowledge-graph change viz (aliases removed / nodes retyped)
- Case × generation **improvement matrix** (✓/✗ + trend)

Insights keeps only a link to this tab.

## Golden suites (200+)

Suites live under `tests/golden/` (schema: [SCHEMA.md](../../tests/golden/SCHEMA.md)).  
Attach a suite by matching `agent_name` to the Fleet agent, or pass `suite_path`.

To push toward ~100%: grow the locked golden set (human-approved), re-run Trust Forge after ingest/hygiene improvements.

## v2 roadmap (not in MVP)

- Genetic population over retrieval knobs + graph patches
- Candidate KG/Vector versions + atomic promote/rollback
- Auto Q&A proposals (human lock before scoring)
