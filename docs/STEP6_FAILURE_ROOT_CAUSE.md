# STEP6_FAILURE_ROOT_CAUSE

Date: 2026-05-22

## Symptom Observed

Frontend status showed:

- `Current status: Failed to fetch`
- `Job ID: None`

## Root Cause Diagnosis

1. **`/api/upload` was effectively failing from the frontend perspective**  
   Reason: frontend called `fetch('/api/upload')`, but the `mykl_churn_webapp/backend/app` package had no runnable API app/route implementation at that point (`main.py` missing, routes not implemented).

2. **Backend was not wired as a runnable web API for this package**  
   `mykl_churn_webapp/backend/app` contained only scaffolding placeholders (`__init__.py`, empty route stubs). So even valid frontend requests had no endpoint handlers.

3. **Route path mismatch in practice (frontend expected endpoints, backend had none)**  
   Frontend correctly expected:
   - `POST /api/upload`
   - `POST /api/process/{job_id}`
   - `GET /api/dashboard/{job_id}`
   - `GET /api/download/{job_id}/final`  
   but these were not implemented in the package backend at the time of failure.

4. **CORS/fetch origin risk**  
   When frontend is opened from `file://`, browser fetch to relative `/api/...` can fail due to no same-origin API host and cross-origin/network context. This contributed to generic `Failed to fetch` messaging.

5. **Response format was not the primary issue**  
   The immediate issue was endpoint absence/unreachable backend, not JSON parsing schema mismatch.

6. **Frontend parsing logic was not the primary issue**  
   `app.js` parsed `job_id` or `jobId` correctly. Failure happened before payload parsing because the request itself failed.

## Conclusion

Primary failure cause was missing/unwired backend API implementation for the website package, plus local serving/origin conditions.  
Fix required: implement actual backend endpoints, run backend server, and wire frontend to those endpoints with clear error surfacing.

