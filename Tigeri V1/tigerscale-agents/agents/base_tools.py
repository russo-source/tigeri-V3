"""Tool schemas and helpers for the agent tool-use loop."""
from __future__ import annotations


def make_tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


def tool_result(tool_use_id: str, content: str, is_error: bool = False) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }


def format_result(result: dict) -> str:
    import json
    safe = {k: v for k, v in result.items() if not isinstance(v, (bytes, bytearray))}
    return json.dumps(safe, default=str)


#  SHARED PROPERTY BLOCKS 
_VENDOR = {"type": "string", "description": "Vendor, supplier, or client name"}
_AMOUNT = {"type": "number", "description": "Amount as a number"}
_CURRENCY = {"type": "string", "description": "Currency code e.g. USD, SGD, INR"}
_INVOICE_NUMBER = {"type": "string", "description": "Invoice or document number"}
_STATUS_FILTER = {"type": "string", "description": "Status filter: paid, pending, overdue, cancelled"}
_VENDOR_FILTER = {"type": "string", "description": "Filter results by vendor name"}
_RECIPIENT_EMAIL = {"type": "string", "description": "Recipient email address"}
_NOTES = {"type": "string", "description": "Additional notes or reason"}
_REFERENCE = {"type": "string", "description": "Reference or ID"}
_DUE_DATE = {"type": "string", "description": "Due date in YYYY-MM-DD format"}


# INVOICE TOOLS 
INVOICE_TOOLS = [
    make_tool(
        "create_invoice",
        "Create a new invoice for a client. Use when user wants to bill a customer.",
        {
            "vendor": _VENDOR,
            "amount": _AMOUNT,
            "currency": _CURRENCY,
            "description": {"type": "string", "description": "What the invoice is for"},
            "due_date": _DUE_DATE,
            "recipient_email": _RECIPIENT_EMAIL,
            "invoice_number": _INVOICE_NUMBER,
        },
        ["vendor", "amount"],
    ),
    make_tool(
        "send_invoice",
        "Send an existing invoice to a client by email with PDF attached.",
        {
            "invoice_number": _INVOICE_NUMBER,
            "vendor": _VENDOR,
            "recipient_email": _RECIPIENT_EMAIL,
        },
        [],
    ),
    make_tool(
        "list_invoices",
        "List invoices, optionally filtered by status or vendor.",
        {
            "status_filter": _STATUS_FILTER,
            "vendor_filter": _VENDOR_FILTER,
        },
        [],
    ),
    make_tool(
        "check_overdue",
        "Check for overdue invoices that have passed their due date.",
        {},
        [],
    ),
    make_tool(
        "track_invoice",
        "Check the status of a specific invoice by number or vendor.",
        {
            "invoice_number": _INVOICE_NUMBER,
            "vendor": _VENDOR,
        },
        [],
    ),
    make_tool(
        "approve_invoice",
        "Approve or authorise one or more pending invoices.",
        {
            "invoice_number": _INVOICE_NUMBER,
            "vendor": _VENDOR,
            "approve_all": {"type": "boolean", "description": "Approve all pending invoices"},
        },
        [],
    ),
    make_tool(
        "edit_invoice",
        "Edit fields on an existing invoice such as amount, due date, or description.",
        {
            "invoice_number": _INVOICE_NUMBER,
            "vendor": _VENDOR,
            "edit_fields": {"type": "object", "description": "Dict of fields to change e.g. {amount: 500, due_date: '2026-05-01'}"},
        },
        ["edit_fields"],
    ),
    make_tool(
        "mark_invoice_paid",
        "Mark an invoice as paid.",
        {
            "invoice_number": _INVOICE_NUMBER,
            "vendor": _VENDOR,
        },
        [],
    ),
    make_tool(
        "send_reminder",
        "Send a payment reminder for an overdue invoice.",
        {
            "invoice_number": _INVOICE_NUMBER,
            "vendor": _VENDOR,
            "recipient_email": _RECIPIENT_EMAIL,
        },
        [],
    ),
    make_tool(
        "create_bill",
        "Log an inbound vendor bill received from a supplier.",
        {
            "vendor": _VENDOR,
            "amount": _AMOUNT,
            "currency": _CURRENCY,
            "description": {"type": "string", "description": "What the bill is for"},
            "invoice_number": _INVOICE_NUMBER,
            "due_date": _DUE_DATE,
        },
        ["vendor", "amount"],
    ),
    make_tool(
        "list_bills",
        "List inbound vendor bills.",
        {
            "status_filter": _STATUS_FILTER,
            "vendor_filter": _VENDOR_FILTER,
        },
        [],
    ),
    make_tool(
        "create_po",
        "Create a purchase order for a vendor.",
        {
            "vendor": _VENDOR,
            "amount": _AMOUNT,
            "currency": _CURRENCY,
            "description": {"type": "string", "description": "What is being purchased"},
            "quantity": {"type": "number", "description": "Quantity"},
            "unit_price": {"type": "number", "description": "Price per unit"},
            "delivery_date": {"type": "string", "description": "Expected delivery date YYYY-MM-DD"},
        },
        ["vendor", "amount"],
    ),
    make_tool(
        "list_pos",
        "List purchase orders.",
        {
            "status_filter": _STATUS_FILTER,
            "vendor_filter": _VENDOR_FILTER,
        },
        [],
    ),
]


#  EXPENSE TOOLS 
EXPENSE_TOOLS = [
    make_tool(
        "capture_expense",
        "Record a new expense. Use when logging a receipt or spend.",
        {
            "vendor": _VENDOR,
            "amount": _AMOUNT,
            "currency": _CURRENCY,
            "category": {
                "type": "string",
                "description": "Category: supplier, logistics, staff, ops, travel, marketing",
            },
            "date": {"type": "string", "description": "Expense date YYYY-MM-DD"},
            "notes": _NOTES,
            "receipt_url": {"type": "string", "description": "URL to receipt image"},
        },
        ["vendor", "amount", "category"],
    ),
    make_tool(
        "approve_expense",
        "Approve a pending expense by vendor name or reference.",
        {
            "vendor": _VENDOR,
            "reference": _REFERENCE,
        },
        [],
    ),
    make_tool(
        "reject_expense",
        "Reject a pending expense.",
        {
            "vendor": _VENDOR,
            "reference": _REFERENCE,
            "reason": _NOTES,
        },
        [],
    ),
    make_tool(
        "list_expenses",
        "List expenses, optionally filtered by vendor, category, or status.",
        {
            "vendor_filter": _VENDOR_FILTER,
            "category_filter": {"type": "string", "description": "Filter by category"},
            "status_filter": _STATUS_FILTER,
            "month": {"type": "string", "description": "Month filter YYYY-MM"},
        },
        [],
    ),
    make_tool(
        "expense_summary",
        "Get a monthly or period spending summary by category.",
        {
            "month": {"type": "string", "description": "Single month YYYY-MM"},
            "month_from": {"type": "string", "description": "Start of range YYYY-MM"},
            "month_to": {"type": "string", "description": "End of range YYYY-MM"},
        },
        [],
    ),
    make_tool(
        "track_expense",
        "Check the status of a specific expense.",
        {
            "vendor": _VENDOR,
            "reference": _REFERENCE,
        },
        [],
    ),
    make_tool(
        "edit_expense",
        "Edit fields on an existing expense.",
        {
            "vendor": _VENDOR,
            "reference": _REFERENCE,
            "edit_fields": {"type": "object", "description": "Dict of fields to change"},
        },
        ["edit_fields"],
    ),
    make_tool(
        "delete_expense",
        "Delete an expense record.",
        {
            "vendor": _VENDOR,
            "reference": _REFERENCE,
            "delete_all": {"type": "boolean", "description": "Delete all expenses"},
        },
        [],
    ),
]


#  ADMIN TOOLS 
ADMIN_TOOLS = [
    make_tool(
        "file_document",
        "File or store a document into the document storage system.",
        {
            "entity_name": {"type": "string", "description": "Document or entity name"},
            "document_type": {"type": "string", "description": "Type of document e.g. contract, invoice"},
            "folder_name": {"type": "string", "description": "Destination folder name"},
        },
        [],
    ),
    make_tool(
        "find_document",
        "Search for a document by name or type.",
        {
            "entity_name": {"type": "string", "description": "File or entity name to search"},
            "document_type": {"type": "string", "description": "Document type"},
            "folder_name": {"type": "string", "description": "Folder to search within"},
        },
        [],
    ),
    make_tool(
        "read_document",
        "Open and read or summarise a document.",
        {
            "entity_name": {"type": "string", "description": "Document name to read"},
            "folder_name": {"type": "string", "description": "Folder containing the document"},
            "content": {"type": "string", "description": "Specific question to answer about the document"},
        },
        [],
    ),
    make_tool(
        "list_documents",
        "List documents in storage, optionally filtered by folder.",
        {
            "folder_name": {"type": "string", "description": "Folder to list"},
            "document_type": {"type": "string", "description": "Filter by document type"},
        },
        [],
    ),
    make_tool(
        "upload_document",
        "Upload an attached file to document storage.",
        {
            "folder_name": {"type": "string", "description": "Destination folder"},
            "entity_name": {"type": "string", "description": "Optional name for the file"},
            "document_type": {"type": "string", "description": "Document type"},
        },
        [],
    ),
    make_tool(
        "move_document",
        "Move a document from one folder to another.",
        {
            "entity_name": {"type": "string", "description": "File to move"},
            "folder_name": {"type": "string", "description": "Source folder"},
            "target_folder": {"type": "string", "description": "Destination folder"},
        },
        ["entity_name", "target_folder"],
    ),
    make_tool(
        "delete_document",
        "Delete a document permanently.",
        {
            "entity_name": {"type": "string", "description": "File to delete"},
            "folder_name": {"type": "string", "description": "Folder containing the file"},
        },
        ["entity_name"],
    ),
    make_tool(
        "share_document",
        "Generate a shareable link for a document.",
        {
            "entity_name": {"type": "string", "description": "File to share"},
            "folder_name": {"type": "string", "description": "Folder containing the file"},
        },
        ["entity_name"],
    ),
    make_tool(
        "schedule_meeting",
        "Schedule a calendar meeting or appointment.",
        {
            "entity_name": {"type": "string", "description": "Who the meeting is with"},
            "meeting_date": {"type": "string", "description": "Date YYYY-MM-DD"},
            "meeting_time": {"type": "string", "description": "Time HH:MM 24hr"},
            "meeting_duration": {"type": "integer", "description": "Duration in minutes, default 60"},
            "attendees": {"type": "array", "items": {"type": "string"}, "description": "List of attendee emails"},
            "timezone": {"type": "string", "description": "IANA timezone e.g. Asia/Singapore"},
        },
        ["entity_name", "meeting_date", "meeting_time"],
    ),
    make_tool(
        "list_meetings",
        "List scheduled meetings.",
        {},
        [],
    ),
    make_tool(
        "track_permit",
        "Track a permit or document expiry date.",
        {
            "entity_name": {"type": "string", "description": "Permit or document name"},
            "document_type": {"type": "string", "description": "Type of permit"},
            "expiry_date": {"type": "string", "description": "Expiry date YYYY-MM-DD"},
        },
        ["entity_name"],
    ),
    make_tool(
        "send_communication",
        "Send an email or message to a client or supplier.",
        {
            "recipient_email": {"type": "string", "description": "Recipient email address"},
            "entity_name": {"type": "string", "description": "Who to send to"},
            "content": {"type": "string", "description": "Message body"},
        },
        ["recipient_email", "content"],
    ),
]


#  PAYMENT TOOLS 
PAYMENT_TOOLS = [
    make_tool(
        "track_payment",
        "Track and record an incoming payment, auto-matching to open invoices.",
        {
            "payer": {"type": "string", "description": "Who made the payment"},
            "amount": _AMOUNT,
            "currency": _CURRENCY,
            "payment_ref": _REFERENCE,
            "payment_method": {"type": "string", "description": "stripe, paypal, or bank_transfer"},
            "invoice_ref": {"type": "string", "description": "Invoice number to match against"},
        },
        ["payer", "amount"],
    ),
    make_tool(
        "reconcile",
        "Manually link a payment reference to an invoice number.",
        {
            "payment_ref": _REFERENCE,
            "invoice_ref": {"type": "string", "description": "Invoice number to reconcile against"},
        },
        ["payment_ref", "invoice_ref"],
    ),
    make_tool(
        "send_payment_reminder",
        "Send a payment reminder to a payer for an outstanding invoice.",
        {
            "payer": {"type": "string", "description": "Payer name"},
            "payer_email": {"type": "string", "description": "Payer email"},
            "invoice_ref": {"type": "string", "description": "Invoice reference"},
        },
        [],
    ),
    make_tool(
        "generate_report",
        "Generate a cash flow or ageing report.",
        {
            "report_type": {"type": "string", "description": "cash_flow or ageing"},
        },
        ["report_type"],
    ),
    make_tool(
        "check_payment_status",
        "Check the status of a payment via Stripe or PayPal.",
        {
            "payment_ref": _REFERENCE,
            "payment_method": {"type": "string", "description": "stripe or paypal"},
        },
        ["payment_ref"],
    ),
    make_tool(
        "refund_payment",
        "Process a refund for a Stripe or PayPal payment.",
        {
            "payment_ref": _REFERENCE,
            "amount": _AMOUNT,
            "payment_method": {"type": "string", "description": "stripe or paypal"},
            "reason": _NOTES,
        },
        ["payment_ref"],
    ),
    make_tool(
        "capture_payment",
        "Capture an authorised payment.",
        {
            "payment_ref": _REFERENCE,
            "amount": _AMOUNT,
            "payment_method": {"type": "string", "description": "stripe or paypal"},
        },
        ["payment_ref"],
    ),
    make_tool(
        "cancel_payment",
        "Cancel a pending payment.",
        {
            "payment_ref": _REFERENCE,
            "payment_method": {"type": "string", "description": "stripe or paypal"},
        },
        ["payment_ref"],
    ),
    make_tool(
        "handle_dispute",
        "Flag and escalate a chargeback or payment dispute.",
        {
            "dispute_id": {"type": "string", "description": "Dispute ID from Stripe or PayPal"},
            "payment_ref": _REFERENCE,
        },
        [],
    ),
]