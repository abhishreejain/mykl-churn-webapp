# RUNTIME_SOURCE_NOTE

This package copies runtime assets from the **original main-project runtime**, not from client handover scripts.

## Copied From Original Runtime

1. Source:
   - `scripts/score_input_file.py`
   - `scripts/add_potential_to_scored_file.py`
   Destination:
   - `mykl_churn_webapp/backend/runtime/scripts/score_input_file.py`
   - `mykl_churn_webapp/backend/runtime/scripts/add_potential_to_scored_file.py`

2. Source:
   - `src/churn_model/`
   Destination:
   - `mykl_churn_webapp/backend/runtime/src/churn_model/`

3. Source:
   - `artifacts/production/`
   Destination:
   - `mykl_churn_webapp/backend/runtime/artifacts/production/`

## Explicit Exclusion

Not copied for website runtime:

- `client_handover/scripts/*`

This ensures website backend runtime remains aligned to the original project execution path.
