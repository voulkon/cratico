"""Template tags for feature flag display."""

from core.services.feature_flag_service import feature_flags
from django import template

register = template.Library()


@register.simple_tag
def get_flag_source(flag_key):
    """Get the source information for a feature flag."""
    return feature_flags.get_flag_info(flag_key)
