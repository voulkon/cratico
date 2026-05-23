"""
Constants for the notifications app.

These constants define subscription types and other configuration values
used throughout the notifications system.
"""

# Subscription Types
SUBSCRIPTION_TYPE_ORGANIZATION = "organization"
SUBSCRIPTION_TYPE_ENTITY = "entity"
SUBSCRIPTION_TYPE_RELATIONSHIP = "relationship"
SUBSCRIPTION_TYPE_PERSON = "person"
SUBSCRIPTION_TYPE_SIGNER = "signer"
SUBSCRIPTION_TYPE_FILTER = "filter"

SUBSCRIPTION_TYPES = [
    SUBSCRIPTION_TYPE_ORGANIZATION,
    SUBSCRIPTION_TYPE_ENTITY,
    SUBSCRIPTION_TYPE_RELATIONSHIP,
    SUBSCRIPTION_TYPE_PERSON,
    SUBSCRIPTION_TYPE_SIGNER,
    SUBSCRIPTION_TYPE_FILTER,
]

# Keyword Match Operators
KEYWORD_OPERATOR_AND = "AND"
KEYWORD_OPERATOR_OR = "OR"

# Check Frequencies
CHECK_FREQUENCY_DAILY = "daily"
CHECK_FREQUENCY_WEEKLY = "weekly"
CHECK_FREQUENCY_MANUAL = "manual"
