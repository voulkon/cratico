"""Custom template filters for health check displays"""

from django import template

register = template.Library()


@register.filter(name="get_item")
def get_item(dictionary, key):
    """
    Template filter to get an item from a dictionary.
    Usage: {{ mydict|get_item:"key_name" }}
    """
    if dictionary is None:
        return None
    return dictionary.get(key)


@register.filter(name="replace")
def replace(value, arg):
    """
    Replace a string with another.
    Usage: {{ value|replace:"old,new" }}
    """
    if not value:
        return value
    try:
        old, new = arg.split(",")
        return value.replace(old, new)
    except (ValueError, AttributeError):
        return value
