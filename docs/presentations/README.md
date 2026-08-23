# VERA — Presentation pack

## Main deliverable (use this)

**`VERA-Complete.pptx`** (or `VERA-Complete-updated.pptx` if the first file is open) — widescreen **16:9 PowerPoint**

Includes PlayReady + Oz + Thoughtworks results, with **why this accuracy** and **next-level accuracy plans** for each corpus.

- Open in **Microsoft PowerPoint** or upload to **Google Slides**
- Present full screen: **F5** (Slide Show)
- Export: **File → Save As → PDF** or share the `.pptx` directly
- Includes Studio screenshots + flow diagrams (magic pipeline, corkboard/sticky notes, hybrid Ask, embed architecture)

Rebuild after new screenshots:

```powershell
cd C:\Parag-Personal\Kite
node docs/presentations/capture-screens.mjs
python docs/presentations/build_pptx.py
```

## Other files

| File | Purpose |
|------|---------|
| `build_pptx.py` | Regenerates `VERA-Complete.pptx` |
| `screenshots/` | Captured Studio PNGs embedded in the PPT |
| `capture-screens.mjs` | Auto-capture screens from localhost:5173 |
| `vera-manager-deck.html` | Shorter HTML briefing (optional) |
| `SCREEN_CAPTURE_GUIDE.md` | Manual video shot list (Win+G) |
