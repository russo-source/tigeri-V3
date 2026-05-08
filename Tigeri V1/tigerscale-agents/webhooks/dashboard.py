"""Contain dashboard backend logic."""
import json

from fastapi import APIRouter, Depends, HTTPException
from auth.deps import get_current_user, require_admin
from config.db_pool import get_conn
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

import redis
from config.settings import settings
from security.audit import log_action
_redis = redis.from_url(settings.redis_url, decode_responses=True)


router = APIRouter()

class ClientConfigUpdate(BaseModel):
    """Represent the ClientConfigUpdate component and its related behavior."""
    expense_approval_threshold: Optional[float] = None
    approve_email: Optional[str] = None


class SystemTogglesRequest(BaseModel):
    """Represent the SystemTogglesRequest component and its related behavior."""
    maintenance_mode: Optional[bool] = None
    maintenance_minutes: Optional[int] = None


class ClientAgentRequest(BaseModel):
    """Represent the ClientAgentRequest component and its related behavior."""
    agent_key: str
    note: Optional[str] = None
    
# Constant for agent type map.
AGENT_TYPE_MAP = {
    "a01_invoice": "Accounting AI",
    "a02_expense": "Accounting AI",
    "a03_admin": "Admin AI",
    "a04_payment": "Finance AI",
    # "a05_staffing": "Workforce AI",
    # "a06_communication": "Communication AI",
}

# Constant for agent label map.
AGENT_LABEL_MAP = {
    "a01_invoice": "Invoice Agent",
    "a02_expense": "Expense Agent",
    "a03_admin": "Admin Agent",
    "a04_payment": "Payment Agent",
    # "a05_staffing": "Staffing Agent",
    # "a06_communication": "Communication Agent",
}

def _agents_label(suggested_agents) -> str:
    """Execute agents label."""
    if not suggested_agents:
        return "No Agents Detected"
    try:
        if isinstance(suggested_agents, str):
            suggested_agents = json.loads(suggested_agents)
        agents = suggested_agents if isinstance(suggested_agents, list) else []
        labels = [a.get("label", "").replace(" Agent", "").strip() for a in agents if a.get("label")]
        return ", ".join(labels) if labels else "No Agents Detected"
    except Exception:
        return "No Agents Detected"
    
@router.get("/client/me")
def client_me(user: dict = Depends(get_current_user)):
    """Execute client me."""
    return {
        "user_id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "client_id": user["client_id"],
        "is_admin": user["is_admin"],
    }


@router.get("/client/agents")
def client_agents(user: dict = Depends(get_current_user)):
    """Execute client agents."""
    client_id = user["client_id"]
    if not client_id:
        raise HTTPException(status_code=404, detail="Onboarding not completed")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT agent_name, intent, status, created_at
            FROM audit_logs WHERE client_id = %s
            ORDER BY created_at DESC LIMIT 100
        """, (client_id,))
        rows = cur.fetchall()
        cur.close()
    return {"agents": [
        {"agent": r[0], "intent": r[1], "status": r[2], "at": str(r[3])}
        for r in rows
    ]}


@router.get("/client/requests")
def client_requests(user: dict = Depends(get_current_user)):
    """Execute client requests."""
    client_id = user["client_id"] or user["id"]
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, use_case, agent_type, business_type,
                   status, admin_notes, suggested_agents, created_at
            FROM agent_requests WHERE client_id = %s
            ORDER BY created_at DESC
        """, (client_id,))
        rows = cur.fetchall()
        cur.close()
    return {"requests": [
        {
            "id": r[0], "use_case": r[1], "agent_type": r[2],
            "business_type": r[3], "status": r[4],
            "admin_notes": r[5], "suggested_agents": r[6],
            "created_at": str(r[7])
        } for r in rows
    ]}


@router.get("/client/requests/{request_id}")
def client_request_detail(request_id: UUID, user: dict = Depends(get_current_user)):
    """Execute client request detail."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, client_id, use_case, agent_type, business_type,
                   scale, integrations, status, admin_notes, suggested_agents,
                   created_at, updated_at
            FROM agent_requests WHERE id = %s AND client_id = %s
        """, (str(request_id), user["client_id"] or user["id"]))
        row = cur.fetchone()
        cur.close()
    if not row:
        raise HTTPException(status_code=404, detail="Request not found")
    return {
        "id": row[0], "client_id": row[1], "use_case": row[2],
        "agent_type": row[3], "business_type": row[4], "scale": row[5],
        "integrations": row[6], "status": row[7], "admin_notes": row[8],
        "suggested_agents": row[9],
        "created_at": str(row[10]), "updated_at": str(row[11])
    }

@router.get("/client/stats")
def client_stats(user: dict = Depends(get_current_user)):
    """Execute client stats."""
    client_id = user["client_id"] or user["id"]
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM invoices WHERE client_id = %s", (client_id,))
        invoices = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM expenses WHERE client_id = %s", (client_id,))
        expenses = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM payments WHERE client_id = %s", (client_id,))
        payments = cur.fetchone()[0]
        cur.execute("""
            SELECT COUNT(*), SUM(CASE WHEN status='success' THEN 1 ELSE 0 END)
            FROM audit_logs
            WHERE client_id = %s
            AND agent_name NOT LIKE 'webhook:%%'
            AND agent_name NOT IN ('auth', 'onboarding', 'integrations')
        """, (client_id,))
        row = cur.fetchone()
        total = row[0] or 0
        success = row[1] or 0
        cur.execute("""
    SELECT suggested_agents FROM agent_requests
    WHERE client_id = %s AND status = 'approved'
    ORDER BY updated_at DESC LIMIT 1
""", (client_id,))
    agent_row = cur.fetchone()
    agents = agent_row[0] if agent_row else []
    cur.close()
    success_rate = round((int(success) / int(total) * 100), 2) if total else 0
    return {
        "invoices": invoices,
        "expenses": expenses,
        "payments": payments,
        "total_requests": total,
        "success_rate": success_rate,
        "total_agents": len(agents) if agents else 0,   
        "active_agents": len(agents) if agents else 0, 
    }

@router.get("/client/logs")
def client_logs(user: dict = Depends(get_current_user)):
    """Execute client logs."""
    client_id = user["client_id"] or user["id"]
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT agent_name, intent, status, error_ref, created_at, message
            FROM audit_logs WHERE client_id = %s
            AND agent_name NOT LIKE 'webhook:%%'
            AND agent_name NOT IN ('auth', 'onboarding', 'integrations')
            ORDER BY created_at DESC LIMIT 50
        """, (client_id,))
        rows = cur.fetchall()
        cur.close()
    return {"logs": [
    {
        "agent": r[0], "intent": r[1], "status": r[2],
        "ref": r[3], "at": str(r[4]),
        "message": r[5] or f"{r[0]} processed {r[1]}",
    } for r in rows
]}


@router.get("/client/integrations")
def client_integrations(user: dict = Depends(get_current_user)):
    """Execute client integrations."""
    client_id = user.get("client_id") or user["id"]
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT provider, connected, scopes, meta, connected_at
            FROM client_integrations WHERE client_id = %s
        """, (client_id,))
        rows = cur.fetchall()
        cur.close()
    connected = {r[0]: {"connected": r[1], "scopes": r[2], "meta": r[3], "connected_at": str(r[4])} for r in rows}
    from integrations.oauth_providers import ALL_PROVIDERS
    result = []
    for provider, cfg in ALL_PROVIDERS.items():
        status = connected.get(provider, {})
        result.append({
            "provider": provider,
            "label": cfg["label"],
            "category": cfg["category"],
            "auth_type": cfg["auth_type"],
            "connected": status.get("connected", False),
            "connected_at": status.get("connected_at"),
        })
    return {"integrations": result}

@router.get("/client/active-agents")
def client_active_agents(user: dict = Depends(get_current_user)):
    """Execute client active agents."""
    client_id = user.get("client_id") or user["id"]
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT suggested_agents, status, admin_notes
            FROM agent_requests
            WHERE client_id = %s AND status = 'approved'
            ORDER BY updated_at DESC
        """, (client_id,))
        rows = cur.fetchall()
        cur.close()  
    if not rows:
        return {"active_agents": [], "status": "pending"}

    merged_agents = []
    seen = set()
    for row in rows:
        suggested = row[0] if row[0] else []
        for agent in suggested:
            agent_key = (agent or {}).get("agent")
            if not agent_key or agent_key in seen:
                continue
            seen.add(agent_key)
            merged_agents.append(agent)

    return {
        "active_agents": merged_agents,
        "status": "approved",
        "admin_notes": rows[0][2],
    }


@router.post("/client/requests/new-agent")
def client_request_new_agent(
    body: ClientAgentRequest,
    user: dict = Depends(get_current_user)
):
    """Execute client request new agent."""
    agent_key = (body.agent_key or "").strip()
    if agent_key not in AGENT_LABEL_MAP:
        raise HTTPException(status_code=400, detail="Unsupported agent key")

    client_id = user.get("client_id") or user["id"]
    label = AGENT_LABEL_MAP[agent_key]

    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute("""
            SELECT suggested_agents
            FROM agent_requests
            WHERE client_id = %s AND status = 'approved'
            ORDER BY updated_at DESC
        """, (client_id,))
        approved_rows = cur.fetchall()
        approved_agents = []
        for approved_row in approved_rows:
            approved_agents.extend(approved_row[0] if approved_row and approved_row[0] else [])
        if any((a or {}).get("agent") == agent_key for a in approved_agents):
            cur.close()
            raise HTTPException(status_code=409, detail=f"{label} is already acquired")

        cur.execute("""
            SELECT 1
            FROM agent_requests
            WHERE client_id = %s AND status = 'pending' AND agent_type = %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (client_id, agent_key))
        if cur.fetchone():
            cur.close()
            raise HTTPException(status_code=409, detail=f"{label} request is already pending")

        suggested_agents = [
            {
                "agent": agent_key,
                "label": label,
                "reason": "Requested by client from New Agent page",
                "priority": "medium",
            }
        ]

        cur.execute("""
            INSERT INTO agent_requests
            (client_id, use_case, agent_type, business_type, scale, integrations, status, admin_notes, suggested_agents)
            VALUES (%s, %s, %s, '', '', '', 'pending', %s, %s)
            RETURNING id
        """, (
            client_id,
            f"Client requested {label}",
            agent_key,
            body.note,
            json.dumps(suggested_agents),
        ))
        row = cur.fetchone()
        cur.close()

    request_id = str(row[0]) if row else ""
    log_action(
        client_id=client_id,
        agent_name="onboarding",
        intent="new_agent_request",
        input_text=agent_key,
        output={"request_id": request_id, "agent": agent_key},
        status="success",
    )

    return {
        "status": "submitted",
        "request_id": request_id,
        "agent": agent_key,
        "label": label,
    }

@router.patch("/client/config")
def update_client_config(body:ClientConfigUpdate, user:dict = Depends(get_current_user)):
    """Update client config."""
    client_id = user.get("client_id") or user["id"]
    try:
        from config.client_config import get_client_config, save_client_config
        config = get_client_config(client_id)
        if body.expense_approval_threshold is not None:
            if body.expense_approval_threshold < 0:
                raise HTTPException(status_code=400, detail="Threshold must be positive")
            config["expense_approval_threshold"] = body.expense_approval_threshold
        if body.approve_email is not None:
            config["approve_email"] = body.approve_email
        save_client_config(client_id,config)
        return {
            "status" : "updated", 
            "config" : {
                "expense_approval_threshold" : config.get("expense_approval_threshold"),
            "approve_email": config.get("approve_email"),                
            }}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="config update failed")
    
@router.get("/client/config")
def get_config(user: dict = Depends(get_current_user)):
    """Return config."""
    client_id = user.get("client_id") or user["id"]
    try:
        from config.client_config import get_client_config
        config = get_client_config(client_id)
        return {
            "expense_approval_threshold": config.get("expense_approval_threshold", 500),
            "approve_email": config.get("approve_email", ""),
            "active_agents": config.get("active_agents", []),
            "channels": config.get("channels", []),
        }
    except Exception:
        raise HTTPException(status_code=404, detail="Config not found") 

@router.get("/admin/dashboard")
def admin_dashboard(admin: dict = Depends(require_admin)):
    """Execute admin dashboard."""
    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM clients WHERE active = TRUE")
        active_clients = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM clients")
        total_clients = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM agent_requests WHERE status = 'pending'")
        pending = cur.fetchone()[0]

        cur.execute("""
            SELECT agent_name, intent, status, created_at
            FROM audit_logs
            WHERE agent_name NOT IN ('auth', 'onboarding', 'integrations')
            AND agent_name NOT LIKE 'webhook:%'
            ORDER BY created_at DESC LIMIT 10
        """)
        recent = cur.fetchall()

        cur.execute("""
            SELECT COUNT(*),
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END)
            FROM audit_logs
            WHERE created_at > NOW() - INTERVAL '24 hours'
            AND agent_name NOT LIKE 'webhook:%'
            AND agent_name NOT IN ('auth', 'onboarding', 'integrations')
        """)
        total_24h, success_24h = cur.fetchone()

        cur.execute("""
            SELECT ar.id, ar.client_id, ar.agent_type, ar.status, ar.created_at,
                   c.name as company, u.name as user_name, ar.suggested_agents
            FROM agent_requests ar
            LEFT JOIN clients c ON c.client_id = ar.client_id
            LEFT JOIN users u ON u.client_id = ar.client_id
            ORDER BY ar.created_at DESC LIMIT 5
        """)
        recent_requests = cur.fetchall()

        cur.execute("""
            SELECT COUNT(*) FROM audit_logs
            WHERE status = 'error'
            AND created_at > NOW() - INTERVAL '24 hours'
        """)
        error_count = cur.fetchone()[0]

        cur.close()

    success_rate = round((success_24h / total_24h * 100), 2) if total_24h else 0

    alerts = []
    if pending > 0:
        alerts.append({"type": "pending", "message": f"{pending} pending requests", "detail": "Requires review"})
    if error_count > 0:
        alerts.append({"type": "error", "message": f"{error_count} agent errors in last 24h", "detail": "Check monitoring"})

    return {
        "active_clients": active_clients,
        "total_clients": total_clients,
        "pending_requests": pending,
        "success_rate_24h": success_rate,
        "total_requests_24h": total_24h,
        "recent_activity": [
            {
                "agent": r[0],
                "display_type": AGENT_TYPE_MAP.get(r[0], r[0]),
                "intent": r[1],
                "status": r[2],
                "at": str(r[3])
            }
            for r in recent
        ],
        "recent_requests": [
            {
                "id": str(r[0]),
                "client_name": r[6] or "-",
                "company": r[5] or "-",
                "display_type": _agents_label(r[7]),
                "status": r[3],
                "date": str(r[4]),
            } for r in recent_requests
        ],
        "alerts": alerts,
    }

@router.get("/admin/requests")
def admin_requests(
    status: Optional[str] = None,
    admin: dict = Depends(require_admin)
):
    """Execute admin requests."""
    with get_conn() as conn:
        cur = conn.cursor()
        if status:
            cur.execute("""
                SELECT ar.id, ar.client_id, ar.agent_type,
                    ar.status, ar.admin_notes, ar.suggested_agents, ar.created_at,
                    c.name as company, u.name as user_name
                FROM agent_requests ar
                LEFT JOIN clients c ON c.client_id = ar.client_id
                LEFT JOIN users u ON u.client_id = ar.client_id
                WHERE ar.status = %s
                ORDER BY ar.created_at DESC
            """, (status,))
        else:
            cur.execute("""
                SELECT ar.id, ar.client_id, ar.agent_type,
                    ar.status, ar.admin_notes, ar.suggested_agents, ar.created_at,
                    c.name as company, u.name as user_name
                FROM agent_requests ar
                LEFT JOIN clients c ON c.client_id = ar.client_id
                LEFT JOIN users u ON u.client_id = ar.client_id
                ORDER BY ar.created_at DESC
            """)
        rows = cur.fetchall()
        cur.close()

    return {"requests": [
        {
            "id": r[0],
            "client_id": r[1],
            "client_name": r[8] or "-",
            "company": r[7] or "-",
            "agent_type": r[2],
            "display_type": _agents_label(r[5]),
            "status": r[3],
            "admin_notes": r[4],
            "suggested_agents": r[5],
            "created_at": str(r[6])
        } for r in rows
    ]}


class RequestAction(BaseModel):
    """Represent the RequestAction component and its related behavior."""
    admin_notes: Optional[str] = None


@router.patch("/admin/requests/{request_id}/approve")
def approve_request(
    request_id: UUID,
    body: RequestAction,
    admin: dict = Depends(require_admin)
):
    """Execute approve request."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE agent_requests
            SET status = 'approved', admin_notes = %s, updated_at = NOW()
            WHERE id = %s RETURNING client_id, suggested_agents
        """, (body.admin_notes, str(request_id)))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Request not found")
        client_id, suggested_agents = row
        cur.execute(
            "UPDATE clients SET active = TRUE WHERE client_id = %s",
            (client_id,)
        )
        if suggested_agents:
            new_keys = [
                a["agent"] for a in suggested_agents
                if isinstance(a, dict) and a.get("agent")
            ]

            cur.execute(
                "SELECT config FROM client_configs WHERE client_id = %s",
                (client_id,)
            )
            config_row = cur.fetchone()

            if config_row:
                config = config_row[0]
                existing = config.get("active_agents", [])
                existing_keys = [
                    a["agent"] if isinstance(a, dict) else a
                    for a in existing
                ]
                for key in new_keys:
                    if key not in existing_keys:
                        existing_keys.append(key)

                config["active_agents"] = existing_keys
                cur.execute(
                    "UPDATE client_configs SET config = %s, updated_at = NOW() WHERE client_id = %s",
                    (json.dumps(config), client_id)
                )
            else:
                new_config = {"active_agents": new_keys}
                cur.execute(
                    "INSERT INTO client_configs (client_id, config) VALUES (%s, %s)",
                    (client_id, json.dumps(new_config))
                )

        conn.commit()
        cur.close()

    try:
        from core.intelligence_loop import enrich_from_onboarding
        enrich_from_onboarding(client_id)
    except Exception as _enrich_exc:
        import logging as _log
        _log.getLogger(__name__).warning(
            "enrich_from_onboarding failed (non-fatal) client=%s: %s", client_id, _enrich_exc
        )

    return {"status": "approved", "client_id": client_id}


@router.patch("/admin/requests/{request_id}/reject")
def reject_request(
    request_id: UUID,
    body: RequestAction,
    admin: dict = Depends(require_admin)
):
    """Execute reject request."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE agent_requests
            SET status = 'rejected', admin_notes = %s, updated_at = NOW()
            WHERE id = %s RETURNING client_id
        """, (body.admin_notes, str(request_id)))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Request not found")
        cur.close()
    return {"status": "rejected"}


@router.get("/admin/clients")
def admin_clients(admin: dict = Depends(require_admin)):
    """Execute admin clients."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                c.client_id, c.name, c.active, c.channel_config, c.created_at,
                u.email, u.name as user_name,
                ar.suggested_agents
            FROM clients c
            LEFT JOIN users u ON u.client_id = c.client_id
            LEFT JOIN LATERAL (
                SELECT suggested_agents FROM agent_requests
                WHERE client_id = c.client_id AND status = 'approved'
                ORDER BY updated_at DESC LIMIT 1
            ) ar ON TRUE
            ORDER BY c.created_at DESC
        """)
        rows = cur.fetchall()
        cur.close()
    return {"clients": [
        {
            "id": r[0],
            "client_id": r[0],
            "name": r[6] or r[1],
            "company": r[1],
            "email": r[5] or "",
            "active": r[2],
            "channels": r[3],
            "created_at": str(r[4]),
            "agents_label": _agents_label(r[7]),
        } for r in rows
    ]}

@router.get("/admin/monitoring")
def admin_monitoring(admin: dict = Depends(require_admin)):
    """Execute admin monitoring."""
    agent_keys = list(AGENT_LABEL_MAP.keys())
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
        SELECT 
            agent_name,
            COUNT(*) as total,
            SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success,
            MAX(created_at) as last_active,
            COUNT(DISTINCT client_id) as client_count
        FROM audit_logs
        WHERE agent_name = ANY(%s)
        GROUP BY agent_name
        ORDER BY total DESC
    """, (agent_keys,))
        rows = cur.fetchall()
        cur.close()

    stats_by_agent = {
        r[0]: {
            "total_requests": int(r[1] or 0),
            "success_count": int(r[2] or 0),
            "last_active": r[3],
            "client_count": int(r[4] or 0),
        }
        for r in rows
    }

    agents = []
    for agent_key in agent_keys:
        stats = stats_by_agent.get(agent_key)
        total_requests = stats["total_requests"] if stats else 0
        success_count = stats["success_count"] if stats else 0
        last_active = stats["last_active"] if stats else None
        client_count = stats["client_count"] if stats else 0

        agents.append({
            "agent": agent_key,
            "label": AGENT_LABEL_MAP.get(agent_key, agent_key),
            "display_type": AGENT_TYPE_MAP.get(agent_key, agent_key),
            "total_requests": total_requests,
            "success_rate": round((success_count / total_requests * 100), 2) if total_requests else 0,
            "last_active": str(last_active) if last_active else None,
            "status": "active" if total_requests > 0 else "paused",
            "client_count": client_count,
        })

    return {"agents": agents}


@router.get("/admin/logs")
def admin_logs(
    severity: Optional[str] = None,
    admin: dict = Depends(require_admin)
):
    """Execute admin logs."""
    with get_conn() as conn:
        cur = conn.cursor()
        if severity and severity.lower() not in ("all",):
            cur.execute("""
                SELECT client_id, agent_name, intent, status, error_ref, created_at
                FROM audit_logs WHERE status = %s
                ORDER BY created_at DESC LIMIT 100
            """, (severity.lower(),))
        else:
            cur.execute("""
                SELECT client_id, agent_name, intent, status, error_ref, created_at
                FROM audit_logs ORDER BY created_at DESC LIMIT 100
            """)
        rows = cur.fetchall()
        cur.close()

    def to_severity(status: str) -> str:
        """Execute to severity."""
        if status in ("success",):
            return "Info"
        if status in ("escalate", "duplicate"):
            return "Warning"
        if status in ("error", "dead_letter"):
            return "Error"
        return "Info"

    return {"logs": [
        {
            "client_id": r[0],
            "agent": r[1],
            "intent": r[2],
            "status": r[3],
            "ref": r[4],
            "at": str(r[5]),
            "severity": to_severity(r[3]),
            "message": f"{r[1]} handled {r[2]} — {r[3]}",
            "source": r[1],
        } for r in rows
    ]}
    
@router.get("/client/system-status")
def client_system_status():
    """Execute client system status."""
    raw = _redis.get("admin:settings:toggles")
    if not raw:
        return {"maintenance_mode": False, "maintenance_until": None}
    data = json.loads(str(raw))
    return {
        "maintenance_mode": data.get("maintenance_mode", False),
        "maintenance_until": data.get("maintenance_until"),
    }


@router.get("/client/system-status/stream")
async def system_status_stream():
    """Execute system status stream."""
    from fastapi.responses import StreamingResponse
    import asyncio

    async def event_generator():
        """Execute event generator."""
        last_state = None
        while True:
            try:
                raw = _redis.get("admin:settings:toggles")
                data = json.loads(str(raw)) if raw else {}
                state = {
                    "maintenance_mode": data.get("maintenance_mode", False),
                    "maintenance_until": data.get("maintenance_until"),
                }
                if state != last_state:
                    last_state = state
                    yield f"data: {json.dumps(state)}\n\n"
                else:
                    yield ": heartbeat\n\n"
            except Exception:
                yield ": error\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/admin/settings/toggles")
def get_toggles(admin: dict = Depends(require_admin)):
    """Return toggles."""
    raw = _redis.get("admin:settings:toggles")
    defaults = {"maintenance_mode": False}
    if raw:
        defaults.update(json.loads(str(raw)))
    return defaults

@router.patch("/admin/settings/toggles")
def update_toggles(body: SystemTogglesRequest, admin: dict = Depends(require_admin)):
    """Update toggles."""
    raw = _redis.get("admin:settings:toggles")
    current = json.loads(str(raw)) if raw else {}
    if body.maintenance_mode is not None:
        current["maintenance_mode"] = body.maintenance_mode
        if body.maintenance_mode and body.maintenance_minutes:
            from datetime import datetime, timezone, timedelta
            until = datetime.now(timezone.utc) + timedelta(minutes=body.maintenance_minutes)
            current["maintenance_until"] = until.isoformat()
        elif not body.maintenance_mode:
            current.pop("maintenance_until", None)
    elif body.maintenance_minutes is not None and current.get("maintenance_mode"):
        from datetime import datetime, timezone, timedelta
        until = datetime.now(timezone.utc) + timedelta(minutes=body.maintenance_minutes)
        current["maintenance_until"] = until.isoformat()
    _redis.set("admin:settings:toggles", json.dumps(current))
    return current

@router.post("/client/agent/{agent_name}/pause")
def pause_agent(agent_name: str, user: dict = Depends(get_current_user)):
    """Execute pause agent."""
    client_id = user.get("client_id") or user["id"]
    _redis.set(f"agent:paused:{client_id}:{agent_name}", "1")
    log_action(client_id, agent_name, "pause", agent_name, {}, "success")
    return {"status": "paused", "agent": agent_name}


@router.post("/client/agent/{agent_name}/resume")
def resume_agent(agent_name: str, user: dict = Depends(get_current_user)):
    """Execute resume agent."""
    client_id = user.get("client_id") or user["id"]
    _redis.delete(f"agent:paused:{client_id}:{agent_name}")
    log_action(client_id, agent_name, "resume", agent_name, {}, "success")
    return {"status": "resumed", "agent": agent_name}


@router.get("/client/activity-feed")
def activity_feed(user: dict = Depends(get_current_user)):
    """Execute activity feed."""
    client_id = user.get("client_id") or user["id"]
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT agent_name, intent, status, error_ref, created_at
            FROM audit_logs
            WHERE client_id = %s
            AND agent_name NOT LIKE 'webhook:%%'
            AND agent_name NOT IN ('auth', 'onboarding', 'integrations')
            ORDER BY created_at DESC LIMIT 20
        """, (client_id,))
        rows = cur.fetchall()
        cur.close()
    return {"feed": [
        {
            "agent": r[0],
            "intent": r[1],
            "status": r[2],
            "ref": r[3],
            "at": str(r[4]),
            "message": f"{r[0]} processed {r[1]} — {r[2]}",
        } for r in rows
    ]}
    
@router.get("/client/session-info")
def session_info(user: dict = Depends(get_current_user)):
    """Execute session info."""
    from webhooks.integrations import _get_status
    client_id = user.get("client_id") or user["id"]
    from config.client_config import get_client_config
    try:
        config = get_client_config(client_id)
    except Exception:
        config = {}
    connected = []
    for provider in ["xero", "quickbooks", "google", "outlook", "stripe", "paypal"]:
        status = _get_status(client_id, provider)
        if status.get("connected"):
            connected.append(provider)
    return {
        "tenant": config.get("name", client_id),
        "region": config.get("region", "unknown"),
        "environment": settings.env.upper(),
        "encryption": "AES-256-GCM at rest + transit",
        "connected_systems": connected,
    }
    
@router.get("/client/monitoring")
def client_monitoring(user: dict = Depends(get_current_user)):
    """Execute client monitoring."""
    client_id = user.get("client_id") or user["id"]
    agent_labels = {
        "a01_invoice": "Invoice Agent",
        "a02_expense": "Expense Agent",
        "a03_admin": "Admin Agent",
        "a04_payment": "Payment Agent",
    }
    with get_conn() as conn:
        cur = conn.cursor()
        
        cur.execute("""
            SELECT suggested_agents FROM agent_requests
            WHERE client_id = %s AND status = 'approved'
            ORDER BY updated_at DESC
        """, (client_id,))
        agent_rows = cur.fetchall()
        approved_agents = []
        seen_agent_keys = set()
        for row in agent_rows:
            suggested = row[0] if row and row[0] else []
            for agent in suggested:
                agent_key = (agent or {}).get("agent")
                if not agent_key or agent_key in seen_agent_keys:
                    continue
                seen_agent_keys.add(agent_key)
                approved_agents.append(agent)

        cur.execute("""
            SELECT 
                agent_name,
                COUNT(*) as total,
                SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success,
                MAX(created_at) as last_active
            FROM audit_logs
            WHERE client_id = %s
            AND agent_name IN ('a01_invoice','a02_expense','a03_admin','a04_payment')
            GROUP BY agent_name
        """, (client_id,))
        rows = cur.fetchall()
        cur.close()

    stats_by_agent = {
        r[0]: {
            "total_requests": r[1],
            "success_rate": round((r[2] / r[1] * 100), 2) if r[1] else 0,
            "last_active": str(r[3]),
        }
        for r in rows
    }

    result = []
    for a in approved_agents:
        agent_name = a.get("agent", "")
        if not agent_name:
            continue
        stats = stats_by_agent.get(agent_name, {})
        result.append({
            "agent": agent_name,
            "label": agent_labels.get(agent_name, a.get("label", "")),
            "display_type": AGENT_TYPE_MAP.get(agent_name, a.get("label", "")),
            "total_requests": stats.get("total_requests", 0),
            "success_rate": stats.get("success_rate", 0),
            "last_active": stats.get("last_active", None),
            "status": "active" if not _redis.exists(f"agent:paused:{client_id}:{agent_name}") else "paused",
        })

    return {"agents": result}