"""Contain stripe integration backend logic."""
import logging
import httpx
from integrations.resilience import CircuitBreaker

logger = logging.getLogger(__name__)


class StripeIntegration:

    """Represent the StripeIntegration component and its related behavior."""
    BASE_URL = "https://api.stripe.com/v1"

    def __init__(self, client_id: str):
        """Initialize the instance state for this class."""
        self.client_id = client_id
        self._breaker = CircuitBreaker(f"stripe:{client_id}")

    @property
    def headers(self) -> dict:
        """Execute headers for StripeIntegration."""
        from integrations.token_manager import _get_stored
        from config.settings import settings
        stored = _get_stored(f"stripe:{self.client_id}")
        api_key = (stored or {}).get("access_token") or settings.stripe_api_key
        if not api_key:
            raise ValueError(f"No Stripe API key configured for this account.")
        return {"Authorization": f"Bearer {api_key}"}

    def get_payment(self, payment_intent_id: str) -> dict:
        """Return payment."""
        return self._breaker.call(self._get_payment, payment_intent_id)

    def _get_payment(self, payment_intent_id: str) -> dict:
        """Return payment."""
        try:
            r = httpx.get(
                f"{self.BASE_URL}/payment_intents/{payment_intent_id}",
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
                f"{self.BASE_URL}/payment_intents",
                headers=self.headers, params={"limit": limit}, timeout=10,
            )
            r.raise_for_status()
            return r.json().get("data", [])
        except httpx.HTTPError as e:
            logger.error("[%s] list_payments failed: %s", self.client_id, e)
            return []

    def check_payment_status(self, payment_intent_id: str) -> dict:
        """Check payment status."""
        return self._breaker.call(self._check_payment_status, payment_intent_id)

    def _check_payment_status(self, payment_intent_id: str) -> dict:
        """Check payment status."""
        try:
            r = httpx.get(
                f"{self.BASE_URL}/payment_intents/{payment_intent_id}",
                headers=self.headers, timeout=10,
            )
            r.raise_for_status()
            data = r.json()
            return {
                "id": data.get("id"),
                "status": data.get("status"),
                "amount": data.get("amount", 0) / 100,
                "currency": data.get("currency", "").upper(),
                "payment_method": data.get("payment_method_types", ["unknown"])[0],
                "created": data.get("created"),
                "last_error": (data.get("last_payment_error") or {}).get("message"),
            }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {"error": "Stripe auth failed — please reconnect Stripe in integrations."}
            logger.error("[%s] check_payment_status failed %s: %s", self.client_id, e.response.status_code, e.response.text)
            return {"error": f"Stripe error: {e.response.status_code}"}
        except httpx.HTTPError as e:
            logger.error("[%s] check_payment_status network error: %s", self.client_id, e)
            return {"error": f"Stripe unreachable: {e}"}

    def capture_payment(self, payment_intent_id: str, amount_to_capture: float | None = None) -> dict:
        """Execute capture payment for StripeIntegration."""
        return self._breaker.call(self._capture_payment, payment_intent_id, amount_to_capture)

    def _capture_payment(self, payment_intent_id: str, amount_to_capture: float | None) -> dict:
        """Execute capture payment for StripeIntegration."""
        try:
            payload = {}
            if amount_to_capture is not None:
                payload["amount_to_capture"] = int(amount_to_capture * 100)
            r = httpx.post(
                f"{self.BASE_URL}/payment_intents/{payment_intent_id}/capture",
                headers=self.headers, data=payload or None, timeout=10,
            )
            r.raise_for_status()
            result = r.json()
            return {
                "captured": True,
                "id": result.get("id"),
                "status": result.get("status"),
                "amount": result.get("amount_received", 0) / 100,
                "currency": result.get("currency", "").upper(),
            }
        except httpx.HTTPStatusError as e:
            logger.error("[%s] capture_payment failed %s: %s", self.client_id, e.response.status_code, e.response.text)
            return {"error": f"Stripe capture failed: {e.response.status_code}"}
        except httpx.HTTPError as e:
            logger.error("[%s] capture_payment network error: %s", self.client_id, e)
            return {"error": f"Stripe unreachable: {e}"}

    def cancel_payment(self, payment_intent_id: str, reason: str = "requested_by_customer") -> dict:
        """Execute cancel payment for StripeIntegration."""
        return self._breaker.call(self._cancel_payment, payment_intent_id, reason)

    def _cancel_payment(self, payment_intent_id: str, reason: str) -> dict:
        """Execute cancel payment for StripeIntegration."""
        try:
            r = httpx.post(
                f"{self.BASE_URL}/payment_intents/{payment_intent_id}/cancel",
                headers=self.headers, data={"cancellation_reason": reason}, timeout=10,
            )
            r.raise_for_status()
            result = r.json()
            return {"cancelled": True, "id": result.get("id"), "status": result.get("status")}
        except httpx.HTTPStatusError as e:
            logger.error("[%s] cancel_payment failed %s: %s", self.client_id, e.response.status_code, e.response.text)
            return {"error": f"Stripe cancel failed: {e.response.status_code}"}
        except httpx.HTTPError as e:
            logger.error("[%s] cancel_payment network error: %s", self.client_id, e)
            return {"error": f"Stripe unreachable: {e}"}

    def refund(self, payment_intent_id: str, amount: float | None = None, reason: str = "requested_by_customer") -> dict:
        """Execute refund for StripeIntegration."""
        return self._breaker.call(self._refund, payment_intent_id, amount, reason)

    def _refund(self, payment_intent_id: str, amount: float | None, reason: str) -> dict:
        """Execute refund for StripeIntegration."""
        try:
            payload: dict = {"payment_intent": payment_intent_id, "reason": reason}
            if amount is not None:
                payload["amount"] = int(amount * 100)
            r = httpx.post(f"{self.BASE_URL}/refunds", headers=self.headers, data=payload, timeout=10)
            r.raise_for_status()
            result = r.json()
            return {
                "refunded": True,
                "refund_id": result.get("id"),
                "status": result.get("status"),
                "amount": result.get("amount", 0) / 100,
                "currency": result.get("currency", "").upper(),
                "payment_intent": payment_intent_id,
            }
        except httpx.HTTPStatusError as e:
            logger.error("[%s] refund failed %s: %s", self.client_id, e.response.status_code, e.response.text)
            return {"error": f"Stripe refund failed: {e.response.status_code}"}
        except httpx.HTTPError as e:
            logger.error("[%s] refund network error: %s", self.client_id, e)
            return {"error": f"Stripe unreachable: {e}"}

    def get_refund(self, refund_id: str) -> dict:
        """Return refund."""
        return self._breaker.call(self._get_refund, refund_id)

    def _get_refund(self, refund_id: str) -> dict:
        """Return refund."""
        try:
            r = httpx.get(f"{self.BASE_URL}/refunds/{refund_id}", headers=self.headers, timeout=10)
            r.raise_for_status()
            result = r.json()
            return {
                "refund_id": result.get("id"),
                "status": result.get("status"),
                "amount": result.get("amount", 0) / 100,
                "currency": result.get("currency", "").upper(),
                "reason": result.get("reason"),
                "created": result.get("created"),
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
            r = httpx.get(f"{self.BASE_URL}/disputes/{dispute_id}", headers=self.headers, timeout=10)
            r.raise_for_status()
            result = r.json()
            evidence = result.get("evidence_details") or {}
            return {
                "dispute_id": result.get("id"),
                "status": result.get("status"),
                "amount": result.get("amount", 0) / 100,
                "currency": result.get("currency", "").upper(),
                "reason": result.get("reason"),
                "payment_intent": result.get("payment_intent"),
                "due_by": evidence.get("due_by"),
                "has_evidence": evidence.get("has_evidence", False),
            }
        except httpx.HTTPStatusError as e:
            logger.error("[%s] get_dispute failed %s: %s", self.client_id, e.response.status_code, e.response.text)
            return {"error": f"Stripe dispute fetch failed: {e.response.status_code}"}
        except httpx.HTTPError as e:
            logger.error("[%s] get_dispute network error: %s", self.client_id, e)
            return {"error": f"Stripe unreachable: {e}"}

    def submit_dispute_evidence(self, dispute_id: str, evidence: dict) -> dict:
        """Execute submit dispute evidence for StripeIntegration."""
        return self._breaker.call(self._submit_dispute_evidence, dispute_id, evidence)

    def _submit_dispute_evidence(self, dispute_id: str, evidence: dict) -> dict:
        """Execute submit dispute evidence for StripeIntegration."""
        try:
            r = httpx.post(
                f"{self.BASE_URL}/disputes/{dispute_id}",
                headers=self.headers, json={"evidence": evidence}, timeout=10,
            )
            r.raise_for_status()
            result = r.json()
            return {"submitted": True, "dispute_id": result.get("id"), "status": result.get("status")}
        except httpx.HTTPError as e:
            logger.error("[%s] submit_dispute_evidence failed: %s", self.client_id, e)
            return {"error": str(e)}