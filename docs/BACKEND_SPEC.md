# BACKEND_SPEC

Backend runtime source of truth:

1. `runtime/scripts/score_input_file.py`
2. `runtime/scripts/add_potential_to_scored_file.py`
3. `runtime/src/churn_model/`
4. `runtime/artifacts/production/`

Processing order contract:

1. run scoring script first
2. run potential enrichment script second

Expected output schemas:

Churn output:

- `State`
- `Customer name`
- `Customer mobile number`
- `Churn probability`
- `Risk`

Final output:

- `State`
- `Customer name`
- `Customer mobile number`
- `Churn probability`
- `Risk`
- `Potential`
- `Potential Band`

Constraint:

- do not use `client_handover/scripts` as runtime source.
