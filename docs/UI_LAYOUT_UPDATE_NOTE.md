# UI_LAYOUT_UPDATE_NOTE

Date: 2026-05-22

## 1) Logo placement

- Added `frontend/MYKL_logo.jpg` to the top-left header area in `frontend/index.html`.
- Header now uses a clean aligned branding row:
  - logo on left
  - `MYKL CHURN PREDICTOR` title on right
- Styling for logo alignment/scaling was added in `frontend/styles.css` (`.header-branding`, `.header-logo`).

## 2) Background image with blur/soft overlay

- Applied `frontend/background_Image.jpg` as full-page background in `frontend/styles.css` using `body::before`.
- Added a softened readability overlay via `body::after`.
- Content cards/panels/tables remain prominent and readable above the background with higher z-index.
- Background stays outside cards (global page backdrop only).

## 3) State filter moved above summary cards

- Moved State filter block above the Red/Orange/Green summary section in `frontend/index.html`.
- State selector now appears before summary cards in the workspace flow.

## 4) State-driven summary updates

- Updated `frontend/app.js` so Red/Orange/Green/Other/Total summary counts are recomputed from records scoped by selected State.
- Summary bars now update whenever State changes.

## 5) Risk/Potential filter placement retained below summary

- Risk buttons and Potential Level buttons remain below summary cards.
- These filters continue to control the detailed influencer list behavior as before.

## Scope confirmation

- No churn or potential business logic was changed.
- No upload/process/download flow changes were introduced.
- Backend dashboard data source remains unchanged (live backend payload).

