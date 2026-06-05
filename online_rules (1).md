# Online LMS Rules — Text-to-SQL Agent Reference

> **DB**: `degreefyd_online_lms` | 35,868 students | 53 tables | `storage.bhugoal.cloud:54321`
> **⚠️ NOT the same as Regular LMS**. Never use Regular rules, statuses, or supervisors here.
>
> **🔑 META-RULE**: These rules are your primary reference and first priority when writing queries. However, they are NOT gospel — the database can drift. When you get stuck, get unexpected results, or need to explore schema/value details beyond what's documented here, use the MCP tools (`mcp_lms_db_describe_table`, `mcp_lms_db_run_select_query`, `mcp_lms_db_get_table_context`) to verify against the live database. These rules prevent repeated mistakes; the MCP tool is your runtime truth.

# ONLINE DIVISION — TEXT-TO-SQL KNOWLEDGE BASE
# Always read RULES before generating any SQL.

---

## TABLES

---

### students
One row per student/lead. The primary funnel record.
Tracks identity, contact info, early funnel stage (`current_student_status`), lead source, assigned counsellors, ICC date, and demographic attributes like age, profession, highest degree.
Key columns: `student_id` (PK, STD-XXXX), `current_student_status`, `"first_Icc_Date"` (double-quoted, TIMESTAMPTZ), `assigned_counsellor_id` (L2), `assigned_counsellor_l3_id` (L3), `enrollment_counsellor_id`, `source`, `mode` (student's study preference — NOT course delivery mode), `preferred_university` (array), `preferred_course` (array), `created_at`, `updated_at`.

Funnel stages this table covers: `Pre Application`, `Initial Counselling Completed`, `NotInterested` (before application).
Funnel stages in `course_status_journeys`: `Application`, `Admission`, `Document Pending`, `Document Submitted`, `Enrolled`, `NotInterested` (after application).
Full order: Pre Application → Initial Counselling Completed → Application → Admission → Document Pending → Document Submitted → Enrolled

NI sub-status: `current_student_ni_sub_status` — only populated when `current_student_status = 'NotInterested'`. Use ONLY when query asks for NI breakdown by reason.

Fresh leads: NOT a `current_student_status` value to query unless user says "total fresh right now". For "fresh leads today" use:
```sql
WHERE created_at >= CURRENT_DATE - INTERVAL '5 hours 30 minutes'
  AND created_at < CURRENT_DATE + INTERVAL '1 day' - INTERVAL '5 hours 30 minutes'
```

---

### counsellors
One row per staff member or partner (L2, L3, team owners, admission counsellors, enrollment counsellors).
Tracks identity, role, manager hierarchy (`assigned_to` self-referential FK), status, lead capacity.
Key columns: `counsellor_id` (PK, CNS-XXXX staff / PAR-XXXX partner), `counsellor_name`, `role` ('l2','l3','to','admission_to','enrollment_counsellor'), `assigned_to` (manager's counsellor_id), `status` ('active','inactive','suspended'), `is_partner`.

Role -> FK mapping:
| Role | FK column on students/csj |
|------|--------------------------|
| l2 (general) | `students.assigned_counsellor_id` |
| l3 (senior) | `students.assigned_counsellor_l3_id` |
| enrollment_counsellor | `students.enrollment_counsellor_id` |
| admission_to | `course_status_journeys.enrollment_counsellor_id` |
| to (team owner) | `counsellors.assigned_to` (self-ref) |

Shift definition: first remark of the day = shift start; last remark = shift end.

---

### student_remarks
Append-only call log. One row per call attempt; multiple rows per student.
Tracks calling status, sub-status, free-text notes, callback date, fees discussed, and timestamps for each call attempt by a counsellor.
Key columns: `remark_id` (PK), `student_id`, `counsellor_id`, `calling_status` ('Connected'/'Not Connected'), `sub_calling_status`, `remarks` (TEXT), `callback_date` (DATE - never apply TZ offset), `feesAmount`, `created_at`.

Metrics:
- Raw connection: `calling_status = 'Connected'`
- Success / efficiency rate: `COUNT(Connected) / COUNT(all remarks)`
- Overdue callbacks: `callback_date < CURRENT_DATE`
- Upcoming callbacks: `callback_date >= CURRENT_DATE`
- Count callbacks by `remark_id`, not `student_id`
- First call per student: `ROW_NUMBER() OVER (PARTITION BY student_id ORDER BY created_at, remark_id) = 1`
- Latest remark per student: `DISTINCT ON (student_id) ORDER BY student_id, created_at DESC`

---

### university_courses
Master course catalog. One row per course offering at a university.
Tracks university name/location, degree/specialization/stream, fee structure (total, semester, annual), delivery mode, duration, status, USPs, and eligibility criteria.
Key columns: `course_id` (PK), `university_name` (ILIKE - spellings vary), `degree_name`, `specialization`, `stream`, `level` ('UG','PG','Diploma','Certificate'), `course_name`, `total_fees`, `semester_fees`, `annual_fees`, `study_mode` ('Online','Regular','Hybrid'), `duration`, `duration_type`, `status` ('active'/'inactive'), `usp` (TEXT[]), `eligibility` (TEXT[]).

Fee concepts:
- Course price / worth -> `total_fees`, `semester_fees`, `annual_fees`
- Actual payment collected -> `course_status_journeys.deposit_amount`
These are NEVER interchangeable.

---

### latest_course_statuses
Snapshot of current course-application status per student x course pair. One row per student-course.
Tracks whether a counsellor has shortlisted a course for a student and the API submission status.
Key columns: `id` (PK), `student_id`, `course_id`, `latest_course_status`, `college_api_sent_status`, `created_by`, `created_at`.

Use ONLY for:
- Shortlisted courses: `latest_course_status = 'Shortlisted'`
- Any payment snapshot: `latest_course_status ILIKE '%Paid%'`
- API status: `college_api_sent_status`
For Application/Admission/Enrolled/NI -> always use `course_status_journeys` instead.

---

### course_status_journeys
Full audit trail of every status change per student-course. One row per event; multiple rows per student.
Tracks course status progression, deposit payments, fee type, exam dates, counsellor notes, and enrollment counsellor.
Key columns: `status_history_id` (PK), `student_id`, `course_id`, `counsellor_id`, `course_status`, `deposit_amount`, `fee_type`, `enrollment_counsellor_id`, `created_at`.

Valid `course_status` values: `Application`, `Admission`, `Document Pending`, `Document Submitted`, `Enrolled`, `NotInterested`.

Valid `fee_type` values (normalize with `INITCAP(TRIM(fee_type))`):
`Annual Paid`, `Semester Paid`, `Semester Fee Paid`, `Full Fee Paid`, `One Year Fee Paid`, `1St Year Fee Paid`, `Registration Done`, `Partially Paid`, `Partial Done`, `partial paid`.

**CRITICAL: This table is append-only and contains duplicate rows.**
- Always use `COUNT(DISTINCT student_id)` - never `COUNT(*)`.
- For date-bounded stage counts (ANY status): always use `MIN(created_at)` per `(student_id, course_id)` first, then apply date filter outside.
- Latest status per student-course: `DISTINCT ON (student_id, course_id) ORDER BY student_id, course_id, created_at DESC`
- First occurrence of each status per student-course: `DISTINCT ON (student_id, course_id, course_status) ORDER BY student_id, course_id, course_status, created_at ASC`
- For Admission rows: ALWAYS exclude partial payments: `fee_type NOT IN ('partial paid', 'Partially Paid', 'Partial Done')`.
- Total fees collected: `SUM(deposit_amount) WHERE deposit_amount > 0` - deduplicate first (see RULE D1).

---

### student_lead_activities
Marketing touchpoint log. One row per activity; multiple per student.
Tracks UTM parameters, form/CTA data, device/browser, IP city, and IVR details for each web/ad interaction.
Key columns: `id` (PK), `student_id`, `utm_source`, `utm_medium`, `utm_campaign`, `utm_keyword`, `ip_city`, `source`, `form_name`, `cta_name`, `working_professional` (BOOLEAN), `highest_qualification`, `created_at`.

Use ONLY for marketing/campaign analysis. Never count students or funnel stages from this table.
- Geographic analysis -> `ip_city` (not students table)
- Working professional -> `working_professional` boolean (not `students.current_profession`)
- "Campaign X" / "utm campaign X" -> `sla.utm_campaign ILIKE '%X%'`
- "Leads from Facebook" -> `students.source ILIKE 'FaceBook%'` (students table, not this one)
- One city per student: `SELECT student_id, MAX(ip_city) FROM student_lead_activities WHERE ip_city IS NOT NULL AND ip_city != '' GROUP BY student_id`

---

### counsellor_break_logs
One row per break session taken by a counsellor.
Tracks break start/end times, duration (minutes/seconds/formatted), break type, and notes.
Key columns: `id` (PK), `counsellor_id`, `break_start` (TIMESTAMPTZ), `break_end` (TIMESTAMPTZ, NULL if ongoing), `duration` (minutes), `duration_formatted`, `break_type`, `created_at`.

- Ongoing break: `break_end IS NULL`
- `duration`/`duration_seconds` only populated after break ends
- Always apply IST timezone conversion on `break_start`/`break_end` filters

---

### l2_assignment_rulesets / admission_assignment_rulesets / lead_assignment_log
Three supporting tables for assignment rules and audit trails.

**l2_assignment_rulesets** - Rules for assigning leads to L2 counsellors. Key columns: `conditions` (JSONB), `assigned_counsellor_ids` (text[]), `is_active`, `priority`, `custom_rule_name`. Use `@>` or `->>` for JSONB filtering. Default: `WHERE is_active = true`.

**admission_assignment_rulesets** - Rules for assigning leads to admission counsellors. Key columns: `university_name` (text[]), `course_conditions` (JSONB), `source` (text[]), `assigned_counsellor_ids` (text[]), `is_active`, `custom_rule_name`. Arrays: use `'Value' = ANY(column)`.

**lead_assignment_log** - Audit trail of assignment events. Key columns: `student_id`, `assigned_counsellor_id`, `assigned_by` ('Ruleset Based'/'Manual'), `created_at`. Always apply IST TZ conversion.

---

## TIMEZONE — READ FIRST

Server is UTC. IST = UTC+5:30.

```sql
-- Today (IST)
WHERE created_at >= CURRENT_DATE - INTERVAL '5 hours 30 minutes'
  AND created_at <  CURRENT_DATE + INTERVAL '1 day' - INTERVAL '5 hours 30 minutes'

-- Yesterday
WHERE created_at >= CURRENT_DATE - INTERVAL '1 day' - INTERVAL '5 hours 30 minutes'
  AND created_at <  CURRENT_DATE - INTERVAL '5 hours 30 minutes'

-- Rolling N days
WHERE created_at >= CURRENT_DATE - INTERVAL 'N days' - INTERVAL '5 hours 30 minutes'
  AND created_at <  CURRENT_DATE + INTERVAL '1 day' - INTERVAL '5 hours 30 minutes'

-- Display
created_at AT TIME ZONE 'Asia/Kolkata'
```

- `callback_date` is type DATE — NEVER apply offset. Use `callback_date < CURRENT_DATE` directly.
- Hour extraction: `EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata')`
- NEVER use `NOW()` — always use `CURRENT_DATE` with the offset form above.
- NEVER alter user's interval value: `INTERVAL '6 months'` stays `'6 months'`, not `'5 months 24 days'`.

---

## RULES

---

### Output Rules

**O1.** Output only raw PostgreSQL SQL - no markdown, no comments, no explanations.
**O2.** Stage breakdown always in wide/pivot format - one row per entity, one column per stage via `COUNT(DISTINCT CASE WHEN ...)`. Never one row per status (long format).
**O3.** Dormant/no-follow-up/uncontacted queries MUST include `student_name` and `counsellor_name`.
**O4.** Counsellor performance queries MUST include `total_students` or `total_calls` as base column.
**O5.** Benchmark comparison queries MUST include the benchmark value as an explicit output column.
**O6.** Only return columns the user explicitly asked for. RULE O3 applies ONLY to dormant/follow-up queries - do NOT add extra columns to general listings.
**O7.** List queries MUST include ORDER BY. Use `created_at DESC` for call records unless specified.
**O8.** Any date/timestamp returned to user MUST be converted to IST: `AT TIME ZONE 'Asia/Kolkata'`. Always use `MIN(created_at)` (not raw) when selecting event dates from append-only tables.
**O9 (PRIVACY).** NEVER SELECT `student_phone`, `student_email`, or any other PII column under any circumstances — including dormant/follow-up queries, "student details", or "student info" requests. If the user explicitly names these columns in their question, respond that PII columns are restricted. No exceptions.

---

### Filter Rules

**F1.** NEVER add `counsellors.status = 'active'` unless user says "active counsellors".
**F2.** NEVER add `is_partner` filter unless user says "internal", "partner", or "external".
**F3.** NEVER add LIMIT unless user says "top N" or uses a superlative ("most/least/best/worst") -> then LIMIT 1.
**F4.** NEVER filter by `current_student_status` on a "total lead count over time" query.
**F5.** NEVER add a status WHERE clause on a full-funnel query - use UNION ALL or CASE WHEN.
**F6.** NEVER add HAVING unless user asks for a minimum threshold. Full-roster queries must include zero-result entities.
**F7.** "Many calls + low success" -> hardcoded: `HAVING COUNT(*) >= 10 AND (connected/total * 100) < 30`. Not dynamic averages.
**F8.** NEVER add WHERE filters not asked for. `WHERE manager.role = 'to'` is ONLY valid for all-teams queries (no specific manager named). NEVER add role filters unless user specifies.
**F9.** University name with location qualifier -> always AND, never OR:
- CORRECT: `uc.university_name ILIKE '%Chandigarh University%' AND uc.university_name ILIKE '%Lucknow%'`
- WRONG: `... ILIKE '%Chandigarh University%' OR ... ILIKE '%Lucknow%'`

---

### Table Selection Rules

**T1.** NEVER use `student_lead_activities` to count students or funnel stages. Marketing analysis only.
**T2.** NEVER query university-level student counts directly from `students`. Join chain: `students -> latest_course_statuses -> university_courses`.
**T3.** ALWAYS JOIN `counsellors` to get `counsellor_name`. Never construct names from other columns.
**T6.** NEVER use `students.mode` for course delivery. Use `university_courses.study_mode`.
**T7.** Call metrics: join `student_remarks` directly to `counsellors`. Do NOT route through `students` unless student data is also needed.
**T8.** Team performance: route through manager -> team_member (counsellors self-join) -> student_remarks.
**T9.** "Applications by source" -> `course_status_journeys JOIN students`, filter `course_status = 'Application'`, group by `students.source`.
**T11.** Fee column selection - NEVER interchangeable:
- "Total fee / course worth / admission fee / fee structure" -> `university_courses.total_fees`
- "Deposit / amount paid / payment collected / fees received" -> `course_status_journeys.deposit_amount`
**T12.** Every query on a child table MUST guard against orphaned records. If `students` is not explicitly JOINed, add: `WHERE student_id IN (SELECT student_id FROM students)`.

---

### Status / Column Rules

**S1.** `current_student_status` -> early funnel only (Pre Application, ICC, NI before application). For Application, Admission, Document Pending, Document Submitted, Enrolled, NI after application -> `course_status_journeys.course_status`.
**S3.** Count callbacks using `remark_id`, not `student_id`.
**S4.** NEVER use `students.remarks_count` for metrics. Use `COUNT(DISTINCT sr.remark_id)` after joining `student_remarks`.
**S5.** ALWAYS use `COUNT(DISTINCT student_id)` when counting students - never `COUNT(*)` after a JOIN.
**S8.** Time-slot / hourly performance: `EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata')` on `student_remarks`. Performance = Connected rate. Include `HAVING COUNT(*) > 0`.
**S9.** When query needs total count AND filtered subset for same entity -> use CASE WHEN inside COUNT, not WHERE (which drops rows).
**S10.** "Spread/distribution across teams" -> GROUP BY both manager AND team_member. Not one aggregated row per team.
**S12.** Total ICC count: ALWAYS use `"first_Icc_Date" IS NOT NULL` from `students`. Do NOT use `current_student_status = 'Initial Counselling Completed'` for this.
**S14.** Canonical ICC count: `SELECT COUNT(*) FROM students WHERE "first_Icc_Date" IS NOT NULL`
**S15.** TAT/average days: ALWAYS use `MIN(created_at)` per `(student_id, course_id)` in a CTE first. NEVER join raw `course_status_journeys` for time calculations. NEVER use `students.updated_at` or `student_remarks.created_at` for TAT.
**S16 (GLOBAL - Admission Dirty Data).** ANY reference to `course_status = 'Admission'` MUST append: `AND fee_type NOT IN ('partial paid', 'Partially Paid', 'Partial Done')`. Applies to COUNT, SUM, list, and join operations. Enrolled does NOT need this filter. Exclude 'Registration done' ONLY when user explicitly says so.
**S17.** Admission counts MUST use `COUNT(DISTINCT student_id)`. NEVER `COUNT(*)` on admission rows.
**S18 (GLOBAL - Append-Only Dedup).** ANY date-filtered query on `course_status_journeys`:
- Single status -> `MIN(created_at)` per `(student_id, course_id)`, then date filter outside (PATTERN 9).
- Multiple statuses in pivot -> `DISTINCT ON (student_id, course_id, course_status) ORDER BY student_id, course_id, course_status, created_at ASC`, then date filter outside (PATTERN 13).
NEVER filter raw `course_status_journeys.created_at` directly for date-bounded stage counts.

**S19 (DISTINCT ON for course_status_journeys).** When selecting one representative row per student-course, ALWAYS use `DISTINCT ON` - never rely on plain GROUP BY or unordered subquery MAX.
- Latest status per student-course: `DISTINCT ON (student_id, course_id) ORDER BY student_id, course_id, created_at DESC`
- First occurrence of a specific status: `DISTINCT ON (student_id, course_id) ORDER BY student_id, course_id, created_at ASC` (with WHERE on course_status)
- First occurrence of each status (multi-status pivot): `DISTINCT ON (student_id, course_id, course_status) ORDER BY student_id, course_id, course_status, created_at ASC`

---

### Join Rules

**J1.** Never OR across two counsellor FK columns in one JOIN. Use a single FK determined by context.
**J2.** NEVER filter by counsellor name on a base table. Always JOIN counsellors and use `c.counsellor_name ILIKE '%Name%'`.
**J3.** Counsellors -> student_remarks for call metrics: ALWAYS LEFT JOIN (includes zero-call counsellors).
**J4.** Conversion rate (application -> admission): use `course_status_journeys` with CASE WHEN for both counts in a single query.
**J5.** Two logically independent counts (different tables, no shared row context): NEVER join - use correlated subqueries or CROSS JOIN of single-row CTEs.
**J6.** Filter by person's name: ALWAYS `ILIKE '%Name%'` with leading+trailing wildcards.
**J7.** Child table without students JOIN -> ALWAYS add `WHERE student_id IN (SELECT student_id FROM students)`.
**J8.** Preserve LEFT JOINs. NEVER put child-table filters in WHERE when using LEFT JOIN for full roster - put them in the ON clause or use CASE WHEN.

---

### Deposit / Payment Rules

**D1 (NEVER SUM without dedup CTE).** Same payment can be logged multiple times. ALWAYS use this CTE before any `SUM(deposit_amount)`:
```sql
deduped_payments AS (
    SELECT DISTINCT ON (student_id, course_id, fee_type, created_at::DATE)
        student_id, course_id, deposit_amount,
        INITCAP(TRIM(fee_type)) AS fee_type_clean
    FROM course_status_journeys
    WHERE deposit_amount > 0
      AND student_id IN (SELECT student_id FROM students)
    ORDER BY student_id, course_id, fee_type, created_at::DATE, created_at DESC
)
```
`created_at DESC` ensures same-day corrections: latest amount wins. Do NOT include `deposit_amount` in the DISTINCT ON key.

**D2.** Admission dedup and payment dedup are independent:
- Admission -> `MIN(created_at)` per `(student_id, course_id)`
- Payment -> `DISTINCT ON (student_id, course_id, fee_type, created_at::DATE) ORDER BY ... created_at DESC`

**D3.** ALWAYS normalize fee_type: `INITCAP(TRIM(fee_type))`. Never aggregate or filter raw `fee_type`.

**D4.** Fee-type breakdown always in pivot format: `COUNT(DISTINCT CASE WHEN fee_type_clean = 'X' THEN student_id END)`. Never use `STRING_AGG`.

---

### Timezone Rules

All `created_at` columns store UTC. User expects IST (UTC+5:30). `CURRENT_DATE` is in IST.

**Case 1 - Explicit day (today/yesterday):**
```sql
WHERE created_at >= CURRENT_DATE - INTERVAL '5 hours 30 minutes'
  AND created_at <  CURRENT_DATE + INTERVAL '1 day' - INTERVAL '5 hours 30 minutes'
```

**Case 2 - Rolling interval (last N days/months):**
```sql
WHERE created_at >= CURRENT_DATE - INTERVAL 'N days' - INTERVAL '5 hours 30 minutes'
  AND created_at <  CURRENT_DATE + INTERVAL '1 day' - INTERVAL '5 hours 30 minutes'
```

**Case 3 - `callback_date` (type DATE):** NEVER apply timezone offset. Use `callback_date < CURRENT_DATE` directly.

**Case 4 - Hour extraction:** `EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata')`

**TZ1.** Always apply `- INTERVAL '5 hours 30 minutes'` to any `created_at` date boundary filter.
**TZ2.** NEVER alter user's specified interval value. Write `INTERVAL '6 months'` exactly - not `'5 months 24 days'`.
**TZ3.** SELECT alias derived via CASE/functions cannot be reused in complex ORDER BY expressions. Use CTE if ORDER BY logic is complex.
**TZ4.** Any returned timestamp -> convert with `AT TIME ZONE 'Asia/Kolkata'`. Never expose raw UTC.

---

## DISTINCTIONS

---

### D1 - Table Split by Funnel Stage

| User asks | Table | Column | Filter |
|---|---|---|---|
| Pre Application / ICC | students | `current_student_status` | `= 'Pre Application'` / `= 'Initial Counselling Completed'` |
| Application / "form filled" / "applied" | course_status_journeys | `course_status` | `= 'Application'` |
| Admission / "got admission" | course_status_journeys | `course_status` | `= 'Admission'` + partial exclusion |
| Document Pending / Submitted | course_status_journeys | `course_status` | `= 'Document Pending'` / `= 'Document Submitted'` |
| Enrolled | course_status_journeys | `course_status` | `= 'Enrolled'` |
| NI before application | students | `current_student_status` | `= 'NotInterested'` |
| NI after application | course_status_journeys | `course_status` | `= 'NotInterested'` |
| Shortlisted courses | latest_course_statuses | `latest_course_status` | `= 'Shortlisted'` |

---

### D2 - Admission vs Enrollment (CRITICAL)

- "admission" / "admissions" / "admitted" -> `course_status IN ('Admission', 'Enrolled')` for combined counts (enrolled = already admitted). ALWAYS exclude partial payments.
- "enrollment" / "enrolled" -> `course_status = 'Enrolled'` ONLY. Do NOT include Admission.

---

### D3 - "Success Rate" / "Performance" vs "Conversion Rate"

| User says | Correct table | Correct metric |
|---|---|---|
| "success rate", "efficiency", "performing well/best/worst" (counsellor/team) | student_remarks | `COUNT(Connected) / COUNT(all)` |
| "conversion rate", "admission rate", "how many students converted" | course_status_journeys | `COUNT(DISTINCT student_id WHERE course_status IN ('Admission','Enrolled'))` |
| "best/worst time slot", "peak performance hour" | student_remarks | Connected rate by hour |

---

### D4 - Three Meanings of "Connected"

| User says | Filter |
|---|---|
| "students connected by L2" | `students.is_connected_yet = true` |
| "students connected by L3" | `students.is_connected_yet_l3 = true` |
| "calls that were connected" | `student_remarks.calling_status = 'Connected'` |

---

### D5 - students.source vs student_lead_activities.source

| User says | Table |
|---|---|
| "leads from Facebook / Google / IVR" | `students.source ILIKE '...'` |
| "activities / form submits / touchpoints from Facebook" | `student_lead_activities.source ILIKE '...'` |
| "applications by source" | `course_status_journeys JOIN students`, group by `students.source` |
| "campaign X" / "utm campaign X" | `student_lead_activities.utm_campaign ILIKE '%X%'` |

---

### D6 - Interest vs Preference vs Shortlisted

| User asks | Table | Logic |
|---|---|---|
| "students interested in course" / "course interest" | course_status_journeys | `COUNT(DISTINCT student_id)` - students who took action |
| "students who prefer / stated" a course | students.preferred_course | `'Course Name' = ANY(preferred_course)` |
| "shortlisted courses" | latest_course_statuses | `latest_course_status = 'Shortlisted'` |

NEVER use `latest_course_statuses` for general interest. NEVER use `students.preferred_course` for interest metrics.

---

### D7 - Fee Column Selection

| User asks | Table | Column |
|---|---|---|
| "total fee / course worth / admission fee / fee structure" | university_courses | `total_fees` |
| "per-semester fee" | university_courses | `semester_fees` |
| "per-year fee" | university_courses | `annual_fees` |
| "deposit / amount paid / payment collected / fees received" | course_status_journeys | `deposit_amount` |

---

### D8 - NotInterested (NI) Variants

**NI-1 - Pre-application NI:** `SELECT COUNT(DISTINCT student_id) FROM students WHERE current_student_status = 'NotInterested';`

**NI-2 - Post-application NI:** `SELECT COUNT(DISTINCT student_id) FROM course_status_journeys WHERE course_status = 'NotInterested' AND student_id IN (SELECT student_id FROM students);`

**NI-3 - General NI (no qualifier) - UNION both tables:**
```sql
SELECT COUNT(DISTINCT student_id) AS total_ni FROM (
    SELECT student_id FROM students WHERE current_student_status = 'NotInterested'
    UNION
    SELECT student_id FROM course_status_journeys
    WHERE course_status = 'NotInterested' AND student_id IN (SELECT student_id FROM students)
) combined;
```
Date-filtered: `students` branch -> `updated_at`; `course_status_journeys` branch -> `created_at`.

**NI-4 - NI at a specific stage:**
```sql
-- Stage from students (Pre Application, ICC):
SELECT COUNT(DISTINCT student_id) FROM course_status_journeys
WHERE course_status = 'NotInterested'
AND student_id IN (SELECT student_id FROM students WHERE current_student_status = '[stage]');
-- Stage from csj (Application, Admission, etc.):
SELECT COUNT(DISTINCT student_id) FROM course_status_journeys
WHERE course_status = 'NotInterested'
AND student_id IN (SELECT student_id FROM course_status_journeys WHERE course_status = '[stage]');
```

**NI-5 - NI breakdown by reason:**
```sql
SELECT current_student_ni_sub_status, COUNT(*) AS count
FROM students WHERE current_student_status = 'NotInterested'
GROUP BY current_student_ni_sub_status ORDER BY count DESC;
```

**NI-6 - Pre-NI (NI with no ICC, never progressed):**
```sql
WITH never_progressed AS (
    SELECT s.student_id FROM students s
    WHERE s.current_student_status = 'NotInterested'
      AND s."first_Icc_Date" IS NULL
      AND s.student_id NOT IN (
          SELECT DISTINCT student_id FROM course_status_journeys
          WHERE course_status IN ('Application','Admission','Document Pending','Document Submitted','Enrolled')
      )
)
SELECT COUNT(DISTINCT np.student_id) AS pre_ni_count FROM never_progressed np
JOIN students s ON np.student_id = s.student_id;
```

**NI-7 - First NI (NI students whose first remark is in the date window):**
```sql
WITH first_ni_students AS (
    SELECT DISTINCT ON (sr.student_id) sr.student_id, sr.created_at AS first_ni_at
    FROM student_remarks sr
    INNER JOIN students s ON sr.student_id = s.student_id
    WHERE s.current_student_status = 'NotInterested'
    ORDER BY sr.student_id, sr.created_at ASC
)
SELECT COUNT(*) AS first_ni_count FROM first_ni_students
WHERE first_ni_at >= <start_ist> AND first_ni_at < <end_ist>;
```

---

## PATTERNS (Canonical Templates)

---

### PATTERN 1 - Funnel Breakdown (UNION ALL)
```sql
SELECT 'Total Leads' AS stage, COUNT(DISTINCT student_id) AS count FROM students
UNION ALL SELECT 'Pre Application', COUNT(DISTINCT student_id) FROM students WHERE current_student_status = 'Pre Application'
UNION ALL SELECT 'Initial Counselling Completed', COUNT(DISTINCT student_id) FROM students WHERE current_student_status = 'Initial Counselling Completed'
UNION ALL SELECT 'Application', COUNT(DISTINCT student_id) FROM course_status_journeys WHERE course_status = 'Application'
UNION ALL SELECT 'Admission', COUNT(DISTINCT student_id) FROM course_status_journeys WHERE course_status = 'Admission' AND fee_type NOT IN ('partial paid','Partially Paid','Partial Done')
UNION ALL SELECT 'Document Pending', COUNT(DISTINCT student_id) FROM course_status_journeys WHERE course_status = 'Document Pending'
UNION ALL SELECT 'Document Submitted', COUNT(DISTINCT student_id) FROM course_status_journeys WHERE course_status = 'Document Submitted'
UNION ALL SELECT 'Enrolled', COUNT(DISTINCT student_id) FROM course_status_journeys WHERE course_status = 'Enrolled';
```

---

### PATTERN 2 - Stage Breakdown per Counsellor (Pivot)
```sql
SELECT
    c.counsellor_name,
    COUNT(DISTINCT s.student_id) AS total_students,
    COUNT(DISTINCT CASE WHEN s.current_student_status = 'Pre Application' THEN s.student_id END) AS pre_application,
    COUNT(DISTINCT CASE WHEN csj.course_status = 'Application' THEN csj.student_id END) AS applications,
    COUNT(DISTINCT CASE WHEN csj.course_status IN ('Admission','Enrolled') AND (csj.course_status = 'Enrolled' OR csj.fee_type NOT IN ('partial paid','Partially Paid','Partial Done')) THEN csj.student_id END) AS admissions,
    COUNT(DISTINCT CASE WHEN csj.course_status = 'Enrolled' THEN csj.student_id END) AS enrolled
FROM counsellors c
JOIN students s ON c.counsellor_id = s.assigned_counsellor_id
LEFT JOIN course_status_journeys csj ON s.student_id = csj.student_id
GROUP BY c.counsellor_id, c.counsellor_name
ORDER BY total_students DESC;
```

---

### PATTERN 3 - Counsellor Call Performance
```sql
SELECT
    c.counsellor_name,
    COUNT(sr.remark_id) AS total_calls,
    COUNT(CASE WHEN sr.calling_status = 'Connected' THEN 1 END) AS connected_calls,
    ROUND(COUNT(CASE WHEN sr.calling_status = 'Connected' THEN 1 END) * 100.0 / NULLIF(COUNT(sr.remark_id), 0), 2) AS success_rate
FROM counsellors c
LEFT JOIN student_remarks sr ON c.counsellor_id = sr.counsellor_id
GROUP BY c.counsellor_id, c.counsellor_name
HAVING COUNT(sr.remark_id) > 0
ORDER BY success_rate DESC;
```

---

### PATTERN 4 - Team Call Performance
```sql
SELECT
    manager.counsellor_name AS team_owner,
    COUNT(sr.remark_id) AS total_calls,
    COUNT(CASE WHEN sr.calling_status = 'Connected' THEN 1 END) AS connected_calls,
    ROUND(COUNT(CASE WHEN sr.calling_status = 'Connected' THEN 1 END) * 100.0 / NULLIF(COUNT(sr.remark_id), 0), 2) AS success_rate
FROM counsellors manager
LEFT JOIN counsellors team_member ON manager.counsellor_id = team_member.assigned_to
LEFT JOIN student_remarks sr ON team_member.counsellor_id = sr.counsellor_id
WHERE manager.role = 'to'
GROUP BY manager.counsellor_id, manager.counsellor_name
ORDER BY success_rate DESC;
```

---

### PATTERN 5 - Benchmark / Above-Below Average
```sql
WITH metrics AS (
    SELECT c.counsellor_id, c.counsellor_name,
        COUNT(sr.remark_id) AS total_calls,
        ROUND(COUNT(CASE WHEN sr.calling_status = 'Connected' THEN 1 END) * 100.0 / NULLIF(COUNT(sr.remark_id), 0), 2) AS success_rate
    FROM counsellors c
    LEFT JOIN student_remarks sr ON c.counsellor_id = sr.counsellor_id
    GROUP BY c.counsellor_id, c.counsellor_name
    HAVING COUNT(sr.remark_id) > 0
),
benchmark AS (SELECT AVG(success_rate) AS avg_rate, STDDEV(success_rate) AS stddev_rate FROM metrics)
SELECT m.*, b.avg_rate AS benchmark_avg,
    CASE WHEN m.success_rate >= b.avg_rate + b.stddev_rate THEN 'Above Average'
         WHEN m.success_rate <= b.avg_rate - b.stddev_rate THEN 'Below Average'
         ELSE 'Average' END AS performance_band
FROM metrics m CROSS JOIN benchmark b
ORDER BY m.success_rate DESC;
```

---

### PATTERN 6 - Dormant Students (no remark in last 7 days)
```sql
SELECT s.student_name, c.counsellor_name, csj.course_status,
    MAX(sr.created_at) AS last_remark_date
FROM students s
JOIN course_status_journeys csj ON s.student_id = csj.student_id
JOIN counsellors c ON s.assigned_counsellor_id = c.counsellor_id
LEFT JOIN student_remarks sr ON s.student_id = sr.student_id
WHERE (csj.course_status = 'Application'
    OR (csj.course_status IN ('Admission','Enrolled') AND (csj.course_status = 'Enrolled' OR csj.fee_type NOT IN ('partial paid','Partially Paid','Partial Done'))))
GROUP BY s.student_id, s.student_name, c.counsellor_name, csj.course_status
HAVING MAX(sr.created_at) < CURRENT_DATE - INTERVAL '7 days' OR MAX(sr.created_at) IS NULL
ORDER BY last_remark_date ASC NULLS FIRST;
```

---

### PATTERN 7 - University Stage Deduplication (Student at Highest Stage)
```sql
WITH stage_priority AS (
    SELECT uc.university_name, csj.student_id,
        MAX(CASE
            WHEN csj.course_status = 'Enrolled' THEN 6
            WHEN csj.course_status = 'Document Submitted' THEN 5
            WHEN csj.course_status = 'Document Pending' THEN 4
            WHEN csj.course_status = 'Admission' AND csj.fee_type NOT IN ('partial paid','Partially Paid','Partial Done') THEN 3
            WHEN csj.course_status = 'Application' THEN 2
            ELSE 0
        END) AS final_rank
    FROM university_courses uc
    JOIN course_status_journeys csj ON uc.course_id = csj.course_id
    GROUP BY uc.university_name, csj.student_id
)
SELECT university_name,
    COUNT(*) FILTER (WHERE final_rank = 2) AS applications,
    COUNT(*) FILTER (WHERE final_rank = 3) AS admissions,
    COUNT(*) FILTER (WHERE final_rank = 4) AS document_pending,
    COUNT(*) FILTER (WHERE final_rank = 5) AS document_submitted,
    COUNT(*) FILTER (WHERE final_rank = 6) AS enrolled
FROM stage_priority GROUP BY university_name ORDER BY admissions DESC;
```

---

### PATTERN 8 - Conversion Rate (Application -> Admission)
```sql
SELECT
    COUNT(DISTINCT CASE WHEN csj.course_status = 'Application' THEN csj.student_id END) AS applications,
    COUNT(DISTINCT CASE WHEN csj.course_status = 'Admission' AND csj.fee_type NOT IN ('partial paid','Partially Paid','Partial Done') THEN csj.student_id END) AS admissions,
    ROUND(
        COUNT(DISTINCT CASE WHEN csj.course_status = 'Admission' AND csj.fee_type NOT IN ('partial paid','Partially Paid','Partial Done') THEN csj.student_id END) * 100.0 /
        NULLIF(COUNT(DISTINCT CASE WHEN csj.course_status = 'Application' THEN csj.student_id END), 0), 2
    ) AS conversion_rate
FROM course_status_journeys csj;
```

---

### PATTERN 9 - Date-Filtered Count (ANY Single Status)
Use for ALL date-bounded queries: "admitted today", "enrolled this week", "applications yesterday".
```sql
SELECT COUNT(DISTINCT student_id) AS count
FROM (
    SELECT student_id, MIN(created_at) AS first_event_date
    FROM course_status_journeys
    WHERE course_status = '<Status>'
      AND fee_type NOT IN ('partial paid','Partially Paid','Partial Done')  -- add ONLY for Admission
      AND student_id IN (SELECT student_id FROM students)
    GROUP BY student_id
) sub
WHERE first_event_date >= CURRENT_DATE - INTERVAL 'N days' - INTERVAL '5 hours 30 minutes'
  AND first_event_date <  CURRENT_DATE + INTERVAL '1 day' - INTERVAL '5 hours 30 minutes';
```

---

### PATTERN 10 - First Connected Count (Total + Counsellor-wise)
**Total:**
```sql
WITH first_connected_dates AS (
    SELECT student_id, MIN(created_at) AS first_connected_at
    FROM student_remarks
    WHERE calling_status = 'Connected' AND student_id IN (SELECT student_id FROM students)
    GROUP BY student_id
)
SELECT COUNT(DISTINCT fcd.student_id) AS first_connected_count
FROM first_connected_dates fcd
WHERE fcd.first_connected_at >= <start_ist> AND fcd.first_connected_at < <end_ist>;
```

**Counsellor-wise (INNER JOIN intentional - only counsellors who made first-connected calls appear):**
```sql
SELECT c.counsellor_name, COUNT(DISTINCT sr.student_id) AS first_connected_count
FROM student_remarks sr
JOIN counsellors c ON c.counsellor_id = sr.counsellor_id
WHERE sr.calling_status = 'Connected'
  AND sr.student_id IN (SELECT student_id FROM students)
  AND sr.created_at = (SELECT MIN(sr2.created_at) FROM student_remarks sr2
                       WHERE sr2.student_id = sr.student_id AND sr2.calling_status = 'Connected')
  AND sr.created_at >= <start_ist> AND sr.created_at < <end_ist>
GROUP BY c.counsellor_id, c.counsellor_name
ORDER BY first_connected_count DESC;
```

---

### PATTERN 11 - Pre-NI Students (Date-Filtered, Counsellor-wise)
```sql
SELECT c.counsellor_name, COUNT(DISTINCT s.student_id) AS pre_ni_count
FROM students s
JOIN counsellors c ON s.assigned_counsellor_id = c.counsellor_id
WHERE s.current_student_status = 'NotInterested'
  AND s."first_Icc_Date" IS NULL
  AND s.student_id NOT IN (
      SELECT DISTINCT student_id FROM course_status_journeys
      WHERE course_status IN ('Application','Admission','Document Pending','Document Submitted','Enrolled')
  )
  AND s.created_at >= <start_ist> AND s.created_at < <end_ist>
GROUP BY c.counsellor_id, c.counsellor_name
ORDER BY pre_ni_count DESC;
```
INNER JOIN intentional. Switch to LEFT JOIN if user wants all counsellors.

---

### PATTERN 12 - Attempted Calls / Total Leads on New Students (Counsellor-wise)
Date filter in JOIN ON clause - not WHERE. `WHERE sr.student_id IS NOT NULL` intentional (only counsellors who attempted appear).
- **Variant A (attempted only):** remove `COUNT(DISTINCT s.student_id) AS total_leads`
- **Variant B (total + attempted):** keep both counts
```sql
SELECT c.counsellor_name,
    COUNT(DISTINCT s.student_id) AS total_leads,
    COUNT(DISTINCT sr.student_id) AS total_attempted_leads
FROM counsellors c
LEFT JOIN students s ON c.counsellor_id = s.assigned_counsellor_id
LEFT JOIN student_remarks sr ON s.student_id = sr.student_id
    AND s.created_at >= <start_ist>
    AND s.created_at <  <end_ist>
WHERE sr.student_id IS NOT NULL
GROUP BY c.counsellor_id, c.counsellor_name
ORDER BY total_attempted_leads DESC;
```

---

### PATTERN 13 - Multiple Status Breakdown by Date Window (Pivot)
```sql
SELECT uc.university_name,
    COUNT(DISTINCT CASE WHEN fs.course_status = 'Application' THEN fs.student_id END) AS applications,
    COUNT(DISTINCT CASE WHEN fs.course_status = 'Admission' THEN fs.student_id END) AS admissions
FROM (
    SELECT DISTINCT ON (student_id, course_id, course_status)
        student_id, course_id, course_status, created_at
    FROM course_status_journeys
    WHERE course_status IN ('Application','Admission')
      AND student_id IN (SELECT student_id FROM students)
    ORDER BY student_id, course_id, course_status, created_at ASC
) fs
JOIN university_courses uc ON fs.course_id = uc.course_id
WHERE fs.created_at >= CURRENT_DATE - INTERVAL '5 hours 30 minutes'
  AND fs.created_at <  CURRENT_DATE + INTERVAL '1 day' - INTERVAL '5 hours 30 minutes'
GROUP BY uc.university_name;
```

---

### PATTERN 14 - NI Reason Breakdown by Campaign
```sql
WITH fresh_leads AS (
    SELECT student_id FROM students
    WHERE created_at >= CURRENT_DATE - INTERVAL '5 hours 30 minutes'
      AND created_at < CURRENT_DATE + INTERVAL '1 day' - INTERVAL '5 hours 30 minutes'
),
campaign_totals AS (
    SELECT COALESCE(sla.utm_campaign, 'Direct/Organic') AS campaign,
        COUNT(DISTINCT fl.student_id) AS total_leads
    FROM fresh_leads fl
    LEFT JOIN student_lead_activities sla ON fl.student_id = sla.student_id
    GROUP BY 1
),
status_breakdown AS (
    SELECT COALESCE(sla.utm_campaign, 'Direct/Organic') AS campaign,
        COALESCE(s.current_student_ni_sub_status, 'Reason Not Given') AS not_interested_reason,
        COUNT(DISTINCT fl.student_id) AS ni_count
    FROM fresh_leads fl
    JOIN students s ON fl.student_id = s.student_id
    LEFT JOIN student_lead_activities sla ON fl.student_id = sla.student_id
    WHERE s.current_student_status = 'NotInterested'
    GROUP BY 1, 2
)
SELECT ct.campaign, ct.total_leads, sb.not_interested_reason, sb.ni_count,
    ROUND(sb.ni_count::numeric * 100.0 / ct.total_leads, 2) AS percentage_of_total
FROM campaign_totals ct
JOIN status_breakdown sb ON ct.campaign = sb.campaign
ORDER BY ct.total_leads DESC, sb.ni_count DESC;
```
When sub_status is NULL use `'Reason Not Given'` - NOT `'Interested / In-Progress'`.

---

### PATTERN 15 - TAT (Average Days to Admission/Enrollment)
```sql
SELECT ROUND(AVG(EXTRACT(EPOCH FROM (sub.first_milestone_date - s.created_at)) / 86400)::numeric, 1) AS avg_tat_days
FROM students s
JOIN (
    SELECT student_id, course_id, MIN(created_at) AS first_milestone_date
    FROM course_status_journeys
    WHERE (course_status = 'Admission' AND fee_type NOT IN ('partial paid','Partially Paid','Partial Done'))
       OR course_status = 'Enrolled'
    GROUP BY student_id, course_id
) sub ON s.student_id = sub.student_id
WHERE s.created_at IS NOT NULL AND sub.first_milestone_date IS NOT NULL;
```

---

### PATTERN 16 - Fee Summary (Canonical Base)
```sql
WITH admitted_students AS (
    SELECT student_id, course_id, MIN(created_at) AS first_admission_date
    FROM course_status_journeys
    WHERE course_status IN ('Admission','Enrolled')
      AND (course_status = 'Enrolled' OR fee_type NOT IN ('partial paid','Partially Paid','Partial Done'))
      AND student_id IN (SELECT student_id FROM students)
    GROUP BY student_id, course_id
),
deduped_payments AS (
    SELECT DISTINCT ON (student_id, course_id, fee_type, created_at::DATE)
        student_id, course_id, deposit_amount, INITCAP(TRIM(fee_type)) AS fee_type_clean
    FROM course_status_journeys
    WHERE deposit_amount > 0 AND student_id IN (SELECT student_id FROM students)
    ORDER BY student_id, course_id, fee_type, created_at::DATE, created_at DESC
),
payments AS (
    SELECT student_id, course_id, SUM(deposit_amount) AS total_deposit_collected
    FROM deduped_payments GROUP BY student_id, course_id
)
SELECT
    uc.university_name,
    COUNT(DISTINCT adm.student_id) AS total_admitted_students,
    SUM(uc.total_fees) AS total_course_worth,
    COALESCE(SUM(p.total_deposit_collected), 0) AS total_deposit_collected,
    SUM(uc.total_fees) - COALESCE(SUM(p.total_deposit_collected), 0) AS total_fee_remaining,
    COUNT(DISTINCT CASE WHEN dp.fee_type_clean = 'Semester Paid' THEN dp.student_id END) AS semester_paid,
    COUNT(DISTINCT CASE WHEN dp.fee_type_clean = 'Full Fee Paid' THEN dp.student_id END) AS full_fee_paid,
    COUNT(DISTINCT CASE WHEN dp.fee_type_clean = 'Annual Paid' THEN dp.student_id END) AS annual_paid,
    COUNT(DISTINCT CASE WHEN dp.fee_type_clean = 'Registration Done' THEN dp.student_id END) AS registration_done,
    COUNT(DISTINCT CASE WHEN dp.fee_type_clean IN ('Partially Paid','Partial Done','Partial Paid') THEN dp.student_id END) AS partially_paid
FROM admitted_students adm
JOIN university_courses uc ON adm.course_id = uc.course_id
LEFT JOIN payments p ON adm.student_id = p.student_id AND adm.course_id = p.course_id
LEFT JOIN deduped_payments dp ON adm.student_id = dp.student_id AND adm.course_id = dp.course_id
GROUP BY uc.university_name
ORDER BY total_deposit_collected DESC;
```
Adapt grouping: by course -> add `uc.course_name`; by counsellor -> join via `students.enrollment_counsellor_id`.

---

### PATTERN 17 - Counsellor Login / Logout (Shift Times)
```sql
SELECT
    c.counsellor_name,
    MIN(sr.created_at AT TIME ZONE 'Asia/Kolkata') AS login_time,
    MAX(sr.created_at AT TIME ZONE 'Asia/Kolkata') AS logout_time,
    EXTRACT(EPOCH FROM (MAX(sr.created_at) - MIN(sr.created_at))) / 3600 AS working_hours
FROM counsellors c
JOIN student_remarks sr ON c.counsellor_id = sr.counsellor_id
WHERE sr.created_at >= CURRENT_DATE - INTERVAL '5 hours 30 minutes'
  AND sr.created_at <  CURRENT_DATE + INTERVAL '1 day' - INTERVAL '5 hours 30 minutes'
  AND EXTRACT(HOUR FROM sr.created_at AT TIME ZONE 'Asia/Kolkata') * 60
      + EXTRACT(MINUTE FROM sr.created_at AT TIME ZONE 'Asia/Kolkata') BETWEEN 570 AND 1230
  AND sr.student_id IN (SELECT student_id FROM students)
GROUP BY c.counsellor_id, c.counsellor_name
ORDER BY login_time ASC;
```
Login = 9:30 AM (570 min), Logout = 8:30 PM (1230 min). For specific counsellor add: `AND c.counsellor_name ILIKE '%name%'`.

---

### PATTERN 18 - Daily Activity Summary (Yesterday)
```sql
WITH first_icc AS (
    SELECT COUNT(DISTINCT student_id) AS icc_count FROM students
    WHERE "first_Icc_Date" >= CURRENT_DATE - INTERVAL '1 day' - INTERVAL '5 hours 30 minutes'
      AND "first_Icc_Date" < CURRENT_DATE - INTERVAL '5 hours 30 minutes'
),
first_ni AS (
    SELECT COUNT(*) AS ni_count FROM (
        SELECT DISTINCT ON (sr.student_id) sr.created_at AS first_ni_at
        FROM student_remarks sr
        INNER JOIN students s ON sr.student_id = s.student_id
        WHERE s.current_student_status = 'NotInterested'
        ORDER BY sr.student_id, sr.created_at ASC
    ) sub
    WHERE first_ni_at >= CURRENT_DATE - INTERVAL '1 day' - INTERVAL '5 hours 30 minutes'
      AND first_ni_at < CURRENT_DATE - INTERVAL '5 hours 30 minutes'
),
first_connected AS (
    SELECT COUNT(DISTINCT student_id) AS connected_count FROM (
        SELECT student_id, MIN(created_at) AS first_connected_at
        FROM student_remarks WHERE calling_status = 'Connected' GROUP BY student_id
    ) sub
    WHERE first_connected_at >= CURRENT_DATE - INTERVAL '1 day' - INTERVAL '5 hours 30 minutes'
      AND first_connected_at < CURRENT_DATE - INTERVAL '5 hours 30 minutes'
)
SELECT
    (SELECT icc_count FROM first_icc) AS total_first_icc,
    (SELECT ni_count FROM first_ni) AS total_first_ni,
    (SELECT connected_count FROM first_connected) AS total_first_connected;
```

---

### 🚨 PATTERN 19 - Lead-Cohort Funnel Metrics (Leads of Day X)

**⚠️ CRITICAL: When the user asks for metrics on leads that came on day X, ALL funnel metrics use "ever" (all-time) filters, NOT same-day.**

The only date filter is on `students.created_at` for the lead cohort. Every downstream metric is unlimited datewise:

| Metric | Filter | Why |
|--------|--------|-----|
| Leads | `students.created_at` = IST day X | The cohort |
| Attempted | any remark, any date | Ever touched |
| Connected | `calling_status='Connected'`, any date | Ever connected |
| ICC | `first_Icc_Date IS NOT NULL` — **NO date filter** | Ever ICC'd |
| Forms | `course_status='Application'`, any date | Ever applied |
| Admissions | `course_status IN ('Admission','Enrolled')` + partial exclusion, any date | Ever admitted |
| Pre-NI | NI + no ICC + no progression | Ever NI'd out |

Connected% = connected/attempted (NOT connected/leads).

```sql
-- Golden query — Leads of day X funnel
WITH cohort AS (
    SELECT student_id FROM students
    WHERE created_at >= 'YYYY-MM-DD 18:30:00+00'::timestamptz
      AND created_at <  'YYYY-MM-DD+1 18:30:00+00'::timestamptz
),
attempted AS (
    SELECT DISTINCT sr.student_id FROM student_remarks sr
    JOIN cohort m ON sr.student_id = m.student_id
    WHERE sr.isdisabled = false
),
connected AS (
    SELECT DISTINCT sr.student_id FROM student_remarks sr
    JOIN cohort m ON sr.student_id = m.student_id
    WHERE sr.calling_status = 'Connected' AND sr.isdisabled = false
),
icc AS (
    SELECT s.student_id FROM students s
    JOIN cohort m ON s.student_id = m.student_id
    WHERE s."first_Icc_Date" IS NOT NULL  -- EVER, NOT same-day
),
forms AS (
    SELECT DISTINCT csj.student_id FROM course_status_journeys csj
    JOIN cohort m ON csj.student_id = m.student_id
    WHERE csj.course_status = 'Application'
),
admissions AS (
    SELECT DISTINCT csj.student_id FROM course_status_journeys csj
    JOIN cohort m ON csj.student_id = m.student_id
    WHERE csj.course_status IN ('Admission', 'Enrolled')
      AND (csj.course_status != 'Admission' OR csj.fee_type NOT IN ('partial paid','Partially Paid','Partial Done'))
),
pre_ni AS (
    SELECT s.student_id FROM students s
    JOIN cohort m ON s.student_id = m.student_id
    WHERE s.current_student_status = 'NotInterested'
      AND s."first_Icc_Date" IS NULL
      AND s.student_id NOT IN (
          SELECT DISTINCT student_id FROM course_status_journeys
          WHERE course_status IN ('Application','Admission','Document Pending','Document Submitted','Enrolled')
      )
)
SELECT
    (SELECT COUNT(*) FROM cohort) AS leads,
    (SELECT COUNT(*) FROM attempted) AS attempted,
    (SELECT COUNT(*) FROM connected) AS connected,
    (SELECT COUNT(*) FROM icc) AS icc_done,
    (SELECT COUNT(*) FROM forms) AS forms,
    (SELECT COUNT(*) FROM admissions) AS admission,
    (SELECT COUNT(*) FROM pre_ni) AS pre_ni,
    ROUND((SELECT COUNT(*)::numeric FROM connected) / NULLIF((SELECT COUNT(*) FROM attempted), 0) * 100, 1) AS connected_pct,
    ROUND((SELECT COUNT(*)::numeric FROM icc) / NULLIF((SELECT COUNT(*) FROM cohort), 0) * 100, 1) AS icc_pct,
    ROUND((SELECT COUNT(*)::numeric FROM forms) / NULLIF((SELECT COUNT(*) FROM cohort), 0) * 100, 1) AS lead_to_form_pct,
    ROUND((SELECT COUNT(*)::numeric FROM admissions) / NULLIF((SELECT COUNT(*) FROM forms), 0) * 100, 1) AS form_to_admission_pct,
    ROUND((SELECT COUNT(*)::numeric FROM admissions) / NULLIF((SELECT COUNT(*) FROM cohort), 0) * 100, 1) AS lead_to_admission_pct,
    ROUND((SELECT COUNT(*)::numeric FROM pre_ni) / NULLIF((SELECT COUNT(*) FROM cohort), 0) * 100, 1) AS pre_ni_pct;
```

### RULE CSJ-GROUPING - Consistent Counts Across Grouping Dimensions
When grouping by different dimensions (e.g. university only vs university + campaign), counts MUST match. Resolve one-to-many joins to a single row per student via CTE; use identical WHERE clauses including NULL handling.
```sql
WITH student_campaigns AS (
    SELECT DISTINCT student_id, COALESCE(utm_campaign, 'Direct/Organic') AS campaign
    FROM student_lead_activities
    WHERE id = (SELECT MAX(id) FROM student_lead_activities sla2
                WHERE sla2.student_id = student_lead_activities.student_id)
)
SELECT uc.university_name, COALESCE(sc.campaign, 'Direct/Organic') AS campaign,
    COUNT(DISTINCT csj.student_id) AS admission_count
FROM course_status_journeys csj
JOIN university_courses uc ON csj.course_id = uc.course_id
LEFT JOIN student_campaigns sc ON csj.student_id = sc.student_id
WHERE csj.course_status = 'Admission'
  AND (csj.fee_type NOT IN ('partial paid','Partially Paid','Partial Done') OR csj.fee_type IS NULL)
  AND csj.student_id IN (SELECT student_id FROM students)
GROUP BY uc.university_name, COALESCE(sc.campaign, 'Direct/Organic')
ORDER BY admission_count DESC;
```

---

## NATURAL LANGUAGE -> SQL INTENT (Quick Reference)

| User says | SQL intent |
|---|---|
| "form filled" / "form fills" / "applied" | `course_status = 'Application'` on `course_status_journeys` |
| "admitted" / "got admission" | `course_status = 'Admission'` + exclude partial fee_types |
| "enrolled" | `course_status = 'Enrolled'` on `course_status_journeys` |
| "converted" / "admitted or beyond" | `course_status IN ('Admission','Document Pending','Document Submitted','Enrolled')` |
| "admissions today / yesterday / this month" | MIN(created_at) per (student_id, course_id) -> PATTERN 9 |
| "total ICC" / "ICC count" | `COUNT(*) WHERE "first_Icc_Date" IS NOT NULL` from students |
| "success rate" / "efficiency" (counsellor) | Connected/Total from student_remarks |
| "conversion rate" (student outcomes) | Admission+Enrolled / Total from course_status_journeys |
| "shortlisted" | `latest_course_status = 'Shortlisted'` from latest_course_statuses |
| "NI" (no qualifier) | UNION both students + course_status_journeys - NI-3 |
| "pre NI" | NI + no ICC + never progressed - NI-6 |
| "first NI" | Earliest remark for current NI students - NI-7 |
| "login time" / "shift" | First/last remark 9:30 AM-8:30 PM - LOGIN PATTERN |
| "dormant" / "no recent follow-up" | HAVING MAX(created_at) < CURRENT_DATE - INTERVAL '7 days' OR IS NULL |
| "overdue callback" | `callback_date < CURRENT_DATE` |
| "upcoming callback" | `callback_date >= CURRENT_DATE` |
| "city" / "where are leads from" | `student_lead_activities.ip_city` |
| "campaign X" / "utm campaign X" | `student_lead_activities.utm_campaign ILIKE '%X%'` |
| "total fee" / "course worth" | `university_courses.total_fees` |
| "deposit" / "payment collected" | `course_status_journeys.deposit_amount` |
| "study mode" / "delivery mode" | `university_courses.study_mode` (NOT students.mode) |
| "supervisor" / "team owner" | `counsellors.role = 'to'` |
| "fresh leads today" | students.created_at IST window - never `current_student_status = 'Fresh'` |
| "above / below average" | Per-entity CTE + CROSS JOIN benchmark (AVG + STDDEV) |
| "TAT" / "average days to admission" | MIN(created_at) per (student_id, course_id) - students.created_at |
| "attempted calls on new leads" | PATTERN 12 - date in JOIN ON clause |
| "NI reasons by campaign" / "why not interested" | PATTERN 14 - campaign_totals + status_breakdown CTEs |
| "latest status per student-course" | `DISTINCT ON (student_id, course_id) ORDER BY ... created_at DESC` |
| "first occurrence of status per student-course" | `DISTINCT ON (student_id, course_id, course_status) ORDER BY ... created_at ASC` |

---

## QUERY AMBIGUITY DISAMBIGUATION

| Ambiguity | Options |
|---|---|
| No date mentioned | Today / This week / This month / This year / All time |
| "counsellor" without qualifier | All counsellors / Active only / L2 / L3 |
| "students" without stage | All stages / Application+ / Enrolled only |
| "performance" / "stats" / "report" | Count / Conversion rate / Average / Total sum |
| Aggregation without GROUP BY | Per counsellor / Per source / Per date / Per university / Total only |
| "not interested" without specifics | All NI reasons / Budget issue / Not eligible / Already enrolled / Other |
| University mentioned ambiguously | All campuses / Specific campus (add city qualifier) |
