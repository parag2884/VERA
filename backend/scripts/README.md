# Backend scripts

Ops / eval helpers copied into the API image at `/app/scripts`.

| Script | Purpose |
|--------|---------|
| `ask_eval_golden.py` | Run suites from `/app/tests/golden/` |
| `ask_eval_thoughtworks.py` | Convenience wrapper for Thoughtworks web suite |
| `eval_ask_smoke.py` | Small PlayReady smoke cases |
| `ask_readiness_ci.py` | Ask-readiness gate for CI |
| `backfill_product_codes.py` | One-off metadata backfill |

Golden Q&A data lives in `tests/golden/` (not here).
