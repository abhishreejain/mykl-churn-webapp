# DASHBOARD_BACKEND_LOGIC

Date: 2026-05-22

## Scope

This document describes the implemented backend service logic for:

- `backend/app/services/churn_service.py`
- `backend/app/services/potential_service.py`
- `backend/app/services/dashboard_service.py`

Runtime source remains the copied original runtime under:

- `backend/runtime/scripts/score_input_file.py`
- `backend/runtime/scripts/add_potential_to_scored_file.py`
- `backend/runtime/src/churn_model/`
- `backend/runtime/artifacts/production/`

`client_handover/scripts` is not used by these backend services.

---

## A) Processing Flow

Implemented flow:

1. Uploaded workbook path is validated by `validate_scoring_workbook(...)`.
2. Churn scoring runs via `run_churn_scoring(...)`, which calls original runtime `run_scoring_job(...)`.
3. Potential enrichment runs via `run_potential_enrichment(...)`, which calls original runtime `run_potential_enrichment_job(...)`.
4. Dashboard dataset is generated from final enriched output via `build_dashboard_dataset(...)`.

Orchestration helper:

- `run_pipeline_with_dashboard(...)` in `churn_service.py`

This helper returns churn result, potential result, and dashboard aggregates in one payload.

---

## B) Input Validation

Validation behavior for upload/scoring input:

1. Accepts only `.xlsx` and `.xls` extensions.
2. Uses original scoring rules for identifier alias resolution and scan inference:
   - `canonicalize_scoring_identifier_columns(...)`
   - `detect_scoring_scan_columns(...)`
   - `prepare_scoring_input(...)`
3. Applies the same duplicate policy as scoring runtime via runtime config (`scoring.duplicate_mobile_policy`).
4. Fails fast with `UploadValidationError` when workbook is not acceptable to scoring.

Validation summary returned includes:

- resolved identifier columns
- inferred scan columns
- scan order policy (`left_to_right_oldest_to_newest`)
- row count
- unusable mobile row count
- duplicate mobile row count after scoring-policy application

---

## C) Dashboard Aggregation

From final enriched output schema:

- `State`
- `Customer name`
- `Customer mobile number`
- `Churn probability`
- `Risk`
- `Potential`
- `Potential Band`

`build_dashboard_dataset(...)` returns:

1. `priority_bucket_counts` for `RED`, `ORANGE`, `GREEN`, `OTHER`
2. `counts_by_state`
3. `counts_by_risk`
4. `counts_by_potential_level`
5. `influencer_records` filterable by:
   - `state`
   - `risk`
   - `potential_level`

Row order is preserved using a stable row-order marker.

---

## D) Potential Mapping

Potential Band to Potential Level mapping is loaded from:

- `frontend/ui_bucket_config.json`

No hidden mapping is embedded in service code.

---

## E) Operational Priority Mapping

Risk x Potential Level to priority bucket mapping is loaded from:

- `frontend/ui_bucket_config.json`

Behavior for unmapped combinations:

- Unmapped combinations are explicitly routed to `OTHER`.
- They are reported in `warnings`.
- They are never silently dropped.

This satisfies explicit `Other` bucketing for leftovers.

---

## Error Distinction in Service Layer

Current service exceptions:

- `UploadValidationError` (upload/scoring input validation failure)
- `ChurnRunError` (churn stage runtime failure)
- `PotentialRunError` (potential stage runtime failure)
- `DashboardBuildError` (dashboard dataset generation failure)

These map cleanly to API-level friendly error responses.
