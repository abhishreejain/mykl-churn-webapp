# DASHBOARD_API_CONTRACT

Date: 2026-05-22  
Status: Contract definition for backend behavior (implementation may follow).

## Runtime Source of Truth (Mandatory)

Backend execution must use runtime copied from original project:

1. `backend/runtime/scripts/score_input_file.py`
2. `backend/runtime/scripts/add_potential_to_scored_file.py`
3. `backend/runtime/src/churn_model/`
4. `backend/runtime/artifacts/production/`

Must not use:

- `client_handover/scripts/*`

---

## API Base

- Base prefix: `/api`
- Job identifier: `job_id` (server-generated, opaque to client)

## Common Response Envelope

All error responses should be friendly and structured:

```json
{
  "ok": false,
  "job_id": "optional-job-id",
  "error_type": "UPLOAD_VALIDATION_FAILURE | CHURN_RUN_FAILURE | POTENTIAL_RUN_FAILURE | DASHBOARD_NOT_READY | NOT_FOUND | INTERNAL_ERROR",
  "message": "User-friendly message",
  "details": {
    "field": "optional",
    "hint": "optional"
  }
}
```

No filesystem paths may be returned in API payloads.

---

## 1) POST /api/upload

Purpose:

- accept workbook upload
- validate file type and basic readability
- create job ID

### Accepted input

- `multipart/form-data` with field `file`

### Validation rules

1. Extension must be `.xlsx` or `.xls`
2. File must be readable as workbook/CSV-style table compatible with `score_input_file.py` input expectations
3. Reject unsupported file content with friendly message

### Success response (example)

```json
{
  "ok": true,
  "job_id": "job_20260522_001",
  "original_filename": "karnataka.xlsx",
  "message": "Upload accepted."
}
```

### Failure class

- `error_type: UPLOAD_VALIDATION_FAILURE`

---

## 2) POST /api/process/{job_id}

Purpose:

- execute pipeline in fixed order:
  1. scoring
  2. potential enrichment

### Processing order (mandatory)

1. Run `score_input_file.py` logic
2. Run `add_potential_to_scored_file.py` logic

### Output schema guarantees

Churn output must be exactly:

1. `State`
2. `Customer name`
3. `Customer mobile number`
4. `Churn probability`
5. `Risk`

Final output must be exactly:

1. `State`
2. `Customer name`
3. `Customer mobile number`
4. `Churn probability`
5. `Risk`
6. `Potential`
7. `Potential Band`

### Behavioral requirements

1. Preserve input row order in generated outputs
2. Friendly error reporting
3. Distinguish failure stage:
   - churn run failure
   - potential run failure

### Success response (example)

```json
{
  "ok": true,
  "job_id": "job_20260522_001",
  "status": "completed",
  "counts": {
    "input_rows": 1200,
    "churn_rows": 1200,
    "final_rows": 1200
  },
  "message": "Processing completed successfully."
}
```

### Failure classes

1. `error_type: CHURN_RUN_FAILURE`
2. `error_type: POTENTIAL_RUN_FAILURE`

---

## 3) GET /api/dashboard/{job_id}

Purpose:

- return dashboard-ready JSON from final enriched output

Potential Level mapping source:

- `frontend/ui_bucket_config.json` (or backend-loaded equivalent contract file)

Must not silently drop unmapped combinations; apply explicit policy from config.

### Success response shape

```json
{
  "ok": true,
  "job_id": "job_20260522_001",
  "state_list": ["All", "Karnataka", "Maharashtra"],
  "risk_list": ["HIGH RISK", "MEDIUM RISK", "LOW RISK"],
  "potential_level_list": ["HIGH", "MEDIUM", "LOW", "OTHER"],
  "priority_bucket_counts": {
    "RED": 320,
    "ORANGE": 510,
    "GREEN": 290,
    "OTHER": 80
  },
  "counts_by_state": {
    "Karnataka": 640,
    "Maharashtra": 560
  },
  "counts_by_risk": {
    "HIGH RISK": 410,
    "MEDIUM RISK": 520,
    "LOW RISK": 270
  },
  "counts_by_potential_level": {
    "HIGH": 360,
    "MEDIUM": 420,
    "LOW": 340,
    "OTHER": 80
  },
  "influencer_records": [
    {
      "state": "Karnataka",
      "customer_name": "Example Name",
      "customer_mobile_number": "9000000000",
      "risk": "HIGH RISK",
      "potential_band": "15-25k",
      "potential_level": "MEDIUM",
      "priority_bucket": "RED"
    }
  ]
}
```

### Failure classes

1. `error_type: DASHBOARD_NOT_READY` (processing not complete)
2. `error_type: NOT_FOUND` (unknown job_id)

---

## 4) GET /api/download/{job_id}/final

Purpose:

- return final enriched output file from completed run

### Response

- file stream / attachment
- filename example: `job_20260522_001_final_output.csv` (or `.xlsx` if configured)

### Failure classes

1. `error_type: DASHBOARD_NOT_READY` (final output not produced yet)
2. `error_type: NOT_FOUND` (unknown job_id/file missing)

---

## Job Lifecycle States (Suggested)

1. `uploaded`
2. `processing_churn`
3. `processing_potential`
4. `completed`
5. `failed_upload_validation`
6. `failed_churn`
7. `failed_potential`

---

## Explicit Error Distinction Requirement

Backend must always distinguish and return clear user-facing messages for:

1. upload validation failure
2. churn run failure
3. potential run failure

This distinction is mandatory for UI messaging and operational troubleshooting.
