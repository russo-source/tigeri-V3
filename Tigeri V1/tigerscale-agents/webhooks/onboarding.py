"""Contain onboarding backend logic."""
import json
import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from config.db_pool import get_conn
from memory.rag import embed_document
from security.audit import log_action
from auth.deps import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


class OnboardingSubmit(BaseModel):
    """Represent the OnboardingSubmit component and its related behavior."""
    submittedAt: str = ""
    progress: int = 0
    steps: list[Any] = []
    serverSavedAt: str = ""
    schemaVersion: int = 1
    client_id: str = ""
    email: str = ""

    class Config:
        """Represent the Config component and its related behavior."""
        extra = "allow"


class OnboardingPreview(BaseModel):
    """Represent the OnboardingPreview component and its related behavior."""
    steps: list[Any] = []

    class Config:
        """Represent the Config component and its related behavior."""
        extra = "allow"


@router.post("/onboarding/preview")
async def preview_onboarding(
    body: OnboardingPreview,
    user: dict = Depends(get_current_user)
):
    """Execute preview onboarding."""
    await asyncio.sleep(0.3)
    steps = body.steps or []

    if not steps:
        logger.warning("[preview] Empty steps for user %s", user.get("id"))
        return {
            "suggested_agents": [],
            "integration_platforms": [],
            "parsed_profile": {"industry": "", "integrations": "", "compliance": ""},
        }

    try:
        parsed = _parse_onboarding(steps)
    except Exception as e:
        logger.error("[preview] parse failed: %s", e)
        raise HTTPException(status_code=422, detail=f"Invalid data: {str(e)}")

    logger.info("[preview] parsed result: %s", json.dumps(parsed, default=str))

    if not any(parsed.values()):
        logger.warning("[preview] parse produced all-empty result — check field key mapping")
        return {
            "suggested_agents": [],
            "integration_platforms": [],
            "parsed_profile": {"industry": "", "integrations": "", "compliance": ""},
        }

    try:
        suggested, platforms = _suggest_agents(parsed)
    except Exception as e:
        logger.warning("[preview] suggest failed: %s — fallback", e)
        suggested = [{"agent": "a01_invoice", "label": "Invoice",
                      "reason": "Core cashflow automation.", "priority": "high"}]
        platforms = []

    return {
        "suggested_agents": suggested,
        "integration_platforms": platforms,
        "parsed_profile": {
            "industry": parsed.get("industry", ""),
            "integrations": parsed.get("integrations_summary", ""),
            "compliance": parsed.get("compliance_frameworks", ""),
        },
    }


@router.post("/onboarding/submit")
async def submit_onboarding(
    body: OnboardingSubmit,
    user: dict = Depends(get_current_user)
):
    """Execute submit onboarding."""
    client_id = user["id"]
    steps = body.steps or []

    try:
        parsed = _parse_onboarding(steps)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid onboarding data: {str(e)}")

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO clients (client_id, name, active)
                VALUES (%s, %s, FALSE)
                ON CONFLICT (client_id) DO UPDATE SET name = EXCLUDED.name
            """, (client_id, parsed.get("company_name", client_id)))
            cur.close()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to create client record")

    try:
        suggested, _ = _suggest_agents(parsed)
        logger.info("[submit] suggested agents: %s", suggested)
    except Exception as e:
        logger.error("[submit] _suggest_agents failed: %s", e)
        suggested = [{"agent": "a01_invoice", "label": "Invoice",
                      "reason": "Core cashflow automation.", "priority": "high"}]

    try:
        loop = asyncio.get_event_loop()
        await asyncio.gather(
            loop.run_in_executor(None, _write_client_yaml, client_id, parsed, suggested),
            loop.run_in_executor(None, _embed_onboarding, client_id, parsed, steps),
        )
    except Exception:
        pass

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, suggested_agents
                FROM agent_requests
                WHERE client_id = %s AND status = 'pending' AND agent_type = 'multi_agent'
                ORDER BY created_at DESC
                LIMIT 1
            """, (client_id,))
            existing = cur.fetchone()
            if existing:
                existing_id = str(existing[0])
                existing_suggested = existing[1] or suggested
                if isinstance(existing_suggested, str):
                    existing_suggested = json.loads(existing_suggested)
                cur.close()
                return {
                    "status": "submitted",
                    "client_id": client_id,
                    "request_id": existing_id,
                    "message": "Your setup is already submitted and under review.",
                    "suggested_agents": existing_suggested,
                }

            cur.execute("""
                INSERT INTO agent_requests
                (client_id, use_case, agent_type, business_type, scale, integrations, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending')
                RETURNING id
            """, (
                client_id,
                parsed.get("challenges", ""),
                "multi_agent",
                parsed.get("industry", ""),
                parsed.get("headcount", ""),
                parsed.get("integrations_summary", ""),
            ))
            row = cur.fetchone()
            request_id = str(row[0]) if row else None
            cur.close()
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to create agent request")

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE agent_requests
                SET suggested_agents = %s
                WHERE id = %s
            """, (json.dumps(suggested), request_id))
            cur.close()
    except Exception:
        pass

    try:
        from auth.repository import set_user_client_id
        set_user_client_id(user["id"], client_id)
    except Exception:
        pass

    log_action(
        client_id=client_id,
        agent_name="onboarding",
        intent="onboarding_submit",
        input_text=client_id,
        output={"status": "pending_review", "request_id": request_id},
        status="success",
    )

    return {
        "status": "submitted",
        "client_id": client_id,
        "request_id": request_id,
        "message": "Your setup is under review. You will be notified once approved.",
        "suggested_agents": suggested,
    }


def _parse_onboarding(steps: list[dict]) -> dict:
    """Parse onboarding."""
    parsed = {}
    all_fields: dict[str, object] = {}

    for step in steps:
        step_id = str(step.get("stepId", "")).strip()
        forms = step.get("forms", [])

        for form in forms:
            fields = form.get("fields", {})
            all_fields.update(fields)

            if step_id == "1":
                parsed["company_name"] = fields.get("company_name") or parsed.get("company_name", "")
                parsed["legal_entity_type"] = _extract_value(fields, "legal_entity_type")
                parsed["industry"] = _extract_value(fields, "primary_industry")
                parsed["region"] = _extract_value(fields, "headquarters_region")
                parsed["revenue"] = _extract_value(fields, "annual_revenue_usd")
                parsed["headcount"] = _extract_value(fields, "total_headcount")
                parsed["prior_ai_investment"] = _extract_value(fields, "prior_ai_investment")
                parsed["contact_name"] = fields.get("full_name", "")
                parsed["contact_role"] = fields.get("title_role", "")
                parsed["contact_email"] = fields.get("email", "")
                parsed["contact_phone"] = fields.get("telephone", "")
                use_case_keys = [
                    k for k, v in fields.items()
                    if isinstance(v, list) and v and k not in (
                        "legal_entity_type", "primary_industry", "headquarters_region",
                        "annual_revenue_usd", "total_headcount", "prior_ai_investment",
                    )
                ]
                parsed["use_cases"] = ", ".join(use_case_keys)

            elif step_id == "2":
                parsed["erp_system"] = fields.get("e_g_sap_s_4hana_oracle_fusion", "")
                parsed["erp_records"] = fields.get("e_g_2m_records", "")
                parsed["crm_system"] = fields.get("e_g_salesforce_hubspot", "")
                parsed["hris_system"] = fields.get("e_g_workday_bamboohr", "")
                parsed["document_store"] = fields.get("e_g_sharepoint_confluence", "")
                parsed["code_repo"] = fields.get("e_g_github_gitlab_azure_devops", "")
                parsed["ticketing_system"] = fields.get("e_g_jira_servicenow", "")
                parsed["data_volume"] = _extract_value(fields, "estimated_total_data_volume")
                parsed["sync_frequency"] = _extract_value(fields, "ingestion_sync_frequency")
                parsed["foundation_model"] = _extract_value(fields, "preferred_foundation_model")
                parsed["human_in_loop"] = _extract_value(fields, "human_in_the_loop_threshold")
                parsed["reasoning_complexity"] = _extract_value(fields, "reasoning_complexity_budget")
                graph_keys = [
                    "business_process_relationships", "data_schema_mapping",
                    "org_chart_reporting_lines", "supplier_vendor_graph"
                ]
                selected_graphs = [k for k in graph_keys if fields.get(k)]
                parsed["knowledge_graph_layers"] = ", ".join(selected_graphs)

            elif step_id == "3":
                all_selected = []
                for k, v in fields.items():
                    if isinstance(v, list) and v:
                        all_selected.extend(
                            [item for item in v if isinstance(item, str) and item != "selected"]
                        )
                        if not all_selected:
                            all_selected.append(k)
                parsed["all_integrations_selected"] = ", ".join(all_selected)
                parsed["custom_api_systems"] = fields.get("system_name", "")

            elif step_id == "4":
                compliance = []
                for key in [
                    "gdpr_eu_uk", "hipaa_us_healthcare", "sox_public_companies",
                    "pci_dss_payments", "fca_pra_uk_finance",
                    "dora_eu_digital_operations", "ccpa_california_privacy",
                    "iso_27001", "nist_csf", "eu_ai_act",
                    "nerc_cip_energy", "basel_iii_banking",
                ]:
                    if fields.get(key):
                        compliance.append(key.upper())
                for k, v in fields.items():
                    if isinstance(v, list) and v:
                        label = k.upper().replace("_", " ")
                        if label not in compliance:
                            compliance.append(label)
                parsed["compliance_frameworks"] = ", ".join(dict.fromkeys(compliance))
                parsed["data_jurisdiction"] = _extract_value(fields, "data_subject_jurisdiction")
                parsed["next_audit"] = fields.get("next_regulatory_audit", "")
                parsed["compliance_notes"] = fields.get(
                    "specific_compliance_constraints_or_recent_findings", ""
                )

            elif step_id == "5":
                parsed["annual_budget"] = _extract_value(fields, "annual_platform_budget_indicative")
                parsed["contract_start_date"] = fields.get("target_contract_start_date", "")
                parsed["economic_buyer"] = _extract_value(fields, "economic_buyer")
                parsed["procurement_process"] = _extract_value(fields, "procurement_process")
                parsed["roi_horizon"] = _extract_value(fields, "expected_roi_horizon")
                parsed["current_tooling_spend"] = _extract_value(
                    fields, "annual_internal_tooling_spend_current"
                )

    KNOWN_INTEGRATION_KEYWORDS = [
        "xero", "quickbook", "netsuite", "sage", "sap", "oracle",
        "dynamics", "stripe", "paypal", "hubspot", "salesforce",
        "zendesk", "intercom", "workday", "bamboohr", "google",
        "sharepoint", "confluence", "onedrive", "github", "gitlab",
        "jira", "servicenow", "datadog", "slack", "notion",
    ]
    detected = set()
    for v in all_fields.values():
        if isinstance(v, str):
            lower = v.lower()
            for kw in KNOWN_INTEGRATION_KEYWORDS:
                if kw in lower:
                    detected.add(v.strip())
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    lower = item.lower()
                    for kw in KNOWN_INTEGRATION_KEYWORDS:
                        if kw in lower:
                            detected.add(item.strip())

    erp = parsed.get("erp_system", "")
    crm = parsed.get("crm_system", "")
    hris = parsed.get("hris_system", "")
    doc = parsed.get("document_store", "")
    existing = parsed.get("all_integrations_selected", "")

    integration_parts = list(filter(None, [erp, crm, hris, doc, existing]))
    integration_parts += [d for d in detected if d not in integration_parts]
    parsed["integrations_summary"] = ", ".join(dict.fromkeys(
        p for p in integration_parts if p
    ))

    if not parsed.get("use_cases"):
        uc_signals = []
        for k, v in all_fields.items():
            if isinstance(v, list) and v:
                uc_signals.append(k.replace("_", " "))
        parsed["use_cases"] = ", ".join(uc_signals[:15])

    logger.info(
        "[_parse_onboarding] industry=%r integrations=%r compliance=%r use_cases=%r",
        parsed.get("industry"),
        parsed.get("integrations_summary"),
        parsed.get("compliance_frameworks"),
        parsed.get("use_cases"),
    )

    return parsed


def _extract_value(fields: dict, prefix: str) -> str:
    """Execute extract value."""
    for key, value in fields.items():
        if key.startswith(prefix):
            if isinstance(value, list):
                return ", ".join(value)
            return str(value)
    return ""


def _suggest_agents(parsed: dict) -> tuple[list[dict], list[str]]:
    """Execute suggest agents."""
    from agents.base_agent import _get_client

    prompt = f"""You are an AI agent recommendation engine for a business automation platform.

Analyse this business profile and recommend ONLY agents with clear evidence in the data.

Available agents:
- a01_invoice: AR/AP workflows, accounting software, cashflow/billing pain, Finance/SaaS/Retail/Professional Services
- a02_expense: Employee expense claims, receipt management, HRIS system, headcount > 10
- a03_admin: Document management, scheduling, SharePoint/Drive/Confluence, approval workflow pain, admin overhead
- a04_payment: Payment reconciliation, bank feeds, Stripe/PayPal, late payments, cashflow tracking

Business Profile:
Industry: {parsed.get('industry', '')}
Headcount: {parsed.get('headcount', '')}
Revenue: {parsed.get('revenue', '')}
ERP/Finance: {parsed.get('erp_system', '')}
CRM: {parsed.get('crm_system', '')}
HRIS: {parsed.get('hris_system', '')}
Document Store: {parsed.get('document_store', '')}
Code Repo: {parsed.get('code_repo', '')}
Ticketing: {parsed.get('ticketing_system', '')}
All Integrations: {parsed.get('integrations_summary', '')}
Knowledge Graph Layers: {parsed.get('knowledge_graph_layers', '')}
Compliance: {parsed.get('compliance_frameworks', '')}
Foundation Model: {parsed.get('foundation_model', '')}
Human-in-loop: {parsed.get('human_in_loop', '')}
ROI Horizon: {parsed.get('roi_horizon', '')}
Economic Buyer: {parsed.get('economic_buyer', '')}
Annual Budget: {parsed.get('annual_budget', '')}

Rules:
1. Use Cases Selected is the strongest signal — weight it first
2. a01_invoice: recommend if ERP/accounting system present OR finance signals in challenges
3. a02_expense: recommend if HRIS present OR headcount > 10 OR expense mentioned
4. a03_admin: recommend if document store present OR org_chart_reporting_lines OR supplier_vendor_graph in knowledge graph layers
5. a04_payment: recommend if payment gateway in integrations OR reconciliation mentioned
6. Priority = high if multiple strong signals, medium if one clear signal, low if inferred
7. reason = one sentence citing actual data from the profile above
8. integration_platforms = ONLY platforms explicitly named in the profile (not inferred)

Reply ONLY with valid JSON. No markdown, no preamble:
{{"agents":[{{"agent":"a01_invoice","label":"Invoice","reason":"ERP present and technology industry with 51-200 headcount.","priority":"high"}}],"integration_platforms":["BambooHR","SharePoint"]}}"""

    response = _get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )

    for block in response.content:
        if block.type == "text":
            try:
                text = block.text.strip()
                if "```" in text:
                    parts = text.split("```")
                    text = parts[1] if len(parts) > 1 else parts[0]
                    if text.startswith("json"):
                        text = text[4:]
                result = json.loads(text.strip())
                known = {"a01_invoice", "a02_expense", "a03_admin", "a04_payment"}
                agents = [
                    a for a in result.get("agents", [])
                    if isinstance(a, dict) and a.get("agent") in known
                ]
                platforms = [
                    p for p in result.get("integration_platforms", [])
                    if isinstance(p, str) and p.strip()
                ]
                return agents, platforms
            except Exception as e:
                logger.error("[_suggest_agents] parse failed: %s — raw: %s", e, block.text[:200])

    return [{"agent": "a01_invoice", "label": "Invoice",
             "reason": "Core cashflow automation.", "priority": "high"}], []


from config.client_config import save_client_config


def _write_client_yaml(client_id: str, parsed: dict, suggested_agents: list[dict] | None = None):
    """Execute write client yaml."""
    erp = (parsed.get("erp_system") or "").lower()
    doc_store = (parsed.get("document_store") or "").lower()
    crm = (parsed.get("crm_system") or "").lower()

    if "quickbook" in erp:
        accounting = "quickbooks"
    elif "xero" in erp:
        accounting = "xero"
    elif "netsuite" in erp:
        accounting = "netsuite"
    elif "sage" in erp:
        accounting = "sage"
    else:
        accounting = "xero"

    if "sharepoint" in doc_store:
        storage = "sharepoint"
    elif "google" in doc_store:
        storage = "google_drive"
    elif "confluence" in doc_store:
        storage = "confluence"
    else:
        storage = "onedrive"

    if "google" in doc_store or "google" in crm:
        calendar, email_system = "google_calendar", "gmail"
    else:
        calendar, email_system = "outlook", "outlook"

    active_agent_ids = (
        [a["agent"] for a in suggested_agents if "agent" in a]
        if suggested_agents
        else ["a01_invoice"]
    )

    config = {
        "client_id": client_id,
        "name": parsed.get("company_name", client_id),
        "accounting_system": accounting,
        "storage": storage,
        "calendar": calendar,
        "email": email_system,
        "active_agents": active_agent_ids,
        "channels": ["whatsapp", "telegram", "email"],
        "industry": parsed.get("industry", ""),
        "region": parsed.get("region", ""),
        "compliance": parsed.get("compliance_frameworks", ""),
        "approve_email": "",
    }
    save_client_config(client_id, config)


def _embed_onboarding(client_id: str, parsed: dict, raw_steps: list):
    """Execute embed onboarding."""
    sections = {
        "company_profile": f"""
Company: {parsed.get('company_name')}
Legal Entity: {parsed.get('legal_entity_type')}
Industry: {parsed.get('industry')}
Region: {parsed.get('region')}
Revenue: {parsed.get('revenue')}
Headcount: {parsed.get('headcount')}
Prior AI Investment: {parsed.get('prior_ai_investment')}
Contact: {parsed.get('contact_name')} ({parsed.get('contact_role')})
Email: {parsed.get('contact_email')}
Phone: {parsed.get('contact_phone')}
""",
        "technical_profile": f"""
ERP: {parsed.get('erp_system')}
ERP Records: {parsed.get('erp_records')}
CRM: {parsed.get('crm_system')}
HRIS: {parsed.get('hris_system')}
Document Store: {parsed.get('document_store')}
Code Repo: {parsed.get('code_repo')}
Ticketing: {parsed.get('ticketing_system')}
Data Volume: {parsed.get('data_volume')}
Sync Frequency: {parsed.get('sync_frequency')}
Foundation Model: {parsed.get('foundation_model')}
Human-in-loop: {parsed.get('human_in_loop')}
Reasoning Complexity: {parsed.get('reasoning_complexity')}
Knowledge Graph Layers: {parsed.get('knowledge_graph_layers')}
""",
        "compliance_profile": f"""
Compliance Frameworks: {parsed.get('compliance_frameworks')}
Data Jurisdiction: {parsed.get('data_jurisdiction')}
Next Audit: {parsed.get('next_audit')}
Compliance Notes: {parsed.get('compliance_notes')}
""",
        "integrations_profile": f"""
All Integrations Selected: {parsed.get('all_integrations_selected')}
Integrations Summary: {parsed.get('integrations_summary')}
Custom API Systems: {parsed.get('custom_api_systems')}
""",
        "business_profile": f"""
Annual Budget: {parsed.get('annual_budget')}
Contract Start: {parsed.get('contract_start_date')}
Economic Buyer: {parsed.get('economic_buyer')}
Procurement Process: {parsed.get('procurement_process')}
ROI Horizon: {parsed.get('roi_horizon')}
Current Tooling Spend: {parsed.get('current_tooling_spend')}
""",
        "challenges_and_readiness": f"""
Use Cases Selected: {parsed.get('use_cases')}
Knowledge Graph Layers: {parsed.get('knowledge_graph_layers')}
""",
    }

    for category, content in sections.items():
        if content.strip():
            embed_document(
                client_id=client_id,
                category=category,
                text=content.strip(),
            )
