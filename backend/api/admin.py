"""
API Admin Configuration

This module imports and exposes the custom admin site from admin_custom.
The custom admin site includes all model registrations and custom views.
"""

from admin_custom.sites import admin_site

# Expose the custom admin site for use in urls.py
__all__ = ["admin_site"]
