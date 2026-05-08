"""Contain authorization backend logic."""
import logging
from config.client_config import get_client_config
from security.audit import log_action

logger = logging.getLogger(__name__)

_MUTATING_ACTIONS = {
    "approve", "edit", "mark_paid", "refund",
    "capture_payment", "cancel_payment", "handle_dispute",
}

def is_mutating(action: str) -> bool:
    """Check whether mutating."""
    return action in _MUTATING_ACTIONS

def check_sender_authorized(client_id: str, sender_id: str, action: str) -> bool:
    """Check sender authorized."""
    if not sender_id:
        return False
    try:
        config = get_client_config(client_id)
        approved = config.get("approved_user_ids", [])
        if not approved:
            approver_chat_id = config.get("approver_chat_id") or config.get("approve_chat_id")
            return str(sender_id) == str(approver_chat_id)
        return str(sender_id) in [str(uid) for uid in approved]
    except Exception as e:
        logger.error("Authorization check failed client=%s sender=%s: %s", client_id, sender_id, e)
        return False

def assert_authorized(client_id: str, sender_id: str, action: str, message: str) -> dict | None:
    """Execute assert authorized."""
    if not is_mutating(action):
        return None
    if check_sender_authorized(client_id, sender_id, action):
        return None
    log_action(
        client_id, "authorization", action, message,
        {"sender_id": sender_id}, "unauthorized",
        message=f"Unauthorized {action} attempt by sender={sender_id}",
    )
    return {
        "status": "unauthorized",
        "message": "You're not authorized to perform this action.",
    }