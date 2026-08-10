# PlayReady golden suites

| File | Role |
|------|------|
| `playready_pdf_inventory.json` | All **44** Prod Normalised PDFs + extract snippets + KB title match |
| `playready_v2.json` | Q&A drafted from PDF text (~178 cases) |
| `playready_publicbot_v1.json` | **135** legacy PublicBot questions (+ 2 refuse) from `PublicBot-Questions.xlsx` |
| `PublicBot-Questions.xlsx` | Original spreadsheet (source of truth for PB* ids) |
| `playready_v1.json` | Smaller hand-tuned smoke suite |

## Source PDFs

`C:\Users\v-pabaheti\Downloads\Prod PDFs\Prod Normalised PDFs`

## Cross-verify

1. Open `source_file` (or matching `source_document` in the PlayReady agent KB).
2. Ctrl+F `must_any` / `kb_quote_hint`.
3. Compare chatbot answer.

## Regenerate

```powershell
docker exec vera-api mkdir -p /app/data/playready_pdfs
docker cp "C:\Users\v-pabaheti\Downloads\Prod PDFs\Prod Normalised PDFs\." vera-api:/app/data/playready_pdfs/
docker cp backend/scripts/_gen_playready_goldens.py vera-api:/app/scripts/
docker exec -e PYTHONPATH=/app vera-api python /app/scripts/_gen_playready_goldens.py --pdf-dir /app/data/playready_pdfs
docker cp vera-api:/app/data/playready_v2_from_pdfs.json tests/golden/documents/playready_v2.json
docker cp vera-api:/app/data/playready_pdf_inventory.json tests/golden/documents/playready_pdf_inventory.json
```

## Import / refresh PublicBot spreadsheet

```powershell
python backend/scripts/_import_publicbot_xlsx.py "c:\Users\v-pabaheti\Downloads\PublicBot-Questions.xlsx"
```

## Run eval

```bash
# Legacy public-bot set (best for regression vs old bot)
docker exec -e PYTHONPATH=/app vera-api \
  python /app/scripts/ask_eval_golden.py \
  --suite /app/tests/golden/documents/playready_publicbot_v1.json

# PDF-derived set
docker exec -e PYTHONPATH=/app vera-api \
  python /app/scripts/ask_eval_golden.py \
  --suite /app/tests/golden/documents/playready_v2.json --ids PR137,PR138,PR003
```
