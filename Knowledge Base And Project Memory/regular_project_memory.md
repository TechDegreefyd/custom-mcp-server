Here are all 14 saved memories for this project:

**#1 — Time Slot Reports**
Total Unique Remarks = COUNT(DISTINCT student_id) per hour slot (not remark_id). Time slots must be hourly (09:00–23:00). For Amity, split large queries to avoid timeout.

**#2 — College Status Report (Amity)**
PRIMARY source = student_college_credentials (scc) filtered by scc.created_at. FALLBACK = first CSJ entry for rows with no scc. Status = first CSJ course_status. UNION ALL both sources.

**#3 — L3 Form Performance Report**
Active Forms = Total minus Enrolled only (NI, Admission, OLR all count as active). Called days = GREATEST(0, days between form_created_at and first_remark_at). First remark = MIN(sr.created_at) by assigned L3 only.

**#4 — Always Ask Which Database**
Ask before every query. Options: regular_lms, regular_cgc_lms, regular_amity_lms. NEVER assume or use online_lms.

**#5 — Counsellor Level Ambiguity**
Default = L2. If prompt is ambiguous (e.g. "counsellor wise report"), STOP and ask L2 or L3 before running any query.

**#6 — Any Ambiguous Query**
STOP and ask for clarification before writing SQL. Never assume date range, metric, or report type.

**#7 — Payment Table Logic**
payment_for = 'application' or 'admission'. Only count COMPLETED status. L3 admissions = CSJ deposit_amount (offline) + payment table final_amount (online).

**#8 — Source-Wise Funnel Denominators**
Connected% = Connected/Leads, ICC% = ICC/Leads, L2F% = Forms/Attempted, F2A% = Adm/Forms, L2A% = Adm/ICC, PreNI% = PreNI/Leads. All use DISTINCT student_id.

**#9 — F2A Report (Verified)**
Forms = DISTINCT ON (student_id, course_id) ASC, 8-pipeline statuses, assigned_l3_counsellor_id IS NOT NULL. Admissions = no fee_type exclusion (all fee types valid). Exclude Amity University Jaipur. FULL OUTER JOIN.

**#10 — Campaign-Wise Queries**
Always deduplicate student_lead_activities to ONE row per student (DISTINCT ON student_id, created_at ASC) before joining. Use COALESCE(NULLIF(utm_campaign,''), 'Direct/Organic').

**#11 — MCP Query Protocol**
ALWAYS output raw SQL first, then execute via MCP tool, then return results. Never skip showing the SQL.

**#12 — Admissions Till Date (regular_lms)**
COUNT DISTINCT (student_id || '_' || course_id) from CSJ where status IN ('Admission','Enrolled'). NO fee_type exclusion. Ground truth = 296 pairs, 291 unique students.

**#13 — Admissions Till Date (regular_amity_lms)**
Same logic as #12. NO fee_type exclusion. Ground truth = 53 pairs, YTD Forms = 938.

**#14 — Privacy Rule**
NEVER share student phone numbers OR email addresses from any Regular LMS database in any query output, under any circumstances.
