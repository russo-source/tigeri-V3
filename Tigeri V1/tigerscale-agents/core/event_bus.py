"""Contain event bus backend logic."""
import redis
import json
import logging
from config.settings import settings

logger = logging.getLogger(__name__)
_r = redis.from_url(settings.redis_url, decode_responses=True)

def publish(channel: str, event: dict) -> None:
    """Execute publish."""
    try:
        _r.publish(channel, json.dumps(event))
    except Exception as e:
        logger.error("publish failed channel=%s: %s", channel, e)

def subscribe(channel: str):
    """Execute subscribe."""
    pubsub = _r.pubsub()
    pubsub.subscribe(channel)
    return pubsub

def listen(channel: str):
    """Execute listen."""
    pubsub = subscribe(channel)
    for message in pubsub.listen():
        if message["type"] == "message":
            try:
                yield json.loads(message["data"])
            except json.JSONDecodeError as e:
                logger.warning("event_bus bad JSON on %s: %s", channel, e)

def enqueue(queue: str, task: dict, priority: str = "normal") -> None:
    """Execute enqueue."""
    key = f"queue:{priority}:{queue}"
    try:
        _r.lpush(key, json.dumps(task))
    except Exception as e:
        logger.error("enqueue failed key=%s: %s", key, e)

def dequeue(queue: str, priority: str = "normal") -> dict | None:
    """Execute dequeue."""
    key  = f"queue:{priority}:{queue}"
    item = _r.rpop(key)
    if item:
        try:
            return json.loads(str(item))
        except json.JSONDecodeError as e:
            logger.error("dequeue bad JSON key=%s: %s", key, e)
    return None