# LOCAL_CONNECTIVITY_FIX_RESULT

Date: 2026-05-22

## Backend Start Command (Verified)

From `mykl_churn_webapp/backend`:

```powershell
py -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Frontend Start / Open Method (Verified)

Recommended:

- Open `http://127.0.0.1:8000/` (served by backend app)

Also supported:

- Open `mykl_churn_webapp/frontend/index.html` directly; frontend will target `http://127.0.0.1:8000`.

## Backend Base URL Used by Frontend

- `http://127.0.0.1:8000` for local file mode and local non-8000 static mode.

## Health Route Tested

- `GET http://127.0.0.1:8000/api/health`
- Response: `200` with `{"ok":"true","status":"healthy"}`

## End-to-End Local Connectivity Verification

Using valid workbook:

- `outputs/web_smoke_process_input.xlsx`

Observed:

1. Upload request reached backend: PASS (`POST /api/upload`, HTTP 200)
2. Job ID returned: PASS (`job_20260522_082340_60719e80`)
3. Process request reached backend: PASS (`POST /api/process/{job_id}`, HTTP 200)
4. Dashboard request reached backend: PASS (`GET /api/dashboard/{job_id}`, HTTP 200)
5. Download request reached backend: PASS (`GET /api/download/{job_id}/final`, HTTP 200)

## Connectivity Issue Status

- Original issue (`Could not reach backend API at http://127.0.0.1:8000`) is resolved when backend is started using the documented command.

## Final Result

- **PASS**

