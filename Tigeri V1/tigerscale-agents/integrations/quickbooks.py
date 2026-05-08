"""Contain quickbooks backend logic."""
import logging
import httpx
logger = logging.getLogger(__name__)
from config.settings import settings
from integrations.resilience import with_retry, CircuitBreaker

CATEGORY_ACCOUNT_MAP = {
    "supplier":  "5000",
    "logistics": "5100",
    "staff":     "5200",
    "ops":       "5300",
    "travel":    "5400",
    "marketing": "5500",
}

COUNTRY_TO_CURRENCY = {
    "US": "USD", "IN": "INR", "GB": "GBP", "AU": "AUD",
    "CA": "CAD", "DE": "EUR", "FR": "EUR", "SG": "SGD",
    "AE": "AED", "NZ": "NZD", "ZA": "ZAR", "JP": "JPY",
    "CH": "CHF", "CN": "CNY", "HK": "HKD", "MX": "MXN",
    "BR": "BRL", "SE": "SEK", "NO": "NOK", "DK": "DKK",
}


class QuickBooksIntegration:
    """Represent the QuickBooksIntegration component and its related behavior."""

    BASE_URL = (
        "https://sandbox-quickbooks.api.intuit.com/v3/company"
        if getattr(settings, "env", "production") == "development"
        else "https://quickbooks.api.intuit.com/v3/company"
    )

    def __init__(self, client_id: str):
        self.client_id = client_id
        self._breaker = CircuitBreaker(f"quickbooks:{client_id}")

    @property
    def headers(self) -> dict:
        from integrations.token_manager import _get_valid_token as get_valid_token
        token = get_valid_token("quickbooks", client_id=self.client_id)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @property
    def base(self) -> str:
        from webhooks.integrations import get_provider_meta
        meta = get_provider_meta(self.client_id, "quickbooks")
        realm = meta.get("realm_id", "")
        if not realm:
            raise ValueError(
                "No connected accounting integration for this account. "
                "Please connect one in Settings → Integrations."
            )
        return f"{self.BASE_URL}/{realm}"

    def _get_or_create_customer(self, name: str) -> str:
        try:
            safe_name = name.replace("'", "\\'")
            query = f"SELECT * FROM Customer WHERE DisplayName = '{safe_name}' MAXRESULTS 1"
            response = httpx.get(
                f"{self.base}/query",
                headers=self.headers,
                params={"query": query},
                timeout=10,
            )
            response.raise_for_status()
            customers = response.json().get("QueryResponse", {}).get("Customer", [])
            if customers:
                return customers[0].get("Id", "1")
            create_resp = httpx.post(
                f"{self.base}/customer",
                headers=self.headers,
                json={"DisplayName": name},
                timeout=10,
            )
            create_resp.raise_for_status()
            return create_resp.json().get("Customer", {}).get("Id", "1")
        except Exception as e:
            self._log(f"_get_or_create_customer failed for {name}: {e}", "WARNING")
            return "1"

    def _get_or_create_vendor(self, name: str) -> str:
        try:
            safe_name = name.replace("'", "\\'")
            query = f"SELECT * FROM Vendor WHERE DisplayName = '{safe_name}' MAXRESULTS 1"
            response = httpx.get(
                f"{self.base}/query",
                headers=self.headers,
                params={"query": query},
                timeout=10,
            )
            response.raise_for_status()
            vendors = response.json().get("QueryResponse", {}).get("Vendor", [])
            if vendors:
                return vendors[0].get("Id", "1")
            create_resp = httpx.post(
                f"{self.base}/vendor",
                headers=self.headers,
                json={"DisplayName": name},
                timeout=10,
            )
            create_resp.raise_for_status()
            return create_resp.json().get("Vendor", {}).get("Id", "1")
        except Exception as e:
            self._log(f"_get_or_create_vendor failed for {name}: {e}", "WARNING")
            return "1"

    def _get_ar_account(self) -> str:
        from integrations.token_manager import _redis
        cache_key = f"quickbooks:ar_account:{self.client_id}"
        cached = _redis.get(cache_key)
        if cached:
            return str(cached)
        try:
            query = "SELECT * FROM Account WHERE AccountType = 'Accounts Receivable' MAXRESULTS 1"
            response = httpx.get(
                f"{self.base}/query",
                headers=self.headers,
                params={"query": query},
                timeout=10,
            )
            response.raise_for_status()
            accounts = response.json().get("QueryResponse", {}).get("Account", [])
            if accounts:
                account_id = accounts[0].get("Id", "1")
                _redis.setex(cache_key, 86400, account_id)
                return account_id
        except Exception as e:
            self._log(f"_get_ar_account failed: {e}", "WARNING")
        return "1"

    def _get_expense_account(self) -> str:
        from integrations.token_manager import _redis
        cache_key = f"quickbooks:expense_account:{self.client_id}"
        cached = _redis.get(cache_key)
        if cached:
            return str(cached)
        try:
            query = "SELECT * FROM Account WHERE AccountType = 'Expense' MAXRESULTS 1"
            response = httpx.get(
                f"{self.base}/query",
                headers=self.headers,
                params={"query": query},
                timeout=10,
            )
            response.raise_for_status()
            accounts = response.json().get("QueryResponse", {}).get("Account", [])
            if accounts:
                account_id = accounts[0].get("Id", "1")
                _redis.setex(cache_key, 86400, account_id)
                return account_id
        except Exception as e:
            self._log(f"_get_expense_account failed: {e}", "WARNING")
        return "1"

    @with_retry
    def create_invoice(self, data: dict) -> dict:
        return self._breaker.call(self._create_invoice, data)

    def _create_invoice(self, data: dict) -> dict:
        amount = data.get("amount")
        if amount is None:
            raise ValueError("Amount is required to create an invoice")

        line_items = data.get("line_items") or []
        if line_items:
            qb_lines = []
            for item in line_items:
                if not item.get("amount"):
                    continue
                qty = float(item.get("quantity") or 1)
                line_total = float(item.get("amount") or 0)
                unit_price = round(line_total / qty, 6)
                qb_lines.append({
                    "Amount": round(line_total, 2),
                    "DetailType": "SalesItemLineDetail",
                    "SalesItemLineDetail": {
                        "ItemRef": {"value": "1", "name": "Services"},
                        "Qty": qty,
                        "UnitPrice": unit_price,
                    },
                    "Description": item.get("description", "Service"),
                })
        else:
            qty = float(data.get("quantity") or 1)
            line_total = float(amount)
            unit_price = round(line_total / qty, 6)
            qb_lines = [{
                "Amount": round(line_total, 2),
                "DetailType": "SalesItemLineDetail",
                "SalesItemLineDetail": {
                    "ItemRef": {"value": "1", "name": "Services"},
                    "Qty": qty,
                    "UnitPrice": unit_price,
                },
                "Description": data.get("description", "Service"),
            }]

        vendor_name = data.get("vendor", "Unknown")
        customer_id = data.get("customer_ref") or self._get_or_create_customer(vendor_name)

        payload = {
            "Line": qb_lines,
            "CustomerRef": {"value": customer_id, "name": vendor_name},
            "CurrencyRef": {"value": (data.get("currency") or "USD").upper()},
        }

        invoice_number = data.get("invoice_number")
        if invoice_number and str(invoice_number) not in ("Pending sync", "None", ""):
            payload["DocNumber"] = invoice_number

        due = data.get("due_date")
        if due and str(due) not in ("Not set", "None", ""):
            payload["DueDate"] = due

        try:
            response = httpx.post(
                f"{self.base}/invoice",
                headers=self.headers,
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            inv = response.json().get("Invoice", {})
            inv["InvoiceID"] = inv.get("Id", "")
            inv["InvoiceNumber"] = inv.get("DocNumber", "")

            if not inv.get("DocNumber") and inv.get("Id"):
                import time as _time
                for _ in range(3):
                    _time.sleep(1)
                    try:
                        fetched = self._get_invoice(inv["Id"])
                        if fetched.get("DocNumber"):
                            inv["DocNumber"] = fetched["DocNumber"]
                            inv["InvoiceNumber"] = fetched["DocNumber"]
                            break
                    except Exception:
                        pass

            return inv
        except httpx.HTTPError as e:
            self._log(f"create_invoice failed: {e}", "ERROR")
            raise

    @with_retry
    def create_bill(self, data: dict) -> dict:
        return self._breaker.call(self._create_bill, data)

    def _create_bill(self, data: dict) -> dict:
        vendor_name = data.get("vendor", "Unknown")
        vendor_id = data.get("vendor_ref") or self._get_or_create_vendor(vendor_name)
        expense_account = self._get_expense_account()

        amount = float(data.get("amount", 0))
        line_items = data.get("line_items") or []

        if line_items:
            qb_lines = []
            for item in line_items:
                if not item.get("amount"):
                    continue
                qty = float(item.get("quantity") or 1)
                line_total = float(item.get("amount") or 0)
                unit_price = round(line_total / qty, 6)
                qb_lines.append({
                    "Amount": round(line_total, 2),
                    "DetailType": "AccountBasedExpenseLineDetail",
                    "AccountBasedExpenseLineDetail": {
                        "AccountRef": {"value": expense_account},
                        "BillableStatus": "NotBillable",
                        "UnitPrice": unit_price,
                        "Qty": qty,
                    },
                    "Description": item.get("description", "Purchase"),
                })
        else:
            qb_lines = [{
                "Amount": round(amount, 2),
                "DetailType": "AccountBasedExpenseLineDetail",
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"value": expense_account},
                    "BillableStatus": "NotBillable",
                },
                "Description": data.get("description", "Purchase"),
            }]

        currency = (data.get("currency") or "USD").upper()
        payload = {
            "Line": qb_lines,
            "VendorRef": {"value": vendor_id, "name": vendor_name},
            "CurrencyRef": {"value": currency},
        }

        if currency != "USD":
            payload["ExchangeRate"] = float(data.get("exchange_rate") or 1.0)

        invoice_number = data.get("invoice_number")
        if invoice_number and str(invoice_number) not in ("None", "Pending sync", "", "null"):
            payload["DocNumber"] = invoice_number
        if data.get("po_number"):
            payload["PrivateNote"] = data["po_number"]

        due = data.get("due_date")
        if due and str(due) not in ("Not set", "None", ""):
            payload["DueDate"] = due

        try:
            response = httpx.post(
                f"{self.base}/bill",
                headers=self.headers,
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            bill = response.json().get("Bill", {})
            if not bill:
                raise ValueError("QuickBooks returned empty Bill response — check if Accounts Payable is configured")
            bill["InvoiceID"] = bill.get("Id", "")
            bill["_amount"] = bill.get("TotalAmt", amount)
            bill["_vendor"] = vendor_name
            return bill
        except httpx.HTTPError as e:
            self._log(f"create_bill failed: {e}", "ERROR")
        raise

    @with_retry
    def create_purchase_order(self, data: dict) -> dict:
        return self._breaker.call(self._create_purchase_order, data)

    def _create_purchase_order(self, data: dict) -> dict:
        vendor_name = data.get("vendor", "Unknown")
        vendor_id = data.get("vendor_ref") or self._get_or_create_vendor(vendor_name)

        line_items_data = data.get("line_items") or []
        if line_items_data:
            qb_lines = []
            for item in line_items_data:
                if not item.get("amount"):
                    continue
                qty = float(item.get("quantity") or 1)
                line_total = float(item.get("amount") or 0)
                unit_price = round(line_total / qty, 6)
                qb_lines.append({
                    "Amount": round(line_total, 2),
                    "DetailType": "ItemBasedExpenseLineDetail",
                    "ItemBasedExpenseLineDetail": {
                        "ItemRef": {"value": "1", "name": "Services"},
                        "Qty": qty,
                        "UnitPrice": unit_price,
                    },
                    "Description": item.get("description", "Purchase"),
                })
        else:
            quantity = float(data.get("quantity") or 1)
            unit_price = float(data.get("unit_price") or 0)
            total = float(data.get("amount") or 0)

            if unit_price and quantity and not total:
                total = round(unit_price * quantity, 2)
            elif total and quantity and not unit_price:
                unit_price = round(total / quantity, 6)
            elif total and unit_price and not quantity:
                quantity = total / unit_price
            elif total and not unit_price:
                unit_price = round(total / quantity, 6)

            qb_lines = [{
                "Amount": round(total, 2),
                "DetailType": "ItemBasedExpenseLineDetail",
                "ItemBasedExpenseLineDetail": {
                    "ItemRef": {"value": "1", "name": "Services"},
                    "Qty": quantity,
                    "UnitPrice": unit_price,
                },
                "Description": data.get("description", "Purchase"),
            }]

        payload = {
            "Line": qb_lines,
            "VendorRef": {"value": vendor_id, "name": vendor_name},
        }

        if data.get("po_number"):
            payload["DocNumber"] = data["po_number"]
        if data.get("reference"):
            payload["Memo"] = data["reference"]

        delivery = data.get("delivery_date")
        if delivery and str(delivery) not in ("Not set", "None", ""):
            payload["TxnDate"] = delivery

        try:
            response = httpx.post(
                f"{self.base}/purchaseorder",
                headers=self.headers,
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            po = response.json().get("PurchaseOrder", {})
            po["PurchaseOrderID"] = po.get("Id", "")
            po["PurchaseOrderNumber"] = po.get("DocNumber", "")
            return po
        except httpx.HTTPError as e:
            self._log(f"create_purchase_order failed: {e}", "ERROR")
            raise

    def approve_purchase_order(self, po_id: str) -> dict:
        try:
            po = self._get_purchase_order(po_id)
            po["POStatus"] = "Open"
            response = httpx.post(
                f"{self.base}/purchaseorder",
                headers=self.headers,
                params={"operation": "update"},
                json=po,
                timeout=10,
            )
            response.raise_for_status()
            result = response.json().get("PurchaseOrder", {})
            result["Status"] = "SUBMITTED"
            return result
        except httpx.HTTPError as e:
            self._log(f"approve_purchase_order failed: {e}", "ERROR")
            raise

    @with_retry
    def get_purchase_order(self, po_id: str) -> dict:
        return self._breaker.call(self._get_purchase_order, po_id)

    def _get_purchase_order(self, po_id: str) -> dict:
        try:
            response = httpx.get(
                f"{self.base}/purchaseorder/{po_id}",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("PurchaseOrder", {})
        except httpx.HTTPError as e:
            self._log(f"get_purchase_order failed: {e}", "ERROR")
            raise

    @with_retry
    def get_purchase_order_pdf(self, po_id: str) -> bytes:
        return self._breaker.call(self._get_purchase_order_pdf, po_id)

    def _get_purchase_order_pdf(self, po_id: str) -> bytes:
        try:
            po = self._get_purchase_order(po_id)
            return self._render_po_pdf(po)
        except Exception as e:
            self._log(f"get_purchase_order_pdf failed: {e}", "ERROR")
            raise

    def _render_po_pdf(self, po: dict) -> bytes:
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
            import io

            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=A4)
            width, height = A4

            c.setFont("Helvetica-Bold", 16)
            c.drawString(50, height - 60, "Purchase Order")

            c.setFont("Helvetica", 11)
            y = height - 100
            fields = [
                ("PO Number", po.get("DocNumber", "N/A")),
                ("Vendor", po.get("VendorRef", {}).get("name", "N/A")),
                ("Status", po.get("POStatus", "N/A")),
                ("Total", f"USD {po.get('TotalAmt', 0):,.2f}"),
                ("Date", po.get("TxnDate", "N/A")),
            ]
            for label, value in fields:
                c.drawString(50, y, f"{label}: {value}")
                y -= 20

            c.save()
            return buf.getvalue()

        except ImportError:
            stub = (
                b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R"
                b"/Resources<<>>>>endobj\nxref\n0 4\ntrailer<</Size 4/Root 1 0 R>>"
                b"\nstartxref\n0\n%%EOF"
            )
            return stub

    def find_purchase_order_by_number(self, po_number: str) -> dict:
        try:
            query = f"SELECT * FROM PurchaseOrder WHERE DocNumber = '{po_number}'"
            response = httpx.get(
                f"{self.base}/query",
                headers=self.headers,
                params={"query": query},
                timeout=10,
            )
            response.raise_for_status()
            orders = response.json().get("QueryResponse", {}).get("PurchaseOrder", [])
            if not orders:
                return {}
            po = orders[0]
            return {
                "PurchaseOrderID": po.get("Id", ""),
                "PurchaseOrderNumber": po.get("DocNumber", ""),
                "Status": po.get("POStatus", ""),
                "Contact": {
                    "Name": po.get("VendorRef", {}).get("name", ""),
                    "ContactID": po.get("VendorRef", {}).get("value", ""),
                },
                "Total": po.get("TotalAmt", 0),
            }
        except httpx.HTTPError as e:
            self._log(f"find_purchase_order_by_number failed: {e}", "ERROR")
            raise

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

        conditions = []
        normalized = (status_filter or "").lower().strip()

        if normalized == "paid":
            conditions.append("Balance = '0'")
        elif normalized in ("pending", "authorized", "draft"):
            conditions.append("Balance > '0'")
        elif normalized in ("cancelled", "voided"):
            conditions.append("TxnStatus = 'Voided'")

        where_clause = " AND ".join(conditions) if conditions else ""
        offset = (page - 1) * page_size + 1

        if where_clause:
            query = (
                f"SELECT * FROM Invoice WHERE {where_clause} "
                f"ORDERBY MetaData.LastUpdatedTime DESC "
                f"STARTPOSITION {offset} MAXRESULTS {page_size}"
            )
        else:
            query = (
                f"SELECT * FROM Invoice "
                f"ORDERBY MetaData.LastUpdatedTime DESC "
                f"STARTPOSITION {offset} MAXRESULTS {page_size}"
            )

        try:
            response = httpx.get(
                f"{self.base}/query",
                headers=self.headers,
                params={"query": query},
                timeout=15,
            )
            response.raise_for_status()
            invoices = response.json().get("QueryResponse", {}).get("Invoice", [])
        except httpx.HTTPError as e:
            self._log(f"list_invoices failed: {e}", "ERROR")
            raise

        today = _date.today()
        results = []

        for inv in invoices:
            balance = float(inv.get("Balance", 0))
            due_raw = inv.get("DueDate", "")
            customer_name = inv.get("CustomerRef", {}).get("name", "")

            if balance == 0:
                display_status = "paid"
            else:
                try:
                    due_date = _date.fromisoformat(due_raw[:10]) if due_raw else None
                    display_status = "overdue" if (due_date and due_date < today) else "pending"
                except Exception:
                    display_status = "pending"

            if normalized == "overdue" and display_status != "overdue":
                continue

            if vendor_filter and vendor_filter.lower() not in customer_name.lower():
                continue

            results.append({
                "invoice_number": inv.get("DocNumber", ""),
                "vendor":         customer_name,
                "amount":         float(inv.get("TotalAmt", 0)),
                "amount_due":     balance,
                "currency":       inv.get("CurrencyRef", {}).get("value", "USD"),
                "due_date":       due_raw[:10] if due_raw else None,
                "status":         display_status,
                "external_id":    inv.get("Id", ""),
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
            "open":       "Open",
            "draft":      "Open",
            "submitted":  "Open",
            "authorized": "Open",
            "billed":     "Closed",
            "received":   "Closed",
            "closed":     "Closed",
        }

        conditions = []
        normalized = (status_filter or "").lower().strip()
        if normalized and normalized in _po_status_map:
            conditions.append(f"POStatus = '{_po_status_map[normalized]}'")

        where_clause = " AND ".join(conditions) if conditions else ""
        offset = (page - 1) * page_size + 1

        if where_clause:
            query = (
                f"SELECT * FROM PurchaseOrder WHERE {where_clause} "
                f"ORDERBY MetaData.LastUpdatedTime DESC "
                f"STARTPOSITION {offset} MAXRESULTS {page_size}"
            )
        else:
            query = (
                f"SELECT * FROM PurchaseOrder "
                f"ORDERBY MetaData.LastUpdatedTime DESC "
                f"STARTPOSITION {offset} MAXRESULTS {page_size}"
            )

        try:
            response = httpx.get(
                f"{self.base}/query",
                headers=self.headers,
                params={"query": query},
                timeout=15,
            )
            response.raise_for_status()
            orders = response.json().get("QueryResponse", {}).get("PurchaseOrder", [])
        except httpx.HTTPError as e:
            self._log(f"list_purchase_orders failed: {e}", "ERROR")
            raise

        results = []
        for po in orders:
            vendor_name = po.get("VendorRef", {}).get("name", "")

            if vendor_filter and vendor_filter.lower() not in vendor_name.lower():
                continue

            results.append({
                "po_number":     po.get("DocNumber", ""),
                "vendor":        vendor_name,
                "amount":        float(po.get("TotalAmt", 0)),
                "currency":      po.get("CurrencyRef", {}).get("value", "USD"),
                "status":        (po.get("POStatus") or "open").lower(),
                "external_id":   po.get("Id", ""),
                "delivery_date": po.get("TxnDate", ""),
            })

        return results

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

        normalized = (status_filter or "").lower().strip()
        offset = (page - 1) * page_size + 1

        query = (
            f"SELECT * FROM Bill "
            f"ORDERBY MetaData.LastUpdatedTime DESC "
            f"STARTPOSITION {offset} MAXRESULTS {page_size}"
        )

        try:
            response = httpx.get(
                f"{self.base}/query",
                headers=self.headers,
                params={"query": query},
                timeout=15,
            )
            response.raise_for_status()
            bills = response.json().get("QueryResponse", {}).get("Bill", [])
        except httpx.HTTPError as e:
            self._log(f"list_bills failed: {e}", "ERROR")
            raise

        today = _date.today()
        results = []

        for bill in bills:
            balance = float(bill.get("Balance", 0))
            due_raw = bill.get("DueDate", "")
            vendor_name = bill.get("VendorRef", {}).get("name", "")

            if balance == 0:
                display_status = "paid"
            else:
                try:
                    due_date = _date.fromisoformat(due_raw[:10]) if due_raw else None
                    display_status = "overdue" if (due_date and due_date < today) else "pending"
                except Exception:
                    display_status = "pending"

            if normalized == "paid" and display_status != "paid":
                continue
            if normalized in ("pending", "authorized", "draft") and display_status != "pending":
                continue
            if normalized == "overdue" and display_status != "overdue":
                continue

            if vendor_filter and vendor_filter.lower() not in vendor_name.lower():
                continue

            results.append({
                "invoice_number": bill.get("DocNumber", ""),
                "vendor":         vendor_name,
                "amount":         float(bill.get("TotalAmt", 0)),
                "amount_due":     balance,
                "currency":       bill.get("CurrencyRef", {}).get("value", "USD"),
                "due_date":       due_raw[:10] if due_raw else None,
                "status":         display_status,
                "external_id":    bill.get("Id", ""),
            })

        return results

    @with_retry
    def post_expense(self, data: dict) -> dict:
        return self._breaker.call(self._post_expense, data)

    def _post_expense(self, data: dict) -> dict:
        category = data.get("category", "ops")
        account_value = data.get("quickbooks_account_code") or self._get_expense_account_by_category(category)
        txn_date = data.get("date") or __import__("datetime").date.today().isoformat()
        vendor_name = data.get("vendor", "Unknown")
        vendor_id = data.get("vendor_ref") or self._get_or_create_vendor(vendor_name)
        amount = float(data.get("amount", 0))
        currency = (data.get("currency") or "USD").upper()

        payload = {
            "PaymentType": "CreditCard",
            "TxnDate": txn_date,
            "PrivateNote": data.get("notes") or data.get("reference", ""),
            "AccountRef": {"value": self._get_credit_card_account()},
            "Line": [{
                "Amount": amount,
                "DetailType": "AccountBasedExpenseLineDetail",
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"value": account_value},
                    "BillableStatus": "NotBillable",
                },
                "Description": data.get("notes") or category,
            }],
            "EntityRef": {
                "value": vendor_id,
                "name": vendor_name,
                "type": "Vendor",
            },
            "DocNumber": data.get("reference", ""),
            "CurrencyRef": {"value": currency},
            "TotalAmt": amount,
        }

        if currency != "USD":
            payload["ExchangeRate"] = float(data.get("exchange_rate") or 1.0)

        try:
            response = httpx.post(
                f"{self.base}/purchase",
                headers=self.headers,
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            purchase = response.json().get("Purchase", {})
            if not purchase:
                raise ValueError("QuickBooks returned empty Purchase response")
            purchase["_amount"] = purchase.get("TotalAmt", amount)
            purchase["_vendor"] = vendor_name
            return purchase
        except httpx.HTTPError as e:
            body = getattr(getattr(e, "response", None), "text", "")
            self._log(f"post_expense failed: {e} — {body}", "WARNING")
            return self._post_expense_as_bill(data, vendor_id, account_value, txn_date, amount)
    def _get_credit_card_account(self) -> str:
        from integrations.token_manager import _redis
        cache_key = f"quickbooks:cc_account:{self.client_id}"
        cached = _redis.get(cache_key)
        if cached:
            return str(cached)
        try:
            for query in [
                "SELECT * FROM Account WHERE AccountType = 'Credit Card' MAXRESULTS 1",
                "SELECT * FROM Account WHERE AccountType = 'Bank' MAXRESULTS 1",
            ]:
                response = httpx.get(
                    f"{self.base}/query",
                    headers=self.headers,
                    params={"query": query},
                    timeout=10,
                )
                response.raise_for_status()
                accounts = response.json().get("QueryResponse", {}).get("Account", [])
                if accounts:
                    account_id = accounts[0].get("Id", "1")
                    _redis.setex(cache_key, 86400, account_id)
                    return account_id
        except Exception as e:
            self._log(f"_get_credit_card_account failed: {e}", "WARNING")
        return self._get_bank_account()
    def _post_expense_as_bill(self, data: dict, vendor_id: str, account_value: str, txn_date: str, amount: float) -> dict:
        vendor_name = data.get("vendor", "Unknown")
        currency = (data.get("currency") or "USD").upper()
        payload = {
            "Line": [{
                "Amount": round(amount, 2),
                "DetailType": "AccountBasedExpenseLineDetail",
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"value": account_value},
                    "BillableStatus": "NotBillable",
                },
                "Description": data.get("notes") or data.get("category", "Expense"),
            }],
            "VendorRef": {"value": vendor_id, "name": vendor_name},
            "CurrencyRef": {"value": currency},
            "TxnDate": txn_date,
            "DocNumber": f"EXP-{data.get('reference', '')}",
        }

        if currency != "USD":
            payload["ExchangeRate"] = float(data.get("exchange_rate") or 1.0)

        try:
            response = httpx.post(
                f"{self.base}/bill",
                headers=self.headers,
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            bill = response.json().get("Bill", {})
            if not bill:
                raise ValueError("QuickBooks returned empty Bill response on expense fallback")
            bill["_amount"] = bill.get("TotalAmt", amount)
            bill["_vendor"] = vendor_name
            bill["_fallback"] = True
            return bill
        except httpx.HTTPError as e:
            self._log(f"post_expense Bill fallback also failed: {e}", "ERROR")
            raise

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
        conditions = []
        offset = (page - 1) * page_size + 1

        if date_from:
            try:
                conditions.append(f"TxnDate >= '{date_from[:10]}'")
            except Exception:
                pass
        if date_to:
            try:
                conditions.append(f"TxnDate <= '{date_to[:10]}'")
            except Exception:
                pass

        where_clause = " AND ".join(conditions) if conditions else ""
        if where_clause:
            query = (
                f"SELECT * FROM Purchase WHERE {where_clause} "
                f"ORDERBY MetaData.LastUpdatedTime DESC "
                f"STARTPOSITION {offset} MAXRESULTS {page_size}"
            )
        else:
            query = (
                f"SELECT * FROM Purchase "
                f"ORDERBY MetaData.LastUpdatedTime DESC "
                f"STARTPOSITION {offset} MAXRESULTS {page_size}"
            )

        try:
            response = httpx.get(
                f"{self.base}/query",
                headers=self.headers,
                params={"query": query},
                timeout=15,
            )
            response.raise_for_status()
            purchases = response.json().get("QueryResponse", {}).get("Purchase", [])
        except httpx.HTTPError as e:
            self._log(f"list_expenses failed: {e}", "ERROR")
            raise

        results = []
        for p in purchases:
            vendor_name = (
                p.get("EntityRef", {}).get("name", "")
                or p.get("VendorRef", {}).get("name", "")
            )

            doc_number = p.get("DocNumber", "")

            if vendor_filter and vendor_filter.lower() not in vendor_name.lower():
                continue
            if reference and reference not in doc_number:
                continue

            lines = p.get("Line", [])
            category = ""
            for line in lines:
                detail = line.get("AccountBasedExpenseLineDetail", {})
                acct_name = detail.get("AccountRef", {}).get("name", "").lower()
                for cat in CATEGORY_ACCOUNT_MAP:
                    if cat in acct_name:
                        category = cat
                        break
                if category:
                    break

            if category_filter and category_filter != category:
                continue

            results.append({
                "external_id": p.get("Id", ""),
                "reference":   doc_number,
                "vendor":      vendor_name,
                "amount":      float(p.get("TotalAmt", 0)),
                "currency":    p.get("CurrencyRef", {}).get("value", "USD"),
                "date":        p.get("TxnDate", ""),
                "category":    category,
                "status":      "approved",
                "notes":       p.get("PrivateNote", ""),
            })

        return results

    @with_retry
    def get_invoice(self, invoice_id: str) -> dict:
        return self._breaker.call(self._get_invoice, invoice_id)

    def _get_invoice(self, invoice_id: str) -> dict:
        try:
            response = httpx.get(
                f"{self.base}/invoice/{invoice_id}",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            return response.json().get("Invoice", {})
        except httpx.HTTPError as e:
            self._log(f"get_invoice failed: {e}", "ERROR")
            raise

    @with_retry
    def get_invoice_pdf(self, invoice_id: str) -> bytes:
        return self._breaker.call(self._get_invoice_pdf, invoice_id)

    def _get_invoice_pdf(self, invoice_id: str) -> bytes:
        try:
            headers = {**self.headers, "Accept": "application/pdf", "Content-Type": "application/pdf"}
            response = httpx.get(
                f"{self.base}/invoice/{invoice_id}/pdf",
                headers=headers,
                timeout=15,
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as e:
            self._log(f"get_invoice_pdf failed: {e}", "ERROR")
            raise

    @with_retry
    def get_bill_pdf(self, bill_id: str) -> bytes:
        return self._breaker.call(self._get_bill_pdf, bill_id)

    def _get_bill_pdf(self, bill_id: str) -> bytes:
        try:
            headers = {**self.headers, "Accept": "application/pdf", "Content-Type": "application/pdf"}
            response = httpx.get(
                f"{self.base}/bill/{bill_id}/pdf",
                headers=headers,
                timeout=15,
            )
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as e:
            self._log(f"get_bill_pdf failed: {e}", "ERROR")
            raise

    @with_retry
    def find_invoice_by_number(self, invoice_number: str) -> dict:
        return self._breaker.call(self._find_invoice_by_number, invoice_number)

    def _find_invoice_by_number(self, invoice_number: str) -> dict:
        try:
            query = f"SELECT * FROM Invoice WHERE DocNumber = '{invoice_number}'"
            response = httpx.get(
                f"{self.base}/query",
                headers=self.headers,
                params={"query": query},
                timeout=10,
            )
            response.raise_for_status()
            invoices = response.json().get("QueryResponse", {}).get("Invoice", [])
            if not invoices:
                return {}
            inv = invoices[0]
            return {
                "Status": "PAID" if inv.get("Balance", 1) == 0 else "AUTHORISED",
                "AmountDue": inv.get("Balance", 0),
                "DueDate": inv.get("DueDate", "N/A"),
                "Contact": {
                    "ContactID": inv.get("CustomerRef", {}).get("value", ""),
                    "Name": inv.get("CustomerRef", {}).get("name", ""),
                },
                "CurrencyCode": inv.get("CurrencyRef", {}).get("value", "USD"),
                "InvoiceNumber": inv.get("DocNumber", ""),
                "InvoiceID": inv.get("Id", ""),
            }
        except httpx.HTTPError as e:
            self._log(f"find_invoice_by_number failed: {e}", "ERROR")
            raise

    @with_retry
    def mark_invoice_paid(self, invoice_id: str, amount: float, date: str) -> None:
        return self._breaker.call(self._mark_invoice_paid, invoice_id, amount, date)

    def _mark_invoice_paid(self, invoice_id: str, amount: float, date: str) -> float | None:
        try:
            invoice = self._get_invoice(invoice_id)
            customer_ref = invoice.get("CustomerRef", {}).get("value", "1")
            bank_account = self._get_bank_account()

            balance = float(invoice.get("Balance", 0))
            total = float(invoice.get("TotalAmt", 0))
            self._log(
                f"mark_invoice_paid invoice={invoice_id} balance={balance} "
                f"total={total} requested_amount={amount}", "INFO"
            )

            if balance <= 0:
                self._log(
                    f"Invoice {invoice_id} balance is {balance} — already fully paid, skipping", "INFO"
                )
                return None

            pay_amount = balance

            payload = {
                "CustomerRef": {"value": customer_ref},
                "TotalAmt": pay_amount,
                "TxnDate": date,
                "DepositToAccountRef": {"value": bank_account},
                "Line": [{
                    "Amount": pay_amount,
                    "LinkedTxn": [{
                        "TxnId": invoice_id,
                        "TxnType": "Invoice",
                    }],
                }],
            }
            response = httpx.post(
                f"{self.base}/payment",
                headers=self.headers,
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            payment = response.json().get("Payment", {})
            self._log(
                f"Payment created id={payment.get('Id')} amount={pay_amount} invoice={invoice_id}", "INFO"
            )
            return pay_amount
        except httpx.HTTPError as e:
            body = getattr(getattr(e, "response", None), "text", "")
            self._log(f"mark_invoice_paid failed: {e} — {body}", "ERROR")
            raise

    @with_retry
    def mark_invoice_authorised(self, invoice_id: str) -> dict:
        return self._breaker.call(self._mark_invoice_authorised, invoice_id)

    def _mark_invoice_authorised(self, invoice_id: str) -> dict:
        """
        QB has no 'authorise' concept. Mark as sent (emailed) to move it forward.
        This is the closest QB equivalent to Xero's AUTHORISED status.
        """
        try:
            inv = self._get_invoice(invoice_id)
            if not inv.get("SyncToken"):
                raise ValueError(f"Could not fetch SyncToken for invoice {invoice_id}")

            payload = {
                "Id": inv["Id"],
                "SyncToken": inv["SyncToken"],
                "sparse": True,
                "EmailStatus": "EmailSent",
                "BillEmail": inv.get("BillEmail") or {"Address": "noreply@placeholder.com"},
            }
            response = httpx.post(
                f"{self.base}/invoice",
                headers=self.headers,
                params={"operation": "update"},
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            result = response.json().get("Invoice", {})
            result["Status"] = "AUTHORISED"
            result["_amount"] = result.get("TotalAmt", inv.get("TotalAmt", 0))
            return result
        except httpx.HTTPError as e:
            body = getattr(getattr(e, "response", None), "text", "")
            self._log(f"mark_invoice_authorised failed: {e} — {body}", "ERROR")
            raise

    @with_retry
    def edit_invoice(self, invoice_id: str, fields: dict) -> dict:
        return self._breaker.call(self._edit_invoice, invoice_id, fields)

    def _edit_invoice(self, invoice_id: str, fields: dict) -> dict:
        try:
            inv = self._get_invoice(invoice_id)
            if not inv.get("SyncToken"):
                raise ValueError(f"Could not fetch SyncToken for invoice {invoice_id}")
            existing_lines = [
                l for l in inv.get("Line", [])
                if l.get("DetailType") != "SubTotalLine"
            ]

            if "line_items" in fields:
                rebuilt = []
                for item in fields["line_items"]:
                    if not item.get("amount"):
                        continue
                    qty        = float(item.get("quantity") or 1)
                    line_total = float(item.get("amount") or 0)
                    unit_price = round(line_total / qty, 2)
                    rebuilt.append({
                        "Amount": round(line_total, 2),
                        "DetailType": "SalesItemLineDetail",
                        "SalesItemLineDetail": {
                            "ItemRef": {"value": "1", "name": "Services"},
                            "Qty": qty,
                            "UnitPrice": unit_price,
                        },
                        "Description": item.get("description", "Service"),
                    })
                inv["Line"] = rebuilt

            elif "amount" in fields or "quantity" in fields or "unit_price" in fields:
                new_total  = float(fields.get("amount") or 0)
                new_qty    = float(fields.get("quantity") or 0)
                new_unit   = float(fields.get("unit_price") or 0)
                target_desc = fields.get("description", "").lower()

                updated = False
                for line in existing_lines:
                    if line.get("DetailType") != "SalesItemLineDetail":
                        continue
                    detail    = line.get("SalesItemLineDetail", {})
                    line_desc = (line.get("Description") or "").lower()

                    if target_desc and target_desc not in line_desc and updated:
                        continue

                    existing_qty  = float(detail.get("Qty") or 1)
                    existing_unit = float(detail.get("UnitPrice") or 0)

                    if new_qty and new_unit:
                        qty   = new_qty
                        unit  = new_unit
                        total = round(qty * unit, 2)
                    elif new_qty and not new_unit:
                        qty   = new_qty
                        unit  = existing_unit
                        total = round(qty * unit, 2)
                    elif new_unit and not new_qty:
                        qty   = existing_qty
                        unit  = new_unit
                        total = round(qty * unit, 2)
                    elif new_total:
                        qty   = existing_qty or 1
                        unit  = round(new_total / qty, 2)
                        total = new_total
                    else:
                        continue

                    line["Amount"] = round(total, 2)
                    detail["Qty"]       = qty
                    detail["UnitPrice"] = round(unit, 2)
                    detail["TaxCodeRef"] = detail.get("TaxCodeRef", {"value": "NON"})
                    line["SalesItemLineDetail"] = detail
                    if "description" in fields:
                        line["Description"] = fields["description"]
                    updated = True
                    break

                inv["Line"] = existing_lines

            elif "description" in fields:
                for line in existing_lines:
                    if line.get("DetailType") == "SalesItemLineDetail":
                        line["Description"] = fields["description"]
                        break
                inv["Line"] = existing_lines

            if "due_date" in fields:
                inv["DueDate"] = fields["due_date"]
            if "vendor" in fields:
                inv["CustomerRef"]["name"]  = fields["vendor"]
                inv["CustomerRef"]["value"] = self._get_or_create_customer(fields["vendor"])

            payload = {
                "Id": inv["Id"],
                "SyncToken": inv["SyncToken"],
                "sparse": True,
                "Line": inv["Line"],
                "CustomerRef": inv["CustomerRef"],
            }
            if "due_date" in fields:
                payload["DueDate"] = inv.get("DueDate", "")
            if inv.get("CurrencyRef"):
                payload["CurrencyRef"] = inv["CurrencyRef"]

            response = httpx.post(
                f"{self.base}/invoice",
                headers=self.headers,
                params={"operation": "update"},
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
            result = response.json().get("Invoice", {})
            result["_amount"] = result.get("TotalAmt", 0)
            return result

        except httpx.HTTPError as e:
            body = getattr(getattr(e, "response", None), "text", "")
            self._log(f"edit_invoice failed: {e} — {body}", "ERROR")
            raise


    @with_retry
    def edit_bill(self, bill_id: str, fields: dict) -> dict:
        return self._breaker.call(self._edit_bill, bill_id, fields)

    def _edit_bill(self, bill_id: str, fields: dict) -> dict:
        """Edit QB bill — same discipline as _edit_invoice: preserve lines, patch target only."""
        try:
            response = httpx.get(
                f"{self.base}/bill/{bill_id}",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            bill = response.json().get("Bill", {})

            if not bill.get("SyncToken"):
                raise ValueError(f"Could not fetch SyncToken for bill {bill_id}")

            existing_lines = bill.get("Line", [])

            if "amount" in fields or "quantity" in fields or "unit_price" in fields:
                new_total = float(fields.get("amount", 0))
                new_qty   = float(fields.get("quantity", 0))
                new_unit  = float(fields.get("unit_price", 0))

                updated = False
                for line in existing_lines:
                    if line.get("DetailType") != "AccountBasedExpenseLineDetail":
                        continue
                    detail = line.get("AccountBasedExpenseLineDetail", {})

                    existing_qty  = float(detail.get("Qty")       or 1)
                    existing_unit = float(detail.get("UnitPrice") or 0)

                    if new_qty and new_unit:
                        qty   = new_qty
                        unit  = new_unit
                        total = round(qty * unit, 2)
                    elif new_qty and not new_unit:
                        qty   = new_qty
                        unit  = existing_unit
                        total = round(qty * unit, 2)
                    elif new_unit and not new_qty:
                        qty   = existing_qty
                        unit  = new_unit
                        total = round(qty * unit, 2)
                    elif new_total:
                        qty   = existing_qty or 1
                        unit  = round(new_total / qty, 6)
                        total = new_total
                    else:
                        continue

                    line["Amount"] = total
                    detail["Qty"] = qty
                    detail["UnitPrice"] = unit
                    line["AccountBasedExpenseLineDetail"] = detail
                    if "description" in fields:
                        line["Description"] = fields["description"]
                    updated = True
                    break

                bill["Line"] = existing_lines

            elif "description" in fields:
                for line in existing_lines:
                    if line.get("DetailType") == "AccountBasedExpenseLineDetail":
                        line["Description"] = fields["description"]
                        break
                bill["Line"] = existing_lines

            if "due_date" in fields:
                bill["DueDate"] = fields["due_date"]
            if "vendor" in fields:
                bill["VendorRef"]["name"] = fields["vendor"]
                bill["VendorRef"]["value"] = self._get_or_create_vendor(fields["vendor"])

            payload = {
                "Id": bill["Id"],
                "SyncToken": bill["SyncToken"],
                "sparse": True,
                "Line": bill["Line"],
                "VendorRef": bill["VendorRef"],
            }
            if "due_date" in fields:
                payload["DueDate"] = bill.get("DueDate", "")
            if bill.get("CurrencyRef"):
                payload["CurrencyRef"] = bill["CurrencyRef"]

            update = httpx.post(
                f"{self.base}/bill",
                headers=self.headers,
                params={"operation": "update"},
                json=payload,
                timeout=10,
            )
            update.raise_for_status()
            result = update.json().get("Bill", {})
            result["_amount"] = result.get("TotalAmt", 0)
            return result

        except httpx.HTTPError as e:
            self._log(f"edit_bill failed: {e}", "ERROR")
            raise

    def get_contact_email(self, contact_id: str) -> str:
        try:
            response = httpx.get(
                f"{self.base}/customer/{contact_id}",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            customer = response.json().get("Customer", {})
            return customer.get("PrimaryEmailAddr", {}).get("Address", "")
        except httpx.HTTPError as e:
            self._log(f"get_contact_email failed: {e}", "ERROR")
            return ""

    def get_organisation_currency(self) -> str:
        from integrations.token_manager import _redis
        cache_key = f"quickbooks:org_currency:{self.client_id}"
        cached = _redis.get(cache_key)
        if cached:
            return str(cached)
        try:
            from webhooks.integrations import get_provider_meta
            meta = get_provider_meta(self.client_id, "quickbooks")
            realm = meta.get("realm_id", "")
            if not realm:
                return "USD"
            response = httpx.get(
                f"{self.BASE_URL}/{realm}/companyinfo/{realm}",
                headers=self.headers,
                timeout=10,
            )
            response.raise_for_status()
            country = (
                response.json()
                .get("CompanyInfo", {})
                .get("Country", "US")
            )
            currency = COUNTRY_TO_CURRENCY.get(country.upper(), "USD")
            _redis.setex(cache_key, 3600, currency)
            return currency
        except Exception as e:
            self._log(f"get_organisation_currency failed: {e}", "WARNING")
            return "USD"
    def _get_bank_account(self) -> str:
        """Fetch first active bank/checking account for payment deposits."""
        from integrations.token_manager import _redis
        cache_key = f"quickbooks:bank_account:{self.client_id}"
        cached = _redis.get(cache_key)
        if cached:
            return str(cached)
        try:
            for query in [
                "SELECT * FROM Account WHERE AccountType = 'Bank' AND AccountSubType = 'Checking' MAXRESULTS 1",
                "SELECT * FROM Account WHERE AccountType = 'Bank' MAXRESULTS 1",
            ]:
                response = httpx.get(
                    f"{self.base}/query",
                    headers=self.headers,
                    params={"query": query},
                    timeout=10,
                )
                response.raise_for_status()
                accounts = response.json().get("QueryResponse", {}).get("Account", [])
                if accounts:
                    account_id = accounts[0].get("Id", "1")
                    _redis.setex(cache_key, 86400, account_id)
                    return account_id
        except Exception as e:
            self._log(f"_get_bank_account failed: {e}", "WARNING")
        return "1"
    
    def _get_expense_account_by_category(self, category: str) -> str:
        """Fetch real expense account from QB by AccountType=Expense, cached per client."""
        from integrations.token_manager import _redis
        cache_key = f"quickbooks:expense_acct_cat:{self.client_id}:{category}"
        cached = _redis.get(cache_key)
        if cached:
            return str(cached)
        try:
            query = "SELECT * FROM Account WHERE AccountType = 'Expense' MAXRESULTS 10"
            response = httpx.get(
                f"{self.base}/query",
                headers=self.headers,
                params={"query": query},
                timeout=10,
            )
            response.raise_for_status()
            accounts = response.json().get("QueryResponse", {}).get("Account", [])
            if accounts:
                account_id = accounts[0].get("Id", "1")
                _redis.setex(cache_key, 86400, account_id)
                return account_id
        except Exception as e:
            self._log(f"_get_expense_account_by_category failed: {e}", "WARNING")
        return self._get_expense_account()

    def edit_purchase_order(self, po_id: str, fields: dict) -> dict:
        return self._breaker.call(self._edit_purchase_order, po_id, fields)

    def _edit_purchase_order(self, po_id: str, fields: dict) -> dict:
        """Edit QB PO — preserves all existing lines, only patches the target line."""
        try:
            po = self._get_purchase_order(po_id)
            existing_lines = po.get("Line", [])

            has_line_change = any(
                k in fields for k in ("amount", "unit_price", "quantity", "description")
            )

            if has_line_change:
                new_amount = float(fields.get("amount", 0))
                new_qty = float(fields.get("quantity", 0))
                new_unit = float(fields.get("unit_price", 0))
                target_desc = fields.get("description", "").lower()

                updated = False
                for line in existing_lines:
                    if line.get("DetailType") != "ItemBasedExpenseLineDetail":
                        continue
                    detail = line["ItemBasedExpenseLineDetail"]
                    line_desc = (line.get("Description") or "").lower()

                    if target_desc and target_desc not in line_desc and updated:
                        continue

                    existing_qty = float(detail.get("Qty") or 1)
                    existing_unit = float(detail.get("UnitPrice") or 0)

                    if new_qty and new_unit:
                        qty, unit, total = new_qty, new_unit, new_qty * new_unit
                    elif new_qty and not new_unit:
                        qty, unit, total = new_qty, existing_unit, new_qty * existing_unit
                    elif new_unit and not new_qty:
                        qty, unit, total = existing_qty, new_unit, existing_qty * new_unit
                    elif new_amount:
                        qty = existing_qty or 1
                        unit = new_amount / qty
                        total = new_amount
                    else:
                        continue

                    line["Amount"] = round(total, 2)
                    detail["Qty"] = qty
                    detail["UnitPrice"] = round(unit, 6)
                    if "description" in fields:
                        line["Description"] = fields["description"]
                    updated = True
                    break

            if "vendor" in fields:
                po["VendorRef"]["name"] = fields["vendor"]
            if "delivery_date" in fields:
                po["TxnDate"] = fields["delivery_date"]
            if "reference" in fields:
                po["Memo"] = fields["reference"]

            response = httpx.post(
                f"{self.base}/purchaseorder",
                headers=self.headers,
                params={"operation": "update"},
                json=po,
                timeout=10,
            )
            response.raise_for_status()
            result = response.json().get("PurchaseOrder", {})
            result["_amount"] = result.get("TotalAmt", 0)
            return result
        except httpx.HTTPError as e:
            self._log(f"edit_purchase_order failed: {e}", "ERROR")
            raise
    
    def _log(self, message: str, level: str = "INFO") -> None:
        getattr(logger, level.lower(), logger.info)("[%s] %s", self.client_id, message)