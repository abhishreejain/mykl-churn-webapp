# UPLOAD_PROCESS_FLOW_NOTE

Date: 2026-05-22

## Implemented API Flow

Backend entrypoint:

- `mykl_churn_webapp/backend/app/main.py`

Registered API routes:

- `POST /api/upload`
- `POST /api/process/{job_id}`
- `GET /api/dashboard/{job_id}`
- `GET /api/download/{job_id}/final`

## Upload Stage (`POST /api/upload`)

Behavior:

1. Accepts multipart field `file`.
2. Enforces extension check: only `.xlsx` / `.xls`.
3. Saves upload to per-job directory:
   - `backend/runtime/jobs/{job_id}/input/source_workbook.<ext>`
4. Validates workbook with scoring-compatible logic (same rules used by original scoring runtime expectations).
5. Returns structured success payload with:
   - `ok`
   - `job_id`
   - `filename`
   - `validation`

Failure response:

- Structured JSON with `error_type=UPLOAD_VALIDATION_FAILURE`.

## Process Stage (`POST /api/process/{job_id}`)

Behavior:

1. Loads uploaded workbook for the job.
2. Executes original script chain in order from repo root:
   - `scripts/score_input_file.py`
   - `scripts/add_potential_to_scored_file.py`
3. Uses full churn output from step 1 as input to step 2.
4. Stores artifacts in per-job output folder:
   - `churn_output.csv`
   - `final_enriched_output.csv`
   - `final_enriched_output.xlsx`
5. Returns structured success payload with counts and stage statuses.

Failure response:

- `error_type=CHURN_RUN_FAILURE` when scoring fails
- `error_type=POTENTIAL_RUN_FAILURE` when potential fails

## Notes

- No `client_handover/scripts` is used.
- No fake/mock preview path is used for processing.
- Per-job state is persisted via metadata in each job folder.

