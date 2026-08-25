"""
Guard against @cached_view being applied ABOVE @api_view / @permission_classes.

Background
----------
DRF's ``api_view`` decorator copies ``permission_classes`` /
``authentication_classes`` from the function it wraps and enforces them inside
``APIView.dispatch()``.  Our ``@cached_view`` decorator (core.decorators) serves
cached responses *without* calling the wrapped view, so when it sits above
``@api_view`` a cache HIT short-circuits authentication/authorization entirely.

This is how a protected endpoint could anonymously return cached data, while
the exact same endpoint returns 401 on a cache miss:

    @cached_view(...)            # BAD: cache hit returns before permission check
    @api_view(["GET"])
    @permission_classes([...])
    def view(request): ...

Correct order — permission check runs first, then the cache:

    @api_view(["GET"])
    @permission_classes([...])
    @cached_view(...)            # GOOD
    def view(request): ...

This test statically scans ``api/views`` and fails if any function applies
``@cached_view`` above (before) ``@api_view``.
"""

import ast
from pathlib import Path

VIEWS_DIR = Path(__file__).resolve().parents[1] / "views"


def _decorator_name(decorator):
    """Return the bare name of a decorator node (e.g. ``cached_view``)."""
    node = decorator
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _functions_with_decorators():
    for path in sorted(VIEWS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names = [
                    name
                    for name in (_decorator_name(d) for d in node.decorator_list)
                    if name is not None
                ]
                yield path, node.name, names


def test_cached_view_is_below_api_view():
    """Every @cached_view must be applied after (below) @api_view."""
    violations = []
    for path, func_name, names in _functions_with_decorators():
        if "cached_view" in names and "api_view" in names:
            if names.index("api_view") > names.index("cached_view"):
                violations.append(f"{path}:{func_name}")

    assert not violations, (
        "@cached_view is applied above @api_view in these views — cache hits "
        "would bypass authentication/permission checks:\n"
        + "\n".join(violations)
    )
