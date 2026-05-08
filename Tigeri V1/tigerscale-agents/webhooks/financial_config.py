from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from auth.deps import get_current_user, require_admin
from config.client_config import (
    _DEFAULT_FINANCIAL_CONFIG,
    get_client_financial_config,
    register_employee,
    save_client_financial_config,
)
from security.audit import log_action

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/client/financial-config", tags=["financial-config"])


class FinancialConfigUpdate(BaseModel):
    """Fields the frontend can update. All optional — partial updates supported."""

    base_currency:          Optional[str]   = Field(None, description="ISO 4217 e.g. SGD, USD")
    tax_rate:               Optional[float] = Field(None, ge=0.0, le=1.0, description="0.09 = 9%")
    tax_name:               Optional[str]   = Field(None, description="GST, VAT, etc.")
    tax_inclusive:          Optional[bool]  = Field(None, description="Are receipt amounts tax-inclusive?")
    fx_enabled:             Optional[bool]  = Field(None, description="Enable FX conversion to base currency")
    auto_approve_expenses:  Optional[bool]  = Field(None, description="Auto-approve all captured expenses")
    expense_categories:     Optional[list[str]] = Field(None, description="Allowed expense categories")
    category_code_map:      Optional[dict[str, str]] = Field(
        None, description="HR claim code → expense category. e.g. {'Wst-gc00': 'logistics'}"
    )
    employee_map:           Optional[dict[str, dict]] = Field(
        None, description="Sender key → employee record. Key: '<channel>:<sender_id>'"
    )
    country:                Optional[str]   = Field(None, description="Country name e.g. Singapore, India, Australia")
    timezone:               Optional[str]   = Field(None, description="IANA timezone e.g. Asia/Singapore, Asia/Kolkata")

    @field_validator("base_currency")
    @classmethod
    def currency_uppercase(cls, v: Optional[str]) -> Optional[str]:
        return v.upper() if v else v

    @field_validator("expense_categories")
    @classmethod
    def categories_not_empty(cls, v: Optional[list]) -> Optional[list]:
        if v is not None and len(v) == 0:
            raise ValueError("expense_categories cannot be empty")
        return v

    @field_validator("timezone")
    @classmethod
    def timezone_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        _KNOWN_ABBRS = {
            "UTC", "GMT", "IST", "EST", "EDT", "PST", "PDT",
            "CST", "CDT", "MST", "MDT", "SGT", "GST", "JST",
            "BST", "CET", "CEST", "AEST", "PKT", "BDT",
        }
        if "/" not in v and v.upper() not in _KNOWN_ABBRS:
            raise ValueError(f"Invalid timezone '{v}' — use IANA format like Asia/Singapore or abbreviation like SGT")
        return v.strip()


class EmployeeRegisterRequest(BaseModel):
    """Register a Telegram/WhatsApp sender as a named employee."""
    channel:     str = Field(..., description="telegram or whatsapp")
    sender:      str = Field(..., description="Chat ID or phone number")
    name:        str = Field(..., description="Full name e.g. Aaron Low")
    employee_id: str = Field("", description="HR employee ID e.g. E024")
    dept:        str = Field("", description="Department e.g. Operations")


class EmployeeRemoveRequest(BaseModel):
    channel: str
    sender:  str



@router.get("")
def get_financial_config(user: dict = Depends(get_current_user)) -> dict:
    """
    Return the current financial config for the authenticated client.

    Frontend usage: populate the accounting settings page on load.
    """
    client_id = user.get("client_id") or user["id"]
    try:
        config = get_client_financial_config(client_id)

        employee_list = [
            {
                "key":         k,
                "channel":     k.split(":")[0] if ":" in k else "",
                "sender":      k.split(":", 1)[1] if ":" in k else k,
                "name":        v.get("name", ""),
                "employee_id": v.get("id", ""),
                "dept":        v.get("dept", ""),
            }
            for k, v in config.get("employee_map", {}).items()
        ]
        return {
            "base_currency":         config.get("base_currency", "USD"),
            "tax_rate":              config.get("tax_rate", 0.0),
            "tax_name":              config.get("tax_name", "TAX"),
            "tax_inclusive":         config.get("tax_inclusive", False),
            "fx_enabled":            config.get("fx_enabled", False),
            "auto_approve_expenses": config.get("auto_approve_expenses", True),
            "expense_categories":    config.get("expense_categories", []),
            "category_code_map":     config.get("category_code_map", {}),
            "employees":             employee_list,
            "country":               config.get("country", ""),
            "timezone":              config.get("timezone", ""),
        }
    except Exception as exc:
        logger.error("get_financial_config failed client=%s: %s", client_id, exc)
        raise HTTPException(status_code=500, detail="Could not load financial config")



@router.put("")
def update_financial_config(
    body: FinancialConfigUpdate,
    user: dict = Depends(get_current_user),
) -> dict:
    """
    Partial update of financial config. Only provided fields are updated.

    Frontend usage: save button on accounting settings page.

    Example payload:
    {
        "base_currency": "SGD",
        "tax_rate": 0.09,
        "tax_name": "GST",
        "tax_inclusive": true,
        "fx_enabled": true,
        "auto_approve_expenses": true,
        "country": "Singapore",
        "timezone": "Asia/Singapore",
        "category_code_map": {
            "Wst-gc00": "logistics",
            "Meals-00": "staff"
        }
    }
    """
    client_id = user.get("client_id") or user["id"]
    try:
        updates: dict = {}
        data = body.model_dump(exclude_none=True)

        data.pop("employee_map", None)

        for key, value in data.items():
            updates[key] = value

        if not updates:
            raise HTTPException(status_code=400, detail="No fields provided to update")

        save_client_financial_config(client_id, updates)

        if "timezone" in updates:
            try:
                from core.conversation import save_client_timezone
                save_client_timezone(client_id, updates["timezone"])
            except Exception as tz_exc:
                logger.warning("timezone cache warm failed client=%s: %s", client_id, tz_exc)

        log_action(
            client_id, "financial_config", "update",
            str(list(updates.keys())), updates, "success",
        )
        return {"status": "updated", "fields": list(updates.keys())}

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("update_financial_config failed client=%s: %s", client_id, exc)
        raise HTTPException(status_code=500, detail="Could not save financial config")



@router.post("/employee")
def add_employee(
    body: EmployeeRegisterRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """
    Map a Telegram chat ID or WhatsApp number to a named employee.

    Frontend usage: employee management table — "Add staff member" form.

    Example payload:
    {
        "channel": "telegram",
        "sender": "123456789",
        "name": "Aaron Low",
        "employee_id": "E024",
        "dept": "Operations"
    }
    """
    client_id = user.get("client_id") or user["id"]
    try:
        register_employee(
            client_id=client_id,
            channel=body.channel,
            sender=body.sender,
            name=body.name,
            employee_id=body.employee_id,
            dept=body.dept,
        )
        log_action(
            client_id, "financial_config", "register_employee",
            f"{body.channel}:{body.sender}",
            {"name": body.name, "employee_id": body.employee_id, "dept": body.dept},
            "success",
        )
        return {
            "status":  "registered",
            "key":     f"{body.channel}:{body.sender}",
            "name":    body.name, 
        }
    except Exception as exc:
        logger.error("add_employee failed client=%s: %s", client_id, exc)
        raise HTTPException(status_code=500, detail="Could not register employee")




@router.delete("/employee")
def remove_employee(
    body: EmployeeRemoveRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """
    Remove a sender  employee mapping.

    Frontend usage: delete button in employee management table.
    """
    client_id = user.get("client_id") or user["id"]
    try:
        fc  = get_client_financial_config(client_id)
        emp = fc.get("employee_map", {})
        key = f"{body.channel}:{body.sender}"

        if key not in emp:
            raise HTTPException(status_code=404, detail=f"Employee mapping '{key}' not found")

        del emp[key]
        save_client_financial_config(client_id, {"employee_map": emp})

        log_action(client_id, "financial_config", "remove_employee", key, {}, "success")
        return {"status": "removed", "key": key}

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("remove_employee failed client=%s: %s", client_id, exc)
        raise HTTPException(status_code=500, detail="Could not remove employee mapping")




@router.get("/defaults")
def get_defaults() -> dict:
    """
    Return the default financial config schema with descriptions.

    Frontend usage: onboarding wizard — pre-fill accounting settings step.
    No auth required (public schema reference).
    """
    return {
        "defaults":     _DEFAULT_FINANCIAL_CONFIG,
        "field_meta": {
            "base_currency":         {"label": "Base Currency",          "type": "text",   "placeholder": "SGD"},
            "tax_rate":              {"label": "Tax Rate",               "type": "number", "placeholder": "0.09 for 9%"},
            "tax_name":              {"label": "Tax Name",               "type": "text",   "placeholder": "GST"},
            "tax_inclusive":         {"label": "Amounts include tax",    "type": "toggle", "default": False},
            "fx_enabled":            {"label": "Enable FX conversion",   "type": "toggle", "default": False},
            "auto_approve_expenses": {"label": "Auto-approve expenses",  "type": "toggle", "default": True},
            "expense_categories":    {"label": "Expense categories",     "type": "tags",   "default": []},
            "category_code_map":     {"label": "HR claim code mapping",  "type": "keyval", "default": {}},
            "country":               {"label": "Country",                "type": "text",     "placeholder": "Singapore"},
            "timezone":              {"label": "Timezone",               "type": "timezone", "placeholder": "Asia/Singapore"},
        },
    }


@router.put("/admin/{client_id}")
def admin_set_financial_config(
    client_id: str,
    body: FinancialConfigUpdate,
    admin: dict = Depends(require_admin),
) -> dict:
    """
    Admin endpoint to set financial config for any client.
    Used during client onboarding / provisioning.

    Example — Codigo setup:
    PUT /api/v1/financial-config/admin/codigo_client_id
    {
        "base_currency": "SGD",
        "tax_rate": 0.09,
        "tax_name": "GST",
        "tax_inclusive": true,
        "fx_enabled": true,
        "country": "Singapore",
        "timezone": "Asia/Singapore",
        "category_code_map": {
            "Wst-gc00": "logistics",
            "Meals-00": "staff",
            "Ent-00":   "marketing"
        }
    }
    """
    try:
        updates = body.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields provided")

        save_client_financial_config(client_id, updates)

        if "timezone" in updates:
            try:
                from core.conversation import save_client_timezone
                save_client_timezone(client_id, updates["timezone"])
            except Exception as tz_exc:
                logger.warning("timezone cache warm failed client=%s: %s", client_id, tz_exc)

        log_action(
            client_id, "financial_config", "admin_update",
            str(list(updates.keys())), updates, "success",
        )
        return {"status": "updated", "client_id": client_id, "fields": list(updates.keys())}

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("admin_set_financial_config failed client=%s: %s", client_id, exc)
        raise HTTPException(status_code=500, detail="Could not save financial config")


@router.get("/admin/{client_id}")
def admin_get_financial_config(
    client_id: str,
    admin: dict = Depends(require_admin),
) -> dict:
    """Admin: get full financial config for any client including raw employee_map."""
    try:
        return get_client_financial_config(client_id)
    except Exception as exc:
        logger.error("admin_get_financial_config failed client=%s: %s", client_id, exc)
        raise HTTPException(status_code=500, detail="Could not load financial config")