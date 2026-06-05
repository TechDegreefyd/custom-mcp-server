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

Stage values by team:
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
- **Documentation Workflows Report counting rule**: TOTAL = SUM of per-stage counts, NOT COUNT(DISTINCT student_id). A student in 2 stages on the same day counts as 2 in TOTAL.
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
- All student_ids in remarks exist in students — no orphaned rows
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
- **Counsellor link**: `raised_by → users.id` — the counsellor who raised the ticket on behalf of the student
- **Ticket aging buckets**: `0-3 Days` = days < 3, `3-5 Days` = days BETWEEN 3 AND 5, `> 5 Days` = days > 5
  - Age = `CURRENT_DATE - (date_raised AT TIME ZONE 'Asia/Kolkata')::date`
  - Aging is only computed on active (non-solved) tickets
- **status exact strings**: `'Support'`, `'Resolution — WIP'`, `'Resolution — Solved'` (em-dash `—`, not hyphen)

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

> Simple GROUP BY queries (funnel counts, DIP sub-stage breakdown, pending installments, open tickets by category, document completeness) are derivable from the table rules above — no pattern needed. Patterns below exist only for non-obvious logic that an agent would likely get wrong.

---

### PATTERN A — University Report (all variants)

All university reports share the same base. Total always includes Refunded. University in UPPERCASE. Swap the stage columns per variant.

**Variant 1 — Lead Status Funnel** (each status as own column):
```sql
SELECT UPPER(s.university) AS university,
    COUNT(DISTINCT s.id) AS total,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'DIP'       THEN s.id END) AS dip,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'Enrolled'  THEN s.id END) AS enrolled,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'Onboarded' THEN s.id END) AS onboarded,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'Activated' THEN s.id END) AS activated,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'Refunded'  THEN s.id END) AS refunded
FROM students s GROUP BY UPPER(s.university) ORDER BY total DESC;
```

**Variant 2 — Admission Report with DIP sub-stages** (Enrolled+ bucket + Refund Applied split from DIP):
- `Enrolled+` = Enrolled/Onboarded/Activated
- `DIP` column excludes Refund Applied (`IS DISTINCT FROM 'Refund Applied'`)
- `IDs Created` never appears here — it's a `student_workflows` stage only
```sql
SELECT s.university,
    COUNT(DISTINCT s.id) AS total,
    COUNT(DISTINCT CASE WHEN s.lead_status IN ('Enrolled','Onboarded','Activated') THEN s.id END) AS enrolled_plus,
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
FROM students s GROUP BY s.university ORDER BY total DESC;
```

**Variant 3 — + Invoicing Variable (Lakhs)**: JOIN `student_finances` (1-to-1, INNER JOIN safe). Add `ROUND(SUM(CASE WHEN <bucket> THEN sf.invoicing_variable ELSE 0 END)::numeric/100000, 2) AS <bucket>_L` alongside each count column.

**Variant 4 — Finance Status buckets**: JOIN `student_finances`, pivot on `sf.current_status`. Exact string values: `'To be Invoiced'` | `'Ready to invoice'` | `'Invoiced- Payment Pending'` | `'Invoiced - Payment done'` | `'Refunded Amount'`.

**Variant 5 — Servicing workflow stages** (current active stage per student):
- ⚠️ Use `student_workflows` NOT `counsellor_tasks` — tasks overcounts General Checkin
- Servicing stages: `Onboarding` / `Activation` / `General Checkin`
```sql
WITH sw AS (
    SELECT DISTINCT ON (student_id) student_id, stage
    FROM student_workflows WHERE team_type = 'servicing' AND status = 'active'
    ORDER BY student_id, created_at DESC
)
SELECT UPPER(s.university) AS university, COUNT(DISTINCT s.id) AS total,
    COUNT(DISTINCT CASE WHEN s.lead_status IN ('Enrolled','Onboarded','Activated') THEN s.id END) AS enrolled_plus,
    COUNT(DISTINCT CASE WHEN s.lead_status = 'Refunded'       THEN s.id END) AS refunded,
    COUNT(DISTINCT CASE WHEN sw.stage = 'Onboarding'          THEN s.id END) AS onboarding,
    COUNT(DISTINCT CASE WHEN sw.stage = 'Activation'          THEN s.id END) AS activation,
    COUNT(DISTINCT CASE WHEN sw.stage = 'General Checkin'     THEN s.id END) AS general_checkin
FROM students s LEFT JOIN sw ON s.id = sw.student_id
GROUP BY UPPER(s.university) ORDER BY total DESC;
```

**Variant 6 — Placement workflow stages** (same pattern, swap team):
- Placement stages: `Onboarding` / `Optimization` / `Strategy` / `Ready` / `Mentorship` / `Preparation` / `Placement`
- Replace `team_type = 'servicing'` → `team_type = 'placement'` in the CTE, then CASE WHEN on placement stages.

---

### PATTERN B — Counsellor Performance

**Call metrics** (from `remarks`): always `is_task = false`. `calling_status` is UPPERCASE (`CONNECTED`/`NOT_CONNECTED`).
```sql
SELECT u.name, COUNT(r.id) AS total_calls,
    COUNT(CASE WHEN r.calling_status = 'CONNECTED' THEN 1 END) AS connected,
    ROUND(COUNT(CASE WHEN r.calling_status = 'CONNECTED' THEN 1 END) * 100.0 / NULLIF(COUNT(r.id),0), 2) AS success_pct
FROM users u
LEFT JOIN remarks r ON u.id = r.counsellor_id AND r.is_task = false
WHERE u.is_active = true
GROUP BY u.id, u.name ORDER BY success_pct DESC;
```

**Student counts by team** — use correct FK per team (rule T9). Filter `lead_status = 'DIP'` when joining doc counsellors. No `is_active` filter unless user says "active".

**Task completion** (from `counsellor_tasks`): `status = 'pending'` / `'completed'`. Note: General Checkin has 0 completed tasks — skip completion rate for it.

**Overdue callbacks**: `callback_at < NOW()` (no IST offset needed on comparison, but display with `AT TIME ZONE 'Asia/Kolkata'`). Always exclude `is_task = true`.

**Enrollment approval rate** (doc team only): JOIN `enrollment_approvals` via `performed_by`. Approval rate is very high — rejections are rare.

---

### PATTERN C — Status History (Date-of-Change Lookup)
⚠️ `student_status_histories` is incomplete — many students have no rows. Only use for "when did X happen", never for counts. Always `MIN(created_at)` per student before date filtering.
```sql
WITH first_change AS (
    SELECT student_id, MIN(created_at) AS changed_at
    FROM student_status_histories WHERE status = 'Onboarded'  -- swap status as needed
    GROUP BY student_id
)
SELECT COUNT(DISTINCT student_id)
FROM first_change
WHERE changed_at >= CURRENT_DATE - INTERVAL '5 hours 30 minutes'
  AND changed_at <  CURRENT_DATE + INTERVAL '1 day' - INTERVAL '5 hours 30 minutes';
```

---

### PATTERN D — LMS Credentials Breakdown
⚠️ Includes Refunded students — do NOT filter `lead_status != 'Refunded'`. `not_created` = `false OR NULL`.
```sql
SELECT COALESCE(u.name, 'UNASSIGNED') AS counsellor,
    COUNT(DISTINCT s.id) AS total,
    COUNT(DISTINCT CASE WHEN s.lms_credentials_shared = true THEN s.id END) AS created,
    COUNT(DISTINCT CASE WHEN s.lms_credentials_shared = false OR s.lms_credentials_shared IS NULL THEN s.id END) AS not_created
FROM students s
LEFT JOIN users u ON s.assigned_servicing_counsellor_id = u.id
GROUP BY COALESCE(u.name, 'UNASSIGNED') ORDER BY total DESC;
```

---

### PATTERN E — Ticket Reports

**Status breakdown** — counsellor = `raised_by → users.id`. Status exact strings use em-dash: `'Support'` / `'Resolution — WIP'` / `'Resolution — Solved'`.
```sql
SELECT u.name AS counsellor,
    COUNT(DISTINCT CASE WHEN t.status = 'Support'              THEN t.id END) AS open_support,
    COUNT(DISTINCT CASE WHEN t.status = 'Resolution — WIP'    THEN t.id END) AS wip,
    COUNT(DISTINCT CASE WHEN t.status = 'Resolution — Solved'  THEN t.id END) AS solved,
    COUNT(DISTINCT t.id) AS total
FROM tickets t JOIN users u ON t.raised_by = u.id
GROUP BY u.name ORDER BY total DESC;
```

**Aging breakdown** — active tickets only (`status != 'Resolution — Solved'`). Age = `CURRENT_DATE - (date_raised AT TIME ZONE 'Asia/Kolkata')::date`. Buckets: `< 3` = 0-3 days | `BETWEEN 3 AND 5` = 3-5 days | `> 5` = >5 days.
```sql
SELECT u.name AS counsellor,
    COUNT(DISTINCT CASE WHEN (CURRENT_DATE - (t.date_raised AT TIME ZONE 'Asia/Kolkata')::date) < 3             THEN t.id END) AS "0_3_days",
    COUNT(DISTINCT CASE WHEN (CURRENT_DATE - (t.date_raised AT TIME ZONE 'Asia/Kolkata')::date) BETWEEN 3 AND 5 THEN t.id END) AS "3_5_days",
    COUNT(DISTINCT CASE WHEN (CURRENT_DATE - (t.date_raised AT TIME ZONE 'Asia/Kolkata')::date) > 5             THEN t.id END) AS "gt_5_days",
    COUNT(DISTINCT t.id) AS total_active
FROM tickets t JOIN users u ON t.raised_by = u.id
WHERE t.status != 'Resolution — Solved'
GROUP BY u.name ORDER BY total_active DESC;
```

---

### PATTERN H — Documentation Workflows Report
-- ⚠️ THREE traps: (1) IST cast `(created_at AT TIME ZONE 'Asia/Kolkata')::date` — NOT manual UTC offset.
-- (2) NO status filter — includes both active AND completed rows.
-- (3) TOTAL = SUM of per-stage counts NOT COUNT(DISTINCT student_id) — a student in 2 stages on the same day counts as 2.
-- For date range: replace `= 'date'` with `BETWEEN 'start' AND 'end'`.

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

### PATTERN I — Connectivity Metrics Report
-- Filter by `remarks.team_type` NOT `users.team_type` (non-team users who log remarks also appear).
-- Two views: Remarks = all calls per hour bucket | Connected = add `AND r.calling_status = 'CONNECTED'` to hour buckets.
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

### PATTERN G — Overall Snapshot Dashboard
-- FTD/MTD = (s.created_at AT TIME ZONE 'Asia/Kolkata')::date. Drive = session='July 2026'. YTD = admission_taken_date year=2026.
-- Exclude 'Refunded Amount' from overall/drive/YTD. total_variable = commission earned, invoicing_variable = collected so far.
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

---

