# Experiments - Decision Decomposition Framework

Quick start guide for testing and developing strategies to decompose Greek government decision text into structured data.

## Overview

This framework allows you to:
1. **Export samples** of decisions for manual inspection
2. **Develop strategies** to extract structured data from decision text
3. **Test strategies** on filesystem samples (fast iteration)
4. **Run experiments** on database with result tracking
5. **Compare strategies** to find the best approach

---

## Quick Start

### 1. Export Sample Decisions

Extract decisions grouped by type for manual inspection:

```bash
# Export 10 random decisions per type (combined JSON format - recommended)
python manage.py export_samples --sample-size 10 --output-dir decision_samples

# Export with separate .txt and .json files (old format)
python manage.py export_samples --sample-size 10 --separate-files

# Export 20 samples to custom folder
python manage.py export_samples --sample-size 20 --output-dir my_samples
```

**Output structure (default combined format):**
```
decision_samples/
├── B.2_Πράξη Ανάληψης Υποχρέωσης/
│   ├── ΩΨ8Λ46904Ω-ΨΚΝ.json     # All data including text
│   └── ...
├── Γ.2_Συμβάσεις/
│   └── ...
```

**JSON structure includes:**
- Decision metadata (ADA, subject, dates)
- **Accurate calculated amounts** (from `FinancialCalculationService`)
- Entity breakdown with amounts per AFM
- Full decision text
- Extraction status

**Manually inspect** these to understand patterns before writing strategies.

---

### 2. Create a Strategy

Create a new file in `experiments/strategies/`:

```python
# experiments/strategies/my_strategy.py
from .base import DecompositionStrategy, DecompositionResult
from core.models.decisions import Decision
import re

class MyPaymentStrategy(DecompositionStrategy):
    @property
    def name(self) -> str:
        return "my_payment_extractor"

    def decompose(self, decision: Decision, text: str) -> DecompositionResult:
        data = {}

        # Extract beneficiary AFM
        afm_match = re.search(r'με ΑΦΜ\s+(\d{9})', text)
        if afm_match:
            data['afm'] = afm_match.group(1)

        # Extract amount
        amount_match = re.search(r'ΣΥΝΟΛΟ\s*:\s*([\d,.]+)', text)
        if amount_match:
            data['amount'] = amount_match.group(1)

        # Return success if found key data
        if len(data) >= 2:
            return DecompositionResult(success=True, data=data)
        else:
            return DecompositionResult(
                success=False,
                error="Not enough data extracted"
            )
```

**That's it!** The strategy is automatically discovered. No imports needed.

---

### 3. Test on Filesystem (Fast Iteration)

Test your strategy on exported samples without touching the database:

```bash
# List all available strategies
python manage.py test_on_samples --list-strategies

# Test single strategy
python manage.py test_on_samples --strategy my_payment_extractor --show-failures

# Compare all strategies
python manage.py test_on_samples --compare-all --show-failures

# Test on custom samples directory
python manage.py test_on_samples --samples-dir my_samples --compare-all
```

**Example output:**
```
=== STRATEGY COMPARISON (Filesystem Test) ===

searchable_content_filter | Success:  85.3% | 195/228 passed
my_payment_extractor      | Success:  72.4% | 165/228 passed
key_sections_extractor    | Success:  45.6% | 104/228 passed

[OK] Filesystem testing complete. Ready for DB testing with 'run_experiment'
```

**Iterate quickly:** Edit your strategy → Run test → See results → Repeat

---

### 4. Run Database Experiments

Once your strategy looks good on samples, test it on the real database:

```bash
# Run single strategy on small sample
python manage.py run_experiment --strategy my_payment_extractor --sample-size 100

# Test on specific decision type
python manage.py run_experiment --strategy my_payment_extractor \
  --decision-type B.2 --sample-size 500

# Compare all strategies on database
python manage.py run_experiment --compare-all --sample-size 1000
```

**Results are saved to database** for analysis.

**Example output:**
```
Completed in 12.3s
Success: 847/1000 (84.7%)
Failed:  153
Run ID: 42
```

---

### 5. Analyze Results

Query experiment results in Django shell or admin:

```python
from experiments.models import ExperimentRun, ExperimentResult

# Find best performing strategy overall
best = ExperimentRun.objects.order_by('-success_rate').first()
print(f"Best: {best.strategy_name} - {best.success_rate}%")

# Compare strategies for a specific decision type
from core.models.types import ActType
act_type = ActType.objects.get(uid='B.2')
runs = ExperimentRun.objects.filter(decision_type=act_type).order_by('-success_rate')
for run in runs:
    print(f"{run.strategy_name:25} | {run.success_rate:5.1f}% | Run #{run.id}")

# Analyze failures for improvement
run = ExperimentRun.objects.get(id=42)
failures = run.results.filter(success=False)[:10]
for f in failures:
    print(f"{f.decision.ada}: {f.error_message}")

# See what was extracted successfully
successes = run.results.filter(success=True)[:5]
for s in successes:
    print(f"{s.decision.ada}: {s.extracted_data}")
```

---

### 6. Promote to Production

Once a strategy proves effective, save its configuration:

```python
from experiments.models import ExperimentRun, StrategyConfiguration

# Find your best run
best_run = ExperimentRun.objects.filter(
    strategy_name='my_payment_extractor',
    success_rate__gt=80
).order_by('-success_rate').first()

# Graduate it to production config
config = StrategyConfiguration.objects.create(
    decision_type=best_run.decision_type,
    strategy_name=best_run.strategy_name,
    name="Production Config v1",
    description="Payment extraction - works well on B.2 decisions",
    config=best_run.config,
    extracted_fields=['afm', 'beneficiary', 'amount', 'ka_code'],
    best_experiment_run=best_run,
    success_rate=best_run.success_rate,
    validated_on_count=best_run.total_decisions,
    is_production_ready=True,
    created_by="your_name"
)
```

---

## Available Strategies

Currently implemented (auto-discovered from `experiments/strategies/`):

- **key_sections_extractor** - Extracts beneficiary, amounts, KA codes, invoices
- **searchable_content_filter** - Identifies high-value content vs boilerplate
- *(Add your own and they appear automatically)*

---

## Typical Workflow

```bash
# 1. Export samples for manual inspection
python manage.py export_samples --sample-size 15

# 2. Inspect files, identify patterns
ls decision_samples/
cat decision_samples/B.2_*/ΩΨ8Λ*.txt

# 3. Create strategy in experiments/strategies/my_strategy.py
# (Write your extraction logic)

# 4. Quick test on filesystem
python manage.py test_on_samples --strategy my_strategy --show-failures

# 5. Iterate and improve based on failures
# (Edit strategy, re-run test)

# 6. When ready, test on database
python manage.py run_experiment --strategy my_strategy --sample-size 200

# 7. Analyze results and refine
# (Check failures, improve patterns)

# 8. Compare with other strategies
python manage.py run_experiment --compare-all --sample-size 1000

# 9. Promote best strategy to production
# (Use Django shell or admin)
```

---

## Strategy Development Tips

### What to extract?

Focus on **high-value, searchable content**:
- [OK] Descriptions, payment reasons, beneficiaries
- [OK] Amounts, invoice numbers, contract details
- [ERROR] Technical metadata (A/A, signatures, boilerplate)

### Example patterns from real decisions:

```python
# Beneficiary with AFM
r':\s*([^:]+?)\s+με ΑΦΜ\s+(\d{9})'

# Payment description
r'Περιγραφή λογ/μου[\s\n]+Ποσό[\s\n]+[\d.]+[\s\n]+([^\d]+?)\s+[\d,]+'

# Total amount
r'ΣΥΝΟΛΟ\s*:\s*([\d,.]+)'

# Payment reason
r'ΑΙΤΙΑ ΠΛΗΡΩΜΗΣ[\s\n]+(.+?)(?:Κράτηση|ΣΥΝΟΔΕΥΤΙΚΑ)'

# KA code
r'Κ\.Α\.\s+εξόδου[\s\n]+(\d+\.\d+\.\d+)'
```

### Return meaningful data:

```python
return DecompositionResult(
    success=True,
    data={
        'afm': '099874785',
        'beneficiary': 'ΕΠΙΤΡΟΠΑΚΗΣ ΓΕΩΡΓΙΟΣ',
        'description': 'Προμήθεια ανταλλακτικών...',
        'amount': 2338.97,
        'ka_code': '20.6672.28',
        'confidence_score': 0.95  # Optional
    }
)
```

---

## Models Reference

### ExperimentRun
Tracks complete experiment execution with summary metrics.

**Key fields:**
- `strategy_name`, `strategy_version`
- `decision_type`, `total_decisions`
- `successful_count`, `failed_count`, `success_rate`
- `started_at`, `completed_at`, `duration_seconds`

### ExperimentResult
Individual decision result within an experiment.

**Key fields:**
- `run`, `decision`, `success`
- `extracted_data` - JSON of what was extracted
- `error_message` - Why it failed
- `processing_time_ms`, `confidence_score`

### StrategyConfiguration
Production-ready strategy configurations.

**Key fields:**
- `decision_type`, `strategy_name`, `config`
- `extracted_fields`, `success_rate`
- `is_production_ready`

---

## Troubleshooting

**Strategy not found?**
```bash
# Check if it's discovered
python manage.py test_on_samples --list-strategies
```

**No samples exported?**
```bash
# Check if decisions exist in DB
python manage.py shell
>>> from core.models.decisions import Decision
>>> Decision.objects.count()
```

```bash
# Test only on ΕΓΚΡΙΣΗ ΔΑΠΑΝΗΣ documents
python manage.py test_on_samples \
  --strategy expense_approval_decomposer \
  --decision-type "Β.2.1_ΕΓΚΡΙΣΗ ΔΑΠΑΝΗΣ" \
  --show-failures

# Or use partial match (just the code)
python manage.py test_on_samples \
  --strategy expense_approval_decomposer \
  --decision-type "Β.2.1" \
  --show-failures

# Or compare all strategies on just this type
python manage.py test_on_samples \
  --compare-all \
  --decision-type "ΕΓΚΡΙΣΗ ΔΑΠΑΝΗΣ" \
  --show-failures
```

**Import errors?**
Ensure your strategy file:
- Is in `experiments/strategies/`
- Imports from `.base` (relative import)
- Has a `name` property

---

## Next Steps

1. **Analyze your decision types** - What patterns exist?
2. **Start simple** - Extract 2-3 key fields first
3. **Iterate based on results** - Check failures, refine patterns
4. **Combine techniques** - Regex + rules + ML if needed
5. **Track what works** - Use the database to compare approaches

**Goal:** Find the strategy with the best success/effort tradeoff for each decision type.



```bash
python manage.py test_on_samples \
  --strategy expense_approval_essence \
  --decision-type "Β.2.1" \
  --export-results \
  --show-failures
```

# This will create:
# extraction_results/expense_approval_essence_YYYYMMDD_HHMMSS/
#   ├── summary.json          # Overall results
#   ├── report.txt            # Human-readable report
#   ├── 6ΑΛΚΩΕΝ-1ΛΠ.json      # Individual extraction details
#   ├── 992Δ469Β7Κ-3ΨΤ.json
#   └── ...

# Compare both strategies
```bash
python manage.py test_on_samples \
  --decision-type "Β.2.1" \
  --compare-all
```
