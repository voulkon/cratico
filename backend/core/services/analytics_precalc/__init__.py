"""
Analytics Pre-Calculation Service

Two-layer design for each covered view:

  compute_*(...)  → pure DB query; returns the same response dict the view
                    would return.  Called by both the view (on cache miss) and
                    the warmup task (to pre-populate).  Single source of truth.

  warm_*_window(...)  → calls compute_* then stores the result under the EXACT
                        Redis key that cached_view would look up for that window.

Adding a new view
─────────────────
1. Add compute_<name>(...)  →  dict
2. Add warm_<name>_window(...)  →  None
3. Register in WARMUP_REGISTRY below
4. Register in warm_analytics_cache's view loop (tasks_post_import.py)

Views covered
─────────────
  explore_organizations_api_dev          cache_prefix="explore_orgs"
  direct_assignment_top_pairs_global     cache_prefix="da_top_pairs"
  explore_decisions_optimized_api        cache_prefix="explore_decisions"
  direct_assignment_top_entities_global  cache_prefix="da_top_entities"
  direct_assignment_top_organizations_global  cache_prefix="da_top_orgs"
  explore_decision_types_api_dev         cache_prefix="explore_decision_types"
  explore_statistics_api_dev             cache_prefix="explore_statistics"
  top_payments_api                       cache_prefix="top_payments"
  top_direct_assignments_api             cache_prefix="top_direct_assignments"
  top_by_amount_api                      cache_prefix="top_by_amount"
  unified endpoint (temporal source)     cache_prefix="unified"

Implementation is split across domain modules under ``analytics_precalc/``:

  _helpers.py              shared date helpers & imports
  explore_orgs.py          compute_explore_orgs, warm_explore_orgs_window
  da_top_pairs.py          compute_da_top_pairs, warm_da_top_pairs_window
  explore_decisions.py     compute_explore_decisions, warm_explore_decisions_window
  da_top_entities.py       compute_da_top_entities, warm_da_top_entities_window
  da_top_orgs.py           compute_da_top_orgs, warm_da_top_orgs_window
  explore_decision_types.py  compute_explore_decision_types, warm_...
  explore_statistics.py    compute_explore_statistics, warm_explore_statistics_window
  top_payments.py          compute_top_payments, warm_top_payments_window
  top_direct_assignments.py  compute_top_direct_assignments, warm_...
  top_by_amount.py         compute_top_by_amount, warm_top_by_amount_window
  unified.py               warm_unified_window
"""

# ── Re-export all public symbols for backward compatibility ───────────
# All existing imports of ``from core.services.analytics_precalc_service
# import X`` continue to work when redirected to this package.

from ._helpers import _make_aware_start, _make_aware_end

from .explore_orgs import (
    compute_explore_orgs,
    warm_explore_orgs_window,
)
from .da_top_pairs import (
    compute_da_top_pairs,
    warm_da_top_pairs_window,
)
from .explore_decisions import (
    compute_explore_decisions,
    warm_explore_decisions_window,
)
from .da_top_entities import (
    compute_da_top_entities,
    warm_da_top_entities_window,
)
from .da_top_orgs import (
    compute_da_top_orgs,
    warm_da_top_orgs_window,
)
from .explore_decision_types import (
    compute_explore_decision_types,
    warm_explore_decision_types_window,
)
from .explore_statistics import (
    compute_explore_statistics,
    warm_explore_statistics_window,
)
from .top_payments import (
    compute_top_payments,
    warm_top_payments_window,
)
from .top_direct_assignments import (
    compute_top_direct_assignments,
    warm_top_direct_assignments_window,
)
from .top_by_amount import (
    compute_top_by_amount,
    warm_top_by_amount_window,
)
from .unified import warm_unified_window


# ── Warmup registry: view_name → warm_function ──────────────────────────
# Used by warm_single_window for on-demand (defer_on_miss) warmup.
# Each key matches the cache_prefix used in @cached_view.

WARMUP_REGISTRY = {
    "explore_orgs": warm_explore_orgs_window,
    "da_top_pairs": warm_da_top_pairs_window,
    "explore_decisions": warm_explore_decisions_window,
    "da_top_entities": warm_da_top_entities_window,
    "da_top_orgs": warm_da_top_orgs_window,
    "explore_decision_types": warm_explore_decision_types_window,
    "explore_statistics": warm_explore_statistics_window,
    "unified": warm_unified_window,
    "top_payments": warm_top_payments_window,
    "top_direct_assignments": warm_top_direct_assignments_window,
    "top_by_amount": warm_top_by_amount_window,
}
