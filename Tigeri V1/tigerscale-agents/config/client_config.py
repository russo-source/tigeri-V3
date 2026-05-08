"""Contain client config backend logic."""
from config.db_pool import get_conn
import json
import logging

logger = logging.getLogger(__name__)


_DEFAULT_FINANCIAL_CONFIG: dict = {
    "base_currency":        "USD",
    "tax_rate":             0.0,       # e.g. 0.09 for SG GST 9%
    "tax_name":             "TAX",     # e.g. "GST", "VAT"
    "tax_inclusive":        True,     # True = receipt amounts include tax 
    "fx_enabled":           True,     # True = convert non-base-currency 
    "pdf_enabled":          True,
    "auto_approve_expenses": True,
    "accounting_platform":  "quickbooks",   # or "xero"
    "expense_categories": [
        "supplier", "logistics", "staff", "ops", "travel", "marketing",
    ],
    # QuickHR / HR-system claim code → internal category
    # e.g. {"Wst-gc00": "logistics", "Meals-00": "staff"}
    "category_code_map":    {},
    # sender key → employee record
    # key format: "<channel>:<sender_id>"  e.g. "telegram:123456789"
    # value: {"name": "Aaron Low", "id": "E024", "dept": "Operations"}
    "employee_map":         {},
    "country":               "",  
    "timezone":              "", 
}

def get_client_config(client_id: str) -> dict:
    """Return client config."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT config FROM client_configs WHERE client_id = %s", (client_id,))
        row = cur.fetchone()
        cur.close()
    if not row:
        return {}
    return row[0] if isinstance(row[0], dict) else json.loads(row[0])


def save_client_config(client_id: str, config: dict) -> None:
    """Execute save client config."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO client_configs (client_id, config)
            VALUES (%s, %s)
            ON CONFLICT (client_id) DO UPDATE SET config = EXCLUDED.config, updated_at = NOW()
        """, (client_id, json.dumps(config)))
        cur.close()


def get_all_client_ids() -> list[str]:
    """Return all client ids."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT client_id FROM client_configs ORDER BY client_id")
            rows = cur.fetchall()
            cur.close()
        return [r[0] for r in rows]
    except Exception:
        return []

def get_client_financial_config(client_id: str) -> dict:
    """
    Return the financial config for a client with safe defaults.
    Merges client-specific overrides on top of _DEFAULT_FINANCIAL_CONFIG.
    Never raises — always returns a usable dict.
    """
    try:
        raw = get_client_config(client_id)
        financial = raw.get("financial", {})
        return {**_DEFAULT_FINANCIAL_CONFIG, **financial}
    except Exception as exc:
        logger.warning("get_client_financial_config failed client=%s: %s", client_id, exc)
        return dict(_DEFAULT_FINANCIAL_CONFIG)


def save_client_financial_config(client_id: str, financial: dict) -> None:
    """
    Upsert only the 'financial' key inside client_configs.config.
    All other config keys are left untouched.
    """
    try:
        raw = get_client_config(client_id)
    except Exception:
        raw = {}
    existing = raw.get("financial", {})
    raw["financial"] = {**_DEFAULT_FINANCIAL_CONFIG, **existing, **financial}
    save_client_config(client_id, raw)


def get_employee_from_sender(client_id: str, sender: str, channel: str = "telegram") -> dict:
    """
    Resolve a sender (Telegram chat ID / WhatsApp number) to an employee record.
    Returns {} if not mapped — caller should fall back to sender ID as label.

    employee_map key format: "<channel>:<sender>"
    e.g. "telegram:123456789" or "whatsapp:6591234567"
    """
    try:
        fc = get_client_financial_config(client_id)
        key = f"{channel}:{sender}"
        return fc.get("employee_map", {}).get(key, {})
    except Exception as exc:
        logger.warning("get_employee_from_sender failed client=%s: %s", client_id, exc)
        return {}


def register_employee(
    client_id: str,
    channel: str,
    sender: str,
    name: str,
    employee_id: str = "",
    dept: str = "",
) -> None:
    """
    Add or update an employee mapping for a sender.
    Safe to call multiple times — upserts in place.
    """
    try:
        fc = get_client_financial_config(client_id)
        employee_map = fc.get("employee_map", {})
        key = f"{channel}:{sender}"
        employee_map[key] = {"name": name, "id": employee_id, "dept": dept}
        save_client_financial_config(client_id, {"employee_map": employee_map})
    except Exception as exc:
        logger.error("register_employee failed client=%s: %s", client_id, exc)



# Category / claim code resolution
def resolve_category_from_code(client_id: str, claim_code: str) -> str | None:
    """
    Map a QuickHR / HR-system claim code to an internal expense category.
    Returns None if no mapping — caller should fall back to LLM classification.
    """
    try:
        fc = get_client_financial_config(client_id)
        code_map = fc.get("category_code_map", {})
        code = claim_code.strip()
        return code_map.get(code) or code_map.get(code.lower())
    except Exception as exc:
        logger.warning("resolve_category_from_code failed client=%s: %s", client_id, exc)
        return None



# Tax / GST utilities
def get_net_amount(client_id: str, gross_amount: float, tax_amount: float | None = None) -> float:
    """
    Return the net (ex-tax) amount to post to the accounting platform.

    Logic:
    - If client has tax_inclusive=True and tax_amount is provided → subtract it.
    - If client has tax_inclusive=True and no tax_amount → derive from tax_rate.
    - If tax_inclusive=False → return gross as-is (tax is additive, not embedded).
    """
    try:
        fc = get_client_financial_config(client_id)
        if not fc.get("tax_inclusive", False):
            return round(gross_amount, 2)

        if tax_amount is not None and tax_amount > 0:
            return round(gross_amount - tax_amount, 2)

        tax_rate = float(fc.get("tax_rate", 0.0))
        if tax_rate > 0:
            # gross = net * (1 + rate)  →  net = gross / (1 + rate)
            net = gross_amount / (1 + tax_rate)
            return round(net, 2)

        return round(gross_amount, 2)
    except Exception as exc:
        logger.warning("get_net_amount failed client=%s: %s", client_id, exc)
        return round(gross_amount, 2)


def get_tax_breakdown(client_id: str, gross_amount: float, tax_amount: float | None = None) -> dict:
    """
    Return full tax breakdown for display / audit.
    {net_amount, tax_amount, gross_amount, tax_rate, tax_name, tax_inclusive}
    """
    try:
        fc = get_client_financial_config(client_id)
        net = get_net_amount(client_id, gross_amount, tax_amount)
        derived_tax = round(gross_amount - net, 2)
        return {
            "gross_amount":  round(gross_amount, 2),
            "net_amount":    net,
            "tax_amount":    derived_tax,
            "tax_rate":      fc.get("tax_rate", 0.0),
            "tax_name":      fc.get("tax_name", "TAX"),
            "tax_inclusive": fc.get("tax_inclusive", False),
        }
    except Exception as exc:
        logger.warning("get_tax_breakdown failed client=%s: %s", client_id, exc)
        return {
            "gross_amount": gross_amount, "net_amount": gross_amount,
            "tax_amount": 0, "tax_rate": 0, "tax_name": "TAX", "tax_inclusive": False,
        }