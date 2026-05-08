"""Contain webhook setup backend logic."""
from fastapi import APIRouter, Depends
from auth.deps import get_current_user
from config.settings import settings

router = APIRouter()


@router.get("/api/v1/integrations/webhook-setup/{provider}")
def get_webhook_setup_guide(provider: str, user: dict = Depends(get_current_user)):
    """Return webhook setup guide."""
    client_id = user.get("client_id") or user["id"]
    base = settings.backend_url

    guides = {
        "stripe": {
            "provider": "Stripe",
            "webhook_url": f"{base}/webhooks/stripe/{client_id}",
            "steps": [
                "Go to Stripe Dashboard → Developers → Webhooks",
                "Click 'Add endpoint'",
                f"Paste this URL: {base}/webhooks/stripe/{client_id}",
                "Select these events: payment_intent.succeeded, invoice.paid, invoice.payment_failed",
                "Click 'Add endpoint'",
                "Copy the 'Signing secret' shown",
                "Come back here and paste it in the Stripe Webhook Secret field",
            ],
            "requires_secret": True,
            "secret_label": "Webhook Signing Secret",
            "secret_placeholder": "whsec_...",
        },
        "paypal": {
            "provider": "PayPal",
            "webhook_url": f"{base}/webhooks/paypal/{client_id}",
            "steps": [
                "Go to PayPal Developer Dashboard → My Apps & Credentials",
                "Select your app",
                "Scroll to Webhooks → Add Webhook",
                f"Paste this URL: {base}/webhooks/paypal/{client_id}",
                "Select: PAYMENT.CAPTURE.COMPLETED, INVOICING.INVOICE.PAID, PAYMENT.CAPTURE.DENIED",
                "Save — no secret needed, we verify via PayPal headers",
            ],
            "requires_secret": False,
        },
        "xero": {
            "provider": "Xero",
            "webhook_url": f"{base}/webhooks/xero",
            "steps": [
                "Go to Xero Developer Portal → Your App → Webhooks",
                f"Add webhook URL: {base}/webhooks/xero",
                "Select events: Invoice Created, Invoice Updated, Payment Created",
                "Copy the Webhook Key shown",
                "Add it to your environment as XERO_WEBHOOK_KEY",
                "Save and verify the webhook",
            ],
            "requires_secret": False,
        },
        "quickbooks": {
            "provider": "QuickBooks",
            "webhook_url": f"{base}/webhooks/quickbooks",
            "steps": [
                "Go to Intuit Developer Portal → Your App → Webhooks",
                f"Add webhook URL: {base}/webhooks/quickbooks",
                "Select entities: Invoice, Payment",
                "Copy the Verifier Token",
                "Add it to your environment as QUICKBOOKS_WEBHOOK_VERIFIER_TOKEN",
                "Save",
            ],
            "requires_secret": False,
        },
    }

    guide = guides.get(provider)
    if not guide:
        return {"error": f"No setup guide for provider: {provider}"}

    return guide