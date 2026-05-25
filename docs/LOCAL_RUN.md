# LOCAL_RUN

Date: 2026-05-22

## Goal

Run `mykl_churn_webapp` locally so frontend can call backend APIs and execute the real churn + potential workflow.

## A) Backend Start (Required First)

From repo root:

```powershell
cd mykl_churn_webapp/backend
py -m pip install -r requirements.txt
py -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Backend base URL:

- `http://127.0.0.1:8000`

Health checks:

- `http://127.0.0.1:8000/healthz`
- `http://127.0.0.1:8000/api/health`

## B) Frontend Start / Open

Recommended (same origin, simplest):

1. Keep backend running.
2. Open:
   - `http://127.0.0.1:8000/`

Alternative static-open mode:

1. Open `mykl_churn_webapp/frontend/index.html` directly in browser.
2. Frontend is configured to call backend at `http://127.0.0.1:8000`.

## C) Local URLs

- App page: `http://127.0.0.1:8000/`
- API health: `http://127.0.0.1:8000/api/health`

## D) Startup Order

1. Start backend on `127.0.0.1:8000`.
2. Confirm health endpoint returns success.
3. Open frontend page.
4. Select workbook and click **Generate Dashboard**.

## Expected Behavior

1. Upload returns a `job_id`.
2. Process route runs:
   - `scripts/score_input_file.py`
   - `scripts/add_potential_to_scored_file.py`
3. Dashboard data renders from final enriched output.
4. Final output download works.

