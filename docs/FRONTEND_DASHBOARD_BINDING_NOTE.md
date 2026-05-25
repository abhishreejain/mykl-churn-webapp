# FRONTEND_DASHBOARD_BINDING_NOTE

Date: 2026-05-22

## What Was Connected

Frontend is now bound to backend APIs using vanilla JavaScript in:

- `frontend/app.js`

UI structure updated in:

- `frontend/index.html`
- `frontend/styles.css`

## Runtime Flow in UI

When user clicks **Generate Dashboard**:

1. `POST /api/upload` with `multipart/form-data` (`file`)
2. `POST /api/process/{job_id}`
3. On success, `GET /api/dashboard/{job_id}`
4. Render real dashboard data
5. Enable final output download via `GET /api/download/{job_id}/final`

## Rendered Dashboard Sections

### Part 1 - Summary

- Red / Orange / Green summary cards now show live influencer counts.
- Mini meter bars are rendered using percentage width from total records.
- Total and Other counts are displayed in a summary strip.

### Part 2 - Filters

- State dropdown (`All States` + backend state list)
- Risk toggle buttons (`All Risks` + backend risk list)
- Potential level toggle buttons (`All Potential Levels` + backend list)

### Part 3 - Influencer List

Filtered rows now render from `influencer_records`:

- Customer name
- Customer mobile number
- Risk
- Potential level
- Priority bucket
- Churn probability (compact)
- Potential (compact)

### Part 4 - Download

- Download button stays hidden until full processing succeeds.
- On success, button points to `/api/download/{job_id}/final`.

## Status Handling

Status card now updates for:

- file selected
- uploading
- processing
- success
- warning/partial
- failure

Status also shows returned `job_id` for operational tracking.

## Notes

- No framework rewrite was done.
- Logic is client-side JavaScript only.
- The right panel is now data-driven after processing completes.
