# UI_STATIC_PREVIEW_NOTE

This step delivers a static frontend preview only.

## Static in this step

1. Layout and visual styling for:
   - header (`MYKL CHURN PREDICTOR`)
   - left upload card
   - selected file display area
   - primary Generate button
   - current status card
   - right Preview Workspace placeholder panel
2. Local file input interaction in vanilla JS:
   - choose file
   - show selected file name
   - basic extension check (`.xlsx`, `.xls`)
   - status text updates

## Not connected in this step (to be wired later)

1. No backend API call on Generate
2. No upload to storage
3. No churn scoring execution
4. No potential enrichment execution
5. No real preview data rendering
6. No download links

Next step will connect this UI to backend routes and runtime processing flow.
