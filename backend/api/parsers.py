import bleach
from rest_framework.parsers import JSONParser

# Fields whose values must reach the view byte-for-byte. HTML-sanitizing them
# corrupts credentials (bleach escapes "&" to "&amp;" and strips tag-like
# sequences), which silently breaks password/token checks.
SENSITIVE_FIELDS = frozenset(
    {
        "password",
        "new_password",
        "old_password",
        "current_password",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "secret",
        "otp",
        "verification_code",
        "email_verification_token",
        "password_reset_token",
    }
)


class SanitizedJSONParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        data = super().parse(stream, media_type, parser_context)
        return self.sanitize_data(data)

    def sanitize_data(self, data, field=None):
        if field in SENSITIVE_FIELDS:
            return data
        if isinstance(data, dict):
            return {k: self.sanitize_data(v, k) for k, v in data.items()}
        elif isinstance(data, list):
            return [self.sanitize_data(item, field) for item in data]
        elif isinstance(data, str):
            return bleach.clean(data, strip=True)
        else:
            return data
