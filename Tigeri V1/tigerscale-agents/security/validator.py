"""Contain validator backend logic."""
import re
from config.db_pool import get_conn

_CLIENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,98}[a-z0-9]$")


def validate_client_id(client_id: str) -> tuple[bool, str]:
    """Validate client id."""
    if not client_id or not isinstance(client_id, str):
        return False, "Missing client_id"
    if not _CLIENT_ID_RE.match(client_id):
        return False, "Invalid client_id format"
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT active FROM clients WHERE client_id = %s", (client_id,))
            row = cur.fetchone()
            cur.close()
    except Exception:
        return False, "Client validation unavailable"
    if not row:
        return False, "Unknown client"
    if not row[0]:
        return False, "Client inactive"
    return True, "ok"


def validate_webhook_payload(payload: dict, required_keys:list[str]) -> tuple[bool,str]:
    """Validate webhook payload."""
    if not isinstance(payload,dict):
        return False, "payload must be a JSON object"
    
    for key in required_keys:
        if key not in payload:
            return False, f"Missing required field: {key}"
        
    return True, "ok"

def validate_agent_task(task:dict) -> tuple[bool,str]:
    """Validate agent task."""
    if not isinstance(task,dict):
        return False, "task must be a dict"
    
    message = task.get("message", "")
    
    if not isinstance(message,str):
        return False, "task message must be a string"
    
    if len(message) == 0:
        return False, "Empty message"
    
    return True, "ok"
    
