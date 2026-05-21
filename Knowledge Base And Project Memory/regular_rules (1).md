# Regular LMS Rules — Text-to-SQL Agent Reference

> **DBs**: `degreefyd_regular_lms` + `degreefyd_regular_cgc_lms` + `degreefyd_regular_amity_lms` | `storage.bhugoal.cloud:54321`
> **⚠️ NOT the same as Online LMS**. Don't use Online rules, statuses, or supervisors here.
>
> **🔑 META-RULE**: These rules are your primary reference and first priority when writing queries. However, they are NOT gospel — the database can drift. When stuck, getting unexpected results, or needing schema/value details beyond what's here, use MCP tools (`mcp_lms_db_describe_table`, `mcp_lms_db_run_select_query`, `mcp_lms_db_get_table_context`) to verify against the live database. These rules prevent repeated mistakes; the MCP tool is your runtime truth.

---

# REGULAR LMS — TEXT-TO-SQL KNOWLEDGE BASE
# READ TIMEZONE BLOCK AND RULES BEFORE WRITING ANY SQL.

---

## TABLES

---

### students
One row per lead. Central funnel record. L2 counsellor owns all pre-application stages (Pre Application, ICC, NI before app) via `assigned_counsellor_id`. L3 takes over from Application onwards — that data lives in `course_status_journeys`, not here.

Key columns: student_id (PK STD-XXXX), student_name, student_email, student_phone, current_student_status, current_student_ni_sub_status, assigned_counsellor_id (L2 FK), assigned_counsellor_l3_id (sparse — do NOT use for L3 queries), first_icc_date (timestamptz lowercase no quotes), is_connected_yet, is_connected_yet_l3, source, mode (student preference — NOT course delivery), preferred_university/stream/degree/level/specialization/city/state (all ARRAY — use ANY()), created_at, updated_at

Business rules:
- Early funnel stages (Pre Application, ICC, NI before app) → this table via current_student_status
- Application/Admission/Enrolled/NI after app → course_status_journeys.course_status ONLY
- preferred_* columns are PostgreSQL arrays → 'Value' = ANY(preferred_university)
- ICC count: COUNT(DISTINCT student_id) WHERE first_icc_date IS NOT NULL. NEVER current_student_status = 'Initial Counselling Completed'
- Fresh leads: NEVER current_student_status = 'Fresh' unless user says "total fresh right now". "Fresh leads today" = students created today (IST on created_at)
- NEVER remarks_count — use COUNT(DISTINCT sr.remark_id) from student_remarks
- is_connected_yet = L2 ever connected; is_connected_yet_l3 = L3 ever connected. NEVER use student_remarks for these

---

### counsellors
One row per staff member. Default to L2 unless user explicitly says L3.

Key columns: counsellor_id (PK CNS-XXXX / PAR-XXXX), counsellor_name, role (l2/l3/to/to_l3), assigned_to (self-ref manager FK), status (active/inactive/suspended)

Business rules:
- CNS-DEFAULT: "counsellor wise" / "counsellor data" / ANY general per-counsellor query → L2 ONLY. Join via students.assigned_counsellor_id, filter role = 'l2'. No UNION of L2+L3. No L3 section.
- CNS-L3: Only use L3 when query says "L3", "l3 counsellor", or "admission counsellor". Join via course_status_journeys.assigned_l3_counsellor_id, filter role = 'l3'
- Supervisor / Team Owner → role ILIKE '%to%' (covers to and to_l3). NEVER role = 'to' alone
- For call metrics: ALWAYS add c.role = 'l2' AND c.status = 'active' to counsellors WHERE clause
- NEVER SELECT * on counsellor queries
- NEVER use students.assigned_counsellor_l3_id for L3 — sparsely populated. Always use course_status_journeys.assigned_l3_counsellor_id

---

### course_status_journeys
Append-only audit trail of every status change. One row per event, multiple per student-course. **This table is append-only — always deduplicate before date filtering.**

Key columns: status_history_id (PK), student_id, course_id, counsellor_id (who LOGGED the event), assigned_l3_counsellor_id (correct L3 FK), course_status, deposit_amount, fee_type, exam_interview_date, created_at

Business rules:
- Application/Admission/Enrolled/Document/NI-after-app all live here
- 8-status Application pipeline: course_status IN ('Form Submitted – Portal Pending', 'Form Submitted – Completed', 'Walkin Completed', 'Walkin Marked', 'Exam/Interview Scheduled', 'Offer Letter/Results Pending', 'Offer Letter/Results Released', 'Ready For Admission')
- NEVER course_status = 'Application' — does not exist in Regular LMS
- Admission: course_status IN ('Admission', 'Enrolled') AND fee_type NOT IN ('Partial Done', 'Partial Paid', 'Partially Paid')
- Enrollment: course_status = 'Enrolled' ONLY
- ALWAYS AND student_id IN (SELECT student_id FROM students) when not joined to students
- ALL date-bounded counts MUST dedup first: MIN(created_at) per (student_id, course_id), THEN date filter. NEVER filter raw created_at (Rule CSJ-FORM)
- assigned_l3_counsellor_id = L3 owner per course row. counsellor_id = who logged the event (different columns)
- Deposit dedup: DISTINCT ON (student_id, course_id, fee_type, created_at::DATE) ORDER BY ... created_at DESC before any SUM

---

### student_remarks
Append-only call log. One row per call attempt, multiple per student.

Key columns: remark_id (PK), student_id, counsellor_id, calling_status ('Connected'/'Not Connected'), sub_calling_status, remarks (TEXT), callback_date (DATE — never apply timezone offset), created_at

Business rules:
- Success rate / call efficiency = COUNT(Connected)/COUNT(all) — NOT conversion
- First call per student: ROW_NUMBER() OVER (PARTITION BY student_id ORDER BY created_at, remark_id) = 1
- Overdue callbacks: callback_date < CURRENT_DATE. Upcoming: callback_date >= CURRENT_DATE
- Count callbacks by remark_id, not student_id
- NEVER remarks_count on students. Always COUNT(DISTINCT remark_id)
- ALWAYS AND student_id IN (SELECT student_id FROM students) when not joined via students table

---

### university_courses
Master catalog. One row per course offering.

Key columns: course_id (PK), university_name, university_state, university_city, degree_name, specialization, stream, level (UG/PG/Diploma/Certificate), course_name, total_fees, semester_fees, annual_fees, study_mode ('Online'/'Regular'/'Hybrid'), duration, usp (TEXT[]), eligibility (TEXT[])

Business rules:
- "region" / "Punjab region" / "region wise" in context of forms/admissions/university → ALWAYS university_state. NEVER students.student_current_state
- study_mode = course delivery. students.mode = student preference. NEVER mix these
- University name with location: use AND not OR (ILIKE '%Chandigarh University%' AND ILIKE '%Lucknow%')
- total_fees = catalog price. deposit_amount on course_status_journeys = actual payment. NEVER confuse

---

### latest_course_statuses
Snapshot — current application status per student-course pair. One row per student × course.

Key columns: id (PK), student_id, course_id, created_by (counsellor FK), latest_course_status, college_api_sent_status

Business rules:
- Use ONLY for shortlisted queries: latest_course_status = 'Shortlisted'
- For Application/Admission/Enrolled → use course_status_journeys
- Any payment check: latest_course_status ILIKE '%Paid%'

---

### student_lead_activities
Marketing touchpoints only. One row per activity, multiple per student.

Key columns: id (PK), student_id, utm_source, utm_medium, utm_keyword, utm_campaign, utm_campaign_id, utm_adgroup_id, utm_creative_id, ip_city, working_professional (boolean), highest_qualification, created_at

Business rules:
- ONLY for marketing/campaign analysis. NEVER count students or funnel stages from this table
- "leads from Facebook" → students.source ILIKE 'FaceBook%'. "utm campaign X" → sla.utm_campaign ILIKE '%X%'
- Geographic analysis: ip_city (NOT students table). Working professional: working_professional boolean (NOT students.current_profession)
- One city per student (no duplicates): SELECT student_id, MAX(ip_city) FROM student_lead_activities WHERE ip_city != '' GROUP BY student_id
- "campaign wise" → JOIN student_lead_activities + COALESCE(utm_campaign, 'Direct/Organic')

---

### counsellor_break_logs
One row per break session.

Key columns: id, counsellor_id, break_start, break_end, duration (minutes), break_type

Business rules: ongoing break = break_end IS NULL. Always apply IST offset on break_start/break_end.

---

### Assignment Rulesets & Lead Assignment Log
Three ruleset tables: l2_assignment_rulesets, l3_assignment_rulesets, admission_assignment_rulesets. One audit table: lead_assignment_log.

Key columns (rulesets): conditions (JSONB — use @> or ->>), assigned_counsellor_ids (TEXT[] — use ANY()), university_name (TEXT[]), source (TEXT[]), is_active, custom_rule_name
Key columns (log): id, student_id, assigned_counsellor_id, assigned_by, created_at

Business rules: Only query is_active = true rules unless user asks otherwise. Use lead_assignment_log for assignment history — NOT counsellors.total_leads which is denormalized.

---

## TIMEZONE — READ FIRST

All created_at columns store UTC. CURRENT_DATE is IST.

```sql
-- Today (IST)
WHERE created_at >= CURRENT_DATE - INTERVAL '5 hours 30 minutes'
  AND created_at <  CURRENT_DATE + INTERVAL '1 day' - INTERVAL '5 hours 30 minutes'

-- Yesterday (IST)
WHERE created_at >= CURRENT_DATE - INTERVAL '1 day' - INTERVAL '5 hours 30 minutes'
  AND created_at <  CURRENT_DATE - INTERVAL '5 hours 30 minutes'

-- Rolling N days
WHERE created_at >= CURRENT_DATE - INTERVAL 'N days' - INTERVAL '5 hours 30 minutes'
  AND created_at <  CURRENT_DATE + INTERVAL '1 day' - INTERVAL '5 hours 30 minutes'

-- Display (convert to IST)
created_at AT TIME ZONE 'Asia/Kolkata'

-- Hour extraction (IST)
EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata')
```

Rules:
- callback_date is type DATE — NEVER apply timezone offset (callback_date < CURRENT_DATE / callback_date >= CURRENT_DATE)
- ALWAYS apply - INTERVAL '5 hours 30 minutes' to any created_at date boundary filter
- NEVER use NOW() or alter IST intervals
- NEVER expose raw UTC timestamps in output — always AT TIME ZONE 'Asia/Kolkata'

---

## RULES

### Output Rules

**O1.** NEVER SELECT * on any counsellor or student query.

**O2.** Stage breakdowns ALWAYS use wide/pivot format — one row per entity, one column per stage via CASE WHEN. NEVER long format (one row per status).

**O3.** Dormant/inactive/uncontacted student queries MUST include student_name and counsellor_name.

**O4.** Counsellor performance queries MUST include total_students or total_calls as a base column.

**O5.** Benchmark comparison queries MUST include the benchmark value as an explicit output column.

**O6.** ONLY return columns the user explicitly asked for. NEVER add unrequested columns. O3 applies ONLY to dormant/follow-up queries — do NOT add student_email to general listing queries. NEVER include student_phone in any query output under any circumstances.

**O7.** List queries MUST include ORDER BY. Use created_at DESC for call records unless specified.

**O8.** Whenever a date/timestamp column is returned to the user, MUST convert to IST using AT TIME ZONE 'Asia/Kolkata'. Always use MIN(created_at) not raw created_at when selecting event dates from append-only tables.

**O9 (PRIVACY).** NEVER SELECT student_phone in any query output. No exceptions, even if user explicitly asks.

---

### Filter Rules

**F1.** NEVER add counsellors.status = 'active' unless user says "active counsellors".

**F2.** NEVER add is_partner filter unless user mentions "internal", "partner", or "external".

**F3.** NEVER add LIMIT unless user says "top N" or uses a superlative ("most/least/best/worst") → LIMIT 1.

**F4.** NEVER filter by current_student_status on "total lead count over time" queries.

**F5.** NEVER add a status WHERE clause on a full-funnel query. Use UNION ALL or CASE WHEN.

**F6.** NEVER add HAVING unless user asks to filter by a minimum count or threshold. Full-roster reports must include zero-call counsellors.

**F7.** "Many calls + low success" thresholds: HAVING COUNT(*) >= 10 AND (connected/total * 100) < 30. Do NOT use dynamic averages.

**F8.** NEVER add WHERE filters not asked for. NEVER add role filter on counsellor queries unless user specifies. WHERE manager.role ILIKE '%to%' is ONLY for all-teams queries (no named manager).

**F9.** University name with location → use AND, never OR. ILIKE '%Chandigarh University%' AND ILIKE '%Lucknow%' — never OR (inflates results).

---

### Table Selection Rules

**T1.** NEVER use student_lead_activities to count students or funnel stages. Marketing/campaign analysis only.

**T2.** NEVER query university-level student counts directly from students. Join chain: students → latest_course_statuses → university_courses.

**T3.** ALWAYS JOIN counsellors to get counsellor_name. Never construct names from other columns.

**T4.** NEVER use students.assigned_counsellor_l3_id for L3 counts — sparsely populated. Always use course_status_journeys.assigned_l3_counsellor_id.

**T5.** NEVER count admissions or applications from students.current_student_status — dirty data. Use course_status_journeys only.

**T6.** NEVER use students.mode for course delivery. Use university_courses.study_mode.

**T7.** Call metrics: join student_remarks directly to counsellors. Do NOT route through students unless student-level data is also needed.

**T8.** Team performance: route manager → team_member (counsellors self-join) → student_remarks. Do NOT route through students table for call metrics.

**T9.** "Applications by source" → course_status_journeys JOIN students, filter 8-status IN list, group by students.source. NEVER use student_lead_activities or latest_course_statuses.

**T10.** Course delivery format (online/regular/hybrid) → university_courses.study_mode. students.mode = student preference only.

**T11.** Fee column selection:
- "Course fee" / "total fee" / "course worth" / "fee structure" → university_courses.total_fees
- "Deposit" / "amount paid" / "payment collected" → course_status_journeys.deposit_amount
- Never mix these two columns.

**T12.** Validation check: EVERY query on child tables (student_remarks, course_status_journeys, latest_course_statuses, student_lead_activities) MUST filter out orphaned records. If students table is not JOINed: AND student_id IN (SELECT student_id FROM students).

---

### Status / Column Rules

**S1.** Early funnel (Pre Application, ICC, NI before app) → students.current_student_status. Application/Admission/Enrolled/Document/NI after app → course_status_journeys.course_status.

**S2.** "form filled" / "applied" / "walkin" / "exam scheduled" / "offer letter" / "ready for admission" → course_status IN ('Form Submitted – Portal Pending', 'Form Submitted – Completed', 'Walkin Completed', 'Walkin Marked', 'Exam/Interview Scheduled', 'Offer Letter/Results Pending', 'Offer Letter/Results Released', 'Ready For Admission'). NEVER course_status = 'Application'.

**S3.** Count callbacks using remark_id, not student_id.

**S4.** NEVER students.remarks_count. Always COUNT(DISTINCT sr.remark_id).

**S5.** ALWAYS COUNT(DISTINCT student_id) after JOIN. Never COUNT(*).

**S6.** same as S2 — enforced globally.

**S7.** "region" in context of university/forms/admissions → university_courses.university_state. Never students.student_current_state.

**S8.** Time-slot / hourly queries → EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata') on student_remarks. Performance = Connected rate only. Always HAVING COUNT(*) > 0. LIMIT 1 for single best/worst.

**S9.** When query needs both total count and filtered subset for same entity → use CASE WHEN inside COUNT. Never use WHERE (drops non-matching rows).

**S10.** "Spread across teams" / "per team breakdown" → one row per team member. GROUP BY both manager AND team_member.

**S11.** NEVER use counsellors.total_leads for breakdowns. Always query students directly.

**S12.** ICC count: COUNT(DISTINCT student_id) WHERE first_icc_date IS NOT NULL. NEVER current_student_status = 'Initial Counselling Completed'.

**S13.** first_icc_date — lowercase, no quotes. NEVER first_Icc_Date or "first_icc_date".

**S14.** Canonical ICC pattern:
```sql
SELECT COUNT(*) FROM students WHERE first_icc_date IS NOT NULL
```

**S15.** TAT / "average days" / "how long" → MUST use subquery with MIN(created_at) GROUP BY student_id, course_id before calculating date diff. Never join raw course_status_journeys for TAT.

**S16.** Admission status is dirty. ALWAYS append: AND fee_type NOT IN ('Partial Done', 'Partial Paid', 'Partially Paid') whenever course_status = 'Admission'. Enrolled is clean — no fee_type filter. Exclude 'Registration done' ONLY if user explicitly asks.

**S17.** Admission counts ALWAYS COUNT(DISTINCT student_id). Never COUNT(*) on admission rows.

**S18.** course_status_journeys is append-only. For ANY date-bounded count:
- Single status → MIN(created_at) per (student_id, course_id), then date filter outside
- Per-status breakdown → DISTINCT ON (student_id, course_id, course_status) ORDER BY ... ASC, then date filter outside
NEVER filter raw created_at directly on course_status_journeys for date-bounded counts.

**S19.** DISTINCT ON for course_status_journeys — three variants:
```sql
-- Latest status per student-course
DISTINCT ON (student_id, course_id) ORDER BY student_id, course_id, created_at DESC

-- First occurrence of specific status per student-course
DISTINCT ON (student_id, course_id) ORDER BY student_id, course_id, created_at ASC
  [WHERE course_status = 'target']

-- First occurrence of EACH status per student-course (for per-status pivots)
DISTINCT ON (student_id, course_id, course_status) ORDER BY student_id, course_id, course_status, created_at ASC
```

---

### Join Rules

**J1.** Never OR across two counsellor FK columns in one JOIN. Use separate subqueries or determine L2 vs L3 from context.

**J2.** NEVER filter by counsellor name on any base table. Always JOIN counsellors and use c.counsellor_name ILIKE '%Name%'.

**J3.** When joining counsellors to student_remarks for call metrics, ALWAYS LEFT JOIN counsellors to preserve zero-call counsellors.

**J4.** Conversion rate queries → course_status_journeys with CASE WHEN for both counts in single query.

**J5.** Two logically independent counts from different tables → use correlated subqueries or CROSS JOIN of single-row CTEs. NEVER join the tables.

**J6.** ALWAYS ILIKE '%Name%' with leading and trailing wildcards for person name filtering.

**J7.** Child table without students JOIN → ALWAYS AND student_id IN (SELECT student_id FROM students).

**J8.** Preserve outer JOINs: when using LEFT JOIN for full roster, put child-table filters in the ON clause, not WHERE. WHERE on LEFT JOINed table turns it into INNER JOIN and hides zero-count entities.

---

### Deposit / Payment Rules

**D1.** Partial payment exclusion for Admission (Regular LMS):
```sql
AND fee_type NOT IN ('Partial Done', 'Partial Paid', 'Partially Paid')
```
Apply to ALL Admission queries (COUNT, SUM, lists, JOINs). 'Enrolled' is clean. 'Registration done' is NOT partial — exclude only if explicitly asked.

**D2.** NEVER add OR fee_type IS NULL to exclusion filters. NULL fee_types are not partial payments.

**D3.** Deposit dedup — ALWAYS before SUM:
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
created_at DESC = if same fee_type corrected same day, latest amount wins. Do NOT include deposit_amount in DISTINCT ON key.

**D4.** Form counting by database:
- degreefyd_regular_lms (CU, LPU): api_sent_status = 'Proceed' in student_college_api_sent_status
- degreefyd_regular_cgc_lms: 8-status IN list from course_status_journeys
- degreefyd_regular_amity_lms: 8-status IN list (or = 'Form Submitted – Completed')
NEVER count forms from students table.

---

### Timezone Rules

**TZ1.** Always apply - INTERVAL '5 hours 30 minutes' to any created_at date boundary filter.
**TZ2.** callback_date is type DATE — NEVER apply timezone offset.
**TZ3.** Display timestamps: AT TIME ZONE 'Asia/Kolkata'. Never raw UTC.
**TZ4.** Hour extraction: EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata').

---

## DISTINCTIONS

### D1 — Leads vs Forms (most critical error source)
| User says | Meaning | Table | Column |
|-----------|---------|-------|--------|
| "leads" / "leads generated" | Students created | students | created_at |
| "forms" / "form fills" / "applied" / "walkin" / "exam" | Students in 8-status pipeline | course_status_journeys | course_status IN 8-status list |

NEVER use students.current_student_status for form/admission/enrolled stages. NEVER use course_status = 'Application' in Regular LMS.

---

### D2 — L2 vs L3 Counsellors (Regular LMS is bi-level)
| Aspect | L2 | L3 |
|--------|----|----|
| FK column | students.assigned_counsellor_id | course_status_journeys.assigned_l3_counsellor_id |
| Role filter | counsellors.role = 'l2' | counsellors.role = 'l3' |
| Owns stages | Pre Application, ICC, NI before app | Application → Enrolled, NI after app |
| Assignment scope | Per student | Per student-course |
| Default for "counsellor" | YES — always default to L2 | Only when explicitly asked |
| WRONG column | — | students.assigned_counsellor_l3_id (sparse) |

---

### D3 — Admission vs Enrollment
| User says | Filter |
|-----------|--------|
| "admission" / "admitted" | course_status IN ('Admission', 'Enrolled') AND fee_type NOT IN ('Partial Done','Partial Paid','Partially Paid') |
| "enrollment" / "enrolled" | course_status = 'Enrolled' ONLY — NOT Admission |

Admission includes Enrolled (enrolled students are admitted). Enrollment does NOT include Admission.

---

### D4 — Partial Exclusion (Regular vs Online differs)
Regular LMS exclusion list: 'Partial Done', 'Partial Paid', 'Partially Paid'
Enrolled is CLEAN — no fee_type filter needed.
'Registration done' is NOT partial — include unless user says otherwise.
NEVER add OR fee_type IS NULL.

---

### D5 — Three Meanings of "Connected"
| Phrase | Source | Filter |
|--------|--------|--------|
| "students connected by L2" / "L2 ever connected" | students | is_connected_yet = true |
| "students connected by L3" / "L3 ever connected" | students | is_connected_yet_l3 = true |
| "calls that were connected" / "connected calls" | student_remarks | calling_status = 'Connected' |

---

### D6 — Success Rate vs Conversion Rate
| Term | Definition | Source |
|------|-----------|--------|
| "success rate" / "efficiency" / "performance" (call context) | COUNT(Connected)/COUNT(all) | student_remarks |
| "conversion rate" / "admission rate" (student outcomes) | COUNT admitted / COUNT applied | course_status_journeys |

---

### D7 — NI Variants
| Variant | Definition |
|---------|-----------|
| Total NI | UNION of students WHERE current_student_status='NotInterested' + csj WHERE course_status='NotInterested' |
| Pre-NI | NI + first_icc_date IS NULL + NOT IN csj for Application+ stages |
| First NI | NI students whose FIRST EVER remark falls in date window (DISTINCT ON sr.student_id ORDER BY created_at ASC) |
| NI with ICC | NI students who had ICC but never progressed to application |
| NI sub-reason | students.current_student_ni_sub_status WHERE current_student_status = 'NotInterested' |
| NI after app | course_status_journeys.course_status = 'NotInterested' |

---

### D8 — Fee Columns
| Asking about | Column | Table |
|-------------|--------|-------|
| Course price / "how much does it cost" / "fee structure" | total_fees (also semester_fees, annual_fees) | university_courses |
| Deposit paid / "amount collected" / "payment received" | deposit_amount (with dedup CTE) | course_status_journeys |
| Study mode / delivery format | study_mode | university_courses |
| Student preference | mode | students |

---

## PATTERNS

### PATTERN DEFINITIONS — Quick Reference

| # | Pattern | Key Definitions |
|---|---------|----------------|
| **1** | Funnel & Stage | Early funnel (Pre App, ICC) = `students.current_student_status`. Funnel (Application+) = `course_status_journeys.course_status`. L2 default counsellor pivot. MAX(stage_rank) per student-university counts each student once at highest stage. |
| **2** | Counsellor Calls (L2) | Mandatory `c.role = 'l2' AND c.status = 'active'`. LEFT JOIN preserves zero-call counsellors. Team view: manager → `counsellors.assigned_to` chain, `role ILIKE '%to%'`. |
| **3** | Benchmark / Avg | Two CTEs: per-counsellor metrics → global AVG+STDDEV. CROSS JOIN for benchmark columns. Adapt metric for call-performance vs conversion. |
| **4** | Dormant Students | Use `csj.course_status` NOT `students.current_student_status`. LEFT JOIN for zero-remark students. NEVER `student_phone`. |
| **5** | Date-Bounded csj | **A (aggregate):** MIN(`created_at`) per (student_id, course_id). **B (per-status):** DISTINCT ON (student_id, course_id, course_status) ORDER BY ASC. NEVER filter raw csj.created_at — always dedup first. |
| **6** | Forms+Admissions by Uni | MIN(`created_at`) per (student_id, course_id) for both forms AND admissions. Counsellor-wise: dedup on student_id before joining to prevent multi-count. |
| **7** | Counsellor-wise Form | **L2:** via `students.assigned_counsellor_id`. **L3:** via `csj.assigned_l3_counsellor_id`. Date filter in ON clause (preserves zero-count). UNION ALL only when both levels requested. |
| **8** | First Connected | Always MIN(`created_at`) per student with `calling_status='Connected'`. Counsellor-wise uses INNER JOIN — only counsellors who made first-connection appear. |
| **9** | NI Patterns | **Pre-NI:** `current_student_status='NotInterested'` + no ICC + never in any csj forward status. **First NI:** earliest `student_remarks` (any calling_status) of current NI students — NOT when they became NI. |
| **10** | Lead Attempts | **A (new leads):** date filter in students LEFT JOIN ON clause + `WHERE sr.student_id IS NOT NULL`. **B (total+attempted):** date filter in students LEFT JOIN ON, all counsellors shown. |
| **11** | L3 Response Time | `csj.assigned_l3_counsellor_id` — NOT `students.assigned_counsellor_l3_id`. `GREATEST(0, days)` handles pre-status remarks. `CONCAT(student_id,'_',course_id)` as form_key. |
| **12** | NI by Campaign | `COALESCE(utm_campaign, 'Direct/Organic')`. NULL sub_status → `'Reason Not Given'` ONLY. |
| **13** | College Status Report | CSJ only — NO `student_college_credentials`. Status = FIRST CSJ entry per pair by `created_at ASC`. Date filter on that first entry. |
| **14** | Form Working Status | Active = latest status in 8 pipeline statuses + ANY csj activity in period. Recency = last remark from **assigned L3 only** (not any counsellor). Not Worked = L3 never remarked. `form_key` dedup per (student, course). |
| **15** | YTD/MTD/FTD Forms+Adm | Form date = first entry into 8-status pipeline. Admission date = first `Admission/Enrolled` excl partial. FULL OUTER JOIN for completeness. F2A = `admissions * 100.0 / NULLIF(forms,0)`. |
| **16** | L3 Counsellor Dashboard | Total Forms = all (student, course) in pipeline (excl Shortlisted). Active = latest status IN 8 pipeline statuses. Not Initiated = no L3 remark. Response-time = `EXTRACT(DAY FROM (first_remark_date - first_status_date))`. |

---

### PATTERN 1 — Funnel & Stage Breakdown

**Variant A — Total funnel (UNION ALL):**
```sql
SELECT 'Total Leads' AS stage, COUNT(DISTINCT student_id) AS count FROM students
UNION ALL
SELECT 'Pre Application', COUNT(DISTINCT student_id) FROM students WHERE current_student_status = 'Pre Application'
UNION ALL
SELECT 'ICC', COUNT(DISTINCT student_id) FROM students WHERE current_student_status = 'Initial Counselling Completed'
UNION ALL
SELECT 'Applications', COUNT(DISTINCT student_id) FROM course_status_journeys
  WHERE course_status IN ('Form Submitted – Portal Pending','Form Submitted – Completed','Walkin Completed','Walkin Marked','Exam/Interview Scheduled','Offer Letter/Results Pending','Offer Letter/Results Released','Ready For Admission')
  AND student_id IN (SELECT student_id FROM students)
UNION ALL
SELECT 'Admission', COUNT(DISTINCT student_id) FROM course_status_journeys
  WHERE course_status = 'Admission' AND fee_type NOT IN ('Partial Done','Partial Paid','Partially Paid')
  AND student_id IN (SELECT student_id FROM students)
UNION ALL
SELECT 'Enrolled', COUNT(DISTINCT student_id) FROM course_status_journeys
  WHERE course_status = 'Enrolled' AND student_id IN (SELECT student_id FROM students);
```

**Variant B — Per-counsellor pivot (L2 default):**
```sql
SELECT
    c.counsellor_name,
    COUNT(DISTINCT s.student_id) AS total_students,
    COUNT(DISTINCT CASE WHEN s.current_student_status = 'Pre Application' THEN s.student_id END) AS pre_application,
    COUNT(DISTINCT CASE WHEN s.current_student_status = 'Initial Counselling Completed' THEN s.student_id END) AS icc,
    COUNT(DISTINCT CASE WHEN csj.course_status IN ('Form Submitted – Portal Pending','Form Submitted – Completed','Walkin Completed','Walkin Marked','Exam/Interview Scheduled','Offer Letter/Results Pending','Offer Letter/Results Released','Ready For Admission') THEN csj.student_id END) AS applications,
    COUNT(DISTINCT CASE WHEN csj.course_status = 'Admission' AND csj.fee_type NOT IN ('Partial Done','Partial Paid','Partially Paid') THEN csj.student_id END) AS admissions,
    COUNT(DISTINCT CASE WHEN csj.course_status = 'Enrolled' THEN csj.student_id END) AS enrolled
FROM counsellors c
JOIN students s ON c.counsellor_id = s.assigned_counsellor_id
LEFT JOIN course_status_journeys csj ON s.student_id = csj.student_id
WHERE c.role = 'l2' AND c.status = 'active'
GROUP BY c.counsellor_id, c.counsellor_name
HAVING COUNT(DISTINCT s.student_id) > 0
ORDER BY total_students DESC;
```

**Variant C — Per-university (student at highest stage):**
```sql
WITH stage_priority AS (
    SELECT uc.university_name, csj.student_id,
        MAX(CASE WHEN csj.course_status='Enrolled' THEN 6
                 WHEN csj.course_status='Document Submitted' THEN 5
                 WHEN csj.course_status='Document Pending' THEN 4
                 WHEN csj.course_status='Admission' AND csj.fee_type NOT IN ('Partial Done','Partial Paid','Partially Paid') THEN 3
                 WHEN csj.course_status IN ('Form Submitted – Portal Pending','Form Submitted – Completed','Walkin Completed','Walkin Marked','Exam/Interview Scheduled','Offer Letter/Results Pending','Offer Letter/Results Released','Ready For Admission') THEN 2
                 ELSE 0 END) AS final_rank
    FROM course_status_journeys csj
    JOIN university_courses uc ON csj.course_id = uc.course_id
    WHERE csj.student_id IN (SELECT student_id FROM students)
    GROUP BY uc.university_name, csj.student_id
)
SELECT university_name,
    COUNT(*) FILTER (WHERE final_rank=2) AS applications,
    COUNT(*) FILTER (WHERE final_rank=3) AS admissions,
    COUNT(*) FILTER (WHERE final_rank=4) AS document_pending,
    COUNT(*) FILTER (WHERE final_rank=5) AS document_submitted,
    COUNT(*) FILTER (WHERE final_rank=6) AS enrolled
FROM stage_priority GROUP BY university_name ORDER BY admissions DESC;
```
Key: Early stages (Pre App, ICC) from students.current_student_status. Application/Admission/Enrolled from csj. L2 default for counsellor queries. Pivot format — never long format. Add LIMIT N only if user asks "top N". Variant C: MAX(stage_rank) per student-university ensures each student counted once at highest stage.

---

### PATTERN 2 — Counsellor Call Performance (L2 only)
```sql
SELECT
    c.counsellor_name,
    COUNT(sr.remark_id) AS total_calls,
    COUNT(CASE WHEN sr.calling_status = 'Connected' THEN 1 END) AS connected_calls,
    ROUND(COUNT(CASE WHEN sr.calling_status='Connected' THEN 1 END)*100.0/NULLIF(COUNT(sr.remark_id),0), 2) || '%' AS success_rate
FROM counsellors c
LEFT JOIN student_remarks sr ON c.counsellor_id = sr.counsellor_id
WHERE c.role = 'l2' AND c.status = 'active'
GROUP BY c.counsellor_id, c.counsellor_name
ORDER BY success_rate DESC;
```
Key: MANDATORY c.role = 'l2' AND c.status = 'active'. LEFT JOIN preserves zero-call counsellors. Percentage appends %. For team performance: replace counsellors with manager -> LEFT JOIN counsellors team_member ON manager.counsellor_id = team_member.assigned_to -> LEFT JOIN student_remarks, WHERE manager.role ILIKE '%to%'.

---

### PATTERN 3 — Benchmark / Above-Average Comparison
```sql
WITH metrics AS (
    SELECT
        c.counsellor_id, c.counsellor_name,
        COUNT(DISTINCT s.student_id) AS total_students,
        COUNT(DISTINCT CASE WHEN csj.course_status IN ('Admission','Enrolled') AND (csj.course_status='Enrolled' OR csj.fee_type NOT IN ('Partial Done','Partial Paid','Partially Paid')) THEN csj.student_id END) AS conversions,
        ROUND(COUNT(DISTINCT CASE WHEN csj.course_status IN ('Admission','Enrolled') AND (csj.course_status='Enrolled' OR csj.fee_type NOT IN ('Partial Done','Partial Paid','Partially Paid')) THEN csj.student_id END)::numeric
              / NULLIF(COUNT(DISTINCT s.student_id),0)*100, 2) AS conversion_rate_pct
    FROM counsellors c
    JOIN students s ON c.counsellor_id = s.assigned_counsellor_id
    LEFT JOIN course_status_journeys csj ON s.student_id = csj.student_id
    WHERE c.role = 'l2' AND c.status = 'active'
    GROUP BY c.counsellor_id, c.counsellor_name
    HAVING COUNT(DISTINCT s.student_id) > 0
),
benchmark AS (
    SELECT ROUND(AVG(conversion_rate_pct),2) AS avg_rate, ROUND(STDDEV(conversion_rate_pct),2) AS stddev_rate FROM metrics
)
SELECT m.*, b.avg_rate AS team_avg,
    ROUND(m.conversion_rate_pct - b.avg_rate, 2) AS diff_from_avg,
    CASE WHEN m.conversion_rate_pct >= b.avg_rate + b.stddev_rate THEN 'Above Average'
         WHEN m.conversion_rate_pct <= b.avg_rate - b.stddev_rate THEN 'Below Average'
         ELSE 'Average' END AS band
FROM metrics m CROSS JOIN benchmark b
ORDER BY m.conversion_rate_pct DESC;
```
Key: Step 1 CTE per-counsellor metrics. Step 2 CTE global AVG+STDDEV. CROSS JOIN for benchmark columns. Adapt metric column (conversion_rate_pct -> success_rate) for call-performance benchmarks.

---

### PATTERN 4 — Dormant Students (No Remark in N Days)
```sql
SELECT
    s.student_name, s.student_email,
    c.counsellor_name, csj.course_status,
    MAX(sr.created_at) AS last_remark_date
FROM students s
JOIN course_status_journeys csj ON s.student_id = csj.student_id
JOIN counsellors c ON s.assigned_counsellor_id = c.counsellor_id
LEFT JOIN student_remarks sr ON s.student_id = sr.student_id
WHERE (csj.course_status IN ('Form Submitted – Portal Pending','Form Submitted – Completed','Walkin Completed','Walkin Marked','Exam/Interview Scheduled','Offer Letter/Results Pending','Offer Letter/Results Released','Ready For Admission')
    OR (csj.course_status = 'Admission' AND csj.fee_type NOT IN ('Partial Done','Partial Paid','Partially Paid'))
    OR csj.course_status = 'Enrolled')
GROUP BY s.student_id, s.student_name, s.student_email, c.counsellor_name, csj.course_status
HAVING MAX(sr.created_at) < CURRENT_DATE - INTERVAL '7 days' OR MAX(sr.created_at) IS NULL
ORDER BY last_remark_date ASC NULLS FIRST;
```
Key: student_name + counsellor_name required (O3). Use csj.course_status NOT students.current_student_status. LEFT JOIN for zero-remark students. NEVER student_phone.

---

### PATTERN 5 — Date-Bounded csj Counts

**Variant A — Aggregate count (forms/admissions/enrolled in a window):**
```sql
WITH first_event AS (
    SELECT student_id, course_id, MIN(created_at) AS first_event_date
    FROM course_status_journeys
    WHERE course_status IN (<target statuses>)
      AND student_id IN (SELECT student_id FROM students)
    GROUP BY student_id, course_id
)
SELECT COUNT(DISTINCT student_id) AS count
FROM first_event
WHERE first_event_date >= <start_ist>
  AND first_event_date <  <end_ist>;
```

**Variant B — Per-individual-status breakdown (e.g. Portal Pending vs Completed today):**
```sql
SELECT
    uc.university_name,
    COUNT(DISTINCT CASE WHEN fs.course_status = 'Form Submitted – Portal Pending' THEN fs.student_id END) AS portal_pending,
    COUNT(DISTINCT CASE WHEN fs.course_status = 'Form Submitted – Completed'      THEN fs.student_id END) AS form_completed
FROM (
    SELECT DISTINCT ON (student_id, course_id, course_status)
        student_id, course_id, course_status, created_at
    FROM course_status_journeys
    WHERE course_status IN ('Form Submitted – Portal Pending','Form Submitted – Completed')
      AND student_id IN (SELECT student_id FROM students)
    ORDER BY student_id, course_id, course_status, created_at ASC
) fs
JOIN university_courses uc ON fs.course_id = uc.course_id
WHERE fs.created_at >= <start_ist> AND fs.created_at < <end_ist>
GROUP BY uc.university_name;
```
Key: Variant A for aggregate counts ("how many forms today"). Variant B for per-status pivots ("Portal Pending vs Completed today"). NEVER filter raw created_at on csj — always dedup first. Variant A: MIN(created_at) per (student_id, course_id). Variant B: DISTINCT ON (student_id, course_id, course_status) ORDER BY ... ASC.

---

### PATTERN 6 — Forms and Admissions by University (Date Range)
```sql
WITH first_form AS (
    SELECT student_id, course_id, assigned_l3_counsellor_id,
           MIN(created_at) AS first_form_date
    FROM course_status_journeys
    WHERE course_status IN ('Form Submitted – Portal Pending','Form Submitted – Completed','Walkin Completed','Walkin Marked','Exam/Interview Scheduled','Offer Letter/Results Pending','Offer Letter/Results Released','Ready For Admission')
      AND student_id IN (SELECT student_id FROM students)
    GROUP BY student_id, course_id, assigned_l3_counsellor_id
),
first_admission AS (
    SELECT student_id, course_id, MIN(created_at) AS first_admission_date
    FROM course_status_journeys
    WHERE course_status IN ('Admission','Enrolled')
      AND (course_status = 'Enrolled' OR fee_type NOT IN ('Partial Done','Partial Paid','Partially Paid'))
      AND student_id IN (SELECT student_id FROM students)
    GROUP BY student_id, course_id
)
SELECT 'Forms' AS metric, COUNT(*) AS total_count
FROM first_form ff
JOIN university_courses uc ON ff.course_id = uc.course_id
WHERE uc.university_name ILIKE '%<University>%'
  AND ff.first_form_date >= <start_ist> AND ff.first_form_date < <end_ist>
UNION ALL
SELECT 'Admissions' AS metric, COUNT(*) AS total_count
FROM first_admission fa
JOIN university_courses uc ON fa.course_id = uc.course_id
WHERE uc.university_name ILIKE '%<University>%'
  AND fa.first_admission_date >= <start_ist> AND fa.first_admission_date < <end_ist>
ORDER BY metric;
```
Key: MIN(created_at) per (student_id, course_id) for BOTH metrics. For counsellor-wise: add deduped_forms CTE with DISTINCT ON (student_id) before joining counsellors — prevents student counted N times for N courses under same counsellor.

---

### PATTERN 7 — Counsellor-wise Form Count (Any Date Window)

**Variant A — L2 only (default, CNS-DEFAULT applies):**
```sql
SELECT
    c.counsellor_name, 'L2' AS counsellor_role,
    COALESCE(COUNT(DISTINCT fs.student_id), 0) AS form_count
FROM counsellors c
LEFT JOIN (
    SELECT DISTINCT ON (s.student_id, csj.course_id)
        s.student_id, csj.course_id, s.assigned_counsellor_id,
        csj.created_at AS form_date
    FROM students s
    JOIN course_status_journeys csj ON s.student_id = csj.student_id
    WHERE csj.course_status IN ('Form Submitted – Portal Pending','Form Submitted – Completed','Walkin Completed','Walkin Marked','Exam/Interview Scheduled','Offer Letter/Results Pending','Offer Letter/Results Released','Ready For Admission')
      AND csj.student_id IN (SELECT student_id FROM students)
    ORDER BY s.student_id, csj.course_id, csj.created_at ASC
) fs ON c.counsellor_id = fs.assigned_counsellor_id
    AND fs.form_date >= <start_ist> AND fs.form_date < <end_ist>
WHERE c.role = 'l2' AND c.status = 'active'
GROUP BY c.counsellor_id, c.counsellor_name
ORDER BY form_count DESC;
```

**Variant B — L3 only (when explicitly asked):**
Replace LEFT JOIN subquery with:
```sql
LEFT JOIN (
    SELECT DISTINCT ON (student_id, course_id)
        student_id, assigned_l3_counsellor_id, created_at AS form_date
    FROM course_status_journeys
    WHERE course_status IN (<8-status list>)
      AND student_id IN (SELECT student_id FROM students)
    ORDER BY student_id, course_id, created_at ASC
) fs ON c.counsellor_id = fs.assigned_l3_counsellor_id
    AND fs.form_date >= <start_ist> AND fs.form_date < <end_ist>
WHERE c.role = 'l3' AND c.status = 'active'
```
Key: L2 form attribution via students.assigned_counsellor_id. L3 via course_status_journeys.assigned_l3_counsellor_id. Date filter in ON clause (J8) to preserve zero-count counsellors. DISTINCT ON dedup per student-course. UNION ALL only when both levels explicitly requested. Add JOIN university_courses inside subquery for region filter (uc.university_state).

---

### PATTERN 8 — First Connected (Total + Counsellor-wise)
```sql
-- Total first connected in window:
WITH first_connected AS (
    SELECT student_id, MIN(created_at) AS first_connected_at
    FROM student_remarks
    WHERE calling_status = 'Connected'
      AND student_id IN (SELECT student_id FROM students)
    GROUP BY student_id
)
SELECT COUNT(DISTINCT student_id) AS first_connected_count
FROM first_connected
WHERE first_connected_at >= <start_ist> AND first_connected_at < <end_ist>;

-- Counsellor-wise first connected:
SELECT c.counsellor_name, COUNT(DISTINCT sr.student_id) AS first_connected_count
FROM student_remarks sr
JOIN counsellors c ON c.counsellor_id = sr.counsellor_id
WHERE sr.calling_status = 'Connected'
  AND sr.student_id IN (SELECT student_id FROM students)
  AND sr.created_at = (
        SELECT MIN(sr2.created_at) FROM student_remarks sr2
        WHERE sr2.student_id = sr.student_id AND sr2.calling_status = 'Connected'
  )
  AND sr.created_at >= <start_ist> AND sr.created_at < <end_ist>
GROUP BY c.counsellor_id, c.counsellor_name
ORDER BY first_connected_count DESC;
```
Key: Always MIN(created_at) to identify first connected call. Counsellor-wise uses INNER JOIN intentionally — only counsellors who made a first-connected call appear.

---

### PATTERN 9 — NI Patterns (Pre-NI + First NI)

**Variant A — Pre-NI (NI with no ICC, never progressed):**
```sql
WITH never_progressed AS (
    SELECT s.student_id FROM students s
    WHERE s.current_student_status = 'NotInterested'
      AND s.first_icc_date IS NULL
      AND s.student_id NOT IN (
          SELECT DISTINCT student_id FROM course_status_journeys
          WHERE course_status IN ('Form Submitted – Portal Pending','Form Submitted – Completed','Walkin Completed','Walkin Marked','Exam/Interview Scheduled','Offer Letter/Results Pending','Offer Letter/Results Released','Ready For Admission','Admission','Document Pending','Document Submitted','Enrolled')
      )
)
SELECT COUNT(DISTINCT np.student_id) AS pre_ni_count
FROM never_progressed np
JOIN students s ON np.student_id = s.student_id
WHERE s.created_at >= <start_ist> AND s.created_at < <end_ist>;
```

**Variant B — First NI (current NI students by when they were first contacted):**
```sql
WITH first_ni_students AS (
    SELECT DISTINCT ON (sr.student_id)
        sr.student_id, sr.created_at AS first_ni_at
    FROM student_remarks sr
    INNER JOIN students s ON sr.student_id = s.student_id
    WHERE s.current_student_status = 'NotInterested'
    ORDER BY sr.student_id, sr.created_at ASC
)
SELECT COUNT(*) AS first_ni_count
FROM first_ni_students
WHERE first_ni_at >= <start_ist> AND first_ni_at < <end_ist>;
```
Key: Pre-NI = NI + no ICC + never in any forward-progression csj status. First NI = earliest remark of current NI students (any calling_status counts — not when they became NI). For counsellor-wise: add JOIN counsellors c ON s.assigned_counsellor_id = c.counsellor_id, GROUP BY counsellor.

---

### PATTERN 10 — Lead Attempt Tracking (Counsellor-wise, Any Window)

**Variant A — Attempted calls on new leads only:**
```sql
SELECT c.counsellor_name, COUNT(DISTINCT sr.student_id) AS total_attempted_calls
FROM counsellors c
LEFT JOIN students s ON c.counsellor_id = s.assigned_counsellor_id
LEFT JOIN student_remarks sr ON s.student_id = sr.student_id
    AND s.created_at >= <start_ist> AND s.created_at < <end_ist>
WHERE sr.student_id IS NOT NULL
GROUP BY c.counsellor_id, c.counsellor_name
ORDER BY total_attempted_calls DESC;
```

**Variant B — Total leads in window + how many were attempted:**
```sql
SELECT c.counsellor_name,
    COUNT(DISTINCT s.student_id) AS total_leads,
    COUNT(DISTINCT sr.student_id) AS total_attempted_leads
FROM counsellors c
LEFT JOIN students s ON c.counsellor_id = s.assigned_counsellor_id
    AND s.created_at >= <start_ist> AND s.created_at < <end_ist>
LEFT JOIN student_remarks sr ON s.student_id = sr.student_id
GROUP BY c.counsellor_id, c.counsellor_name
ORDER BY total_attempted_leads DESC;
```
Key: Variant A — date filter on students.created_at in LEFT JOIN ON clause; WHERE sr.student_id IS NOT NULL keeps only counsellors who called new leads. Variant B — date filter for students in students LEFT JOIN ON; all counsellors shown with zero-attempt possible.

---

### PATTERN 11 — L3 Form Assignment Performance and Response Time
```sql
WITH
all_combinations AS (
    SELECT DISTINCT student_id, course_id FROM course_status_journeys
    WHERE student_id IN (SELECT student_id FROM students)
),
first_status AS (
    SELECT DISTINCT ON (student_id, course_id)
        student_id, course_id, course_status, created_at AS first_status_date,
        counsellor_id AS status_created_by, assigned_l3_counsellor_id
    FROM course_status_journeys
    WHERE student_id IN (SELECT student_id FROM students)
    ORDER BY student_id, course_id, created_at ASC
),
first_remark_by_l3 AS (
    SELECT DISTINCT ON (fs.student_id, fs.course_id)
        fs.student_id, fs.course_id, sr.created_at AS first_remark_date
    FROM first_status fs
    LEFT JOIN student_remarks sr ON sr.student_id = fs.student_id
        AND sr.counsellor_id = fs.assigned_l3_counsellor_id
    WHERE sr.student_id IN (SELECT student_id FROM students)
    ORDER BY fs.student_id, fs.course_id, sr.created_at ASC
),
latest_status AS (
    SELECT DISTINCT ON (student_id, course_id)
        student_id, course_id, course_status AS latest_status, fee_type
    FROM course_status_journeys
    WHERE student_id IN (SELECT student_id FROM students)
    ORDER BY student_id, course_id, created_at DESC
),
base AS (
    SELECT ac.student_id, ac.course_id,
        fs.first_status_date, fs.assigned_l3_counsellor_id,
        fr.first_remark_date, ls.latest_status, ls.fee_type,
        CASE WHEN fr.first_remark_date IS NOT NULL
             THEN GREATEST(0, EXTRACT(DAY FROM (fr.first_remark_date - fs.first_status_date)))
             ELSE NULL END AS days_to_first_action,
        c.counsellor_name,
        CONCAT(ac.student_id, '_', ac.course_id) AS student_course_key
    FROM all_combinations ac
    JOIN first_status fs ON ac.student_id = fs.student_id AND ac.course_id = fs.course_id
    LEFT JOIN first_remark_by_l3 fr ON ac.student_id = fr.student_id AND ac.course_id = fr.course_id
    LEFT JOIN latest_status ls ON ac.student_id = ls.student_id AND ac.course_id = ls.course_id
    LEFT JOIN counsellors c ON fs.assigned_l3_counsellor_id = c.counsellor_id
    WHERE fs.course_status <> 'Shortlisted'
)
SELECT
    COALESCE(b.assigned_l3_counsellor_id, 'Unassigned') AS l3_counsellor_id,
    COALESCE(b.counsellor_name, 'Unassigned') AS counsellor_name,
    COUNT(DISTINCT b.student_course_key) AS total_forms,
    COUNT(DISTINCT CASE WHEN b.latest_status NOT IN ('Registration done','Partially Paid','Semester Paid','Enrollment in Process','Enrolled','NotInterested','NI - Student Denied','Counselling Yet to be Done') OR b.latest_status IS NULL THEN b.student_course_key END) AS active_forms,
    COUNT(DISTINCT CASE WHEN b.latest_status = 'Enrolled' OR (b.latest_status = 'Admission' AND b.fee_type NOT IN ('Partial Done','Partial Paid','Partially Paid')) THEN b.student_course_key END) AS completed,
    COUNT(DISTINCT CASE WHEN b.latest_status IN ('NotInterested','NI - Student Denied','Counselling Yet to be Done') THEN b.student_course_key END) AS ni_other,
    COUNT(DISTINCT CASE WHEN b.first_remark_date IS NULL THEN b.student_course_key END) AS not_initiated,
    COUNT(DISTINCT CASE WHEN b.first_remark_date IS NOT NULL AND b.days_to_first_action BETWEEN 0 AND 3 THEN b.student_course_key END) AS called_0_to_3_days,
    COUNT(DISTINCT CASE WHEN b.first_remark_date IS NOT NULL AND b.days_to_first_action BETWEEN 4 AND 6 THEN b.student_course_key END) AS called_4_to_6_days,
    COUNT(DISTINCT CASE WHEN b.first_remark_date IS NOT NULL AND b.days_to_first_action >= 7 THEN b.student_course_key END) AS called_7_plus_days,
    ROUND(AVG(b.days_to_first_action) FILTER (WHERE b.first_remark_date IS NOT NULL)::numeric, 1) AS avg_response_days
FROM base b
GROUP BY b.assigned_l3_counsellor_id, b.counsellor_name
ORDER BY total_forms DESC;
```
Key: csj.assigned_l3_counsellor_id (NOT students.assigned_counsellor_l3_id). GREATEST(0,...) handles pre-status remarks. student_course_key = CONCAT(student_id,'_',course_id). For date-bounded: add AND created_at >= ... to first_status CTE WHERE clause.

---

### PATTERN 12 — NI Reason Breakdown by Campaign
```sql
WITH fresh_leads AS (
    SELECT student_id FROM students
    WHERE created_at >= <start_ist> AND created_at < <end_ist>
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
    ROUND((sb.ni_count::numeric*100.0/ct.total_leads), 2) AS percentage_of_total
FROM campaign_totals ct
JOIN status_breakdown sb ON ct.campaign = sb.campaign
ORDER BY ct.total_leads DESC, sb.ni_count DESC;
```
Key: COALESCE(utm_campaign, 'Direct/Organic'). LEFT JOIN student_lead_activities. NULL sub_status -> 'Reason Not Given' ONLY (never 'Interested / In-Progress').

---

### PATTERN 13 — College Status Report (Amity / Regular)

**Logic**: For each (student_id, course_id) pair, find the FIRST `course_status_journeys` entry by `created_at ASC`. Filter by that entry's `created_at` in date range. Group by `university_courses.university_name` and `course_status`.

**NOT** `student_college_credentials` (SCC) — those are used for credential tracking, not for the College Status Report.

```sql
WITH first_csj_per_pair AS (
    SELECT student_id, course_id, MIN(created_at) AS first_ts
    FROM course_status_journeys
    GROUP BY student_id, course_id
),
pairs_first_status AS (
    SELECT fc.student_id, fc.course_id, csj.course_status
    FROM first_csj_per_pair fc
    JOIN course_status_journeys csj
        ON csj.student_id = fc.student_id
       AND csj.course_id = fc.course_id
       AND csj.created_at = fc.first_ts
    WHERE (fc.first_ts AT TIME ZONE 'Asia/Kolkata')::date
        BETWEEN '2026-05-01' AND '2026-05-15'
)
SELECT uc.university_name, pfs.course_status, COUNT(*) AS cnt
FROM pairs_first_status pfs
JOIN university_courses uc ON uc.course_id = pfs.course_id
WHERE pfs.course_status IN (
    'Form Submitted – Portal Pending',
    'Form Submitted – Completed',
    'Offer Letter/Results Released',
    'NotInterested',
    'Walkin Marked',
    'Exam/Interview Pending'
)
GROUP BY uc.university_name, pfs.course_status
ORDER BY uc.university_name, pfs.course_status;
```
Key: Uses CSJ only — no SCC join. Status = first CSJ entry per pair. Filter to report's 6 status buckets. Verified on regular_amity_lms (May 1-15, 2026): 5 of 7 universities match exactly; Gurugram off by 2 in Completed (70 vs 68). If exact match needed from SCC, see the SCC+CSJ-fallback approach.

---

### PATTERN 14 — Form Working Status (College-Wise, Active Forms by Recency)

**Purpose**: Find active student application forms per university and show how recently the assigned L3 counsellor has worked on them. Output: college name, not-worked count, 0-3 days, 4-6 days, 6+ days, total.

**Logic (5 CTEs)**:

1. **`active_forms_all`** — Latest pipeline status per (student_id, course_id) via `DISTINCT ON ... ORDER BY created_at DESC`. Also captures `assigned_l3_counsellor_id` and `counsellor_id AS status_by` (who set the current status).
   ```sql
   SELECT DISTINCT ON (csj.student_id, csj.course_id)
       csj.student_id, csj.course_id, csj.course_status,
       csj.assigned_l3_counsellor_id, csj.counsellor_id AS status_by
   FROM course_status_journeys csj
   WHERE csj.student_id IN (SELECT student_id FROM students)
   ORDER BY csj.student_id, csj.course_id, csj.created_at DESC
   ```

2. **`period_active`** — Any CSJ activity during the target date range (IST-adjusted by subtracting 5h30m from UTC). This catches forms that were active *anywhere in the pipeline* during the period, not just ones that entered it.
   ```sql
   SELECT DISTINCT csj.student_id, csj.course_id
   FROM course_status_journeys csj
   WHERE csj.created_at >= '<start>::timestamptz' - INTERVAL '5 hours 30 minutes'
     AND csj.created_at <  '<end>::timestamptz' - INTERVAL '5 hours 30 minutes'
   ```

3. **`active_forms`** — Join the above two: latest-status per form × forms active in period. Filter to the 8 pipeline statuses (Portal Pending, Completed, Walkin Completed/Marked, Exam/Interview Scheduled, Offer Letter Pending/Released, Ready For Admission). Create `form_key = student_id || '_' || course_id` for clean dedup.
   ```sql
   JOIN period_active pa ON afa.student_id = pa.student_id AND afa.course_id = pa.course_id
   WHERE afa.course_status IN ('Form Submitted – Portal Pending', ..., 'Ready For Admission')
   ```

4. **`last_l3_remark`** — For each student, the most recent `student_remarks` entry made by their *assigned L3 counsellor* (NOT any counsellor). This is the key to recency buckets.
   ```sql
   SELECT DISTINCT ON (sr.student_id)
       sr.student_id, sr.created_at AS last_remark_at
   FROM student_remarks sr
   JOIN active_forms af ON sr.student_id = af.student_id
     AND sr.counsellor_id = af.assigned_l3_counsellor_id
   ORDER BY sr.student_id, sr.created_at DESC
   ```

5. **Final SELECT** — Group by `university_courses.university_name`. Buckets:
   - **Not Worked** (`last_remark_at IS NULL`) — The L3 has never left a remark. Status may have been set by an L2 counsellor (checked via `status_by`).
   - **0-3 Days** — `EXTRACT(DAY FROM (NOW() - last_remark_at)) <= 3`
   - **4-6 Days** — `BETWEEN 4 AND 6`
   - **6+ Days** — `>= 7`
   ```sql
   SELECT uc.university_name,
       COUNT(DISTINCT CASE WHEN lr.last_remark_at IS NULL THEN af.form_key END) AS not_worked,
       ...
   FROM active_forms af
   JOIN university_courses uc ON af.course_id = uc.course_id
   LEFT JOIN last_l3_remark lr ON af.student_id = lr.student_id
   GROUP BY uc.university_name
   ```

**Key pitfalls**:
- **Date filter on ANY CSJ activity, not pipeline entry.** Filtering by pipeline status + date misses forms already in pipeline before the period. The separate `period_active` CTE (no status filter) catches them all.
- **L3 remark only.** The recency buckets measure only the *assigned L3's* activity. A form worked yesterday by an L2 or another L3 will still show as "Not Worked" for the correct L3.
- **Not Worked ≠ "L3 never assigned."** A form with an assigned L3 who hasn't remarked yet is correctly "Not Worked." A form where L3 was never assigned (assigned_l3_counsellor_id IS NULL) also falls here.
- **`form_key` dedup**: One student can have multiple courses at the same college. `COUNT(DISTINCT form_key)` counts each (student, course) pair once.
- **Verified against user reference** (May 1-14, 2026): CU Lucknow 46, CU Mohali 248, LPU 101 = 395 total. Not Worked = 94.

---

### PATTERN 15 — Forms & Admissions by College (YTD / MTD / FTD)

**Purpose**: College-wise forms, admissions, and F2A conversion rate across three time windows — YTD (till date), MTD (current month), FTD (today). Verified against ground truth (May 15, 2026).

**Logic**: Two DISTINCT ON CTEs — one for forms (first pipeline entry), one for admissions (first Admission/Enrolled entry, excluding partial fees). FULL OUTER JOIN on (student_id, course_id) to catch forms without admissions and vice versa.

```sql
WITH first_form AS (
    SELECT DISTINCT ON (csj.student_id, csj.course_id)
        csj.student_id, csj.course_id,
        (csj.created_at AT TIME ZONE 'Asia/Kolkata')::date AS form_date,
        uc.university_name
    FROM course_status_journeys csj
    JOIN university_courses uc ON csj.course_id = uc.course_id
    WHERE csj.course_status IN (
        'Form Submitted – Portal Pending','Form Submitted – Completed',
        'Walkin Completed','Walkin Marked','Exam/Interview Scheduled',
        'Offer Letter/Results Pending','Offer Letter/Results Released',
        'Ready For Admission'
    )
    ORDER BY csj.student_id, csj.course_id, csj.created_at ASC
),
first_admission AS (
    SELECT DISTINCT ON (csj.student_id, csj.course_id)
        csj.student_id, csj.course_id,
        (csj.created_at AT TIME ZONE 'Asia/Kolkata')::date AS adm_date,
        uc.university_name
    FROM course_status_journeys csj
    JOIN university_courses uc ON csj.course_id = uc.course_id
    WHERE csj.course_status IN ('Admission', 'Enrolled')
      AND (csj.fee_type IS NULL OR csj.fee_type NOT ILIKE '%partial%')
    ORDER BY csj.student_id, csj.course_id, csj.created_at ASC
)
SELECT
    COALESCE(ff.university_name, fa.university_name) AS college_name,
    COUNT(DISTINCT CASE WHEN ff.form_date <= '<end_date>' THEN ff.student_id || '_' || ff.course_id END) AS ytd_forms,
    COUNT(DISTINCT CASE WHEN ff.form_date >= '<month_start>' AND ff.form_date <= '<end_date>' THEN ff.student_id || '_' || ff.course_id END) AS mtd_forms,
    COUNT(DISTINCT CASE WHEN ff.form_date = '<end_date>' THEN ff.student_id || '_' || ff.course_id END) AS ftd_forms,
    COUNT(DISTINCT CASE WHEN fa.adm_date <= '<end_date>' THEN fa.student_id || '_' || fa.course_id END) AS ytd_adm,
    COUNT(DISTINCT CASE WHEN fa.adm_date >= '<month_start>' AND fa.adm_date <= '<end_date>' THEN fa.student_id || '_' || fa.course_id END) AS mtd_adm,
    COUNT(DISTINCT CASE WHEN fa.adm_date = '<end_date>' THEN fa.student_id || '_' || fa.course_id END) AS ftd_adm
FROM first_form ff
FULL OUTER JOIN first_admission fa ON ff.student_id = fa.student_id AND ff.course_id = fa.course_id
GROUP BY COALESCE(ff.university_name, fa.university_name)
ORDER BY ytd_forms DESC;
```

**Key details**:
- **Form date**: First time the (student, course) pair entered the 8-status pipeline (MIN csj.created_at where status is in pipeline). NOT current status.
- **Admission date**: First time the pair reached 'Admission' or 'Enrolled' with partial exclusion.
- **F2A Rate**: Calculate as `admissions * 100.0 / NULLIF(forms, 0)` in your app layer.
- **FULL OUTER JOIN** ensures colleges with admissions but no forms in a period still appear.
- **student_id || '_' || course_id** = form_key for clean dedup.
- **Verified** (May 15, 2026 on regular_lms): All 18 college-level metrics matched ground truth within ±1. Exceptions: YTD Forms off +3 (CU Mohali +1, LPU +1, extra Amity Jaipur row with 1 form).

---

### PATTERN 16 — L3 Counsellor Performance Dashboard (Total/Active/Response Time)

**Purpose**: L3 counsellor-level breakdown showing total forms, active forms, not-initiated count, and response-time buckets (≤3 days, 4-6 days, 7+ days from form creation to first L3 remark). Verified against dashboard ground truth (May 15, 2026, regular_lms).

**Logic**: 5 CTEs — `all_combinations` (every student-course), `first_status` (first pipeline entry), `first_remark_by_l3` (first remark from assigned L3), `latest_status` (current status), then `base` that calculates `days_to_first_action`. Final SELECT groups by L3 counsellor.

```sql
WITH all_combinations AS (
    SELECT DISTINCT student_id, course_id FROM course_status_journeys
    WHERE student_id IN (SELECT student_id FROM students)
),
first_status AS (
    SELECT DISTINCT ON (student_id, course_id)
        student_id, course_id, course_status, created_at AS first_status_date,
        counsellor_id AS status_created_by, assigned_l3_counsellor_id
    FROM course_status_journeys
    WHERE student_id IN (SELECT student_id FROM students)
    ORDER BY student_id, course_id, created_at ASC
),
first_remark_by_l3 AS (
    SELECT DISTINCT ON (fs.student_id, fs.course_id)
        fs.student_id, fs.course_id, sr.created_at AS first_remark_date
    FROM first_status fs
    LEFT JOIN student_remarks sr ON sr.student_id = fs.student_id
        AND sr.counsellor_id = fs.assigned_l3_counsellor_id
    ORDER BY fs.student_id, fs.course_id, sr.created_at ASC
),
latest_status AS (
    SELECT DISTINCT ON (student_id, course_id)
        student_id, course_id, course_status AS latest_status, fee_type
    FROM course_status_journeys
    WHERE student_id IN (SELECT student_id FROM students)
    ORDER BY student_id, course_id, created_at DESC
),
base AS (
    SELECT ac.student_id, ac.course_id,
        fs.first_status_date, fs.assigned_l3_counsellor_id,
        fr.first_remark_date, ls.latest_status, ls.fee_type,
        CASE WHEN fr.first_remark_date IS NOT NULL
             THEN GREATEST(0, EXTRACT(DAY FROM (fr.first_remark_date - fs.first_status_date)))
             ELSE NULL END AS days_to_first_action,
        c.counsellor_name,
        CONCAT(ac.student_id, '_', ac.course_id) AS student_course_key
    FROM all_combinations ac
    JOIN first_status fs ON ac.student_id = fs.student_id AND ac.course_id = fs.course_id
    LEFT JOIN first_remark_by_l3 fr ON ac.student_id = fr.student_id AND ac.course_id = fr.course_id
    LEFT JOIN latest_status ls ON ac.student_id = ls.student_id AND ac.course_id = ls.course_id
    LEFT JOIN counsellors c ON fs.assigned_l3_counsellor_id = c.counsellor_id
    WHERE fs.course_status <> 'Shortlisted'
)
SELECT
    COALESCE(b.counsellor_name, 'Unassigned') AS counsellor,
    COUNT(DISTINCT b.student_course_key) AS total_forms,
    COUNT(DISTINCT CASE WHEN b.latest_status IN (
        'Form Submitted – Portal Pending','Form Submitted – Completed',
        'Walkin Completed','Walkin Marked','Exam/Interview Scheduled',
        'Offer Letter/Results Pending','Offer Letter/Results Released',
        'Ready For Admission'
    ) THEN b.student_course_key END) AS active_forms,
    COUNT(DISTINCT CASE WHEN b.first_remark_date IS NULL THEN b.student_course_key END) AS not_initiated,
    COUNT(DISTINCT CASE WHEN b.first_remark_date IS NOT NULL AND b.days_to_first_action BETWEEN 0 AND 3 THEN b.student_course_key END) AS called_within_3_days,
    COUNT(DISTINCT CASE WHEN b.first_remark_date IS NOT NULL AND b.days_to_first_action BETWEEN 4 AND 6 THEN b.student_course_key END) AS called_4_to_6_days,
    COUNT(DISTINCT CASE WHEN b.first_remark_date IS NOT NULL AND b.days_to_first_action >= 7 THEN b.student_course_key END) AS called_7_plus_days
FROM base b
GROUP BY b.assigned_l3_counsellor_id, b.counsellor_name
ORDER BY total_forms DESC;
```

**Key details**:
- **Total Forms** = every (student, course) pair that entered the pipeline (excl 'Shortlisted'). This is YTD/all-time count.
- **Active Forms** = latest status is one of the 8 active pipeline statuses. NOT an exclusion list.
- **Not Initiated** = assigned L3 has never left a remark on that student.
- **Response-time buckets** = `EXTRACT(DAY FROM (first_remark_date - first_status_date))`. Days between first pipeline entry and first L3 remark.
- **GREATEST(0, ...)** handles edge cases where remark predates the first status.
- **`csj.assigned_l3_counsellor_id`**, NOT `students.assigned_counsellor_l3_id`.
- **Verified** (May 15, 2026, regular_lms): Active Forms, Not Initiated, Called 4-6 Days, Called 7+ Days — 100% match across all counsellors. Total Forms and Called ≤3 Days off by +2 (same YTD boundary drift seen in PATTERN 15).

---

### Example 1 — Counsellor Conversion + Callbacks (L2, Adds Callback Detail)
Question: For each counsellor, show students who reached admission/enrollment, remarks, callbacks, and conversion rate.
```sql
SELECT
    c.counsellor_name,
    COUNT(DISTINCT s.student_id) AS total_students,
    COUNT(DISTINCT CASE WHEN csj.course_status IN ('Admission','Enrolled') AND (csj.course_status='Enrolled' OR csj.fee_type NOT IN ('Partial Done','Partial Paid','Partially Paid')) THEN csj.student_id END) AS converted_students,
    COUNT(DISTINCT sr.remark_id) AS total_remarks,
    COUNT(DISTINCT CASE WHEN sr.callback_date >= CURRENT_DATE THEN sr.remark_id END) AS upcoming_callbacks,
    COUNT(DISTINCT CASE WHEN sr.callback_date < CURRENT_DATE THEN sr.remark_id END) AS overdue_callbacks,
    ROUND(COUNT(DISTINCT CASE WHEN csj.course_status IN ('Admission','Enrolled') AND (csj.course_status='Enrolled' OR csj.fee_type NOT IN ('Partial Done','Partial Paid','Partially Paid')) THEN csj.student_id END)::numeric
          / NULLIF(COUNT(DISTINCT s.student_id),0) * 100, 2) || '%' AS conversion_rate
FROM counsellors c
JOIN students s ON c.counsellor_id = s.assigned_counsellor_id
LEFT JOIN course_status_journeys csj ON s.student_id = csj.student_id
LEFT JOIN student_remarks sr ON s.student_id = sr.student_id AND sr.counsellor_id = c.counsellor_id
WHERE c.role = 'l2' AND c.status = 'active'
GROUP BY c.counsellor_id, c.counsellor_name
HAVING COUNT(DISTINCT s.student_id) > 0
ORDER BY total_students DESC;
```
Key: Callbacks count remark_id. Admission = Admission+Enrolled minus partial. No LIMIT.

---

### Example 2 — University Stage Breakdown (Pre-App from students, rest from csj)
Question: Show how many students are at pre-application, application, admission, enrolled for each university.
```sql
WITH stage_priority AS (
    SELECT uc.university_name, s.student_id,
        MAX(CASE
            WHEN csj.course_status = 'Enrolled' THEN 4
            WHEN csj.course_status = 'Admission' AND csj.fee_type NOT IN ('Partial Done','Partial Paid','Partially Paid') THEN 3
            WHEN csj.course_status IN ('Form Submitted – Portal Pending','Form Submitted – Completed','Walkin Completed','Walkin Marked','Exam/Interview Scheduled','Offer Letter/Results Pending','Offer Letter/Results Released','Ready For Admission') THEN 2
            WHEN s.current_student_status = 'Pre Application' THEN 1
            ELSE 0 END) AS final_stage_rank
    FROM students s
    LEFT JOIN course_status_journeys csj ON s.student_id = csj.student_id
    LEFT JOIN university_courses uc ON csj.course_id = uc.course_id
    GROUP BY uc.university_name, s.student_id
)
SELECT university_name,
    COUNT(*) FILTER (WHERE final_stage_rank=1) AS pre_application,
    COUNT(*) FILTER (WHERE final_stage_rank=2) AS applications,
    COUNT(*) FILTER (WHERE final_stage_rank=3) AS admissions,
    COUNT(*) FILTER (WHERE final_stage_rank=4) AS enrolled
FROM stage_priority
GROUP BY university_name ORDER BY applications DESC;
```
Key: Pre Application uses students.current_student_status; Application/Admission/Enrolled use csj. One student counted at highest stage per university. No LIMIT.

---

### Example 3 — Average TAT (Time to Admission, University-level)
Question: Average days from student creation to admission/enrollment by university.
```sql
SELECT
    uc.university_name,
    COUNT(DISTINCT s.student_id) AS converted_students,
    ROUND(AVG(EXTRACT(EPOCH FROM (sub.first_milestone_date - s.created_at))/86400)::numeric,1) AS avg_tat_days,
    ROUND(MIN(EXTRACT(EPOCH FROM (sub.first_milestone_date - s.created_at))/86400)::numeric,1) AS min_tat_days,
    ROUND(MAX(EXTRACT(EPOCH FROM (sub.first_milestone_date - s.created_at))/86400)::numeric,1) AS max_tat_days
FROM students s
JOIN (
    SELECT student_id, course_id, MIN(created_at) AS first_milestone_date
    FROM course_status_journeys
    WHERE (course_status = 'Admission' AND fee_type NOT IN ('Partial Done','Partial Paid','Partially Paid'))
       OR course_status = 'Enrolled'
    GROUP BY student_id, course_id
) sub ON s.student_id = sub.student_id
JOIN university_courses uc ON sub.course_id = uc.course_id
WHERE s.created_at IS NOT NULL AND sub.first_milestone_date IS NOT NULL
GROUP BY uc.university_name
ORDER BY converted_students DESC;
```
Key: TAT = csj.created_at - students.created_at. NEVER students.updated_at. NEVER student_remarks for TAT.

---

### Example 4 — Monthly Lead Counts by Source
Question: Monthly lead counts over last 6 months by source.
```sql
SELECT
    DATE_TRUNC('month', s.created_at) AS month,
    s.source,
    COUNT(*) AS lead_count
FROM students s
WHERE s.created_at >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '5 months')
GROUP BY DATE_TRUNC('month', s.created_at), s.source
ORDER BY month DESC, lead_count DESC;
```
Key: COUNT(*) for lead counts — each student row is one lead. No DATE_TRUNC offset. No current_student_status filter. No LIMIT.

---

### Example 5 — Course Interest + Shortlist Rate by Degree
Question: For each degree type, which courses have most student interest and shortlist rate.
```sql
SELECT
    uc.degree_name, uc.course_name,
    COUNT(DISTINCT csj.student_id) AS interested_students,
    COUNT(DISTINCT CASE WHEN lcs.latest_course_status = 'Shortlisted' THEN lcs.student_id END) AS shortlisted_students,
    ROUND(COUNT(DISTINCT CASE WHEN lcs.latest_course_status = 'Shortlisted' THEN lcs.student_id END)::numeric * 100.0
          / NULLIF(COUNT(DISTINCT csj.student_id),0), 2) || '%' AS shortlist_rate
FROM university_courses uc
LEFT JOIN course_status_journeys csj ON uc.course_id = csj.course_id AND csj.student_id IN (SELECT student_id FROM students)
LEFT JOIN latest_course_statuses lcs ON uc.course_id = lcs.course_id AND lcs.student_id = csj.student_id
GROUP BY uc.degree_name, uc.course_name
ORDER BY uc.degree_name, interested_students DESC;
```
Key: "student interest" = COUNT(DISTINCT student_id) from csj. Shortlisted from latest_course_statuses (join on both course_id AND student_id). NEVER use preferred_course for interest metrics.

---

### Example 6 — University Fee Breakdown with Deduped Payments
Question: For each university, total admitted students, course worth, deposit collected, fee remaining, breakdown by payment type.
```sql
WITH admitted_students AS (
    SELECT student_id, course_id, MIN(created_at) AS first_admission_date
    FROM course_status_journeys
    WHERE course_status = 'Admission'
      AND fee_type NOT IN ('Partial Done','Partial Paid','Partially Paid')
      AND student_id IN (SELECT student_id FROM students)
    GROUP BY student_id, course_id
),
deduped_payments AS (
    SELECT DISTINCT ON (student_id, course_id, fee_type, created_at::DATE)
        student_id, course_id, deposit_amount,
        INITCAP(TRIM(fee_type)) AS fee_type_clean
    FROM course_status_journeys
    WHERE deposit_amount > 0 AND student_id IN (SELECT student_id FROM students)
    ORDER BY student_id, course_id, fee_type, created_at::DATE, created_at DESC
),
payments AS (
    SELECT student_id, course_id, SUM(deposit_amount) AS total_deposit
    FROM deduped_payments GROUP BY student_id, course_id
)
SELECT
    uc.university_name,
    COUNT(DISTINCT adm.student_id) AS total_admitted_students,
    SUM(uc.total_fees) AS total_course_worth,
    COALESCE(SUM(p.total_deposit),0) AS total_deposit_collected,
    SUM(uc.total_fees) - COALESCE(SUM(p.total_deposit),0) AS total_fee_remaining,
    COUNT(DISTINCT CASE WHEN dp.fee_type_clean = 'Admission Block' THEN dp.student_id END) AS admission_block,
    COUNT(DISTINCT CASE WHEN dp.fee_type_clean = 'Admission Blocked' THEN dp.student_id END) AS admission_blocked,
    COUNT(DISTINCT CASE WHEN dp.fee_type_clean IN ('Partially Paid','Partial Done','Partial Paid') THEN dp.student_id END) AS partially_paid
FROM admitted_students adm
JOIN university_courses uc ON adm.course_id = uc.course_id
LEFT JOIN payments p ON adm.student_id = p.student_id AND adm.course_id = p.course_id
LEFT JOIN deduped_payments dp ON adm.student_id = dp.student_id AND adm.course_id = dp.course_id
GROUP BY uc.university_name
ORDER BY total_deposit_collected DESC;
```
Key: MIN(created_at) per (student_id, course_id) for first admission. DISTINCT ON dedup for payments. INITCAP(TRIM()) normalizes fee_type. COALESCE for NULL payments.

---

### Example 7 — Login/Logout Time per Counsellor (Today)
Question: Each counsellor's login and logout time for today (first/last remark 9:30 AM–8:30 PM).
```sql
SELECT
    c.counsellor_name,
    MIN(sr.created_at AT TIME ZONE 'Asia/Kolkata') AS login_time,
    MAX(sr.created_at AT TIME ZONE 'Asia/Kolkata') AS logout_time,
    EXTRACT(EPOCH FROM (MAX(sr.created_at) - MIN(sr.created_at)))/3600 AS working_hours
FROM counsellors c
JOIN student_remarks sr ON c.counsellor_id = sr.counsellor_id
WHERE sr.created_at >= CURRENT_DATE - INTERVAL '5 hours 30 minutes'
  AND sr.created_at <  CURRENT_DATE + INTERVAL '1 day' - INTERVAL '5 hours 30 minutes'
  AND EXTRACT(HOUR FROM sr.created_at AT TIME ZONE 'Asia/Kolkata') * 60
      + EXTRACT(MINUTE FROM sr.created_at AT TIME ZONE 'Asia/Kolkata') BETWEEN 570 AND 1230
  AND sr.student_id IN (SELECT student_id FROM students)
  AND c.role = 'l2' AND c.status = 'active'
GROUP BY c.counsellor_id, c.counsellor_name
ORDER BY login_time ASC;
```
Key: 9:30 AM = 570 min, 8:30 PM = 1230 min. MIN = login, MAX = logout. IST display. L2 default.

---

### Example 8 — Yesterday's Daily Activity Summary
Question: Yesterday's summary — first ICC, first NI, first connected, unique remarks.
```sql
WITH first_icc AS (
    SELECT COUNT(DISTINCT student_id) AS icc_count FROM students
    WHERE first_icc_date >= CURRENT_DATE - INTERVAL '1 day' - INTERVAL '5 hours 30 minutes'
      AND first_icc_date <  CURRENT_DATE - INTERVAL '5 hours 30 minutes'
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
      AND first_ni_at <  CURRENT_DATE - INTERVAL '5 hours 30 minutes'
),
first_connected AS (
    SELECT COUNT(DISTINCT student_id) AS connected_count FROM (
        SELECT student_id, MIN(created_at) AS first_connected_at
        FROM student_remarks WHERE calling_status = 'Connected' GROUP BY student_id
    ) sub
    WHERE first_connected_at >= CURRENT_DATE - INTERVAL '1 day' - INTERVAL '5 hours 30 minutes'
      AND first_connected_at <  CURRENT_DATE - INTERVAL '5 hours 30 minutes'
),
unique_remarks AS (
    SELECT COUNT(DISTINCT student_id) AS unique_remarks_count FROM student_remarks
    WHERE created_at >= CURRENT_DATE - INTERVAL '1 day' - INTERVAL '5 hours 30 minutes'
      AND created_at <  CURRENT_DATE - INTERVAL '5 hours 30 minutes'
      AND student_id IN (SELECT student_id FROM students)
)
SELECT
    (SELECT icc_count FROM first_icc) AS total_first_icc,
    (SELECT ni_count FROM first_ni) AS total_first_ni,
    (SELECT connected_count FROM first_connected) AS total_first_connected,
    (SELECT unique_remarks_count FROM unique_remarks) AS total_unique_remarks;
```
Key: first_icc_date (lowercase, no quotes). Four scalar subqueries return one summary row. first_ni = DISTINCT ON earliest remark of current NI students.

---

## NATURAL LANGUAGE -> SQL INTENT

| User says | SQL intent | Pattern/Rule |
|-----------|-----------|--------------|
| "leads today" / "leads generated" | COUNT(*) from students WHERE created_at (IST today) | TZ1, F4 |
| "forms today" / "form fills" / "applications" | MIN(created_at) per (student_id,course_id), 8-status IN list, date filter | PATTERN 5A, S2 |
| "admissions yesterday" / "admitted this week" | MIN(created_at) per (student_id,course_id), Admission+Enrolled excl partial | PATTERN 5A, S16 |
| "Portal Pending vs Completed today" | DISTINCT ON per status, date filter on outer query | PATTERN 5B |
| "enrolled count" | course_status = 'Enrolled' ONLY | D3 |
| "funnel breakdown" / "stage wise count" | UNION ALL from students + csj | PATTERN 1A |
| "counsellor wise stage breakdown" | Pivot, L2 default | PATTERN 1B |
| "university wise stage breakdown" | MAX(stage_rank) per student-university | PATTERN 1C |
| "counsellor wise" / "per counsellor" | L2 default, join via assigned_counsellor_id, role='l2' | CNS-DEFAULT |
| "L3 counsellor form count" | course_status_journeys.assigned_l3_counsellor_id, role='l3' | CNS-L3, PATTERN 7B |
| "team performance" / "team wise calls" | manager -> team_member -> student_remarks, role ILIKE '%to%' | PATTERN 2 note |
| "success rate" / "connection rate" | COUNT(Connected)/COUNT(all) from student_remarks | D6 |
| "conversion rate" | COUNT admitted / COUNT applied from csj via CASE WHEN | D6, PATTERN 3 |
| "ICC count" / "initial counselling" | first_icc_date IS NOT NULL | S12, S14 |
| "dormant students" / "no follow-up" | HAVING MAX(sr.created_at) < CURRENT_DATE - 7 days OR IS NULL | PATTERN 4 |
| "shortlisted" | latest_course_status = 'Shortlisted' from latest_course_statuses | D1 |
| "region" / "Punjab region" | university_courses.university_state | S7 |
| "NI reasons" / "why NI" | students.current_student_ni_sub_status | D7 |
| "pre-NI" | current_student_status=NI + no ICC + not in csj forward stages | PATTERN 9A |
| "first NI today" | DISTINCT ON earliest remark of NI students, date filter | PATTERN 9B |
| "first connected today" | MIN(created_at) per student WHERE Connected, date filter | PATTERN 8 |
| "attempted calls on new leads" | date filter in students LEFT JOIN ON clause | PATTERN 10A |
| "total leads + attempted today" | date filter in students LEFT JOIN ON, all counsellors | PATTERN 10B |
| "login time" / "working hours" | MIN/MAX remark between 9:30AM-8:30PM IST | Example 7 |
| "forms and admissions for [uni]" | two CTEs MIN(created_at), UNION ALL | PATTERN 6 |
| "L3 response time" / "L3 form TAT" | complex CTE: first/latest status + first remark by L3 | PATTERN 11 |
| "above/below average" | Two CTEs + CROSS JOIN benchmark | PATTERN 3 |
| "campaign wise NI" | fresh_leads + campaign_totals + status_breakdown CTEs | PATTERN 12 |
| "form working status" / "active forms by college" / "forms not worked" | 5 CTEs: active_forms_all + period_active + active_forms + last_l3_remark + final SELECT | PATTERN 14 |
| "YTD/MTD/FTD forms and admissions" / "college wise forms admissions" | DISTINCT ON first-form + DISTINCT ON first-admission, FULL OUTER JOIN, date-window CASE | PATTERN 15 |
| "L3 counsellor performance" / "counsellor dashboard" / "counsellor total active forms" | 5 CTEs: all_combinations + first_status + first_remark_by_l3 + latest_status + base, GROUP BY assigned_l3_counsellor_id | PATTERN 16 |

---

## QUERY AMBIGUITY DISAMBIGUATION

| Ambiguous term | Regular LMS clarification |
|---------------|--------------------------|
| "Application" | NOT a single status. Means 8-status IN list. NEVER course_status = 'Application' |
| "Admission" | course_status IN ('Admission','Enrolled') with partial exclusion. NOT students table |
| "counsellor" (no level) | Always L2 by default. Only L3 if explicitly requested |
| "connected" | 3 meanings: is_connected_yet (L2 boolean), is_connected_yet_l3 (L3 boolean), calling_status = 'Connected' (call-level) |
| "forms" vs "leads" | Forms = 8-status pipeline in csj. Leads = students created (created_at) |
| "fresh leads" | "Fresh leads today" = students created today. "Total fresh right now" = current_student_status = 'Fresh' |
| "region" | university_courses.university_state — NOT students.student_current_state |
| "team owner" | role ILIKE '%to%' (covers both to and to_l3). NEVER role = 'to' alone |
| "L3 counsellor FK" | course_status_journeys.assigned_l3_counsellor_id — NEVER students.assigned_counsellor_l3_id |
| "success rate" vs "conversion rate" | Success = call connection rate (student_remarks). Conversion = admission rate (course_status_journeys) |
| "Chandigarh University Lucknow" | ILIKE '%Chandigarh University%' AND ILIKE '%Lucknow%' — AND not OR |
| "College Status Report" | FIRST CSJ per (student_id,course_id) by created_at ASC within date range — NOT student_college_credentials. Status = that CSJ entry's course_status. Date filter on min(created_at) per pair. See PATTERN 13. |
