"""
Analytics Pre-Calculation Service  (backward-compatibility shim)

This module has been split into the ``analytics_precalc/`` package.
All public symbols are re-exported from there — existing imports
continue to work without changes.

See ``analytics_precalc/__init__.py`` for the full list of views.
"""

# Re-export everything from the new package for backward compatibility.
# This file exists so that imports like:
#     from core.services.analytics_precalc_service import compute_explore_orgs
# continue to work without modification.

from core.services.analytics_precalc import *  # noqa: F401, F403, E402
