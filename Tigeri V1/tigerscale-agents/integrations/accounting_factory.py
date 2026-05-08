"""Contain accounting factory backend logic."""
from typing import Protocol

class AccountingSystem(Protocol):
    """Represent the AccountingSystem component and its related behavior."""
    # Create a new invoice in the connected accounting platform.
    def create_invoice(self, data: dict) -> dict: ...
    # Create a new bill in the connected accounting platform.
    def create_bill(self, data: dict) -> dict: ...
    # Create a purchase order in the connected accounting platform.
    def create_purchase_order(self, data: dict) -> dict: ...
    # Fetch one purchase order by its unique identifier.
    def get_purchase_order(self, po_id: str) -> dict: ...
    # Download a purchase order as a PDF document.
    def get_purchase_order_pdf(self, po_id: str) -> bytes: ...
    # Look up a purchase order by human-readable document number.
    def find_purchase_order_by_number(self, po_number: str) -> dict: ...
    # Post an expense transaction into the accounting system.
    def post_expense(self, data: dict) -> dict: ...
    # Fetch one invoice by its unique identifier.
    def get_invoice(self, invoice_id: str) -> dict: ...
    # Download an invoice as a PDF document.
    def get_invoice_pdf(self, invoice_id: str) -> bytes: ...
    # Download a bill as a PDF document.
    def get_bill_pdf(self, bill_id: str) -> bytes: ...
    # Look up an invoice by human-readable document number.
    def find_invoice_by_number(self, invoice_number: str) -> dict: ...
    # Mark an invoice as paid with amount and payment date details.
    def mark_invoice_paid(self, invoice_id: str, amount: float, date: str) -> None: ...
    # Mark an invoice as authorized/approved for payment.
    def mark_invoice_authorised(self, invoice_id: str) -> dict: ...
    # Update editable fields on an existing invoice.
    def edit_invoice(self, invoice_id: str, fields: dict) -> dict: ...
    # Update editable fields on an existing bill.
    def edit_bill(self, bill_id: str, fields: dict) -> dict: ...
    # Return the email address for a contact record.
    def get_contact_email(self, contact_id: str) -> str: ...
    # for getting currency org
    def get_organisation_currency(self) -> str: ...
    def edit_purchase_order(self, po_id: str, fields: dict) -> dict: ...
    def approve_purchase_order(self, po_id: str) -> dict: ...
    def list_invoices(
        self,
        status_filter: str = "",
        vendor_filter: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]: ...
    def list_purchase_orders(
        self,
        status_filter: str = "",
        vendor_filter: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]: ...
    def list_bills(
    self,
    status_filter: str = "",
    vendor_filter: str = "",
    page: int = 1,
    page_size: int = 50,
    ) -> list[dict]: ...
    def list_expenses(
        self,
        vendor_filter: str = "",
        status_filter: str = "",
        category_filter: str = "",
        date_from: str = "",
        date_to: str = "",
        reference: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]: ...

def get_accounting_system(client_id: str, system: str):
    """Return accounting system."""
    if system == "xero":
        from integrations.xero import XeroIntegration
        return XeroIntegration(client_id=client_id)

    elif system == "quickbooks":
        from integrations.quickbooks import QuickBooksIntegration
        return QuickBooksIntegration(client_id=client_id)
    else:
        raise ValueError(f"Unsupported accounting system: {system}")

def get_system_from_config(client_id: str):
    """Return system from config."""
    from integrations.integration_resolver import resolve_provider
    system = resolve_provider(client_id, "accounting")
    return get_accounting_system(client_id=client_id, system=system)

def get_accounting_platform_name(client_id: str) -> str:
    """Return human-readable platform name for the connected accounting system."""
    try:
        from integrations.integration_resolver import resolve_provider
        system = resolve_provider(client_id, "accounting")
        return {"xero": "Xero", "quickbooks": "QuickBooks"}.get(system, "your accounting platform")
    except Exception:
        return "your accounting platform"