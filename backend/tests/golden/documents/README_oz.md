# Oz series (L. Frank Baum) — document golden suite

Public-domain **connected series** corpus for multi-format ingest (PDF / DOCX / TXT).

## Corpus

Upload everything from your local folder, e.g.:

`C:\Users\v-pabaheti\Downloads\mixed-formats`

| File | Book |
|------|------|
| `01-wizard-of-oz.pdf` | The Wonderful Wizard of Oz |
| `02-marvelous-land-of-oz.docx` | The Marvelous Land of Oz |
| `03-ozma-of-oz.txt` | Ozma of Oz |
| `04-dorothy-and-the-wizard.pdf` | Dorothy and the Wizard in Oz |
| `05-road-to-oz.docx` | The Road to Oz |
| `06-emerald-city-of-oz.txt` | The Emerald City of Oz |
| `07-patchwork-girl-of-oz.pdf` | The Patchwork Girl of Oz |
| `08-tik-tok-of-oz.docx` | Tik-Tok of Oz |
| `09-scarecrow-of-oz.txt` | The Scarecrow of Oz |
| `10-rinkitink-in-oz.pdf` | Rinkitink in Oz |
| `11-lost-princess-of-oz.docx` | The Lost Princess of Oz |
| `12-tin-woodman-of-oz.txt` | The Tin Woodman of Oz |

Fleet agent used in eval: **`Frank Baum - Novel`** (override with `--agent` if renamed).

## Suite

- `oz_baum_v1.json` — characters, plot, places, cross-book, refuse traps  
- Grounded in Gutenberg text (especially TXT volumes; PDF/DOCX share the same books)

## Run

```bash
# inside vera-api after upload + weave finished
python /app/scripts/ask_eval_golden.py \
  --agent "Frank Baum - Novel" \
  --suite /app/tests/golden/documents/oz_baum_v1.json
```

Spot-check:

```bash
python /app/scripts/ask_eval_golden.py \
  --suite /app/tests/golden/documents/oz_baum_v1.json \
  --ids OZ002,OZ004,OZ010,OZ019
```

## Note on missing DOCX

If your Downloads folder is missing some `.docx` files, re-copy the full `mixed-formats` set (all 12 books) before Connect — the suite lists all twelve as `required_documents`.
