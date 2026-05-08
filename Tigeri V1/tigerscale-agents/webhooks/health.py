"""Contain health backend logic."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
import redis
from config.db_pool import get_conn
from config.settings import settings

router = APIRouter()

_redis = redis.from_url(settings.redis_url, decode_responses=True)

# Constant for beat maximum gap seconds.
BEAT_MAX_GAP_SECONDS = 360


@router.get("/health")
def health_api():
    """Execute health api."""
    return {"status": "ok", "service": "api"}


@router.get("/health/db")
def health_db():
    """Execute health db."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
        return {"status": "ok", "service": "db"}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "degraded", "service": "db", "reason": str(e)})


@router.get("/health/redis")
def health_redis():
    """Execute health redis."""
    try:
        _redis.ping()
        return {"status": "ok", "service": "redis"}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "degraded", "service": "redis", "reason": str(e)})


@router.get("/health/celery")
def health_celery():
    """Execute health celery."""
    try:
        from core.worker import celery_app
        inspector = celery_app.control.inspect(timeout=3)
        active = inspector.active()
        if active is None:
            return JSONResponse(status_code=503, content={"status": "degraded", "service": "celery", "reason": "No workers responding"})
        return {"status": "ok", "service": "celery", "workers": list(active.keys())}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "degraded", "service": "celery", "reason": str(e)})


@router.get("/health/beat")
def health_beat():
    """Execute health beat."""
    try:
        last_run = _redis.get("health:beat:last_run")
        if not last_run:
            return JSONResponse(status_code=503, content={"status": "degraded", "service": "beat", "reason": "No heartbeat recorded yet"})

        import time
        gap = time.time() - float(str(last_run))
        if gap > BEAT_MAX_GAP_SECONDS:
            return JSONResponse(status_code=503, content={"status": "degraded", "service": "beat", "reason": f"Last heartbeat {int(gap)}s ago"})

        return {"status": "ok", "service": "beat", "last_run_seconds_ago": int(gap)}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "degraded", "service": "beat", "reason": str(e)})
    
    
    
@router.get("/health/dlq")
def health_dlq():
    """Execute health dlq."""
    try:
        from core.worker import celery_app
        inspector = celery_app.control.inspect(timeout=3)
        reserved = inspector.reserved() or {}
        dlq_tasks = [
            t for w in reserved.values()
            for t in w
            if t.get("delivery_info", {}).get("routing_key") == "dead_letter"
        ]
        return {"status": "ok", "dead_letter_count": len(dlq_tasks)}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "degraded", "reason": str(e)})