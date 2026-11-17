# UI checks: "הגשות עובדים" with injected leave (test data only)

Same check as `../submissions-tab/` (8 runs, 0 problems, `--expect-leave`), with approved leave injected by a test-only launcher (not committed):
תמר for the whole week (exempt: the "בחופשה" card shows 1 and its filter lists only her), אורי for two days (no submission) and דנה for one day
(with a submission; partial leave stays with her submission status). The real application has no leave data until Issue #28.
