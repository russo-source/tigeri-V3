from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    db_user: str = "postgres"
    db_password: str = "postgres"
    db_name: str = "tigerscale"
    db_host: str = "localhost"
    db_port: int = 5432
    db_max_connections: int = 20
    db_sslmode: str = "require"

  
    # Redis
    redis_url: str = "redis://redis:6379"

  
    # Anthropic
    anthropic_api_key: str = ""

  
    # Encryption (Fernet key — base64-encoded 32-byte secret)
    secret_encryption_key: str = ""

  
    # JWT / Auth
    jwt_secret_key: str = ""
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    forgot_password_token_expire_minutes: int = 30

  
    # URLs
    frontend_url: str = ""
    backend_url: str = ""
    google_redirect_uri: str = ""

  
    # Admin
    admin_api_key: str = ""
    admin_init_secret: str = ""

  
    # OAuth — client credentials only (NO access/refresh tokens here)
    # Tokens are stored exclusively in the token_manager (Redis + Postgres).
    # Xero
    xero_client_id: str = ""
    xero_client_secret: str = ""
    xero_webhook_key: str = ""

    # QuickBooks
    quickbooks_client_id: str = ""
    quickbooks_client_secret: str = ""
    quickbooks_webhook_verifier_token: str = ""
    qb_base_url: str = "https://quickbooks.api.intuit.com/v3/company"

    # Google  (Drive + Gmail + Calendar)
    google_client_id: str = ""
    google_client_secret: str = ""

    # Microsoft  (Outlook + OneDrive + SharePoint + Calendar)
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""

    # PayPal
    paypal_client_id: str = ""
    paypal_client_secret: str = ""

  
    stripe_api_key: str = ""
    stripe_webhook_secret: str = ""

  
    # Telegram
    telegram_bot_token: str = ""
    telegram_alert_chat_id: str = ""

  
    # WhatsApp (360dialog)
    whatsapp_api_key: str = ""

  
    # Vector / RAG
    voyage_api_key: str = ""

    # Twilio WhatsApp
    twilio_account_sid: str = ""         # e.g. ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    twilio_auth_token: str = ""          # Twilio Auth Token (not API key)
    twilio_whatsapp_number: str = ""     # E.g. 14155238886  (no + or spaces)
  
    # Environment
    env: str = "production"

  
    # Pydantic config
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

  
    # Computed properties
    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @property
    def is_development(self) -> bool:
        return self.env.lower() == "development"


settings = Settings()