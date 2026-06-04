"""
Default legal page content for Crati.
Fallback used when no custom content has been set by an admin.

Content is loaded from .md files in <doc_type>/<language>.md,
e.g.  tos/en.md, tos/el.md, privacy/en.md, …

Titles are kept inline (short strings); only long-form content
lives in the markdown files so they can be reviewed/edited
independently of the Python code.
"""

from pathlib import Path

_HERE = Path(__file__).resolve().parent

# Registry of default document types: slug → {en_title, el_title}
_DEFAULT_DOCS = {
    "tos": {"en": "Terms of Service", "el": "Όροι Χρήσης"},
    "privacy": {"en": "Privacy Policy", "el": "Πολιτική Απορρήτου"},
    "cookies": {"en": "Cookie Policy", "el": "Πολιτική Cookies"},
}

# ---------------------------------------------------------------------------
# Content caching – loaded once at import time
# ---------------------------------------------------------------------------
_CONTENT_CACHE: dict[tuple[str, str], str] = {}


def _load_content(doc_type: str, language: str) -> str:
    """Read the markdown content for *doc_type*/*language* from disk."""
    key = (doc_type, language)
    if key not in _CONTENT_CACHE:
        md_path = _HERE / doc_type / f"{language}.md"
        try:
            _CONTENT_CACHE[key] = md_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            _CONTENT_CACHE[key] = (
                f"# {doc_type.title()}\n\nContent coming soon."
            )
    return _CONTENT_CACHE[key]


# ---------------------------------------------------------------------------
# Public API (same as before the refactor)
# ---------------------------------------------------------------------------


def get_available_types():
    """Return the list of known document type slugs."""
    return list(_DEFAULT_DOCS.keys())


def get_default_legal_content(doc_type: str, field: str, language: str = "en") -> str:
    """
    Return the default value for a document type and field.

    Args:
        doc_type: Slug like 'tos', 'privacy', 'cookies'
        field: 'title' or 'content'
        language: 'en' or 'el'

    Returns:
        The default title or content for the given document type.
    """
    if field == "title":
        return _DEFAULT_DOCS.get(doc_type, {}).get(language, doc_type.title())

    # field == "content"
    return _load_content(doc_type, language)
