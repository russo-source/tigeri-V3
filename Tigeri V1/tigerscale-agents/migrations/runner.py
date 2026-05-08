"""Contain runner backend logic."""
import os
import psycopg2
from config.settings import settings

def run_migrations():
    """Run migrations."""
    conn = psycopg2.connect(
        host=settings.db_host, port=settings.db_port,
        user=settings.db_user, password=settings.db_password,
        dbname=settings.db_name
    )
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(10) PRIMARY KEY,
            applied_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    conn.commit()

    migration_dir = os.path.join(os.path.dirname(__file__))
    files = sorted(f for f in os.listdir(migration_dir) if f.endswith(".sql"))

    for filename in files:
        version = filename.split("_")[0]
        cur.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (version,))
        if cur.fetchone():
            print(f"[MIGRATION] {filename} already applied, skipping")
            continue
        with open(os.path.join(migration_dir, filename)) as f:
            sql = f.read()
        cur.execute(sql)
        cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
        conn.commit()
        print(f"[MIGRATION] Applied {filename}")

    cur.close()
    conn.close()

if __name__ == "__main__":
    run_migrations()