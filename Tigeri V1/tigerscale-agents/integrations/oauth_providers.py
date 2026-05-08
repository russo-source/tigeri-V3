"""Contain oauth providers backend logic."""
from config.settings import settings

# Constant for oauth providers.
OAUTH_PROVIDERS = {
    "xero": {
    "auth_url": "https://login.xero.com/identity/connect/authorize",
    "token_url": "https://identity.xero.com/connect/token",
    # CURRENT: accounting.transactions intentionally excluded 
    # requires Xero Partner/Certified app approval.
    # FUTURE: add "accounting.transactions" to this string once approved,
    "scopes": "openid profile email offline_access accounting.invoices accounting.payments accounting.contacts accounting.settings.read",

    "client_id": settings.xero_client_id,
    "client_secret": settings.xero_client_secret,
    "redirect_path": "/api/v1/integrations/callback/xero",
    "auth_type": "oauth2",
    "label": "Xero",
    "category": "accounting",
    },
    "quickbooks": {
        "auth_url": "https://appcenter.intuit.com/connect/oauth2",
        "token_url": "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        "scopes": "com.intuit.quickbooks.accounting",
        "client_id": settings.quickbooks_client_id,
        "client_secret": settings.quickbooks_client_secret,
        "redirect_path": "/api/v1/integrations/callback/quickbooks",
        "auth_type": "oauth2",
        "label": "QuickBooks",
        "category": "accounting",
    },
    "google": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": "openid profile email https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/calendar",
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_path": "/api/v1/integrations/callback/google",
        "auth_type": "oauth2",
        "label": "Google (Drive + Gmail + Calendar)",
        "category": "productivity",
    },
    "outlook": {
        "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scopes": "offline_access Mail.Send Calendars.ReadWrite Files.ReadWrite.All Sites.ReadWrite.All",        
        "client_id": settings.microsoft_client_id,
        "client_secret": settings.microsoft_client_secret,
        "redirect_path": "/api/v1/integrations/callback/outlook",
        "auth_type": "oauth2",
        "label": "Microsoft 365 (Outlook + OneDrive + SharePoint + Calendar)",
        "category": "productivity",
    },
    "paypal": {
        "auth_url": "https://www.paypal.com/signin/authorize",
        "token_url": "https://api-m.paypal.com/v1/oauth2/token",
        "scopes": "openid https://uri.paypal.com/services/invoicing https://uri.paypal.com/services/payments/realtimepayment",
        "client_id": settings.paypal_client_id,
        "client_secret": settings.paypal_client_secret,
        "redirect_path": "/api/v1/integrations/callback/paypal",
        "auth_type": "oauth2",
        "label": "PayPal",
        "category": "payments",
    },
}

# Constant for apikey providers.
APIKEY_PROVIDERS = {
    "stripe": {
        "auth_type": "apikey",
        "label": "Stripe",
        "category": "payments",
        "field_label": "Secret Key",
        "field_placeholder": "sk_live_...",
        "validate_url": "https://api.stripe.com/v1/balance",
        "validate_header": "Authorization",
        "validate_prefix": "Bearer",
    },
    "whatsapp": {
        "auth_type": "apikey",
        "label": "WhatsApp (360dialog)",
        "category": "channels",
        "field_label": "API Key",
        "field_placeholder": "Your 360dialog API key",
        "extra_fields": [
            {
                "key": "phone_number",
                "label": "WhatsApp Business Phone Number",
                "placeholder": "919876543210",
                "required": True,
                "hint": "Country code + number, no + or spaces. Example: 919876543210",
            }
        ],
    },
    "telegram": {
        "auth_type": "apikey",
        "label": "Telegram",
        "category": "channels",
        "field_label": "Bot Token",
        "field_placeholder": "123456:ABC-DEF...",
        "validate_url_template": "https://api.telegram.org/bot{token}/getMe",
    },
    "twilio_whatsapp": {
        "auth_type": "apikey",
        "label": "WhatsApp (Twilio)",
        "category": "channels",
        "field_label": "Auth Token",
        "field_placeholder": "Your Twilio Auth Token",
        "extra_fields": [
            {
                "key": "account_sid",
                "label": "Account SID",
                "placeholder": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                "required": True,
                "hint": "Your Twilio Account SID from console.twilio.com",
            },
            {
                "key": "phone_number",
                "label": "WhatsApp Business Phone Number",
                "placeholder": "14155238886",
                "required": True,
                "hint": "Country code + number, no + or spaces. Example: 14155238886",
            },
        ],
    },
}

# Constant for all providers.
ALL_PROVIDERS = {**OAUTH_PROVIDERS, **APIKEY_PROVIDERS}


def get_redirect_uri(provider: str) -> str:
    """Return redirect uri."""
    cfg = OAUTH_PROVIDERS.get(provider)
    if not cfg:
        raise ValueError(f"Unknown OAuth provider: {provider}")
    return f"{settings.backend_url}{cfg['redirect_path']}"


def build_auth_url(provider: str, state: str) -> str:
    """Build auth url."""
    from urllib.parse import urlencode
    cfg = OAUTH_PROVIDERS[provider]
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": get_redirect_uri(provider),
        "response_type": "code",
        "scope": cfg["scopes"],
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    if provider == "quickbooks":
        params.pop("access_type", None)
        params.pop("prompt", None)
    if provider in ("outlook",):
        params.pop("access_type", None)
        params.pop("prompt", None)
    return f"{cfg['auth_url']}?{urlencode(params)}"