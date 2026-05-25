# STEP6_LOCAL_FIX_TEST

Date: 2026-05-22  
Backend URL used: `http://127.0.0.1:8010`

## Test Input

Workbook used:

- `outputs/web_smoke_process_input.xlsx`

## Test Steps and Results

1. Upload workbook (`POST /api/upload`)  
   Result: PASS

2. Receive job ID from upload response  
   Result: PASS

3. Run churn step via process route (`POST /api/process/{job_id}`)  
   Result: PASS

4. Run potential step (same process route, chained second stage)  
   Result: PASS

5. Final enriched output file created  
   Result: PASS

6. Dashboard JSON built from final enriched output  
   Result: PASS

7. Right-hand-side UI population path verified from final file-backed dashboard JSON  
   Result: PASS  
   Evidence: frontend flow executes `upload -> process -> dashboard fetch -> renderDashboard()` in `frontend/app.js`; dashboard endpoint source file is `final_enriched_output.csv`.

8. Final download endpoint works (`GET /api/download/{job_id}/final`)  
   Result: PASS

## Captured Responses

### Upload response payload

```json
{
  "ok": true,
  "job_id": "job_20260522_081525_09f453b3",
  "filename": "web_smoke_process_input.xlsx",
  "message": "Upload accepted.",
  "validation": {
    "ok": true,
    "row_count": 3,
    "resolved_identifier_columns": {
      "State": "State",
      "Name": "Customer Name",
      "MobileNo1": "mobileNo"
    },
    "scan_columns": [
      "Month 1 scan",
      "Month 2 scan",
      "Month 3 scan",
      "Month 4 scan",
      "Month 5 scan",
      "Month 6 scan"
    ],
    "scan_order_policy": "left_to_right_oldest_to_newest",
    "unusable_mobile_rows": 0
  }
}
```

### Job ID returned

- `job_20260522_081525_09f453b3`

### Process response summary

```json
{
  "ok": true,
  "job_id": "job_20260522_081525_09f453b3",
  "status": "completed",
  "message": "Processing completed successfully.",
  "counts": {
    "churn_rows": 3,
    "final_rows": 3
  },
  "stages": {
    "churn": { "return_code": 0, "status": "ok" },
    "potential": { "return_code": 0, "status": "ok" }
  }
}
```

### Churn output path

- `mykl_churn_webapp/backend/runtime/jobs/job_20260522_081525_09f453b3/output/churn_output.csv`

### Final enriched output path

- `mykl_churn_webapp/backend/runtime/jobs/job_20260522_081525_09f453b3/output/final_enriched_output.csv`

### Dashboard source verification

- Dashboard response includes:
  - `"source_file": "final_enriched_output.csv"`
- Confirms dashboard JSON was built from the final enriched output.

### Download verification

- Endpoint: `GET /api/download/job_20260522_081525_09f453b3/final`
- HTTP status: `200`
- Content type: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- Bytes returned: `5094`

## Log Summary

- Upload accepted with validation.
- Process route executed churn then potential in correct order.
- Both stage return codes were `0`.
- Final output and download artifact were present.
- Dashboard payload returned counts and influencer records from final output.

## Final Conclusion

- **PASS**

Acceptance condition met for Step 6:

- upload returns valid job ID
- both scripts run in order
- potential script consumes full churn output
- dashboard payload is final-output-driven
- download works

