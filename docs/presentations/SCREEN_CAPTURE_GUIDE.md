# VERA manager deck — screen capture guide

## Presentation

Open in a browser (Chrome/Edge):

`docs/presentations/vera-manager-deck.html`

- Arrow keys / buttons to navigate  
- **Print / PDF** → Save as PDF to email managers  
- Screenshots auto-load from `docs/presentations/screenshots/` when present  

## Auto-capture (when Studio is running)

```powershell
cd C:\Parag-Personal\Kite
npx --yes playwright@1.49.0 install chromium
node docs/presentations/capture-screens.mjs
```

Requires `http://localhost:5173` (vera-web) healthy.

## Manual video (Windows)

If you need a screen **recording** (video), use:

1. `Win + G` → Capture → Record  
   or Clipchamp / OBS  
2. Follow this shot list (60–90 seconds each):

| # | Screen | Show |
|---|--------|------|
| 1 | Home | Trust Center + AI Findings |
| 2 | Prove it | Click Conflicts → drawer with sides + sources |
| 3 | Connect | Upload / Website / SharePoint tiles |
| 4 | Map | Click a node (e.g. CapnBill) |
| 5 | Ask | Ask a question → open Trust Trail |
| 6 | Fleet / Deploy | Published agent + embed hint |

Talk track: *“Not trust me — here’s the evidence.”*
