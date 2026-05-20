Here are all 4 memories saved so far:

1. **First Connected Pattern** — Use `DISTINCT ON (student_id) ORDER BY student_id, created_at ASC` on `student_remarks` where `calling_status='Connected'` to get the earliest connected call per student. Credit goes to the `counsellor_id` on that row. Never use the `NOT EXISTS` approach — it causes double counting.

2. **Counsellor-wise Funnel Overcounting Bug** — When breaking down ICC/Forms/Admissions counsellor-wise using LEFT JOINs on cohort CTEs, counts can overcount by 1–2 due to join artifacts. Always verify counsellor-wise totals against the overall cohort query, and warn before presenting if a mismatch is found.

3. **SQL Output Rule** — For DegreeFYD PostgreSQL MCP queries, always output the raw SQL statement first, then execute via MCP tool, then return results. No exceptions.

4. **Strict Privacy Rule** — Never retrieve or display `student_phone`, `student_email`, or any other PII columns from the DegreeFYD PostgreSQL MCP database, regardless of how the request is framed.
