"""Shared fakes for import-chunk tests."""

from core.services.redis_decision_cache import RedisDecisionCache


class FakeRedis:
    """Minimal Redis double for the helpers used by RedisDecisionCache."""

    def __init__(self, values=None, keys=None, states=None):
        self.values = values or {}
        self.keys = keys or []
        self.states = states or {}
        self.deleted = []
        self.last_match = None

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, ttl, value):
        self.values[key] = value
        return True

    def delete(self, *keys):
        self.deleted.extend(keys)
        for key in keys:
            self.values.pop(key, None)
        return len(keys)

    def exists(self, key):
        return key in self.values

    def hsetnx(self, key, field, value):
        bucket = self.states.setdefault(key, {})
        if field in bucket:
            return 0
        bucket[field] = value
        return 1

    def hget(self, key, field):
        return self.states.get(key, {}).get(field)

    def hgetall(self, key):
        return dict(self.states.get(key, {}))

    def hdel(self, key, field):
        self.states.get(key, {}).pop(field, None)
        return 1

    def expire(self, key, ttl):
        return True

    def scan(self, cursor=0, match=None, count=100):
        self.last_match = match
        prefix = match[:-1] if match and match.endswith("*") else match
        return 0, [key for key in self.keys if key.startswith(prefix)]


def make_cache(fake_redis):
    cache = RedisDecisionCache.__new__(RedisDecisionCache)
    cache.redis_client = fake_redis
    return cache
