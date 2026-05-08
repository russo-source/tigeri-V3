CREATE TABLE IF NOT EXISTS channel_tokens (
    channel VARCHAR(50) NOT NULL,
    token TEXT NOT NULL,
    client_id VARCHAR(100) NOT NULL,
    webhook_url TEXT,
    webhook_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (channel, client_id)
);
CREATE INDEX IF NOT EXISTS idx_channel_tokens_lookup ON channel_tokens(channel, token);
CREATE INDEX IF NOT EXISTS idx_channel_tokens_client ON channel_tokens(channel, client_id);