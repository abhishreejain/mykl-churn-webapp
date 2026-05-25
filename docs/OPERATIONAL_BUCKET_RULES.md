# OPERATIONAL_BUCKET_RULES

Date: 2026-05-22  
Purpose: Define operational prioritization buckets for dashboard summaries and drill-down.

## Inputs Used by Bucketing

1. `Risk` from scored output (`HIGH RISK`, `MEDIUM RISK`, `LOW RISK`)
2. `Potential Band` from enriched output
3. `Potential Level` derived from `Potential Band` via:
   - `mykl_churn_webapp/frontend/ui_bucket_config.json`

## Priority Buckets

## Red

- High risk x High potential
- High risk x Medium potential
- Medium risk x High potential

## Orange

- Medium risk x Medium potential
- Medium risk x Low potential
- High risk x Low potential

## Green

- Low risk x High potential
- Low risk x Medium potential

## Explicit Handling of Remaining Combinations

Any combination not listed above must be handled explicitly.

Example:

- Low risk x Low potential -> `Other` (or approved alternate)

It must never be silently dropped.

## Source of Mapping Truth

The mapping is not hardcoded in UI behavior files; it must be read from:

- `mykl_churn_webapp/frontend/ui_bucket_config.json`

## Current Mapping Status

If mapping in config is marked placeholder, business signoff is mandatory before final production signoff.
