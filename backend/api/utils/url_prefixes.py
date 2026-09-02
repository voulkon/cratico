"""
URL Prefix Utilities

Shared utilities for discovering and managing API URL prefixes.
Used by both stealth middleware and admin interface to ensure consistency.
"""

import importlib
from pathlib import Path


def get_all_url_module_prefixes():
    """
    Dynamically discover and import PREFIX constants from all api.urls modules.

    Automatically scans the api/urls/ directory to find all Python modules,
    imports them, and extracts their PREFIX constants.

    Returns:
        list: List of tuples (module_name, prefix) e.g., [('auth', 'auth/'), ('system', 'system/')]
    """
    prefixes = []

    # Get the path to the api/urls directory
    api_urls_dir = Path(__file__).parent.parent / "urls"

    if not api_urls_dir.exists():
        return prefixes

    # Iterate through all Python files in api/urls/
    for file_path in api_urls_dir.glob("*.py"):
        # Skip __init__.py and any private modules
        if file_path.name.startswith("_"):
            continue

        # Extract module name (e.g., 'auth' from 'auth.py')
        module_name = file_path.stem
        module_path = f"api.urls.{module_name}"

        try:
            # Import the module
            module = importlib.import_module(module_path)

            # Check if it has a PREFIX constant
            if hasattr(module, "PREFIX"):
                prefixes.append((module_name, module.PREFIX))
        except (ImportError, AttributeError):
            # Module can't be imported or doesn't have PREFIX - skip it
            continue

    return prefixes


def get_default_exempt_prefixes():
    """
    Get the default list of URL prefixes that should always be exempt from stealth mode.

    These are critical endpoints that must remain accessible:
    - Health checks (for monitoring)
    - Admin interface
    - API documentation
    - Authentication endpoints (critical - users need to login!)

    Returns:
        list: List of prefix strings without /api/ (e.g., ['health', 'admin', 'auth/'])
    """
    # Always exempt these critical endpoints (without /api/ prefix)
    always_exempt = [
        "health",  # /api/health - Monitoring & health checks
        "v1/health",  # /api/v1/health - Versioned health check
        "admin",  # /api/admin - Admin interface
        "docs",  # /api/docs - API documentation
        "public/",  # /api/public/ - Public sharing endpoints (must be unauthenticated)
        # /api/system/config/auth/ must stay reachable before login: in stealth
        # mode the login gate renders from its payload (auth_methods, Clerk
        # publishable key). All system/* endpoints are AllowAny by design.
        "system/",
    ]

    # Always include auth module - users MUST be able to login!
    all_prefixes = get_all_url_module_prefixes()
    auth_prefix = next(
        (prefix for name, prefix in all_prefixes if name == "auth"), None
    )
    if auth_prefix:
        always_exempt.append(auth_prefix)

    return always_exempt


def get_additional_exempt_prefixes():
    """
    Get additional exempt prefixes from feature flag configuration.

    These are configurable exemptions beyond the always-exempt defaults.

    Returns:
        list: List of prefix strings selected by admin in feature flag settings
    """
    from core.services.feature_flag_service import feature_flags

    # Get selected prefixes from feature flag (returns list of module names like ['system', 'tasks'])
    selected_modules = feature_flags.get_value("STEALTH_EXEMPT_PREFIXES")

    if not selected_modules:
        return []

    # Convert module names to actual prefixes
    all_prefixes = get_all_url_module_prefixes()
    prefix_map = {name: prefix for name, prefix in all_prefixes}

    return [prefix_map[module] for module in selected_modules if module in prefix_map]


def get_all_exempt_prefixes():
    """
    Get complete list of exempt prefixes (defaults + additional from feature flag).

    Returns:
        list: List of full URL prefixes with /api/ (e.g., ['/api/health', '/api/auth/'])
    """
    # Combine default and additional exemptions
    exempt_prefixes = get_default_exempt_prefixes() + get_additional_exempt_prefixes()

    # Add /api/ prefix to all paths
    return [f"/api/{prefix}" for prefix in exempt_prefixes]
