"""Contain rate limiter backend logic."""
import time
import redis as redis_lib
from config.settings import settings

_redis = redis_lib.from_url(settings.redis_url, decode_responses=True)

# Default limit used by this module.
DEFAULT_LIMIT = 30     
# Default window used by this module.
DEFAULT_WINDOW = 60

# Lua script
_RATE_LIMIT_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local window_start = now - window

redis.call('ZREMRANGEBYSCORE', key, 0, window_start)
local count = redis.call('ZCARD', key)

if count >= limit then
    return 0
end

redis.call('ZADD', key, now, tostring(now) .. math.random())
redis.call('EXPIRE', key, window * 2)
return 1
"""

_script = _redis.register_script(_RATE_LIMIT_SCRIPT)

def check_rate_limit(
    client_id: str,
    endpoint:str,
    limit:int = DEFAULT_LIMIT,
    window:int= DEFAULT_WINDOW,
) -> tuple[bool,str]:
    """Check rate limit."""
    key = f"ratelimit:{endpoint}:{client_id}"
    try:
        result = _script(keys=[key], args=[time.time(), window, limit])
        if result == 0:
            return False, f"Rate limit exceeded: {limit} req/{window}s"
        return True, "ok"
    except Exception:
        return True, "ok"
    
async def get_remaining(
    client_id: str,
    endpoint: str,
    window: int = DEFAULT_WINDOW,
) -> int:
    """Return remaining."""
    key = f"ratelimit:{endpoint}:{client_id}"
    now = time.time()
    await _redis.zremrangebyscore(key, 0, now - window)
    count = await _redis.zcard(key)
    return max(0, DEFAULT_LIMIT - count)
