# UI checks: "הגשות עובדים" with injected leave (test data only)

Same check as `../submissions-tab/` (8 runs, 0 problems, `--expect-leave`), but the instance was started through a test-only
launcher that injects approved leave: תמר for the whole week (exempt, not counted as missing), אורי for two days (no submission)
and דנה for one day (with a submission). The real application has no leave data until Issue #28; this folder only shows how the
report displays it.
