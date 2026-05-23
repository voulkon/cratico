"""
Vulture whitelist for pytest fixtures and other false positives.

This file tells vulture to ignore certain items that are used but not
detected by static analysis (e.g., pytest fixtures, Django models, etc.)
"""

# Pytest fixtures (used implicitly by pytest)
_.clear_import_queue
_.celery_eager_mode
_.mock_nominatim_response_dodoni_valid
_.notification_with_read_status

# Django test fixtures
_.request_num
_.discovered_via_afm
_.search_rank
_.max_concurrency
