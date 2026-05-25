# LOCAL_API_DEBUG_NOTE

Date: 2026-05-22

## Root Cause of "Could not reach backend API at http://127.0.0.1:8000"

The frontend error appears when browser cannot connect to backend URL, typically because:

1. Backend server is not running.
2. Backend is running on a different port.
3. Frontend is opened from a different local origin without API base override.

## Current Local API Contract

Backend should run at:

- `http://127.0.0.1:8000`

Required routes:

- `GET /api/health`
- `POST /api/upload`
- `POST /api/process/{job_id}`
- `GET /api/dashboard/{job_id}`
- `GET /api/download/{job_id}/final`

## Frontend API Base Resolution

In `frontend/app.js`:

1. `?apiBase=<url>` query param (highest priority)
2. `window.MYKL_API_BASE` global
3. If `file://`, fallback to `http://127.0.0.1:8000`
4. If opened on `localhost`/`127.0.0.1` but not port `8000`, fallback to `http://127.0.0.1:8000`
5. Otherwise same-origin (`""`)

## Quick Debug Checklist

1. Check backend health:
   - `http://127.0.0.1:8000/api/health`
2. If not reachable, start backend:
   - `py -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
3. Open app at:
   - `http://127.0.0.1:8000/`
4. Try upload again.

## Notes

- Local CORS is enabled for all origins.
- API responses are structured JSON for failures (not silent failures).

