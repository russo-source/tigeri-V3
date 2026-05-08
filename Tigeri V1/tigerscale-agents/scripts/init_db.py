"""Bootstrap baseline database schema, constraints, and indexes for backend services."""
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from config.settings import settings

# Embedding dimension shared by vector-backed memory and knowledge tables.
EMBEDDING_DIMS = 1024 

def init_db():
    """Create core tables and apply idempotent schema upgrades."""
    # Open an autocommit connection because this script executes many DDL statements.
    conn = psycopg2.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        dbname=settings.db_name
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()

    # Required PostgreSQL extensions for vector search and fuzzy matching.
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    # Core tenant and configuration tables.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id SERIAL PRIMARY KEY,
            client_id VARCHAR(100) UNIQUE NOT NULL,
            name VARCHAR(255),
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)


    cur.execute("""
                CREATE TABLE IF NOT EXISTS client_configs (
                client_id VARCHAR(100) PRIMARY KEY,
                config JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
                );
                """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS agent_logs (
            id SERIAL PRIMARY KEY,
            client_id VARCHAR(100),
            agent_name VARCHAR(100),
            intent VARCHAR(100),
            input TEXT,
            output TEXT,
            status VARCHAR(50),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id SERIAL PRIMARY KEY,
            client_id VARCHAR(100),
            invoice_number VARCHAR(100),
            vendor VARCHAR(255),
            amount DECIMAL(10,2),
            status VARCHAR(50),
            idempotency_key VARCHAR(64),
            raw_message TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            client_id VARCHAR(100),
            vendor VARCHAR(255),
            amount DECIMAL(10,2),
            category VARCHAR(100),
            status VARCHAR(50),
            idempotency_key VARCHAR(64),
            raw_message TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    
    # Integration connection metadata per client/provider pair.
    cur.execute("""
    CREATE TABLE IF NOT EXISTS client_integrations (
        id SERIAL PRIMARY KEY,
        client_id VARCHAR(100) NOT NULL,
        provider VARCHAR(50) NOT NULL,
        connected BOOLEAN NOT NULL DEFAULT FALSE,
        scopes TEXT,
        meta JSONB DEFAULT '{}',
        connected_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        UNIQUE (client_id, provider)
    );
""")

    # Domain transaction tables for bookings and expiring documents.
    cur.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id SERIAL PRIMARY KEY,
                client_id VARCHAR(100),
                booking_ref VARCHAR(100),
                details TEXT,
                status VARCHAR(50),
                raw_message TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)   

    cur.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id SERIAL PRIMARY KEY,
            client_id VARCHAR(100),
            doc_type VARCHAR(100),
            filename VARCHAR(255),
            storage_path TEXT,
            expiry_date DATE,
            status VARCHAR(50),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # Vector-backed memory and knowledge stores used by retrieval features.
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS agent_memory (
            id SERIAL PRIMARY KEY,
            client_id VARCHAR(100),
            agent_name VARCHAR(100),
            content TEXT,
            embedding vector({EMBEDDING_DIMS}),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id SERIAL PRIMARY KEY,
            client_id VARCHAR(100),
            category VARCHAR(100),
            content TEXT,
            embedding vector({EMBEDDING_DIMS}),
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id SERIAL PRIMARY KEY,
            client_id VARCHAR(100),
            agent_name VARCHAR(100),
            intent VARCHAR(100),
            input_hash VARCHAR(64),
            output_hash VARCHAR(64),
            status VARCHAR(50),
            error_ref VARCHAR(50),
            created_at TIMESTAMP WITH TIME ZONE
        );
    """)

    # Payment and purchasing ledgers.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            client_id VARCHAR(100),
            payment_ref VARCHAR(100),
            payer VARCHAR(255),
            amount DECIMAL(10,2),
            currency VARCHAR(10),
            payment_method VARCHAR(50),
            status VARCHAR(50),
            idempotency_key VARCHAR(64),
            raw_message TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS purchase_orders (
        id SERIAL PRIMARY KEY,
        client_id VARCHAR(100) NOT NULL,
        po_number VARCHAR(100),
        vendor VARCHAR(255),
        amount DECIMAL(10,2),
        currency VARCHAR(10) DEFAULT 'USD',
        description TEXT,
        external_id VARCHAR(100),
        status VARCHAR(50) DEFAULT 'open',
        idempotency_key VARCHAR(64) UNIQUE,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
""")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_po_client_status ON purchase_orders(client_id, status);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_po_vendor ON purchase_orders(client_id, vendor);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_po_number ON purchase_orders(client_id, po_number);")
    cur.execute("ALTER TABLE purchase_orders ENABLE ROW LEVEL SECURITY;")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bills (
            id SERIAL PRIMARY KEY,
            client_id VARCHAR(100) NOT NULL,
            vendor VARCHAR(255),
            amount DECIMAL(10,2),
            currency VARCHAR(10) DEFAULT 'USD',
            invoice_number VARCHAR(100),
            po_number VARCHAR(100),
            due_date DATE,
            status VARCHAR(50) DEFAULT 'pending',
            external_id VARCHAR(100),
            idempotency_key VARCHAR(64) UNIQUE,
            raw_data JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_bills_client_status ON bills(client_id, status);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bills_vendor ON bills(client_id, vendor);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bills_po_number ON bills(client_id, po_number);")
    cur.execute("ALTER TABLE bills ENABLE ROW LEVEL SECURITY;")

    # Channel tokens + agent request intake/metrics.
    cur.execute("""
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
""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS agent_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id VARCHAR(100),
    use_case VARCHAR(255),
    agent_type VARCHAR(100),
    business_type VARCHAR(100),
    scale VARCHAR(100),
    integrations TEXT,
    status VARCHAR(50) DEFAULT 'pending',
    admin_notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
    );
""")
    cur.execute("""
                CREATE TABLE IF NOT EXISTS agent_metrics (
    id          BIGSERIAL    PRIMARY KEY,
    client_id   TEXT         NOT NULL,
    agent_name  TEXT         NOT NULL,
    intent      TEXT         NOT NULL,
    action      TEXT,
    status      TEXT         NOT NULL,
    confidence  FLOAT,
    duration_ms INT,
    created_at  TIMESTAMPTZ  DEFAULT NOW()
);
                """)

    # Authentication and OAuth support tables.
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id VARCHAR(36) PRIMARY KEY,
        email VARCHAR(255) UNIQUE NOT NULL,
        name VARCHAR(255) NOT NULL,
        password_hash VARCHAR(255),
        provider VARCHAR(20) DEFAULT 'local' NOT NULL,
        google_id VARCHAR(255) UNIQUE,
        avatar_url VARCHAR(500),
        client_id VARCHAR(100) UNIQUE,
        is_admin BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
""")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token VARCHAR(255) UNIQUE NOT NULL,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token VARCHAR(255) UNIQUE NOT NULL,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            used_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS oauth_states (
            id VARCHAR(36) PRIMARY KEY,
            provider VARCHAR(50) NOT NULL,
            state VARCHAR(255) UNIQUE NOT NULL,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS google_watch_channels (
            id SERIAL PRIMARY KEY,
            client_id VARCHAR(100) NOT NULL,
            resource_type VARCHAR(50) NOT NULL,
            channel_id TEXT NOT NULL,
            resource_id TEXT,
            expiration BIGINT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (client_id, resource_type)
        );
    """)

    # Performance indexes and additive schema evolution for existing deployments.
    cur.execute("CREATE INDEX IF NOT EXISTS idx_google_watch_expiration ON google_watch_channels(expiration);")
    cur.execute("CREATE INDEX ON agent_metrics (agent_name, created_at DESC);")
    cur.execute("CREATE INDEX ON agent_metrics (client_id,  created_at DESC);")
    cur.execute("CREATE INDEX ON agent_metrics (status,     created_at DESC);")
    cur.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS description TEXT;")
    cur.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_payments_payment_ref ON payments(client_id, payment_ref);")

    # Dispute tracking for payment gateway chargebacks.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS disputes (
            id SERIAL PRIMARY KEY,
            client_id VARCHAR(100),
            dispute_id VARCHAR(100) UNIQUE,
            payment_ref VARCHAR(100),
            gateway VARCHAR(50),
            amount DECIMAL(10,2),
            currency VARCHAR(10),
            reason VARCHAR(255),
            status VARCHAR(50),
            due_by TIMESTAMPTZ,
            evidence_submitted BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_disputes_client ON disputes(client_id, status);")
    cur.execute("ALTER TABLE disputes ENABLE ROW LEVEL SECURITY;")
    cur.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64);")
    cur.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64);")
    cur.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64);")
    cur.execute("ALTER TABLE client_integrations ADD COLUMN IF NOT EXISTS refresh_token_expires_at TIMESTAMPTZ;")
    # Backfill uniqueness constraints safely if they were missing in older schemas.
    cur.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'expenses_idempotency_key_unique'
            ) THEN
                ALTER TABLE expenses ADD CONSTRAINT expenses_idempotency_key_unique UNIQUE (idempotency_key);
            END IF;
        END $$;
    """)
    cur.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'invoices_idempotency_key_unique'
            ) THEN
                ALTER TABLE invoices ADD CONSTRAINT invoices_idempotency_key_unique UNIQUE (idempotency_key);
            END IF;
        END $$;
    """)
    cur.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'payments_idempotency_key_unique'
            ) THEN
                ALTER TABLE payments ADD CONSTRAINT payments_idempotency_key_unique UNIQUE (idempotency_key);
            END IF;
        END $$;
    """)

    # Enable row-level security and append newer business columns/indexes.
    cur.execute("ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;")
    cur.execute("ALTER TABLE expenses ENABLE ROW LEVEL SECURITY;")
    cur.execute("ALTER TABLE bookings ENABLE ROW LEVEL SECURITY;")
    cur.execute("ALTER TABLE documents ENABLE ROW LEVEL SECURITY;")
    cur.execute("ALTER TABLE agent_logs ENABLE ROW LEVEL SECURITY;")
    cur.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;")
    cur.execute("ALTER TABLE agent_memory ENABLE ROW LEVEL SECURITY;")
    cur.execute("ALTER TABLE knowledge_base ENABLE ROW LEVEL SECURITY;")
    cur.execute("ALTER TABLE payments ENABLE ROW LEVEL SECURITY;")
    cur.execute("ALTER TABLE agent_requests ADD COLUMN IF NOT EXISTS suggested_agents JSONB DEFAULT '[]';")
    cur.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS due_date DATE;")
    cur.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS sent_at TIMESTAMPTZ;")
    cur.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS reminder_sent_at TIMESTAMPTZ;")
    cur.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS reminder_count INTEGER DEFAULT 0;")
    cur.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS external_id VARCHAR(100);")
    cur.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS currency VARCHAR(10) DEFAULT 'USD';")
    cur.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS approval_status VARCHAR(50) DEFAULT 'pending';")
    cur.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS approved_by VARCHAR(100);")
    cur.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;")
    cur.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS due_date DATE;")
    cur.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS currency VARCHAR(10) DEFAULT 'USD';")
    cur.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS external_id VARCHAR(100);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_channel_tokens_lookup ON channel_tokens(channel, token);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_channel_tokens_client ON channel_tokens(channel, client_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_expenses_approval ON expenses(client_id, approval_status);")
    cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS client_name VARCHAR(255);")
    cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS alert_sent_at TIMESTAMPTZ;")
    cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS alert_count INTEGER DEFAULT 0;")
    cur.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS line_items JSONB DEFAULT '[]';")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_documents_expiry ON documents(client_id, expiry_date, status);")
    cur.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS message TEXT;")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_message ON audit_logs(client_id, agent_name, created_at DESC);")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_invoices_due_date ON invoices(client_id, due_date, status);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_client_integrations_client_id ON client_integrations(client_id);")
    cur.execute("""
    ALTER TABLE clients 
    ADD COLUMN IF NOT EXISTS channel_config JSONB DEFAULT '{}';
    """)

    # Core lookup and vector indexes for API and retrieval performance.
    cur.execute("CREATE INDEX IF NOT EXISTS idx_invoices_client_status ON invoices(client_id, status);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_invoices_idempotency ON invoices(idempotency_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_payments_client_status ON payments(client_id, status);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_payments_idempotency ON payments(idempotency_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_client ON audit_logs(client_id, created_at);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_agent_memory_client ON agent_memory(client_id, agent_name);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_expenses_idempotency ON expenses(idempotency_key);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at DESC);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_agent_requests_client ON agent_requests(client_id, status);")
    
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_memory_embedding
        ON agent_memory USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100);
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_knowledge_base_embedding
        ON knowledge_base USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100);
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_client_id ON users(client_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_refresh_tokens_token ON refresh_tokens(token);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_password_reset_token ON password_reset_tokens(token);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_oauth_states_state ON oauth_states(state);")

    # Extended expense metadata fields and supporting index.
    cur.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS expense_date DATE;")
    cur.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS tax_amount DECIMAL(10,2);")
    cur.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS project_code VARCHAR(100);")
    cur.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS receipt_url TEXT;")
    cur.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS notes TEXT;")
    cur.execute("ALTER TABLE expenses ADD COLUMN IF NOT EXISTS reference VARCHAR(100);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_expenses_reference ON expenses(client_id, reference);")

    # Conditional unique constraints for document and booking de-duplication.
    cur.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'documents_client_doc_filename_unique'
            ) THEN
                ALTER TABLE documents ADD CONSTRAINT documents_client_doc_filename_unique
                UNIQUE (client_id, doc_type, filename);
            END IF;
        END $$;
    """)

    cur.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'bookings_client_booking_ref_unique'
            ) THEN
                ALTER TABLE bookings ADD CONSTRAINT bookings_client_booking_ref_unique
                UNIQUE (client_id, booking_ref);
            END IF;
        END $$;
    """)

    # Close DB resources explicitly after successful schema bootstrap.
    cur.close()
    conn.close()
    print("Database initialized successfully.")


if __name__ == "__main__":
    init_db()