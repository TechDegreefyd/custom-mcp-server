# CRM Rules — Text-to-SQL Agent Reference

> **⚠️ NOT an LMS database.** This is a post-admission servicing CRM — students here are already enrolled. Do NOT use LMS rules, statuses, or counsellor patterns here.
>
> **🔑 META-RULE**: These rules are your primary reference. However, the database can drift. When stuck, getting unexpected results, or needing schema/value details, use MCP tools (`get_table_context`, `run_select_query`, `describe_table`) to verify against the live database.

---

# CRM — TEXT-TO-SQL KNOWLEDGE BASE
# READ TIMEZONE BLOCK AND RULES BEFORE WRITING ANY SQL.

---

## CONTEXT — What this CRM does

This CRM manages enrolled students **after** they have been admitted via the LMS. It covers:
- **Documentation** — collecting and verifying student documents (KYC, academic, work)
- **Enrollment** — DIP workflow (Docs Pending → Docs Submitted → Under Verification → E-sign → Enrolled)
- **Servicing** — onboarding, activation, check-ins, LMS credential sharing
- **Placement** — placement follow-ups, strategy sessions, optimization
- **Finance** — invoicing, installment tracking, revenue items, commission calculations
- **Ticketing** — LMS issues, academic queries, portal problems raised by students

Students flow through: `DIP → Enrolled → Onboarded → Activated → Refunded`

**Sessions:** Jan 2026, July 2026

---

## TABLES

---

### students
One row per enrolled student. Central record.

Key columns: id (PK — `STD-XXXXXXXX` format), name, age, state, city, university, course, course_id, highest_degree, work_experience, current_profession, lead_status (enum), dip_sub_stage, lms_status, session, source, fee_type, deposit_amount, payment_mode, admission_taken_date, enrollment_date, student_created_at, created_at, updated_at

Counsellor FK columns:
- `assigned_servicing_counsellor_id` → servicing team (not all students assigned)
- `assigned_documentation_counsellor_id` → documentation team (all students assigned)
- `assigned_placement_counsellor_id` → placement team (very sparse — most students unassigned)
- `assigned_sales_counsellor_id` → sales team (sparse)
- `assigned_sales_team_counsellor` → sales team text label (sparse)

Status columns:
- `lead_status` (enum): `DIP`, `Enrolled`, `Onboarded`, `Activated`, `Refunded`
- `dip_sub_stage`: `Docs Pending`, `Docs Submitted`, `Under Verification`, `Enrolled_L1 Checked`, `E-sign Pending`, `Resubmitted`, `Results Awaited`, `Rework Required`, `Refund Applied`, `Completed`, `Enrolled`
- ⚠️ `IDs Created` is **NOT** a `dip_sub_stage` value on the `students` table — it exists only as a `stage` in `student_workflows` (documentation team). It represents university/LMS credentials being created after a student leaves DIP. Never use it as a `dip_sub_stage` filter on `students`.
- `lms_status`: currently only `New`

Boolean flags: `review_link_sent`, `lms_credentials_shared`, `calendar_link_sent`, `resume_optimized`, `linkedin_optimized`, `classes_started`, `review_posted`, `instagram_posted`, `gap`

Business rules:
- PK is `id` (not `student_id` — that's the FK name in other tables)
- `student_created_at` = when student originally came into system (may differ from `created_at` = CRM record creation)
- `session` values: `Jan 2026`, `July 2026`
- `languages` is a PostgreSQL ARRAY — use `'Value' = ANY(languages)`
- NEVER count students using `lms_status` for funnel — use `lead_status`
- Refunded students: `lead_status = 'Refunded'` — always exclude from active counts unless user asks
- `dip_sub_stage` is only meaningful when `lead_status = 'DIP'` — **but Refunded students can also have dip_sub_stage set** (e.g. `Refund Applied`, `Docs Pending`) — do not assume dip_sub_stage=NULL for Refunded
- `source` has casing inconsistencies: `FaceBook` / `Facebook`, `student_ref` / `Student_Ref` — always use ILIKE for source filtering

---

### users
One row per CRM staff member.

Key columns: id (PK — hex string like `9643B571D1`), name, email, role (enum: `admin`, `supervisor`, `counsellor`), team_type (enum: `servicing`, `placement`, `documentation`), supervisor_id (self-ref FK), is_active, last_login, accesslevel

Business rules:
- ALWAYS JOIN users for staff names — never construct names from IDs
- Filter active staff: `is_active = true`
- Supervisor: `role = 'supervisor'` or check `supervisor_id` chain
- `team_type` determines which team a counsellor belongs to — always filter by it for team-specific queries
- **`admin` role users often have NULL `team_type`** — do not assume all users have a team
- **⚠️ "Anupama Jha" exists 3 times with 3 different IDs** (servicing supervisor, documentation supervisor, admin with null team_type). NEVER filter by name alone — always JOIN and filter by `team_type` or `role` too
- NEVER SELECT password column
- `accesslevel` values: `all`, `everything` — not used for filtering in most queries

---

### student_workflows
Append-only audit log of every workflow stage transition. Multiple rows per student.

Key columns: id (PK uuid), student_id, team_type (enum), stage, status (`active`/`completed`), assigned_counsellor_id, remark, created_at, updated_at

Stage values by team (validated):
- **documentation**: Docs Pending, Docs Submitted, Under Verification, Enrolled_L1 Checked, E-sign Pending, Resubmitted, Results Awaited, IDs Created, Rework Required, Refund Applied
  - `IDs Created` exists here but NOT in `students.dip_sub_stage` — student has already left DIP by this point
  - Stage order: Docs Pending → Docs Submitted → Under Verification → Enrolled_L1 Checked → E-sign Pending → Resubmitted/Rework Required → Results Awaited → IDs Created → Refund Applied
- **servicing**: Onboarding, Activation, General Checkin
- **placement**: Onboarding, Optimization, Strategy
- **admin**: Enrollment Approval Required

Business rules:
- This is append-only — ALWAYS deduplicate before date-filtering (use `MIN(created_at)` or `DISTINCT ON`)
- `status = 'active'` = stage currently in progress; `status = 'completed'` = stage done
- For current stage per student: `DISTINCT ON (student_id) ORDER BY student_id, created_at DESC`
- `team_type` filters which team's workflow is being viewed (servicing/placement/documentation/admin)
- Do NOT use this table to count students — use `students` table
- **All students have at least one workflow row** — no gaps
- **Date filtering uses IST cast**: `(sw.created_at AT TIME ZONE 'Asia/Kolkata')::date = 'YYYY-MM-DD'` — this is how the CRM app filters, NOT manual UTC offset math
- **A student can have multiple workflow rows created on the same day across different stages** — do NOT assume one row per student per day
- **Documentation Workflows Report counting rule (validated from app source code)**: The app's "TOTAL" column = SUM of per-stage counts, NOT COUNT(DISTINCT student_id). A single student can appear in multiple stage columns if they have workflow rows for multiple stages created on the same date. This is by design — tracks workflow activity, not unique students.
- **No status filter on date-based reports** — the Documentation Workflows Report includes both `active` AND `completed` workflow rows when filtering by date. Do NOT add `AND status = 'active'` when replicating this report.

---

### remarks
Call/interaction log. Multiple rows per student.

Key columns: id (PK uuid), student_id, counsellor_id (FK → users.id), team_type, stage, calling_status (enum: `CONNECTED`/`NOT_CONNECTED`), call_type (enum: `phone`/`video`), callback_at (timestamptz — NOT a date), remark (text), stage_status (enum: `in_progress`/`completed`), is_task, is_completed, created_at

Business rules:
- `calling_status` is UPPERCASE: `CONNECTED` / `NOT_CONNECTED` (unlike LMS which uses `Connected`/`Not Connected`)
- `callback_at` is a full timestamptz — APPLY timezone offset when filtering (unlike LMS `callback_date` which is DATE)
- Success rate = `COUNT(CASE WHEN calling_status='CONNECTED' THEN 1 END) / COUNT(*)`
- Always COUNT(DISTINCT id) after JOINs — never COUNT(*)
- `is_task = true` rows are tasks, not calls — always exclude from call metrics unless user asks
- For upcoming callbacks: `callback_at > NOW()`; overdue: `callback_at < NOW() AND callback_at IS NOT NULL`
- ALWAYS filter `AND student_id IN (SELECT id FROM students)` when not joined to students
- **Validated: 0 orphaned remarks** — all student_ids in remarks exist in students
- Almost all students have at least one call remark
- **stages in remarks include extra values** not in student_workflows: `System Migration`, `Ticketing`, `Ticketing Progress`, `Meeting Rescheduled`, `Placement Call`, `Placement Follow up`, `Placement session` — these are remark-only stages
- `call_type`: `phone` is the vast majority; `video` calls are rare

---

### student_status_histories
Append-only audit of lead_status changes.

Key columns: id (PK uuid), student_id, status, sub_stage, remarks, changed_by (FK → users.id), created_at

Status values: `DIP`, `Enrolled`, `Onboarded`, `Activated`, `Refunded`

Business rules:
- Use this table for "when did student become X" queries (date of status change)
- For current status use `students.lead_status` — this table is for history/audit
- First occurrence of a status: `MIN(created_at)` per student filtered by status
- Refund reason: check `remarks` column (contains text like "Refund Processed: ...")
- **⚠️ This table is incomplete** — many students have NO status history rows. Do NOT use it to count all students at a status; use `students.lead_status` for that

---

### enrollment_approvals
Manager approval/rejection records for enrollments.

Key columns: id (PK uuid), student_id, manager_id, performed_by, status (enum: `approved`/`rejected`), rejection_reason, created_at

Business rules:
- `performed_by` = documentation counsellor who submitted for approval
- `manager_id` = supervisor who approved/rejected
- Rejection reasons are stored as free text in `rejection_reason`
- For approval rate: `COUNT(CASE WHEN status='approved' THEN 1 END) / COUNT(*)`
- Approval rate is very high — almost all submissions get approved
- `performed_by` is sparse — only a small number of counsellors have submitted approvals

---

### documents
Student documents uploaded for enrollment. Multiple rows per student.

Key columns: id (PK uuid), student_id, document_name, document_type, file_url, uploaded_by (FK → users.id), created_at

Document types: `Academic`, `KYC`, `L1 Checked Document`, `Photo`, `Work`

Business rules:
- One row per document — a student can have multiple documents
- `uploaded_by` links to the documentation counsellor who uploaded
- Document completeness = COUNT of docs per student by type
- NEVER return `file_url` unless user explicitly asks
- Many students have no documents uploaded yet — document coverage is incomplete

---

### counsellor_tasks
Pending/completed tasks per counsellor.

Key columns: id (PK uuid), student_id, counsellor_id, name (enum: `Onboarding`/`Placement Follow up`/`General Checkin`/`Activation`), assigned_team (enum: `servicing`/`placement`), status (enum: `pending`/`completed`), count, last_action_at, created_at

Business rules:
- Use for task completion rate per counsellor: `COUNT(CASE WHEN status='completed' THEN 1 END) / COUNT(*)`
- Pending tasks per counsellor: `WHERE status = 'pending'`
- `count` = number of interactions on this task
- `last_action_at` = last time counsellor acted on this task
- **General Checkin has 0 completed tasks** — do not use completion rate for General Checkin
- `assigned_team` can be `servicing` or `placement` — Placement Follow up appears under both

---

### student_finances
One row per student's financial record.

Key columns: id (PK int), student_id, course_id, invoice_date, total_payment_credited, gst_payment_credited, variable_payment_credited, tds_deducted, deficit_amount, total_variable, invoicing_variable, fee_type, payment_mode, current_status, duration_years, is_eligible_for_payment, subvention_deducted, invoicing_payment_credited, invoicing_deficit_amount, created_at

current_status values: `To be Invoiced`, `Ready to invoice`, `Invoiced- Payment Pending`, `Invoiced - Payment done`, `Refunded Amount`

fee_type values: `Full Fee Paid`, `Semester fee paid`, `Semester Paid`, `Annual Paid`
payment_mode values: `Self`, `self`, `EMI`, `emi` (inconsistent casing — always use ILIKE or UPPER())

Business rules:
- One row per student — JOIN on `student_id`
- `total_payment_credited` = total money received from university
- `deficit_amount` = amount still pending from university
- `is_eligible_for_payment`: whether university has cleared the student for payment
- ALWAYS use ILIKE or UPPER() for `payment_mode` and `fee_type` — casing is inconsistent
- For revenue totals: SUM(total_payment_credited) per university/counsellor
- `invoicing_variable` and `total_variable` = commission components

---

### student_installments
EMI/installment schedule per student. Multiple rows per student (~2 on average).

Key columns: id (PK int), finance_id (FK → student_finances.id), student_id, period, amount, status (enum: `pending`/`invoiced`/`paid`), paid_date, invoice_id, created_at

Period values: `Full Payment`, `Year`, `Year 1`, `Year 2`, `Year 3`, `Semester 1` through `Semester 6`

Business rules:
- For pending collections: `WHERE status = 'pending'`
- For paid installments: `WHERE status = 'paid'`
- JOIN to `student_finances` via `finance_id` for university/course context
- SUM(amount) WHERE status = 'pending' = total outstanding EMI collection
- `paid_date` is type DATE — no timezone offset needed

---

### student_pricing_snapshots
Locked fee/commission structure at time of enrollment. One row per student.

Key columns: id (PK int), student_id, course_id, commission_percentage, annual_fee, semester_fee, full_course_fee, fee_type, gst_rate (default 18%), tds_rate, is_locked, subvention_semester/annual/full, discount_percentage, created_at

Business rules:
- `is_locked = true` means rates are frozen and should not change
- Use this table for commission calculations — NOT `course_fee_master` (which is catalog/master data)
- `commission_percentage` = Degreefyd's commission % for this student's enrollment
- Snapshot is taken at time of enrollment and locked — reflects actual deal terms

---

### student_revenue_items
Breakdown of revenue components per finance record. Two rows per student.

Key columns: id (PK int), finance_id, student_id, label (`Invoicing Variable`/`Total Variable`), amount_wo_gst, amount_with_gst, gst_amount, tds_deduction, subvention_deduction, discount_deduction, net_wo_gst, net_with_gst, collected_amount, is_received, received_date, created_at

Business rules:
- Two rows per student: one for `Invoicing Variable`, one for `Total Variable`
- `is_received = true` = payment received from university
- `collected_amount` = actual amount collected
- For revenue analysis: JOIN to student_finances via finance_id

---

### course_fee_master
Master catalog of course fees per university.

Key columns: id (PK int), university_name, course_name, specialization, course_id (FK), annual_fee, semester_fee, full_course_fee, is_active, created_at

University names: `Amity University Online`, `Chandigarh University Online`, `Galgotias University Online`, `GLA University Online`, `Lovely Professional University Online`, `Manipal University Online`, `Shoolini University online`, `Sikkim Manipal University Online`, `Vivekanand Global University Online`

Business rules:
- Use for catalog/master fee lookup — NOT for individual student fee (use `student_pricing_snapshots`)
- Always filter `is_active = true` unless user asks for all/inactive courses
- University name matching: use ILIKE '%University Name%' — casing inconsistent (e.g. "Galgotia" vs "Galgotias")

---

### college_onboardings
University partnership config. One row per partner university.

Key columns: id (PK int), college_name, commission_percentage, course_commissions (JSONB), gst_applicable, gst_percentage, tds_applicable, tds_percentage, billing_cycle, subvention_semester/annual/full, global_discounts (JSONB), course_discounts (JSONB), created_at

Business rules:
- One row per partner university
- `course_commissions` is JSONB with per-course commission overrides — use `->>` for key access
- `billing_cycle = 'Monthly'` for all current universities
- Commission for a student = check `student_pricing_snapshots.commission_percentage` (locked at enrollment) not this table

---

### tickets
Student support tickets.

Key columns: id (PK — `TKT-2026-XXXX` format), student_id, raised_by (FK → users.id), date_raised, issue_category (enum: `Academic`/`LMS`/`Other`), issue_description, status (enum: `Support`/`Resolution — WIP`/`Resolution — Solved`), resolution_notes, closed_by, closed_date, created_at

Business rules:
- Ticket status flow: `Support` → `Resolution — WIP` → `Resolution — Solved`
- Open tickets: `status != 'Resolution — Solved'`
- Closed tickets: `status = 'Resolution — Solved'`
- Resolution time: `closed_date - date_raised`

---

### notifications
System notifications per user. High volume — avoid full scans.

Key columns: id (PK uuid), user_id, message, type (enum: `Approval`/`SLA`/`Success`/`Error`/`Task`), is_read, metadata (JSONB), created_at

Business rules:
- High row count — ALWAYS add a date filter or LIMIT for queries on this table
- `is_read = false` = unread notifications
- `metadata` is JSONB — use `->>` for key access

---

## TIMEZONE — READ FIRST

All `created_at` / `updated_at` columns store UTC. `CURRENT_DATE` is IST.

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
- `paid_date` (student_installments), `invoice_date`, `received_date` are type DATE — NEVER apply timezone offset
- `callback_at` (remarks) is timestamptz — ALWAYS apply IST offset when filtering by date
- NEVER use NOW() without IST adjustment for date boundary comparisons
- NEVER expose raw UTC timestamps in output — always `AT TIME ZONE 'Asia/Kolkata'`

---

## RULES

### Output Rules

**O1.** NEVER SELECT `password`, `phone`, `email` unless the user explicitly requests them.

**O2.** NEVER SELECT * — always name columns explicitly.

**O3.** Stage breakdowns use wide/pivot format — one row per entity, one column per stage via CASE WHEN. NEVER long format.

**O4.** Counsellor performance queries MUST include total_students or total_tasks as a base column.

**O5.** ONLY return columns the user explicitly asked for.

**O6.** List queries MUST include ORDER BY.

**O7.** Whenever a timestamptz column is returned to the user, MUST convert to IST using `AT TIME ZONE 'Asia/Kolkata'`.

---

### Filter Rules

**F1.** NEVER add `is_active` filter on users unless user says "active counsellors".

**F2.** NEVER add LIMIT unless user says "top N" or uses a superlative.

**F3.** NEVER add HAVING unless user asks for a minimum count or threshold.

**F4.** ALWAYS exclude `lead_status = 'Refunded'` from active student counts unless user explicitly includes refunds.

**F5.** `dip_sub_stage` filter is only meaningful combined with `lead_status = 'DIP'`.

---

### Table Selection Rules

**T1.** ALWAYS JOIN users to get counsellor/staff names. Never construct names from IDs.

**T2.** For current student status → `students.lead_status`. For history of status changes → `student_status_histories`.

**T3.** For workflow stage currently active → `student_workflows WHERE status = 'active'`. For history → all rows.

**T4.** For fee catalog/course fee structure → `course_fee_master`. For individual student's locked fee deal → `student_pricing_snapshots`.

**T5.** For overall finance status/totals → `student_finances`. For installment breakdown → `student_installments`. For revenue line items → `student_revenue_items`.

**T6.** NEVER count students from `student_workflows` or `remarks` — always from `students`.

**T7.** For call metrics → `remarks` table. NOT `counsellor_tasks`.

**T8.** For task completion → `counsellor_tasks`. NOT `remarks`.

**T9.** Counsellor FK on `students` differs by team — use the right one:
- Servicing: `assigned_servicing_counsellor_id`
- Documentation: `assigned_documentation_counsellor_id`
- Placement: `assigned_placement_counsellor_id`
- Sales: `assigned_sales_counsellor_id`

**T10.** Child tables without students JOIN → ALWAYS add `AND student_id IN (SELECT id FROM students)`.

---

### Status / Column Rules

**S1.** Student funnel order: `DIP → Enrolled → Onboarded → Activated → Refunded`

**S2.** DIP sub-stages order: `Docs Pending → Docs Submitted → Under Verification → Enrolled_L1 Checked → E-sign Pending → Resubmitted/Rework Required → Results Awaited → Completed`

**S3.** `calling_status` in `remarks` is UPPERCASE: `CONNECTED` / `NOT_CONNECTED`. Never lowercase.

**S4.** `payment_mode` and `fee_type` have inconsistent casing — always use `UPPER(payment_mode)` or `ILIKE`.

**S5.** ALWAYS `COUNT(DISTINCT id)` after JOINs. Never `COUNT(*)`.

**S6.** `callback_at` is timestamptz — apply IST offset. `paid_date` is DATE — no offset.

**S7.** `is_task = true` rows in `remarks` are tasks, not calls. Exclude from call metrics.

**S8.** University name matching → always use ILIKE with wildcards: `ILIKE '%Manipal%'`. Names have casing inconsistencies across tables.

**S9.** `student_workflows` is append-only — for current stage use `DISTINCT ON (student_id) ORDER BY student_id, created_at DESC`.

**S10.** `student_status_histories` is **incomplete** — many students have no rows. NEVER count students from this table. Use it only for date-of-change lookups on students where it exists.

**S11.** `source` column has duplicate values with inconsistent casing (`FaceBook`/`Facebook`, `student_ref`/`Student_Ref`, `counsellor_ref`). Always use ILIKE for source filtering. Top sources: FaceBook (~142), Google_Lead_Form (111), FaceBook_University_Admit (91), Landing Page (54).

**S12.** **"Anupama Jha" is 3 different users** with 3 different IDs and team types. When querying by name for a specific team, always add `AND u.team_type = '<team>'` or `AND u.role = '<role>'` to disambiguate.

---

### Join Rules

**J1.** NEVER filter by counsellor name on any base table. Always JOIN users and use `u.name ILIKE '%Name%'`.

**J2.** When joining users for call metrics, use LEFT JOIN to preserve zero-call counsellors.

**J3.** `student_finances` → `student_pricing_snapshots` → `student_revenue_items` all JOIN on `student_id`. **Every student has exactly 1 row in each** — INNER JOIN is safe.

**J4.** `student_installments` JOINs to `student_finances` via `finance_id`. Every student has installment rows.

**J5.** Two logically independent counts from different tables → use correlated subqueries or CROSS JOIN of single-row CTEs. NEVER join the tables directly.

**J6.** Child table without students JOIN → `AND student_id IN (SELECT id FROM students)`.

---

### Finance Rules

**FIN1.** Commission calculation uses `student_pricing_snapshots.commission_percentage` — locked at enrollment. Do NOT use `college_onboardings.commission_percentage` for individual student calculations.

**FIN2.** Revenue received from university: `student_finances.total_payment_credited`.

**FIN3.** Outstanding from university: `student_finances.deficit_amount`.

**FIN4.** Student's payment to university: `students.deposit_amount` (what they paid to Degreefyd) — separate from what university pays Degreefyd.

**FIN5.** EMI students: filter `UPPER(students.payment_mode) = 'EMI'`. Self-pay: `UPPER(students.payment_mode) = 'SELF'`.

**FIN6.** For revenue line-item analysis: use `student_revenue_items`. Two rows per student: `Invoicing Variable` and `Total Variable`.

---

## DISTINCTIONS

### D1 — Three Counsellor FK Columns on students
| Team | FK Column | users.team_type filter |
|------|-----------|----------------------|
| Servicing | `assigned_servicing_counsellor_id` | `team_type = 'servicing'` |
| Documentation | `assigned_documentation_counsellor_id` | `team_type = 'documentation'` |
| Placement | `assigned_placement_counsellor_id` | `team_type = 'placement'` |

NEVER mix FK columns. A "servicing counsellor wise" query uses `assigned_servicing_counsellor_id`.

---

### D2 — lead_status vs dip_sub_stage
| Column | When to use |
|--------|------------|
| `students.lead_status` | Current top-level funnel stage: DIP / Enrolled / Onboarded / Activated / Refunded |
| `students.dip_sub_stage` | Only meaningful for students in DIP stage — granular docs/verification sub-stage |

---

### D3 — Fee Tables
| User asks about | Table | Column |
|----------------|-------|--------|
| Course catalog price | `course_fee_master` | `annual_fee` / `semester_fee` / `full_course_fee` |
| Student's locked fee at enrollment | `student_pricing_snapshots` | same column names |
| Revenue from university | `student_finances` | `total_payment_credited` |
| Student paid Degreefyd | `students` | `deposit_amount` |
| Installment schedule | `student_installments` | `amount`, `status`, `paid_date` |

---

### D4 — Student Created vs Enrolled
| Column | Meaning |
|--------|---------|
| `students.student_created_at` | When student originally came into system (from LMS) |
| `students.created_at` | When CRM record was created |
| `students.admission_taken_date` | Date of admission |
| `students.enrollment_date` | Date of enrollment confirmation |

---

### D5 — Remarks vs Tasks
| Table | Purpose |
|-------|---------|
| `remarks` | Call/interaction log — calling_status CONNECTED/NOT_CONNECTED |
| `counsellor_tasks` | Structured tasks (Onboarding, Activation, Placement Follow up, General Checkin) |
| `remarks WHERE is_task = true` | Tasks logged within the remarks system — exclude from call metrics |

---

## PATTERNS

### PATTERN 1 — Student Count by Lead Status (Funnel)
```sql
SELECT
    lead_status,
    COUNT(DISTINCT id) AS student_count
FROM students
WHERE lead_status != 'Refunded'   -- exclude unless asked
GROUP BY lead_status
ORDER BY
    CASE lead_status
        WHEN 'DIP'       THEN 1
        WHEN 'Enrolled'  THEN 2
        WHEN 'Onboarded' THEN 3
        WHEN 'Activated' THEN 4
        ELSE 5
    END;
```

---

### PATTERN 2 — DIP Sub-Stage Breakdown
```sql
SELECT
    dip_sub_stage,
    COUNT(DISTINCT id) AS student_count
FROM students
WHERE lead_status = 'DIP'
GROUP BY dip_sub_stage
ORDER BY student_count DESC;
```
-- NOTE: 'IDs Created' will never appear here — it only exists in student_workflows, not students.dip_sub_stage

---

### PATTERN 13 — University-wise Admission Report (Validated)
-- Four mutually exclusive top-level buckets: Enrolled+ | Refunded | Refund Applied | DIP
-- Enrolled+ = Enrolled/Onboarded/Activated | Refund Applied = DIP students with dip_sub_stage='Refund Applied'
-- DIP column = active DIP students excluding Refund Applied sub-stage
-- IDs Created is intentionally excluded — it is a student_workflows stage, NOT a dip_sub_stage on students
```sql
SELECT
    s.university,
    COUNT(DISTINCT s.id) AS total_admissions,
    COUNT(DISTINCT CASE WHEN s.lead_status IN ('Enrolled', 'Onboarded', 'Activated') THEN s.id END) AS enrolled_plus,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'Refunded' THEN s.id END) AS refunded,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'DIP' AND s.dip_sub_stage = 'Refund Applied' THEN s.id END) AS refund_applied,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'DIP' AND s.dip_sub_stage IS DISTINCT FROM 'Refund Applied' THEN s.id END) AS dip,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'DIP' AND s.dip_sub_stage = 'Docs Pending'        THEN s.id END) AS docs_pending,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'DIP' AND s.dip_sub_stage = 'Docs Submitted'      THEN s.id END) AS docs_submitted,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'DIP' AND s.dip_sub_stage = 'Under Verification'  THEN s.id END) AS under_verification,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'DIP' AND s.dip_sub_stage = 'E-sign Pending'      THEN s.id END) AS esign_pending,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'DIP' AND s.dip_sub_stage = 'Rework Required'     THEN s.id END) AS rework_required,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'DIP' AND s.dip_sub_stage = 'Resubmitted'         THEN s.id END) AS resubmitted,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'DIP' AND s.dip_sub_stage = 'Results Awaited'     THEN s.id END) AS results_awaited,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'DIP' AND s.dip_sub_stage = 'Enrolled_L1 Checked' THEN s.id END) AS l1_checked
FROM students s
GROUP BY s.university
ORDER BY total_admissions DESC;
```

---

### PATTERN 3 — Counsellor-wise Student Count (by team)
```sql
-- Servicing team: owns Enrolled + Activated students
SELECT
    u.name AS counsellor_name,
    COUNT(DISTINCT s.id) AS total_students,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'Enrolled'  THEN s.id END) AS enrolled,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'Onboarded' THEN s.id END) AS onboarded,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'Activated' THEN s.id END) AS activated
FROM users u
LEFT JOIN students s ON u.id = s.assigned_servicing_counsellor_id
WHERE u.team_type = 'servicing' AND u.is_active = true
GROUP BY u.id, u.name
ORDER BY total_students DESC;

-- Documentation team: owns DIP students
SELECT
    u.name AS counsellor_name,
    COUNT(DISTINCT s.id) AS total_students,
    COUNT(DISTINCT CASE WHEN s.dip_sub_stage = 'Docs Pending'       THEN s.id END) AS docs_pending,
    COUNT(DISTINCT CASE WHEN s.dip_sub_stage = 'Docs Submitted'     THEN s.id END) AS docs_submitted,
    COUNT(DISTINCT CASE WHEN s.dip_sub_stage = 'Under Verification' THEN s.id END) AS under_verification,
    COUNT(DISTINCT CASE WHEN s.dip_sub_stage = 'E-sign Pending'     THEN s.id END) AS esign_pending
FROM users u
LEFT JOIN students s ON u.id = s.assigned_documentation_counsellor_id AND s.lead_status = 'DIP'
WHERE u.team_type = 'documentation' AND u.is_active = true
GROUP BY u.id, u.name
ORDER BY total_students DESC;
```


---

### PATTERN 4 — Call Performance per Counsellor
```sql
SELECT
    u.name AS counsellor_name,
    COUNT(r.id) AS total_calls,
    COUNT(CASE WHEN r.calling_status = 'CONNECTED' THEN 1 END) AS connected_calls,
    ROUND(COUNT(CASE WHEN r.calling_status = 'CONNECTED' THEN 1 END) * 100.0
          / NULLIF(COUNT(r.id), 0), 2) AS success_rate_pct
FROM users u
LEFT JOIN remarks r ON u.id = r.counsellor_id
    AND r.is_task = false   -- exclude task rows
WHERE u.is_active = true
GROUP BY u.id, u.name
ORDER BY success_rate_pct DESC;
```

---

### PATTERN 5 — Document Completeness per Student
```sql
SELECT
    s.id AS student_id,
    s.name AS student_name,
    COUNT(DISTINCT d.id) AS total_docs,
    COUNT(DISTINCT CASE WHEN d.document_type = 'KYC'      THEN d.id END) AS kyc_docs,
    COUNT(DISTINCT CASE WHEN d.document_type = 'Academic' THEN d.id END) AS academic_docs,
    COUNT(DISTINCT CASE WHEN d.document_type = 'Work'     THEN d.id END) AS work_docs,
    COUNT(DISTINCT CASE WHEN d.document_type = 'Photo'    THEN d.id END) AS photos
FROM students s
LEFT JOIN documents d ON s.id = d.student_id
WHERE s.lead_status = 'DIP'
GROUP BY s.id, s.name
ORDER BY total_docs ASC;
```

---

### PATTERN 6 — Pending Installments (Outstanding Collection)
```sql
SELECT
    s.university,
    COUNT(DISTINCT si.student_id) AS students_with_pending,
    SUM(si.amount) AS total_pending_amount
FROM student_installments si
JOIN students s ON si.student_id = s.id
WHERE si.status = 'pending'
GROUP BY s.university
ORDER BY total_pending_amount DESC;
```

---

### PATTERN 7 — Enrollment Approval Rate per Documentation Counsellor
```sql
SELECT
    u.name AS counsellor_name,
    COUNT(ea.id) AS total_submitted,
    COUNT(CASE WHEN ea.status = 'approved' THEN 1 END) AS approved,
    COUNT(CASE WHEN ea.status = 'rejected' THEN 1 END) AS rejected,
    ROUND(COUNT(CASE WHEN ea.status = 'approved' THEN 1 END) * 100.0
          / NULLIF(COUNT(ea.id), 0), 2) AS approval_rate_pct
FROM users u
LEFT JOIN enrollment_approvals ea ON u.id = ea.performed_by
WHERE u.team_type = 'documentation' AND u.is_active = true
GROUP BY u.id, u.name
ORDER BY approval_rate_pct DESC;
```

---

### PATTERN 8 — Date-Bounded Status Change Count
```sql
-- How many students moved to Onboarded today (IST)?
-- ⚠️ student_status_histories is INCOMPLETE — many students have no rows. Use for date-of-change lookups only.
-- For current counts always use students.lead_status.
WITH first_onboarded AS (
    SELECT student_id, MIN(created_at) AS first_onboarded_at
    FROM student_status_histories
    WHERE status = 'Onboarded'
    GROUP BY student_id
)
SELECT COUNT(DISTINCT student_id) AS onboarded_today
FROM first_onboarded
WHERE first_onboarded_at >= CURRENT_DATE - INTERVAL '5 hours 30 minutes'
  AND first_onboarded_at <  CURRENT_DATE + INTERVAL '1 day' - INTERVAL '5 hours 30 minutes';
```
Key: Always use `MIN(created_at)` per student before date filtering. **Warning:** this table is incomplete — use `students.lead_status` for total current counts, this table only for when a transition happened.

---

### PATTERN 9 — Revenue Summary per University
```sql
SELECT
    s.university,
    COUNT(DISTINCT s.id) AS students,
    SUM(sf.total_payment_credited) AS total_received,
    SUM(sf.deficit_amount) AS total_pending,
    ROUND(AVG(sps.commission_percentage), 2) AS avg_commission_pct
FROM students s
JOIN student_finances sf ON s.id = sf.student_id
JOIN student_pricing_snapshots sps ON s.id = sps.student_id
WHERE s.lead_status != 'Refunded'
GROUP BY s.university
ORDER BY total_received DESC;
```

---

### PATTERN 10 — Open Tickets by Category
```sql
SELECT
    issue_category,
    status,
    COUNT(*) AS ticket_count
FROM tickets
WHERE status != 'Resolution — Solved'
GROUP BY issue_category, status
ORDER BY ticket_count DESC;
```

---

### PATTERN 11 — Overdue Callbacks per Counsellor
```sql
SELECT
    u.name AS counsellor_name,
    COUNT(DISTINCT r.id) AS overdue_callbacks
FROM users u
LEFT JOIN remarks r ON u.id = r.counsellor_id
    AND r.callback_at < NOW() AT TIME ZONE 'Asia/Kolkata'
    AND r.callback_at IS NOT NULL
    AND r.is_task = false
WHERE u.is_active = true
GROUP BY u.id, u.name
ORDER BY overdue_callbacks DESC;
```

---

### PATTERN 12 — Task Completion Rate per Counsellor
```sql
SELECT
    u.name AS counsellor_name,
    ct.assigned_team,
    COUNT(ct.id) AS total_tasks,
    COUNT(CASE WHEN ct.status = 'completed' THEN 1 END) AS completed_tasks,
    COUNT(CASE WHEN ct.status = 'pending'   THEN 1 END) AS pending_tasks,
    ROUND(COUNT(CASE WHEN ct.status = 'completed' THEN 1 END) * 100.0
          / NULLIF(COUNT(ct.id), 0), 2) AS completion_rate_pct
FROM users u
LEFT JOIN counsellor_tasks ct ON u.id = ct.counsellor_id
WHERE u.is_active = true
GROUP BY u.id, u.name, ct.assigned_team
ORDER BY completion_rate_pct DESC;
```

---

### PATTERN 14 — Documentation Workflows Report (replicated from app source code)
-- **Validated against app export. 100% match.**
-- Source: `getDocumentationWorkflowsReport` backend controller.
--
-- ⚠️ KEY BEHAVIOURS (validated from source code + live data):
-- 1. Date filter: `(sw.created_at AT TIME ZONE 'Asia/Kolkata')::date` — IST cast, NOT manual UTC offset
-- 2. NO status filter — includes BOTH active AND completed workflow rows
-- 3. NO lead_status filter — not restricted to DIP students
-- 4. TOTAL in app = SUM of per-stage counts, NOT COUNT(DISTINCT student_id)
--    → A student with workflow rows in 2 stages on the same day counts as 2 in TOTAL
--    → Example: a student with Docs Pending + Docs Submitted + L1 Checked on the same day counts as 3 in TOTAL
-- 5. For date range query: replace the WHERE clause with BETWEEN
--

```sql
-- Single date
SELECT
    COALESCE(s.university, 'Unassigned') AS university,
    COUNT(DISTINCT CASE WHEN sw.stage = 'Docs Pending'        THEN sw.student_id END) AS docs_pending,
    COUNT(DISTINCT CASE WHEN sw.stage = 'Docs Submitted'      THEN sw.student_id END) AS docs_submitted,
    COUNT(DISTINCT CASE WHEN sw.stage = 'IDs Created'         THEN sw.student_id END) AS ids_created,
    COUNT(DISTINCT CASE WHEN sw.stage = 'Under Verification'  THEN sw.student_id END) AS under_verification,
    COUNT(DISTINCT CASE WHEN sw.stage = 'E-sign Pending'      THEN sw.student_id END) AS esign_pending,
    COUNT(DISTINCT CASE WHEN sw.stage = 'Rework Required'     THEN sw.student_id END) AS rework_required,
    COUNT(DISTINCT CASE WHEN sw.stage = 'Resubmitted'         THEN sw.student_id END) AS resubmitted,
    COUNT(DISTINCT CASE WHEN sw.stage = 'Results Awaited'     THEN sw.student_id END) AS results_awaited,
    COUNT(DISTINCT CASE WHEN sw.stage = 'Enrolled_L1 Checked' THEN sw.student_id END) AS l1_checked,
    COUNT(DISTINCT CASE WHEN sw.stage = 'Refund Applied'      THEN sw.student_id END) AS refund_applied
FROM student_workflows sw
JOIN students s ON sw.student_id = s.id
WHERE (sw.created_at AT TIME ZONE 'Asia/Kolkata')::date = '2026-06-04'  -- replace with target date
  AND sw.team_type = 'documentation'
GROUP BY COALESCE(s.university, 'Unassigned')
ORDER BY university;

-- Date range variant (e.g. week/month)
-- Replace WHERE clause with:
-- WHERE (sw.created_at AT TIME ZONE 'Asia/Kolkata')::date BETWEEN '2026-06-01' AND '2026-06-04'
```

---

### PATTERN 15 — Connectivity Metrics Report
-- Filters by `remarks.team_type` NOT `users.team_type` — non-doc users (admin, servicing) who log doc remarks also appear.
-- Two metric views toggled in app — same base query, only the hourly CASE changes:
--   • Remarks view  → hourly counts ALL calls (no calling_status filter in hour buckets)
--   • Connected view → hourly counts CONNECTED only (add `AND r.calling_status = 'CONNECTED'`)
```sql
SELECT
    u.name AS counsellor,
    COUNT(r.id) AS remarks,
    COUNT(CASE WHEN r.calling_status = 'CONNECTED' THEN 1 END) AS connected,
    ROUND(COUNT(CASE WHEN r.calling_status = 'CONNECTED' THEN 1 END) * 100.0
          / NULLIF(COUNT(r.id), 0), 0) AS success_rate_pct,
    -- REMARKS VIEW: all calls per hour (remove "AND r.calling_status='CONNECTED'" for connected-only view)
    COUNT(CASE WHEN EXTRACT(HOUR FROM r.created_at AT TIME ZONE 'Asia/Kolkata') = 9  THEN 1 END) AS "9AM",
    COUNT(CASE WHEN EXTRACT(HOUR FROM r.created_at AT TIME ZONE 'Asia/Kolkata') = 10 THEN 1 END) AS "10AM",
    COUNT(CASE WHEN EXTRACT(HOUR FROM r.created_at AT TIME ZONE 'Asia/Kolkata') = 11 THEN 1 END) AS "11AM",
    COUNT(CASE WHEN EXTRACT(HOUR FROM r.created_at AT TIME ZONE 'Asia/Kolkata') = 12 THEN 1 END) AS "12PM",
    COUNT(CASE WHEN EXTRACT(HOUR FROM r.created_at AT TIME ZONE 'Asia/Kolkata') = 13 THEN 1 END) AS "1PM",
    COUNT(CASE WHEN EXTRACT(HOUR FROM r.created_at AT TIME ZONE 'Asia/Kolkata') = 14 THEN 1 END) AS "2PM",
    COUNT(CASE WHEN EXTRACT(HOUR FROM r.created_at AT TIME ZONE 'Asia/Kolkata') = 15 THEN 1 END) AS "3PM",
    COUNT(CASE WHEN EXTRACT(HOUR FROM r.created_at AT TIME ZONE 'Asia/Kolkata') = 16 THEN 1 END) AS "4PM",
    COUNT(CASE WHEN EXTRACT(HOUR FROM r.created_at AT TIME ZONE 'Asia/Kolkata') = 17 THEN 1 END) AS "5PM",
    COUNT(CASE WHEN EXTRACT(HOUR FROM r.created_at AT TIME ZONE 'Asia/Kolkata') = 18 THEN 1 END) AS "6PM",
    COUNT(CASE WHEN EXTRACT(HOUR FROM r.created_at AT TIME ZONE 'Asia/Kolkata') = 19 THEN 1 END) AS "7PM"
FROM remarks r
JOIN users u ON u.id = r.counsellor_id
WHERE r.is_task = false
  AND r.team_type = 'documentation'        -- swap team for servicing/placement view
  AND (r.created_at AT TIME ZONE 'Asia/Kolkata')::date = '2026-06-04'
GROUP BY u.id, u.name
ORDER BY remarks DESC;
```

---

### PATTERN 16 — University Admission Report with Invoicing Variable (Validated)
-- Count + Lakh value per DIP sub-stage bucket. Lakh = student_finances.invoicing_variable ÷ 100,000
-- JOIN: students → student_finances on student_id (1-to-1, INNER JOIN safe)
-- Same bucket logic as PATTERN 13 for counts; amounts use SUM(sf.invoicing_variable) per bucket
-- Validated 100% match against app export.
```sql
SELECT
    s.university,
    COUNT(DISTINCT s.id) AS total_count,
    ROUND(SUM(sf.invoicing_variable)::numeric/100000, 2) AS total_L,
    COUNT(DISTINCT CASE WHEN s.lead_status IN ('Enrolled','Onboarded','Activated') THEN s.id END) AS enrolled_plus_count,
    ROUND(SUM(CASE WHEN s.lead_status IN ('Enrolled','Onboarded','Activated') THEN sf.invoicing_variable ELSE 0 END)::numeric/100000, 2) AS enrolled_plus_L,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'Refunded' THEN s.id END) AS refunded_count,
    ROUND(SUM(CASE WHEN s.lead_status = 'Refunded' THEN sf.invoicing_variable ELSE 0 END)::numeric/100000, 2) AS refunded_L,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'DIP' AND s.dip_sub_stage = 'Refund Applied' THEN s.id END) AS refund_applied_count,
    ROUND(SUM(CASE WHEN s.lead_status = 'DIP' AND s.dip_sub_stage = 'Refund Applied' THEN sf.invoicing_variable ELSE 0 END)::numeric/100000, 2) AS refund_applied_L,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'DIP' AND s.dip_sub_stage IS DISTINCT FROM 'Refund Applied' THEN s.id END) AS dip_count,
    ROUND(SUM(CASE WHEN s.lead_status = 'DIP' AND s.dip_sub_stage IS DISTINCT FROM 'Refund Applied' THEN sf.invoicing_variable ELSE 0 END)::numeric/100000, 2) AS dip_L
    -- extend with per-sub-stage columns following same CASE WHEN pattern
FROM students s
JOIN student_finances sf ON s.id = sf.student_id
GROUP BY s.university
ORDER BY total_count DESC;
```

---

### PATTERN 17 — University Finance Status Report (Validated)
-- Buckets by student_finances.current_status with invoicing_variable Lakh values
-- current_status values: 'To be Invoiced' | 'Ready to invoice' | 'Invoiced- Payment Pending' | 'Invoiced - Payment done' | 'Refunded Amount'
-- Validated 100% match against app export.
```sql
SELECT
    s.university,
    COUNT(DISTINCT s.id) AS total_count,
    ROUND(SUM(sf.invoicing_variable)::numeric/100000, 2) AS total_L,
    COUNT(DISTINCT CASE WHEN sf.current_status = 'To be Invoiced'           THEN s.id END) AS to_be_invoiced_count,
    ROUND(SUM(CASE WHEN sf.current_status = 'To be Invoiced'           THEN sf.invoicing_variable ELSE 0 END)::numeric/100000, 2) AS to_be_invoiced_L,
    COUNT(DISTINCT CASE WHEN sf.current_status = 'Ready to invoice'          THEN s.id END) AS ready_to_invoice_count,
    ROUND(SUM(CASE WHEN sf.current_status = 'Ready to invoice'          THEN sf.invoicing_variable ELSE 0 END)::numeric/100000, 2) AS ready_to_invoice_L,
    COUNT(DISTINCT CASE WHEN sf.current_status = 'Invoiced- Payment Pending' THEN s.id END) AS invoiced_pending_count,
    ROUND(SUM(CASE WHEN sf.current_status = 'Invoiced- Payment Pending' THEN sf.invoicing_variable ELSE 0 END)::numeric/100000, 2) AS invoiced_pending_L,
    COUNT(DISTINCT CASE WHEN sf.current_status = 'Invoiced - Payment done'   THEN s.id END) AS invoiced_done_count,
    ROUND(SUM(CASE WHEN sf.current_status = 'Invoiced - Payment done'   THEN sf.invoicing_variable ELSE 0 END)::numeric/100000, 2) AS invoiced_done_L,
    COUNT(DISTINCT CASE WHEN sf.current_status = 'Refunded Amount'           THEN s.id END) AS refunded_count,
    ROUND(SUM(CASE WHEN sf.current_status = 'Refunded Amount'           THEN sf.invoicing_variable ELSE 0 END)::numeric/100000, 2) AS refunded_L
FROM students s
JOIN student_finances sf ON s.id = sf.student_id
GROUP BY s.university
ORDER BY total_count DESC;
```

---

### PATTERN 18 — Overall Snapshot Dashboard
-- FTD/MTD   = filter on (s.created_at AT TIME ZONE 'Asia/Kolkata')::date
-- Drive     = s.session = 'July 2026' AND sf.current_status != 'Refunded Amount'
-- YTD       = EXTRACT(YEAR FROM s.admission_taken_date) = 2026 AND excl Refunded Amount
-- Amounts   = total_variable (commission earned) | invoicing_variable (collected so far)
```sql
SELECT
    COUNT(DISTINCT s.id) FILTER (WHERE sf.current_status != 'Refunded Amount')                                                                                 AS overall_admissions,
    SUM(sf.total_variable)     FILTER (WHERE sf.current_status != 'Refunded Amount')                                                                           AS overall_total_variable,
    SUM(sf.invoicing_variable) FILTER (WHERE sf.current_status != 'Refunded Amount')                                                                           AS overall_invoicing_variable,
    COUNT(DISTINCT s.id) FILTER (WHERE (s.created_at AT TIME ZONE 'Asia/Kolkata')::date = CURRENT_DATE)                                                         AS ftd_admissions,
    SUM(sf.total_variable)     FILTER (WHERE (s.created_at AT TIME ZONE 'Asia/Kolkata')::date = CURRENT_DATE)                                                   AS ftd_total_variable,
    SUM(sf.invoicing_variable) FILTER (WHERE (s.created_at AT TIME ZONE 'Asia/Kolkata')::date = CURRENT_DATE)                                                   AS ftd_invoicing_variable,
    COUNT(DISTINCT s.id) FILTER (WHERE (s.created_at AT TIME ZONE 'Asia/Kolkata')::date = CURRENT_DATE - 1)                                                     AS yesterday_admissions,
    SUM(sf.total_variable)     FILTER (WHERE (s.created_at AT TIME ZONE 'Asia/Kolkata')::date = CURRENT_DATE - 1)                                               AS yesterday_total_variable,
    SUM(sf.invoicing_variable) FILTER (WHERE (s.created_at AT TIME ZONE 'Asia/Kolkata')::date = CURRENT_DATE - 1)                                               AS yesterday_invoicing_variable,
    COUNT(DISTINCT s.id) FILTER (WHERE (s.created_at AT TIME ZONE 'Asia/Kolkata')::date BETWEEN DATE_TRUNC('month', CURRENT_DATE)::date AND CURRENT_DATE)       AS mtd_admissions,
    SUM(sf.total_variable)     FILTER (WHERE (s.created_at AT TIME ZONE 'Asia/Kolkata')::date BETWEEN DATE_TRUNC('month', CURRENT_DATE)::date AND CURRENT_DATE) AS mtd_total_variable,
    SUM(sf.invoicing_variable) FILTER (WHERE (s.created_at AT TIME ZONE 'Asia/Kolkata')::date BETWEEN DATE_TRUNC('month', CURRENT_DATE)::date AND CURRENT_DATE) AS mtd_invoicing_variable,
    COUNT(DISTINCT s.id) FILTER (WHERE s.session = 'July 2026' AND sf.current_status != 'Refunded Amount')                                                      AS drive_admissions,
    SUM(sf.total_variable)     FILTER (WHERE s.session = 'July 2026' AND sf.current_status != 'Refunded Amount')                                                AS drive_total_variable,
    SUM(sf.invoicing_variable) FILTER (WHERE s.session = 'July 2026' AND sf.current_status != 'Refunded Amount')                                                AS drive_invoicing_variable,
    COUNT(DISTINCT s.id) FILTER (WHERE EXTRACT(YEAR FROM s.admission_taken_date) = 2026 AND sf.current_status != 'Refunded Amount')                             AS ytd_admissions,
    SUM(sf.total_variable)     FILTER (WHERE EXTRACT(YEAR FROM s.admission_taken_date) = 2026 AND sf.current_status != 'Refunded Amount')                       AS ytd_total_variable,
    SUM(sf.invoicing_variable) FILTER (WHERE EXTRACT(YEAR FROM s.admission_taken_date) = 2026 AND sf.current_status != 'Refunded Amount')                       AS ytd_invoicing_variable
FROM students s
JOIN student_finances sf ON s.id = sf.student_id;
```
