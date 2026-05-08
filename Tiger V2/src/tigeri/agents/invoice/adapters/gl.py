"""General-ledger adapter contract + a stub + a smart router."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from tigeri.core.ids import new_id


@dataclass
class GLPostRequest:
    tenant_id: str
    invoice_id: str
    amount: Decimal
    currency: str
    vendor_name: str
    invoice_number: str
    line_description: str = ""
    due_date: str | None = None  # ISO date

    # Tax fields. ``tax_total`` is the absolute tax amount (computed upstream).
    # When > 0, the GL adapter renders tax as a separate line item so we don't
    # depend on org-specific Xero tax codes. ``tax_rate_label`` is shown in the
    # tax line description (e.g. "GST 10%") for traceability.
    tax_total: Decimal = Decimal("0")
    tax_rate_label: str = ""


@dataclass
class PostingResult:
    posting_reference: str
    posted: bool
    view_url: str = ""  # Provider-side URL where the user can view the invoice
    provider: str = ""  # "xero" | "qb_sandbox" | "stub" — for downstream display
    # Set when ``posted=False`` and the failure was a real upstream rejection
    # (e.g. Xero "currency not subscribed"). Surfaced to the user so they know
    # what to fix, instead of the old behaviour where any Xero error silently
    # routed to the stub and the user was told "Xero not connected".
    error: str = ""


class GLAdapter(Protocol):
    async def post(self, req: GLPostRequest, session: AsyncSession) -> PostingResult: ...


class StubGLAdapter:
    """In-process stub. Returns a synthetic ``gl_...`` reference."""

    def __init__(self) -> None:
        self.postings: list[dict] = []

    async def post(self, req: GLPostRequest, session: AsyncSession) -> PostingResult:
        ref = new_id("gl")
        self.postings.append(
            {
                "tenant_id": req.tenant_id,
                "invoice_id": req.invoice_id,
                "amount": str(req.amount),
                "currency": req.currency,
                "ref": ref,
            }
        )
        return PostingResult(posting_reference=ref, posted=True)


class RoutingGLAdapter:
    """Picks the right GL based on what the tenant has connected.

    Priority:
    1. Real Xero connection (mode != sandbox) → call Xero API
    2. QuickBooks connection (mode != sandbox) → call QB API (TODO)
    3. Sandbox connection on either Xero or QB → tagged stub (e.g.
       ``xero_sandbox:<id>``) so the demo UI looks "real" without hitting
       the upstream.
    4. Nothing → plain stub with ``gl_<id>``.

    Lookup happens per-call so a tenant that just connected is served
    immediately, no restart needed.
    """

    def __init__(self, fallback: GLAdapter | None = None) -> None:
        self._fallback = fallback or StubGLAdapter()

    async def post(self, req: GLPostRequest, session: AsyncSession) -> PostingResult:
        from tigeri.core.logging import get_logger
        from tigeri.integrations import token_manager

        logger = get_logger(__name__)

        # Prefer Xero if connected (real before demo)
        xero_row = await token_manager.get(session, req.tenant_id, "xero")
        if xero_row is not None:
            mode = (xero_row.meta_json or {}).get("mode", "real")
            if mode == "sandbox":
                return await self._tagged_stub(req, session, "xero_sandbox")
            try:
                from tigeri.agents.invoice.adapters.xero_gl import XeroGLAdapter

                return await XeroGLAdapter().post(req, session)
            except Exception as e:  # noqa: BLE001
                # Real Xero failed. We used to log + silently fall through to
                # the stub here, which masked real upstream errors as "Xero
                # not connected" in the UI. Now we surface the error so the
                # user can see (e.g.) "currency INR not subscribed" and fix
                # it. The frontend renders the `error` field on the invoice
                # card.
                logger.error(
                    "xero_gl_post_failed",
                    tenant_id=req.tenant_id,
                    invoice_id=req.invoice_id,
                    error=f"{type(e).__name__}: {e}",
                )
                return PostingResult(
                    posting_reference="",
                    posted=False,
                    provider="xero",
                    error=_humanise_xero_error(str(e)),
                )

        qb_row = await token_manager.get(session, req.tenant_id, "quickbooks")
        if qb_row is not None:
            mode = (qb_row.meta_json or {}).get("mode", "real")
            if mode == "sandbox":
                return await self._tagged_stub(req, session, "qb_sandbox")
            # No real QB GLAdapter wired yet — sandbox-tag the stub
            return await self._tagged_stub(req, session, "qb_sandbox")

        return await self._fallback.post(req, session)

    async def _tagged_stub(
        self, req: GLPostRequest, session: AsyncSession, tag: str
    ) -> PostingResult:
        """Stub that returns a posting reference prefixed with the provider name.
        Same behaviour as StubGLAdapter but the audit log + UI clearly show
        which provider would have been used."""
        ref = f"{tag}:{new_id('inv')}"
        return PostingResult(posting_reference=ref, posted=True, provider=tag)


def _humanise_xero_error(raw: str) -> str:
    """Trim Xero's verbose error strings down to the human-actionable bit.

    Xero's 400 responses look like ``Xero invoice POST 400: Organisation is
    not subscribed to currency INR``. The user only needs the second half;
    the prefix is just a context tag. We also catch the most common cases
    and add a one-line "what to do" hint so the chat card is actionable
    without the user having to know Xero's product surface."""

    msg = raw.split(":", 1)[-1].strip() if ":" in raw else raw

    lower = msg.lower()
    if "not subscribed to currency" in lower:
        return f"{msg}. Either pick a currency the org supports, or enable this currency in Xero → Organisation settings → Currencies."
    if "invalid_grant" in lower or "refresh" in lower:
        return f"{msg}. Reconnect Xero from Admin → Integrations."
    if "401" in lower or "unauthorized" in lower:
        return f"{msg}. The Xero connection looks expired — reconnect from Admin → Integrations."
    return msg


def default_gl_adapter() -> GLAdapter:
    """The Invoice Agent uses the routing adapter by default."""
    return RoutingGLAdapter()
