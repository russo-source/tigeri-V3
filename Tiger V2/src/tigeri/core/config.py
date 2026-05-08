from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TIGERI_", extra="ignore")

    database_url: str = "postgresql+asyncpg://tigeri:tigeri_local@localhost:5432/tigeri"
    log_level: str = "INFO"
    env: str = "local"

    a2a_hmac_secret: str = "dev-secret-change-me"
    a2a_replay_window_seconds: int = 30

    # Per-tenant daily LLM input+output token cap. 0 = disabled. When a
    # tenant exceeds the cap, chat returns a 429-equivalent SSE error and
    # the orchestrator does NOT call Anthropic. This is the runaway-spend
    # guard for Phase-1 production.
    chat_tenant_daily_token_budget: int = Field(
        default=2_000_000, validation_alias="TIGERI_CHAT_TENANT_DAILY_TOKEN_BUDGET"
    )

    llm_agent_model: str = "claude-sonnet-4-6"
    llm_reasoning_model: str = "claude-opus-4-7"
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")

    # Chat orchestrator (A2UI) LLM. "anthropic" uses claude via the Anthropic
    # API; "openrouter" uses any OpenRouter-hosted model via the OpenAI-compatible
    # endpoint at https://openrouter.ai/api/v1.
    chat_llm_provider: str = Field(default="anthropic", validation_alias="TIGERI_CHAT_LLM_PROVIDER")
    chat_llm_model: str = Field(default="", validation_alias="TIGERI_CHAT_LLM_MODEL")
    openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")

    discovery_timeout_seconds: int = 60

    aws_region: str = Field(default="us-east-1", validation_alias="AWS_REGION")
    s3_documents_bucket: str = ""

    langsmith_api_key: str = Field(default="", validation_alias="LANGSMITH_API_KEY")
    langsmith_project: str = Field(default="tigeri", validation_alias="LANGSMITH_PROJECT")
    langsmith_tracing: bool = Field(default=False, validation_alias="LANGSMITH_TRACING")

    session_checkpointer: str = "memory"  # "memory" | "postgres"
    ocr_backend: str = "heuristic"  # "heuristic" | "claude"

    # ---- Public host for OAuth callbacks --------------------------------
    public_api_base_url: str = "http://localhost:8000"
    frontend_base_url: str = "http://localhost:3000"
    secret_encryption_key: str = ""

    # ---- Integration credentials (rotate after pilot) -------------------
    xero_client_id: str = Field(default="", validation_alias="XERO_CLIENT_ID")
    xero_client_secret: str = Field(default="", validation_alias="XERO_CLIENT_SECRET")
    xero_tenant_id: str = Field(default="", validation_alias="XERO_TENANT_ID")

    quickbooks_client_id: str = Field(default="", validation_alias="QUICKBOOKS_CLIENT_ID")
    quickbooks_client_secret: str = Field(
        default="", validation_alias="QUICKBOOKS_CLIENT_SECRET"
    )

    google_client_id: str = Field(default="", validation_alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field(default="", validation_alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = Field(default="", validation_alias="GOOGLE_REDIRECT_URI")
    google_integration_redirect_uri: str = Field(
        default="", validation_alias="GOOGLE_INTEGRATION_REDIRECT_URI"
    )
    # Server-side Maps Platform API key for Geocoding / Places / Distance
    # Matrix. Empty = Maps tools refuse with "Maps API key not configured"
    # rather than crashing the chat. Restrict the key to "IPs" in the Cloud
    # Console (this EC2's IP) since it's not exposed to browsers.
    google_maps_api_key: str = Field(default="", validation_alias="GOOGLE_MAPS_API_KEY")

    microsoft_client_id: str = Field(default="", validation_alias="MICROSOFT_CLIENT_ID")
    microsoft_client_secret_id: str = Field(
        default="", validation_alias="MICROSOFT_CLIENT_SECRET_ID"
    )
    microsoft_client_secret_value: str = Field(
        default="", validation_alias="MICROSOFT_CLIENT_SECRET_VALUE"
    )

    paypal_client_id: str = Field(default="", validation_alias="PAYPAL_CLIENT_ID")
    paypal_client_secret: str = Field(default="", validation_alias="PAYPAL_CLIENT_SECRET")

    voyage_api_key: str = Field(default="", validation_alias="VOYAGE_API_KEY")

    whatsapp_biz_number: str = Field(default="", validation_alias="WHATSAPP_BIZ_NUMBER")
    whatsapp_api_key: str = Field(default="", validation_alias="WHATSAPP_API_KEY")
    whatsapp_use_sandbox: bool = Field(default=True, validation_alias="WHATSAPP_USE_SANDBOX")

    telegram_bot_username: str = Field(default="", validation_alias="TELEGRAM_BOT_USERNAME")
    telegram_bot_token: str = Field(default="", validation_alias="TELEGRAM_BOT_TOKEN")
    telegram_webhook_secret: str = Field(
        default="", validation_alias="TELEGRAM_WEBHOOK_SECRET"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
