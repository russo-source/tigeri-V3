"""Contain paypal integration backend logic."""
import logging
import httpx
from integrations.resilience import CircuitBreaker

logger = logging.getLogger(__name__)


class PayPalIntegration:

    """Represent the PayPalIntegration component and its related behavior."""
    BASE_URL = "https://api-m.paypal.com/v2"

    def __init__(self, client_id: str):
        """Initialize the instance state for this class."""
        self.client_id = client_id
        self._breaker = CircuitBreaker(f"paypal:{client_id}")

    @property
    def headers(self) -> dict:
        """Execute headers for PayPalIntegration."""
        from integrations.token_manager import _get_valid_token
        token = _get_valid_token("paypal", client_id=self.client_id)
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def get_payment(self, order_id: str) -> dict:
        """Return payment."""
        return self._breaker.call(self._get_payment, order_id)

    def _get_payment(self, order_id: str) -> dict:
        """Return payment."""
        try:
            r = httpx.get(
                f"{self.BASE_URL}/checkout/orders/{order_id}",
                headers=self.headers, timeout=10,
            )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            logger.error("[%s] get_payment failed %s: %s", self.client_id, e.response.status_code, e.response.text)
            raise
        except httpx.HTTPError as e:
            logger.error("[%s] get_payment network error: %s", self.client_id, e)
            raise

    def list_payments(self, limit: int = 10) -> list[dict]:
        """List payments."""
        return self._breaker.call(self._list_payments, limit)

    def _list_payments(self, limit: int) -> list[dict]:
        """List payments."""
        try:
            r = httpx.get(
                f"{self.BASE_URL}/reporting/transactions",
                headers=self.headers, params={"page_size": limit}, timeout=10,
            )
            r.raise_for_status()
            return r.json().get("transaction_details", [])
        except httpx.HTTPError as e:
            logger.error("[%s] list_payments failed: %s", self.client_id, e)
            return []

    def check_payment_status(self, order_id: str) -> dict:
        """Check payment status."""
        return self._breaker.call(self._check_payment_status, order_id)

    def _check_payment_status(self, order_id: str) -> dict:
        """Check payment status."""
        try:
            r = httpx.get(
                f"{self.BASE_URL}/checkout/orders/{order_id}",
                headers=self.headers, timeout=10,
            )
            r.raise_for_status()
            data = r.json()
            purchase = data.get("purchase_units", [{}])[0]
            capture = purchase.get("payments", {}).get("captures", [{}])[0]
            amount = capture.get("amount", {})
            return {
                "id": data.get("id"),
                "status": data.get("status"),
                "amount": float(amount.get("value", 0)),
                "currency": amount.get("currency_code", ""),
                "payment_method": "paypal",
                "created": data.get("create_time"),
                "last_error": None,
            }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"error": "PayPal auth expired — please reconnect PayPal in integrations."}
            logger.error("[%s] check_payment_status failed %s: %s", self.client_id, e.response.status_code, e.response.text)
            return {"error": f"PayPal error: {e.response.status_code}"}
        except httpx.HTTPError as e:
            logger.error("[%s] check_payment_status network error: %s", self.client_id, e)
            return {"error": f"PayPal unreachable: {e}"}

    def capture_order(self, order_id: str) -> dict:
        """Execute capture order for PayPalIntegration."""
        return self._breaker.call(self._capture_order, order_id)

    def _capture_order(self, order_id: str) -> dict:
        """Execute capture order for PayPalIntegration."""
        try:
            r = httpx.post(
                f"{self.BASE_URL}/checkout/orders/{order_id}/capture",
                headers=self.headers, json={}, timeout=10,
            )
            r.raise_for_status()
            result = r.json()
            purchase = result.get("purchase_units", [{}])[0]
            capture = purchase.get("payments", {}).get("captures", [{}])[0]
            amount = capture.get("amount", {})
            return {
                "captured": True,
                "id": result.get("id"),
                "capture_id": capture.get("id"),
                "status": result.get("status"),
                "amount": float(amount.get("value", 0)),
                "currency": amount.get("currency_code", ""),
            }
        except httpx.HTTPStatusError as e:
            logger.error("[%s] capture_order failed %s: %s", self.client_id, e.response.status_code, e.response.text)
            return {"error": f"PayPal capture failed: {e.response.status_code}"}
        except httpx.HTTPError as e:
            logger.error("[%s] capture_order network error: %s", self.client_id, e)
            return {"error": f"PayPal unreachable: {e}"}

    def cancel_order(self, order_id: str) -> dict:
        """Execute cancel order for PayPalIntegration."""
        return self._breaker.call(self._cancel_order, order_id)

    def _cancel_order(self, order_id: str) -> dict:
        """Execute cancel order for PayPalIntegration."""
        try:
            r = httpx.delete(
                f"{self.BASE_URL}/checkout/orders/{order_id}",
                headers=self.headers, timeout=10,
            )
            r.raise_for_status()
            return {"cancelled": True, "id": order_id}
        except httpx.HTTPStatusError as e:
            logger.error("[%s] cancel_order failed %s: %s", self.client_id, e.response.status_code, e.response.text)
            return {"error": f"PayPal cancel failed: {e.response.status_code}"}
        except httpx.HTTPError as e:
            logger.error("[%s] cancel_order network error: %s", self.client_id, e)
            return {"error": f"PayPal unreachable: {e}"}

    def refund(self, capture_id: str, amount: float | None = None, currency: str = "USD", reason: str = "requested_by_customer") -> dict:
        """Execute refund for PayPalIntegration."""
        return self._breaker.call(self._refund, capture_id, amount, currency, reason)

    def _refund(self, capture_id: str, amount: float | None, currency: str, reason: str) -> dict:
        """Execute refund for PayPalIntegration."""
        try:
            body: dict = {"note_to_payer": reason}
            if amount is not None:
                body["amount"] = {"value": f"{amount:.2f}", "currency_code": currency}
            r = httpx.post(
                f"{self.BASE_URL}/payments/captures/{capture_id}/refund",
                headers=self.headers, json=body, timeout=10,
            )
            r.raise_for_status()
            result = r.json()
            refund_amount = result.get("amount", {})
            return {
                "refunded": True,
                "refund_id": result.get("id"),
                "status": result.get("status"),
                "amount": float(refund_amount.get("value", 0)),
                "currency": refund_amount.get("currency_code", ""),
                "capture_id": capture_id,
            }
        except httpx.HTTPStatusError as e:
            logger.error("[%s] refund failed %s: %s", self.client_id, e.response.status_code, e.response.text)
            return {"error": f"PayPal refund failed: {e.response.status_code}"}
        except httpx.HTTPError as e:
            logger.error("[%s] refund network error: %s", self.client_id, e)
            return {"error": f"PayPal unreachable: {e}"}

    def get_refund(self, refund_id: str) -> dict:
        """Return refund."""
        return self._breaker.call(self._get_refund, refund_id)

    def _get_refund(self, refund_id: str) -> dict:
        """Return refund."""
        try:
            r = httpx.get(
                f"{self.BASE_URL}/payments/refunds/{refund_id}",
                headers=self.headers, timeout=10,
            )
            r.raise_for_status()
            result = r.json()
            amount = result.get("amount", {})
            return {
                "refund_id": result.get("id"),
                "status": result.get("status"),
                "amount": float(amount.get("value", 0)),
                "currency": amount.get("currency_code", ""),
                "created": result.get("create_time"),
            }
        except httpx.HTTPError as e:
            logger.error("[%s] get_refund failed: %s", self.client_id, e)
            return {"error": str(e)}

    def get_dispute(self, dispute_id: str) -> dict:
        """Return dispute."""
        return self._breaker.call(self._get_dispute, dispute_id)

    def _get_dispute(self, dispute_id: str) -> dict:
        """Return dispute."""
        try:
            r = httpx.get(
                f"{self.BASE_URL}/customer/disputes/{dispute_id}",
                headers=self.headers, timeout=10,
            )
            r.raise_for_status()
            result = r.json()
            amount = result.get("dispute_amount", {})
            return {
                "dispute_id": result.get("dispute_id"),
                "status": result.get("status"),
                "amount": float(amount.get("value", 0)),
                "currency": amount.get("currency_code", ""),
                "reason": result.get("reason"),
                "due_by": result.get("seller_response_due_date"),
                "has_evidence": bool(result.get("messages")),
            }
        except httpx.HTTPStatusError as e:
            logger.error("[%s] get_dispute failed %s: %s", self.client_id, e.response.status_code, e.response.text)
            return {"error": f"PayPal dispute fetch failed: {e.response.status_code}"}
        except httpx.HTTPError as e:
            logger.error("[%s] get_dispute network error: %s", self.client_id, e)
            return {"error": f"PayPal unreachable: {e}"}

    def submit_dispute_evidence(self, dispute_id: str, note: str, documents: list[dict] | None = None) -> dict:
        """Execute submit dispute evidence for PayPalIntegration."""
        return self._breaker.call(self._submit_dispute_evidence, dispute_id, note, documents)

    def _submit_dispute_evidence(self, dispute_id: str, note: str, documents: list[dict] | None) -> dict:
        """Execute submit dispute evidence for PayPalIntegration."""
        try:
            body: dict = {"note": note}
            if documents:
                body["documents"] = documents
            r = httpx.post(
                f"{self.BASE_URL}/customer/disputes/{dispute_id}/provide-evidence",
                headers=self.headers, json=body, timeout=10,
            )
            r.raise_for_status()
            return {"submitted": True, "dispute_id": dispute_id}
        except httpx.HTTPError as e:
            logger.error("[%s] submit_dispute_evidence failed: %s", self.client_id, e)
            return {"error": str(e)}