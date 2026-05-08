"""Contain xero backend logic."""
import logging
import httpx

logger = logging.getLogger(__name__)

from integrations.resilience import (
    with_retry,
    CircuitBreaker,
    XeroValidationError,
    _extract_xero_validation_errors,
)


class XeroIntegration:
    """Represent the XeroIntegration component and its related behavior."""
    BASE_URL = "https://api.xero.com/api.xro/2.0"

    _STATUS_MAP = {
        "pending":    ["DRAFT", "SUBMITTED", "AUTHORISED"],
        "authorized": ["AUTHORISED"],
        "authorised": ["AUTHORISED"],
        "paid":       ["PAID"],
        "cancelled":  ["VOIDED"],
        "voided":     ["VOIDED"],
        "draft":      ["DRAFT"],
        "overdue":    ["AUTHORISED"],
    }

    _STATUS_DISPLAY = {
        "DRAFT":      "pending",
        "SUBMITTED":  "pending",
        "AUTHORISED": "authorized",
        "PAID":       "paid",
        "VOIDED":     "cancelled",
        "DELETED":    "cancelled",
    }

    def __init__(self, client_id: str):
        self.client_id = client_id
        self._breaker = CircuitBreaker(f"xero:{client_id}")

    @property
    def headers(self) -> dict:
        from integrations.token_manager import _get_valid_token as get_valid_token
        token = get_valid_token("xero", client_id=self.client_id)
        return {
            "Authorization": f"Bearer {token}",
            "Xero-tenant-id": self._get_tenant_id(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _get_tenant_id(self) -> str:
        from webhooks.integrations import get_provider_meta
        meta = get_provider_meta(self.client_id, "xero")
        tenant_id = meta.get("tenant_id", "")
        if not tenant_id:
            logger.warning("No tenant_id found for xero client=%s", self.client_id)
        return tenant_id

    def _raise_for_xero_status(self, response: httpx.Response) -> None:
        if response.status_code == 400:
            errors = _extract_xero_validation_errors(response.text)
            raise XeroValidationError(errors)
        response.raise_for_status()

    @with_retry
    def list_invoices(
        self,
        status_filter: str = "",
        vendor_filter: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]:
        return self._breaker.call(
            self._list_invoices, status_filter, vendor_filter, page, page_size
        )

    def _list_invoices(
        self,
        status_filter: str = "",
        vendor_filter: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]:
        from datetime import date as _date

        xero_statuses = []
        if status_filter:
            normalized = status_filter.lower().strip()
            xero_statuses = self._STATUS_MAP.get(normalized, [])

        params: dict = {
            "Type": "ACCREC",
            "page": page,
            "pageSize": page_size,
            "order": "UpdatedDateUTC DESC",
        }

        if xero_statuses and len(xero_statuses) == 1:
            params["Statuses"] = xero_statuses[0]

        try:
            response = httpx.get(
                f"{self.BASE_URL}/Invoices",
                headers=self.headers,
                params=params,
                timeout=15,
            )
            response.raise_for_status()
            invoices = response.json().get("Invoices", [])
        except httpx.HTTPError as e:
            self._log(f"list_invoices failed: {e}", "ERROR")
            raise

        today = _date.today()
        results = []

        for inv in invoices:
            xero_status = inv.get("Status", "")

            if xero_statuses and xero_status not in xero_statuses:
                continue

            if status_filter and status_filter.lower() == "overdue":
                due_raw = inv.get("DueDate", "")
                due_parsed = _parse_xero_date_str(due_raw)
                if not due_parsed or due_parsed >= today:
                    continue

            if vendor_filter:
                contact_name = inv.get("Contact", {}).get("Name", "")
                if vendor_filter.lower() not in contact_name.lower():
                    continue

            results.append({
                "invoice_number": inv.get("InvoiceNumber") or inv.get("InvoiceID"),
                "vendor":         inv.get("Contact", {}).get("Name", ""),
                "amount":         inv.get("Total", 0),
                "amount_due":     inv.get("AmountDue", 0),
                "currency":       inv.get("CurrencyCode", "USD"),
                "due_date":       _parse_xero_date_str(inv.get("DueDate", "")),
                "status":         self._STATUS_DISPLAY.get(xero_status, xero_status.lower()),
                "external_id":    inv.get("InvoiceID"),
                "xero_status":    xero_status,
            })

        return results

    @with_retry
    def list_purchase_orders(
        self,
        status_filter: str = "",
        vendor_filter: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]:
        return self._breaker.call(
            self._list_purchase_orders, status_filter, vendor_filter, page, page_size
        )

    def _list_purchase_orders(
        self,
        status_filter: str = "",
        vendor_filter: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]:
        _po_status_map = {
            "open":       "SUBMITTED",
            "draft":      "DRAFT",
            "submitted":  "SUBMITTED",
            "authorized": "AUTHORISED",
            "authorised": "AUTHORISED",
            "billed":     "BILLED",
            "received":   "BILLED",
            "deleted":    "DELETED",
        }

        params: dict = {"page": page, "pageSize": page_size}

        if status_filter:
            xero_status = _po_status_map.get(status_filter.lower().strip())
            if xero_status:
                params["Status"] = xero_status

        try:
            response = httpx.get(
                f"{self.BASE_URL}/PurchaseOrders",
                headers=self.headers,
                params=params,
                timeout=15,
            )
            response.raise_for_status()
            orders = response.json().get("PurchaseOrders", [])
        except httpx.HTTPError as e:
            self._log(f"list_purchase_orders failed: {e}", "ERROR")
            raise

        results = []
        for po in orders:
            if vendor_filter:
                contact_name = po.get("Contact", {}).get("Name", "")
                if vendor_filter.lower() not in contact_name.lower():
                    continue

            results.append({
                "po_number":     po.get("PurchaseOrderNumber") or po.get("PurchaseOrderID"),
                "vendor":        po.get("Contact", {}).get("Name", ""),
                "amount":        po.get("Total", 0),
                "currency":      po.get("CurrencyCode", "USD"),
                "status":        po.get("Status", "").lower(),
                "external_id":   po.get("PurchaseOrderID"),
                "delivery_date": _parse_xero_date_str(po.get("DeliveryDate", "")),
            })

        return results

    @with_retry
    def edit_purchase_order(self, po_id: str, fields: dict) -> dict:
        return self._breaker.call(self._edit_purchase_order, po_id, fields)

    def _edit_purchase_order(self, po_id: str, fields: dict) -> dict:
        try:
            current = self._get_purchase_order(po_id)
        except Exception as e:
            self._log(f"edit_purchase_order fetch failed: {e}", "ERROR")
            raise

        existing_line_items = current.get("LineItems", [])
        existing_contact = current.get("Contact", {})
        existing_delivery = current.get("DeliveryDate")
        existing_reference = current.get("Reference", "")
        existing_currency = current.get("CurrencyCode", "USD")

        has_line_item_change = any(
            k in fields for k in ("amount", "unit_price", "quantity", "description")
        )

        if has_line_item_change:
            existing_item = existing_line_items[0] if existing_line_items else {}
            quantity  = float(fields.get("quantity")   or existing_item.get("Quantity")  or 1)
            unit_price = float(fields.get("unit_price") or existing_item.get("UnitAmount") or 0)
            total      = float(fields.get("amount")     or 0)
            description = fields.get("description") or existing_item.get("Description") or "Purchase"

            if total and quantity and not fields.get("unit_price"):
                unit_price = total / quantity
            elif unit_price and quantity and not fields.get("amount"):
                total = unit_price * quantity
            elif total and not unit_price:
                unit_price = total
                quantity = quantity or 1.0

            new_line_items = [{
                "Description": description,
                "Quantity":    quantity,
                "UnitAmount":  unit_price,
                "AccountCode": existing_item.get("AccountCode", "400"),
                "TaxType":     existing_item.get("TaxType", "NONE"),
            }]
        else:
            new_line_items = existing_line_items

        payload: dict = {
            "LineItems":    new_line_items,
            "Contact":      {"Name": fields["vendor"]} if "vendor" in fields else existing_contact,
            "CurrencyCode": existing_currency,
        }

        if "delivery_date" in fields:
            payload["DeliveryDate"] = fields["delivery_date"]
        elif existing_delivery:
            payload["DeliveryDate"] = existing_delivery

        if "reference" in fields:
            payload["Reference"] = fields["reference"]
        elif existing_reference:
            payload["Reference"] = existing_reference

        try:
            response = httpx.post(
                f"{self.BASE_URL}/PurchaseOrders/{po_id}",
                headers=self.headers,
                json=payload,
                timeout=10,
            )
            self._raise_for_xero_status(response)
            return response.json()["PurchaseOrders"][0]
        except (XeroValidationError, httpx.HTTPError):
            raise
        except Exception as e:
            self._log(f"edit_purchase_order failed: {e}", "ERROR")
            raise

    @with_retry
    def create_purchase_order(self, data: dict) -> dict:
        return self._breaker.call(self._create_purchase_order, data)

    def _create_purchase_order(self, data: dict) -> dict:
        vendor = data.get("vendor", "Unknown")
        contact_id = self._get_or_create_contact(vendor)
        contact = {"Name": vendor}
        if contact_id:
            contact["ContactID"] = contact_id

        line_items_data = data.get("line_items") or []
        if line_items_data:
            xero_line_items = []
            for item in line_items_data:
                if not item.get("amount"):
                    continue
                qty  = float(item.get("quantity") or 1)
                unit = float(item.get("amount") or 0)
                xero_line_items.append({
                    "Description": item.get("description", "Purchase"),
                    "Quantity":    qty,
                    "UnitAmount":  unit,
                    "AccountCode": "400",
                    "TaxType":     "NONE",
                })
        else:
            quantity   = float(data.get("quantity")   or 1)
            unit_price = float(data.get("unit_price") or 0)
            total      = float(data.get("amount")     or 0)

            if unit_price and quantity and not total:
                total = unit_price * quantity
            elif total and quantity and not unit_price:
                unit_price = total / quantity
            elif total and unit_price and not quantity:
                quantity = total / unit_price
            elif total and not unit_price:
                unit_price = total

            xero_line_items = [{
                "Description": data.get("description", "Purchase"),
                "Quantity":    quantity,
                "UnitAmount":  unit_price,
                "AccountCode": "400",
                "TaxType":     "NONE",
            }]

        payload = {
            "Contact":      contact,
            "LineItems":    xero_line_items,
            "Status":       "DRAFT",
            "CurrencyCode": (data.get("currency") or "USD").upper(),
        }

        if data.get("po_number"):
            payload["PurchaseOrderNumber"] = data["po_number"]
        if data.get("reference"):
            payload["Reference"] = data["reference"]

        delivery = data.get("delivery_date")
        if delivery and str(delivery).lower() not in ("not set", "none", ""):
            payload["DeliveryDate"] = delivery

        try:
            response = httpx.post(
                f"{self.BASE_URL}/PurchaseOrders",
                headers=self.headers,
                json={"PurchaseOrders": [payload]},
                timeout=10,
            )
            self._raise_for_xero_status(response)
            return response.json()["PurchaseOrders"][0]
        except (XeroValidationError, httpx.HTTPError):
            raise
        except Exception as e:
            body = getattr(getattr(e, "response", None), "text", "")
            self._log(f"create_purchase_order failed: {e} — {body}", "ERROR")
            raise

    @with_retry
    def create_invoice(self, data: dict) -> dict:
        return self._breaker.call(self._create_invoice, data)

    def _create_invoice(self, data: dict) -> dict:
        from datetime import date, timedelta

        amount = data.get("amount")
        if amount is None:
            raise ValueError("Amount is required to create an invoice")

        due = data.get("due_date")
        if not due or str(due).lower() in ("not set", "none", ""):
            due = (date.today() + timedelta(days=30)).isoformat()

        line_items = data.get("line_items") or []
        if line_items:
            xero_line_items = [
                {
                    "Description": item.get("description", "Service"),
                    "Quantity": float(item.get("quantity", 1)),
                    "UnitAmount": float(item.get("amount", 0)),
                    "AccountCode": "200",
                }
                for item in line_items if item.get("amount")
            ]
        else:
            xero_line_items = [{
                "Description": data.get("description", "Service"),
                "Quantity": 1.0,
                "UnitAmount": float(amount),
                "AccountCode": "200",
            }]

        payload = {
            "Type": "ACCREC",
            "Contact": {"Name": data["vendor"]},
            "LineItems": xero_line_items,
            "Date": data.get("date"),
            "DueDate": due,
            "Reference": data.get("invoice_number") or data.get("reference", ""),
            "LineAmountTypes": "NoTax",
            "Status": "DRAFT",
            "CurrencyCode": (data.get("currency") or "USD").upper(),
        }

        try:
            response = httpx.post(
                f"{self.BASE_URL}/Invoices",
                headers=self.headers,
                json={"Invoices": [payload]},
                timeout=10,
            )
            self._raise_for_xero_status(response)
            return response.json()["Invoices"][0]
        except (XeroValidationError, httpx.HTTPError):
            raise
        except Exception as e:
            self._log(f"create_invoice failed: {e}", "ERROR")
            raise

    @with_retry
    def create_bill(self, data: dict) -> dict:
        return self._breaker.call(self._create_bill, data)

    def _create_bill(self, data: dict) -> dict:
        payload = {
            "Type": "ACCPAY",
            "Contact": {"Name": data.get("vendor", "Unknown")},
            "LineItems": [{
                "Description": data.get("description", "Purchase"),
                "Quantity": 1,
                "UnitAmount": data.get("amount", 0),
                "AccountCode": data.get("xero_account_code") or data.get("accounting_code", "400"),
                "TaxType": "NONE",
            }],
            "Status": "DRAFT",
            "Reference": data.get("po_number", data.get("reference", data.get("invoice_number", ""))),
            "LineAmountTypes": "NoTax",
            "CurrencyCode": (data.get("currency") or "USD").upper(),
        }

        due = data.get("due_date")
        if due and str(due).lower() not in ("not set", "none", ""):
            payload["DueDate"] = due

        try:
            response = httpx.post(
                f"{self.BASE_URL}/Invoices",
                headers=self.headers,
                json={"Invoices": [payload]},
                timeout=10,
            )
            self._raise_for_xero_status(response)
            return response.json()["Invoices"][0]
        except (XeroValidationError, httpx.HTTPError):
            raise
        except Exception as e:
            self._log(f"create_bill failed: {e}", "ERROR")
            raise

    def _get_or_create_contact(self, name: str) -> str:
        try:
            response = httpx.get(
                f"{self.BASE_URL}/Contacts",
                headers=self.headers,
                params={"where": f'Name="{name}"'},
                timeout=10,
            )
            response.raise_for_status()
            contacts = response.json().get("Contacts", [])
            if contacts:
                return contacts[0]["ContactID"]
            create_resp = httpx.put(
                f"{self.BASE_URL}/Contacts",
                headers=self.headers,
                json={"Contacts": [{"Name": name}]},
                timeout=10,
            )
            create_resp.raise_for_status()
            return create_resp.json()["Contacts"][0]["ContactID"]
        except Exception as e:
            self._log(f"Contact lookup/create failed for {name}: {e}", "WARNING")
            return ""

    def _get_xero_user_id(self) -> str:
        """Fetch first active Xero user ID. Cached in Redis 24h per client."""
        from integrations.token_manager import _redis
        cache_key = f"xero:user_id:{self.client_id}"
        cached = _redis.get(cache_key)
        if cached:
            return str(cached)

        try:
            response = httpx.get(
                f"{self.BASE_URL}/Users",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            users = response.json().get("Users", [])

            for user in users:
                if user.get("OrganisationRole") in ("STANDARD", "ADVISOR", "FINANCIALADVISER"):
                    user_id = user.get("UserID", "")
                    if user_id:
                        _redis.setex(cache_key, 86400, user_id)
                        logger.info("Xero UserID cached client=%s", self.client_id)
                        return user_id

            if users:
                user_id = users[0].get("UserID", "")
                if user_id:
                    _redis.setex(cache_key, 86400, user_id)
                    return user_id

        except Exception as e:
            self._log(f"_get_xero_user_id failed: {e}", "WARNING")

        return ""

    @with_retry
    def post_expense(self, data: dict) -> dict:
        return self._breaker.call(self._post_expense, data)

    def _post_expense(self, data: dict) -> dict:
        """Post expense as Xero Expense Claim — appears in Expenses tab."""
        user_id = self._get_xero_user_id()

        if not user_id:
            logger.warning("No Xero UserID found, falling back to bill client=%s", self.client_id)
            return self._post_expense_as_bill(data)

        try:
            receipt = self._create_receipt(data, user_id)
            receipt_id = receipt.get("ReceiptID")

            if not receipt_id:
                logger.warning("No ReceiptID returned client=%s, falling back to bill", self.client_id)
                return self._post_expense_as_bill(data)

            claim = self._submit_expense_claim(receipt_id, user_id)
            claim["ReceiptID"] = receipt_id
            return claim

        except Exception as e:
            self._log(f"post_expense claim flow failed: {e} — falling back to bill", "WARNING")
            return self._post_expense_as_bill(data)

    def _create_receipt(self, data: dict, user_id: str) -> dict:
        """Create a Xero Receipt for the expense."""
        from datetime import date as _date

        account_code = data.get("xero_account_code") or data.get("accounting_code") or "429"
        txn_date     = data.get("date") or _date.today().isoformat()
        currency     = (data.get("currency") or "USD").upper()
        amount       = float(data.get("amount") or 0)
        description  = data.get("notes") or data.get("category", "Expense") or "Expense"
        vendor       = data.get("vendor", "Unknown")

        payload = {
            "Type":            "SPEND",
            "Contact":         {"Name": vendor},
            "Date":            txn_date,
            "LineAmountTypes": "NoTax",
            "CurrencyCode":    currency,
            "User":            {"UserID": user_id},
            "LineItems": [{
                "Description": description,
                "Quantity":    1.0,
                "UnitAmount":  amount,
                "AccountCode": account_code,
                "TaxType":     "NONE",
            }],
            "Reference": data.get("reference") or data.get("idempotency_key", ""),
        }

        response = httpx.post(
            f"{self.BASE_URL}/Receipts",
            headers=self.headers,
            json={"Receipts": [payload]},
            timeout=10,
        )
        self._raise_for_xero_status(response)
        receipts = response.json().get("Receipts", [])
        if not receipts:
            raise ValueError("Xero returned empty Receipts response")
        return receipts[0]

    def _submit_expense_claim(self, receipt_id: str, user_id: str) -> dict:
        """Submit a Receipt as an ExpenseClaim."""
        payload = {
            "User":     {"UserID": user_id},
            "Receipts": [{"ReceiptID": receipt_id}],
            "Status":   "SUBMITTED",
        }

        response = httpx.post(
            f"{self.BASE_URL}/ExpenseClaims",
            headers=self.headers,
            json={"ExpenseClaims": [payload]},
            timeout=10,
        )
        self._raise_for_xero_status(response)
        claims = response.json().get("ExpenseClaims", [])
        if not claims:
            raise ValueError("Xero returned empty ExpenseClaims response")
        return claims[0]

    def _post_expense_as_bill(self, data: dict) -> dict:
        """Fallback: post expense as ACCPAY bill."""
        bill_data = {
            **data,
            "description": data.get("notes") or data.get("category", "Expense"),
            "vendor":      data.get("vendor", "Unknown"),
            "amount":      data.get("amount", 0),
            "currency":    data.get("currency", "USD"),
            "due_date":    data.get("date"),
            "reference":   data.get("reference", ""),
            "po_number":   data.get("idempotency_key", ""),
        }
        result = self._create_bill(bill_data)
        result["_fallback"] = True
        return result


    @with_retry
    def get_purchase_order(self, po_id: str) -> dict:
        return self._breaker.call(self._get_purchase_order, po_id)

    def _get_purchase_order(self, po_id: str) -> dict:
        try:
            response = httpx.get(
                f"{self.BASE_URL}/PurchaseOrders/{po_id}",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            return response.json()["PurchaseOrders"][0]
        except httpx.HTTPError as e:
            self._log(f"get_purchase_order failed: {e}", "ERROR")
            raise

    @with_retry
    def get_purchase_order_pdf(self, po_id: str) -> bytes:
        return self._breaker.call(self._get_purchase_order_pdf, po_id)

    def _get_purchase_order_pdf(self, po_id: str) -> bytes:
        headers = {**self.headers, "Accept": "application/pdf"}
        try:
            response = httpx.get(
                f"{self.BASE_URL}/PurchaseOrders/{po_id}",
                headers=headers,
                timeout=15,
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as e:
            self._log(f"get_purchase_order_pdf failed: {e}", "ERROR")
            raise

    @with_retry
    def find_purchase_order_by_number(self, po_number: str) -> dict:
        return self._breaker.call(self._find_purchase_order_by_number, po_number)

    def _find_purchase_order_by_number(self, po_number: str) -> dict:
        try:
            response = httpx.get(
                f"{self.BASE_URL}/PurchaseOrders",
                headers=self.headers,
                params={"PurchaseOrderNumber": po_number},
                timeout=10,
            )
            response.raise_for_status()
            orders = response.json().get("PurchaseOrders", [])
            return orders[0] if orders else {}
        except httpx.HTTPError as e:
            self._log(f"find_purchase_order_by_number failed: {e}", "ERROR")
            raise

    @with_retry
    def approve_purchase_order(self, po_id: str) -> dict:
        return self._breaker.call(self._approve_purchase_order, po_id)

    def _approve_purchase_order(self, po_id: str) -> dict:
        try:
            response = httpx.post(
                f"{self.BASE_URL}/PurchaseOrders/{po_id}",
                headers=self.headers,
                json={"Status": "SUBMITTED"},
                timeout=10,
            )
            self._raise_for_xero_status(response)
            return response.json()["PurchaseOrders"][0]
        except (XeroValidationError, httpx.HTTPError):
            raise
        except Exception as e:
            self._log(f"approve_purchase_order failed: {e}", "ERROR")
            raise


    @with_retry
    def get_invoice(self, invoice_id: str) -> dict:
        return self._breaker.call(self._get_invoice, invoice_id)

    def _get_invoice(self, invoice_id: str) -> dict:
        try:
            response = httpx.get(
                f"{self.BASE_URL}/Invoices/{invoice_id}",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            return response.json()["Invoices"][0]
        except httpx.HTTPError as e:
            self._log(f"get_invoice failed: {e}", "ERROR")
            raise

    @with_retry
    def get_invoice_pdf(self, invoice_id: str) -> bytes:
        return self._breaker.call(self._get_invoice_pdf, invoice_id)

    def _get_invoice_pdf(self, invoice_id: str) -> bytes:
        headers = {**self.headers, "Accept": "application/pdf"}
        try:
            response = httpx.get(
                f"{self.BASE_URL}/Invoices/{invoice_id}",
                headers=headers,
                timeout=15,
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as e:
            self._log(f"get_invoice_pdf failed: {e}", "ERROR")
            raise

    def get_bill_pdf(self, bill_id: str) -> bytes:
        return self.get_invoice_pdf(bill_id)

    @with_retry
    def find_invoice_by_number(self, invoice_number: str) -> dict:
        return self._breaker.call(self._find_invoice_by_number, invoice_number)

    def _find_invoice_by_number(self, invoice_number: str) -> dict:
        try:
            response = httpx.get(
                f"{self.BASE_URL}/Invoices",
                headers=self.headers,
                params={"InvoiceNumbers": invoice_number},
                timeout=10,
            )
            response.raise_for_status()
            invoices = response.json().get("Invoices", [])
            return invoices[0] if invoices else {}
        except httpx.HTTPError as e:
            self._log(f"find_invoice_by_number failed: {e}", "ERROR")
            raise

    @with_retry
    def mark_invoice_paid(self, xero_invoice_id: str, amount: float, payment_date: str) -> dict:
        return self._breaker.call(self._mark_invoice_paid, xero_invoice_id, amount, payment_date)

    def _mark_invoice_paid(self, xero_invoice_id: str, amount: float, payment_date: str) -> dict:
        payload = {
            "Invoice": {"InvoiceID": xero_invoice_id},
            "Account": {"Code": "090"},
            "Amount": amount,
            "Date": payment_date,
        }
        try:
            response = httpx.put(
                f"{self.BASE_URL}/Payments",
                headers=self.headers,
                json=payload,
                timeout=10,
            )
            self._raise_for_xero_status(response)
            return response.json()
        except (XeroValidationError, httpx.HTTPError):
            raise
        except Exception as e:
            body = getattr(getattr(e, "response", None), "text", "")
            self._log(f"mark_invoice_paid failed: {e} — {body}", "ERROR")
            raise

    @with_retry
    def get_contact_email(self, contact_id: str) -> str:
        return self._breaker.call(self._get_contact_email, contact_id)

    def _get_contact_email(self, contact_id: str) -> str:
        try:
            response = httpx.get(
                f"{self.BASE_URL}/Contacts/{contact_id}",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            contacts = response.json().get("Contacts", [])
            return contacts[0].get("EmailAddress", "") if contacts else ""
        except httpx.HTTPError as e:
            self._log(f"get_contact_email failed: {e}", "ERROR")
            raise

    @with_retry
    def mark_invoice_authorised(self, invoice_id: str) -> dict:
        return self._breaker.call(self._mark_invoice_authorised, invoice_id)

    def _mark_invoice_authorised(self, invoice_id: str) -> dict:
        try:
            current = self._get_invoice(invoice_id)
            status = current.get("Status", "")

            if status == "AUTHORISED":
                logger.info("Invoice %s already AUTHORISED client=%s", invoice_id, self.client_id)
                return current

            due_date = current.get("DueDate") or current.get("DateString")
            if not due_date:
                from datetime import date, timedelta
                due_date = (date.today() + timedelta(days=30)).isoformat()
                self._edit_invoice(invoice_id, {"due_date": due_date})

            response = httpx.post(
                f"{self.BASE_URL}/Invoices/{invoice_id}",
                headers=self.headers,
                json={"Status": "AUTHORISED"},
                timeout=10,
            )
            self._raise_for_xero_status(response)
            return response.json()["Invoices"][0]

        except XeroValidationError as e:
            self._log(f"mark_invoice_authorised validation error: {e}", "ERROR")
            raise
        except httpx.HTTPError as e:
            body = getattr(getattr(e, "response", None), "text", "")
            self._log(f"mark_invoice_authorised failed: {e} — {body}", "ERROR")
            raise

    @with_retry
    def edit_invoice(self, invoice_id: str, fields: dict) -> dict:
        return self._breaker.call(self._edit_invoice, invoice_id, fields)

    def _edit_invoice(self, invoice_id: str, fields: dict) -> dict:
        payload: dict = {}
        xero_status = ""
        try:
            current = self._get_invoice(invoice_id)
            xero_status = current.get("Status", "")
        except Exception as e:
            logger.warning("Pre-edit status check failed client=%s id=%s: %s",
                           self.client_id, invoice_id, e)

        if xero_status == "AUTHORISED":
            restricted_fields = {k for k in fields if k not in ("due_date", "reference")}
            if restricted_fields:
                raise ValueError(
                    f"Cannot edit {', '.join(restricted_fields)} on an authorised invoice. "
                    f"Only due date and reference can be changed after authorisation."
                )
        line_items = fields.get("line_items")
        if line_items:
            payload["LineItems"] = [
                {
                    "Description": item.get("description", "Service"),
                    "Quantity": float(item.get("quantity", 1)),
                    "UnitAmount": float(item.get("amount", 0)),
                    "AccountCode": "200",
                }
                for item in line_items if item.get("amount")
            ]
        elif "amount" in fields:
            payload["LineItems"] = [{
                "Description": fields.get("description", "Service"),
                "Quantity": 1.0,
                "UnitAmount": float(fields["amount"]),
                "AccountCode": "200",
            }]
        elif "description" in fields:
            payload["LineItems"] = [{
                "Description": fields["description"],
                "Quantity": 1.0,
                "AccountCode": "200",
            }]
        if "due_date" in fields:
            from datetime import datetime as _dt
            value = fields["due_date"]
            try:
                ts = int(_dt.strptime(value, "%Y-%m-%d").timestamp() * 1000)
                payload["DueDate"] = f"/Date({ts})/"
            except (ValueError, TypeError):
                payload["DueDate"] = value
        if "vendor" in fields: payload["Contact"] = {"Name": fields["vendor"]}
        if "reference" in fields: payload["Reference"] = fields["reference"]
        if "status" in fields: payload["Status"] = fields["status"]

        if not payload:
            return {"error": "No valid fields to update"}
        try:
            response = httpx.post(
                f"{self.BASE_URL}/Invoices/{invoice_id}",
                headers=self.headers,
                json=payload,
                timeout=10,
            )
            self._raise_for_xero_status(response)
            return response.json()["Invoices"][0]
        except XeroValidationError as e:
            self._log(f"edit_invoice validation error: {e}", "ERROR")
            raise
        except httpx.HTTPError as e:
            body = getattr(getattr(e, "response", None), "text", "")
            self._log(f"edit_invoice failed: {e} — {body}", "ERROR")
            raise

    @with_retry
    def edit_bill(self, bill_id: str, fields: dict) -> dict:
        return self._breaker.call(self._edit_bill, bill_id, fields)

    def _edit_bill(self, bill_id: str, fields: dict) -> dict:
        return self._edit_invoice(bill_id, fields)

    def get_organisation_currency(self) -> str:
        from integrations.token_manager import _redis
        cache_key = f"xero:org_currency:{self.client_id}"
        cached = _redis.get(cache_key)
        if cached:
            return str(cached)
        try:
            response = httpx.get(
                f"{self.BASE_URL}/Organisations",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            orgs = response.json().get("Organisations", [])
            currency = orgs[0].get("BaseCurrency", "USD") if orgs else "USD"
            _redis.setex(cache_key, 3600, currency)
            return currency
        except Exception as e:
            self._log(f"get_organisation_currency failed: {e}", "WARNING")
            return "USD"
        
    @with_retry
    def list_bills(
        self,
        status_filter: str = "",
        vendor_filter: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]:
        return self._breaker.call(
            self._list_bills, status_filter, vendor_filter, page, page_size
        )

    def _list_bills(
        self,
        status_filter: str = "",
        vendor_filter: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]:
        from datetime import date as _date

        xero_statuses = []
        if status_filter:
            normalized = status_filter.lower().strip()
            xero_statuses = self._STATUS_MAP.get(normalized, [])

        params: dict = {
            "Type": "ACCPAY",
            "page": page,
            "pageSize": page_size,
            "order": "UpdatedDateUTC DESC",
        }

        if xero_statuses and len(xero_statuses) == 1:
            params["Statuses"] = xero_statuses[0]

        try:
            response = httpx.get(
                f"{self.BASE_URL}/Invoices",
                headers=self.headers,
                params=params,
                timeout=15,
            )
            response.raise_for_status()
            bills = response.json().get("Invoices", [])
        except httpx.HTTPError as e:
            self._log(f"list_bills failed: {e}", "ERROR")
            raise

        today = _date.today()
        results = []

        for bill in bills:
            xero_status = bill.get("Status", "")

            if xero_statuses and xero_status not in xero_statuses:
                continue

            if status_filter and status_filter.lower() == "overdue":
                due_raw = bill.get("DueDate", "")
                due_parsed = _parse_xero_date_str(due_raw)
                if not due_parsed or due_parsed >= today:
                    continue

            if vendor_filter:
                contact_name = bill.get("Contact", {}).get("Name", "")
                if vendor_filter.lower() not in contact_name.lower():
                    continue

            results.append({
                "invoice_number": bill.get("InvoiceNumber") or bill.get("InvoiceID"),
                "vendor":         bill.get("Contact", {}).get("Name", ""),
                "amount":         bill.get("Total", 0),
                "amount_due":     bill.get("AmountDue", 0),
                "currency":       bill.get("CurrencyCode", "USD"),
                "due_date":       _parse_xero_date_str(bill.get("DueDate", "")),
                "status":         self._STATUS_DISPLAY.get(xero_status, xero_status.lower()),
                "external_id":    bill.get("InvoiceID"),
            })

        return results

    @with_retry
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
    ) -> list[dict]:
        return self._breaker.call(
            self._list_expenses,
            vendor_filter, status_filter, category_filter,
            date_from, date_to, reference, page, page_size,
        )

    def _list_expenses(
        self,
        vendor_filter: str = "",
        status_filter: str = "",
        category_filter: str = "",
        date_from: str = "",
        date_to: str = "",
        reference: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict]:
        params: dict = {"page": page, "pageSize": page_size}

        if date_from:
            try:
                params["fromDate"] = date_from[:10]
            except Exception:
                pass
        if date_to:
            try:
                params["toDate"] = date_to[:10]
            except Exception:
                pass

        try:
            response = httpx.get(
                f"{self.BASE_URL}/Receipts",
                headers=self.headers,
                params=params,
                timeout=15,
            )
            response.raise_for_status()
            receipts = response.json().get("Receipts", [])
        except httpx.HTTPError as e:
            self._log(f"list_expenses failed: {e}", "ERROR")
            raise

        results = []
        for r in receipts:
            vendor_name = r.get("Contact", {}).get("Name", "")
            doc_ref = r.get("Reference", "")

            if vendor_filter and vendor_filter.lower() not in vendor_name.lower():
                continue
            if reference and reference not in doc_ref:
                continue

            lines = r.get("LineItems", [])
            category = ""
            for line in lines:
                acct = (line.get("AccountCode") or "").lower()
                desc = (line.get("Description") or "").lower()
                for cat in ("supplier", "logistics", "staff", "ops", "travel", "marketing"):
                    if cat in acct or cat in desc:
                        category = cat
                        break
                if category:
                    break

            if category_filter and category_filter != category:
                continue

            xero_status = r.get("Status", "")
            status = {
                "DRAFT":      "pending",
                "SUBMITTED":  "pending",
                "AUTHORISED": "approved",
                "PAID":       "approved",
            }.get(xero_status, xero_status.lower())

            if status_filter and status_filter.lower() not in (status, xero_status.lower()):
                continue

            amount = sum(float(l.get("UnitAmount", 0)) * float(l.get("Quantity", 1)) for l in lines)

            results.append({
                "external_id": r.get("ReceiptID", ""),
                "reference":   doc_ref,
                "vendor":      vendor_name,
                "amount":      amount,
                "currency":    r.get("CurrencyCode", "USD"),
                "date":        _parse_xero_date_str(r.get("Date", "")),
                "category":    category,
                "status":      status,
                "notes":       lines[0].get("Description", "") if lines else "",
            })

        return results
    def _log(self, message: str, level: str = "INFO") -> None:
        getattr(logger, level.lower(), logger.info)("[%s] %s", self.client_id, message)


def _parse_xero_date_str(raw: str):
    """Parse Xero date string to datetime.date or None."""
    import re as _re
    from datetime import datetime, timezone, date
    if not raw:
        return None
    match = _re.search(r"/Date\((\d+)", raw)
    if match:
        try:
            return datetime.fromtimestamp(
                int(match.group(1)) / 1000, tz=timezone.utc
            ).date()
        except Exception:
            return None
    try:
        return date.fromisoformat(raw[:10])
    except Exception:
        return None
    
