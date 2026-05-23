import bleach
from rest_framework.parsers import JSONParser


class SanitizedJSONParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        data = super().parse(stream, media_type, parser_context)
        return self.sanitize_data(data)

    def sanitize_data(self, data):
        if isinstance(data, dict):
            return {k: self.sanitize_data(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self.sanitize_data(item) for item in data]
        elif isinstance(data, str):
            return bleach.clean(data, strip=True)
        else:
            return data
