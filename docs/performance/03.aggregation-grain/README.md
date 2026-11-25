# Decision aggregation: the join-grain cliff

Decisions are the core entity of the app. Almost every screen is the same
question in a different context:

> *"Show me the decisions for this organization / counterpart / signer / unit,
> with optional parent-level filters, sorted by date or by amount, and show the
> aggregate totals / peaks for that same context."*

Because the amount lives in a child table (`core_decisionamountfield`, via the
`amount_fields` reverse relation), every such screen joins a **to-many** table
and then aggregates. That is normal and correct — but the ORM makes two
specific mistakes extremely easy, and both turn into a performance cliff at
large organizations.

---

## 1. The two traps

### Trap A — `COUNT` over a to-many join (a correctness bug)

```python
# Aggregate over a queryset that joins amount_fields:
qs = Decision.objects.filter(organization_id="6167")
qs.annotate(acc_total=amount_sum_excluding_kae())  # Sum over amount_fields
stats = qs.aggregate(
    total_decisions=Count("id"),   # WRONG: counts amount rows, not decisions
    total_amount=Sum("acc_total"),
)
```

`Count("id")` counts the rows produced by the join. A decision with 3 amount
rows contributes 3. The real prod numbers prove it: the `date_range` aggregate
reported **102,897** "decisions" for an organization with **~80,820**.

Correct forms:

```python
Count("id", distinct=True)   # COUNT(DISTINCT core_decision.id)
```

or count a **join-free** queryset (no amount annotation/filter).

### Trap B — double aggregation (the performance cliff)

```python
qs.annotate(acc_total=amount_sum_excluding_kae())   # already GROUP BY decision.id
qs.values("issue_date_year").annotate(
    count=Count("id"),            # counts groups, not decisions
    total=Sum("acc_total"),       # sums groups, not decisions
)
```

The first `annotate` already makes Django emit `GROUP BY decision.id` (plus the
join's columns). The second `.values().annotate()` is then a **second**
aggregation on top of a grouped queryset. Django's
`django/db/models/sql/query.py::get_aggregation()` detects the existing
aggregate/grouping and **nests** the query:

```sql
SELECT MIN(__c1), MAX(__c1), COUNT(__c2), SUM(COALESCE(__c3, __c4)) FILTER (...)
FROM (
    SELECT core_decision.issue_date_day, core_decision.id,
           core_decisionamountfield.verified_amount, core_decisionamountfield.amount,
           core_decisionamountfield.parent_key_path, core_decisionamountfield.invalid_amount_reason
    FROM core_decision
    LEFT OUTER JOIN core_decisionamountfield
      ON (core_decision.id = core_decisionamountfield.decision_id)
    WHERE core_decision.organization_id = ?
    GROUP BY core_decision.id, verified_amount, amount, parent_key_path, invalid_amount_reason
) subquery
```

Consequences:

- **Wrong grain**: the outer aggregate sees groups (one per amount row because
  the group includes the amount columns), not decisions. `COUNT`, `AVG`,
  `MIN`, `MAX` are all computed at the wrong grain.
- **Performance cliff**: the database must materialize and sort the fan-out
  (the "103k groups" in the prod `EXPLAIN`), then aggregate again. On big
  queries Postgres also trips JIT (0.75 s + 1.47 s of compile time in the prod
  plans).
- **Amounts were still right, counts were not.** Because each amount row is its
  own group, `SUM` over the groups equals the true sum; but `COUNT(id)` counts
  groups. That asymmetry is what makes the bug hard to notice.

### What is *not* a trap

- `SUM(child.amount)` over a to-many join is the normal way to total children.
- `annotate(calculated_amount=Sum("amount_fields__..."))` on a plain queryset
  (one row per decision) is correct and is how listing/sorting by amount works.
- `Count("id", filter=Q(...))` on a join-free queryset is correct.
- A grouping over a single-valued relation (FK/OneToOne) does not fan out.

---

## 2. Worked example (dummy data)

Organization `6167`, three decisions:

`core_decision`:

| id | organization_id | issue_date_day | issue_date_year |
|---:|---|---|---|
| 101 | 6167 | 2024-03-10 | 2024 |
| 102 | 6167 | 2024-07-22 | 2024 |
| 103 | 6167 | 2025-01-05 | 2025 |

`core_decisionamountfield`:

| id | decision_id | parent_key_path | amount | verified_amount | invalid_amount_reason |
|---:|---:|---|---:|---:|---|
| 1 | 101 | `amountWithVAT` | 100 | — | — |
| 2 | 101 | `amountWithoutVAT` | 80 | — | — |
| 3 | 102 | `amountWithVAT` | 200 | **250** | — |
| 4 | 102 | `amountWithKae[0]` | 999 | — | — |
| 5 | 103 | `sponsor[0].amount` | 300 | — | `kae_as_amount` |
| 6 | 103 | `amountWithVAT` | 400 | — | — |

`amount_sum_excluding_kae()` = `SUM(COALESCE(verified_amount, amount))` with
`FILTER (NOT path LIKE 'amountWithKae%' AND invalid_amount_reason IS NULL)`:

| daf.id | COALESCE | path | invalid | contributes |
|---:|---:|---|---|---:|
| 1 | 100 | amountWithVAT | — | 100 |
| 2 | 80 | amountWithoutVAT | — | 80 |
| 3 | 250 | amountWithVAT | — | 250 |
| 4 | 999 | amountWithKae[0] | — | excluded (KAE) |
| 5 | 300 | sponsor[0].amount | `kae_as_amount` | excluded (invalid) |
| 6 | 400 | amountWithVAT | — | 400 |

True answer: **3 decisions, total 830**.

### The fan-out (`LEFT JOIN` produces one row per amount field)

| decision.id | issue_date_day | daf.id | amount | verified | path | invalid |
|---:|---|---:|---:|---:|---|---|
| 101 | 2024-03-10 | 1 | 100 | — | amountWithVAT | — |
| 101 | 2024-03-10 | 2 | 80 | — | amountWithoutVAT | — |
| 102 | 2024-07-22 | 3 | 200 | 250 | amountWithVAT | — |
| 102 | 2024-07-22 | 4 | 999 | — | amountWithKae[0] | — |
| 103 | 2025-01-05 | 5 | 300 | — | sponsor[0].amount | kae_as_amount |
| 103 | 2025-01-05 | 6 | 400 | — | amountWithVAT | — |

**3 decisions → 6 rows.**

### Old aggregate (Trap B)

Inner `GROUP BY decision.id, verified, amount, path, invalid` = **6 groups**.
Outer aggregate:

| aggregate | old result | correct? |
|---|---:|---|
| `MIN(issue_date_day)` | 2024-03-10 | yes |
| `MAX(issue_date_day)` | 2025-01-05 | yes |
| `COUNT(id)` | **6** | **no** (should be 3) |
| `SUM(...) FILTER (...)` | 830 | yes |

### Old activity chart (`GROUP BY year, COUNT(id)` over the fan-out)

| period | rows | old `COUNT(id)` | old `SUM` |
|---|---:|---:|---:|
| 2024 | 4 | **4** | 430 |
| 2025 | 2 | **2** | 400 |
| total | 6 | **6** | 830 |

### New shape

Query 1 — metadata, no join at all:

```sql
SELECT MIN(issue_date_day), MAX(issue_date_day)
FROM core_decision WHERE organization_id = '6167'
```

Query 2 — one amount-table pass, grouped by period only:

```sql
SELECT issue_date_year AS period,
       COUNT(DISTINCT core_decision.id),
       SUM(COALESCE(verified_amount, amount)) FILTER (...)
FROM core_decision
LEFT OUTER JOIN core_decisionamountfield
  ON core_decision.id = core_decisionamountfield.decision_id
WHERE core_decision.organization_id = '6167'
GROUP BY 1 ORDER BY 1
```

| period | `COUNT(DISTINCT id)` | `SUM` |
|---|---:|---:|
| 2024 | 2 (`{101,102}`) | 430 |
| 2025 | 1 (`{103}`) | 400 |

Totals derived from the chart (every decision is in exactly one period):
**3 decisions, 830**. No subquery, no per-amount group, no JIT.

