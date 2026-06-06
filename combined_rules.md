# Combined Analysis Guide — Online LMS + CRM

> Use this when a question spans both systems.
> Online LMS = pre-admission (leads, counselling, applications).
> CRM = post-admission (servicing, docs, placement, finance).

---

## HOW TO MAP DATA BETWEEN SYSTEMS

### The Join Problem
There is **no direct DB-level foreign key** between the two databases.

| LMS field | CRM field | Usable? |
|-----------|-----------|--------|
| `students.primary_db_id` (10-char alphanum) | `students.id` (`STD-XXXXXXXX`) | ❌ Different formats — not a join key |
| `students.student_phone` | `students.phone` | ✅ **Primary join key** — 97% match rate validated |
| `students.student_name` | `students.name` | ⚠️ Fuzzy only — duplicates exist |
| `students.student_email` | `students.email` | ✅ Works but sparse |

### What `primary_db_id` actually is
`primary_db_id` is a **sync flag**, not a join key. It tells you *whether* the live sync ran for this student — not which CRM record it maps to.

⚠️ `primary_db_id` is NOT a date cutoff. Students admitted as late as May 2026 have it `NULL`, and it has been set since Sept 2025. It is per-student, not per-cohort.

| `primary_db_id` value | Meaning |
|----------------------|---------|
| `NOT NULL` | Live sync ran — CRM record exists, join via phone |
| `NULL` + admitted | Bulk-migrated — CRM record also exists, **join via phone to get LMS `student_id`** for pre-admission history |
| `NULL` + not admitted | Lead only, no CRM record |

### Practical mapping rule
- **Join key is always `lms.student_phone = crm.phone`** — works for both live-synced and migrated students
- `primary_db_id IS NOT NULL` → join via phone, CRM record guaranteed
- `primary_db_id IS NULL` + admitted → also join via phone to retrieve LMS `student_id` for pre-admission data (source, counsellor, calls, funnel)
- 5% phone mismatch rate (number changed between entry and sync) — expected, not a data error
- Run each DB query separately, then join in application layer on phone

---

## WHICH DB TO QUERY FOR WHAT

### Always Online LMS
| Question | Table | Key column/rule |
|----------|-------|----------------|
| Lead source / UTM campaign | `students.source`, `student_lead_activities.utm_campaign` | |
| First ICC date | `students."first_Icc_Date"` | double-quoted, TIMESTAMPTZ |
| Application count | `course_status_journeys` | `course_status='Application'` |
| Admission count | `course_status_journeys` | `course_status IN ('Admission','Enrolled')` + partial exclusion |
| Counsellor who converted the lead | `students.assigned_counsellor_id` → `counsellors` | L2 = conversion counsellor |
| Call attempts / success rate pre-admission | `student_remarks` | `calling_status='Connected'/'Not Connected'` |
| Lead funnel (Fresh → ICC → App → Admission) | `students` + `csj` | See P1 pattern |
| Conversion rate (App → Admission) | `csj` | P7 |
| TAT to admission | `students.created_at` vs `csj` | P14 |
| Deposit paid at admission | `csj.deposit_amount` | dedup first |
| NI reasons | `students.current_student_ni_sub_status` | pre-app NI only |

### Always CRM
| Question | Table | Key column/rule |
|----------|-------|----------------|
| Post-admission funnel (DIP → Enrolled → Onboarded → Activated) | `students.lead_status` | |
| DIP sub-stage (docs status) | `students.dip_sub_stage` | only when `lead_status='DIP'` |
| Documentation workflow progress | `student_workflows` | `team_type='documentation'` |
| Servicing / placement stage | `student_workflows` | `team_type='servicing'/'placement'` |
| Post-admission call activity | `remarks` | `calling_status='CONNECTED'/'NOT_CONNECTED'` (UPPERCASE) |
| Revenue from university | `student_finances.total_payment_credited` | |
| Invoicing / commission | `student_finances.invoicing_variable`, `student_pricing_snapshots` | |
| EMI / installment schedule | `student_installments` | |
| Refund status / reason | `students.lead_status='Refunded'`, `student_status_histories.remarks` | |
| LMS credentials shared | `students.lms_credentials_shared` | boolean flag |
| Enrollment approval | `enrollment_approvals` | |
| Tickets | `tickets` | em-dash `—` in status strings |
| Session (Jan 2026 / July 2026) | `students.session` | |

### Could be either — depends on context
| Question | Use LMS if... | Use CRM if... |
|----------|--------------|--------------|
| "How many admissions today?" | Asking about new conversions (when fee was paid) | Asking about DIP students created today |
| "Enrolled students" | `csj.course_status='Enrolled'` (university enrollment step) | `lead_status='Enrolled'` (CRM onboarding stage after DIP) |
| "Source of students" | Lead source at acquisition | `students.source` in CRM (copied from LMS at sync) |
| "Counsellor performance" | Pre-admission calling/conversion | Post-admission servicing/documentation calls |
| "Fee" | Deposit paid at admission (`csj.deposit_amount`) | Revenue received from university (`student_finances`) |

---

## KEY TERM DIFFERENCES ACROSS SYSTEMS

| Term | Online LMS meaning | CRM meaning |
|------|--------------------|-------------|
| "Enrolled" | `csj.course_status='Enrolled'` — university enrollment complete | `lead_status='Enrolled'` — post-DIP CRM stage |
| "Admitted" | `csj.course_status IN ('Admission','Enrolled')` + partial excl | `lead_status != 'Refunded'` (all active) or `lead_status='DIP'` (just arrived) |
| "Counsellor" | `counsellors` table, role=l2/l3/to | `users` table, team_type=servicing/documentation/placement |
| calling_status values | `'Connected'` / `'Not Connected'` (mixed case) | `'CONNECTED'` / `'NOT_CONNECTED'` (UPPERCASE) |
| Student PK | `student_id` (no prefix) | `id` = `STD-XXXXXXXX`; child tables use `student_id → students.id` |
| "Created at" | When lead entered LMS | When CRM record was created (~3 min after LMS admission) |
| "Original entry date" | `students.created_at` | `students.student_created_at` (copied from LMS) |

---

## COMBINED ANALYSIS PATTERNS

### Pattern C1 — Source-to-Revenue (Full Funnel)
*"Which lead source generates the most revenue?"*
```
Step 1 → LMS: get admitted students with source
  SELECT student_phone, source FROM students
  JOIN csj ON admission criteria

Step 2 → CRM: get revenue per student
  SELECT phone, invoicing_variable FROM students
  JOIN student_finances ON id=student_id

Step 3 → Join in app layer on phone, GROUP BY source
```

### Pattern C2 — Conversion Counsellor vs Servicing Counsellor
*"Who converts leads and who services them?"*
```
LMS: assigned_counsellor_id → counsellors.counsellor_name (converter)
CRM: assigned_servicing_counsellor_id → users.name (servicer)
Join via phone to get one row per student with both names
```

### Pattern C3 — Admission-to-DIP Lag
*"How long after admission does a student appear in CRM?"*
```
LMS: MIN(csj.created_at) WHERE course_status='Admission' → admission_date (per phone)
CRM: students.created_at → crm_created_date (per phone)
Lag = crm_created_date - admission_date (expect ~minutes for live sync, days/weeks for migrated)
```

### Pattern C4 — LMS Cohort → CRM Outcome
*"Of leads acquired in April, how many are now Enrolled/Onboarded in CRM?"*
```
LMS cohort: students WHERE created_at IN April → phone list
CRM: students WHERE phone IN (list) → GROUP BY lead_status
```

### Pattern C5 — Admission Count vs CRM DIP Count
*"Are all admissions reaching CRM?"*
```
LMS: COUNT(DISTINCT student_id) WHERE primary_db_id IS NOT NULL AND course_status='Admission'...
CRM: COUNT(DISTINCT id) WHERE created_at >= <integration_start_date>
Gap = students admitted but not yet in CRM (processing lag or sync failure)
```

---

## GOTCHAS FOR COMBINED QUERIES

1. **Never JOIN directly in SQL** — these are separate databases on the same server but different DBs. Pull each result set via separate MCP tool calls, join in the response.

2. **Phone number format** — normalize before matching: strip spaces, country code (+91 or 91 prefix). LMS `student_phone` vs CRM `phone`.

3. **Migrated students have no LMS link** — ~411 students in CRM predate integration. Any phone-based join that finds no LMS match is likely a migrated student, not a data error.

4. **"Enrolled" means different things** — always clarify which system before writing the query.

5. **Dates**: LMS `students.created_at` = lead entry. CRM `students.student_created_at` = same date copied over. CRM `students.created_at` = when CRM record was made (a few minutes to days later).

6. **Source in CRM** — `students.source` in CRM is copied from LMS at sync time. For acquisition analysis, LMS source is authoritative. For CRM-only students (migrated), CRM source may have been manually entered.
