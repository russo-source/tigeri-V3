"""Contain payment factory backend logic."""
from typing import Protocol
import logging

logger = logging.getLogger(__name__)


class PaymentGateway(Protocol):
    """Represent the PaymentGateway component and its related behavior."""
    # Fetch current payment status and provider metadata.
    def check_payment_status(self, payment_ref: str) -> dict: ...
    # Issue a refund for a payment reference, optionally with partial amount.
    def refund(self, payment_ref: str, amount: float | None, reason: str) -> dict: ...
    # Capture authorized funds for the given payment reference.
    def capture_payment(self, payment_ref: str, amount_to_capture: float | None) -> dict: ...
    # Cancel a pending payment transaction.
    def cancel_payment(self, payment_ref: str, reason: str) -> dict: ...
    # Retrieve dispute details by dispute identifier.
    def get_dispute(self, dispute_id: str) -> dict: ...


def get_payment_gateway(gateway: str, client_id: str):
    """Return payment gateway."""
    normalized = gateway.lower().strip()
    if normalized == "stripe":
        from integrations.stripe_integration import StripeIntegration
        return StripeIntegration(client_id=client_id)
    elif normalized == "paypal":
        from integrations.paypal_integration import PayPalIntegration
        return PayPalIntegration(client_id=client_id)
    else:
        raise ValueError(
            f"Unsupported payment gateway: '{gateway}'. "
            "Supported: stripe, paypal."
        )


def get_gateway_from_config(client_id: str):
    """Return gateway from config."""
    from integrations.integration_resolver import resolve_provider
    try:
        gateway = resolve_provider(client_id, "payment")
    except ValueError:
        raise ValueError(
            "No payment gateway connected. "
            "Please connect Stripe or PayPal in Settings → Integrations."
        )
    return get_payment_gateway(gateway, client_id)