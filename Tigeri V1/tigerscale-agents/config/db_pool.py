"""PostgreSQL connection pool helpers with retry-safe checkout logic."""
import threading
import time
from psycopg2 import pool, OperationalError, InterfaceError
from contextlib import contextmanager
from config.settings import settings

_pool = None
_lock = threading.Lock()

DB_MIN_CONN = 2
DB_MAX_CONN = int(getattr(settings, "db_max_connections", 20))
CONN_TIMEOUT = 10
MAX_RETRIES = 2


def _get_pool():
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                _pool = pool.ThreadedConnectionPool(
                    minconn=DB_MIN_CONN,
                    maxconn=DB_MAX_CONN,
                    host=settings.db_host,
                    port=settings.db_port,
                    user=settings.db_user,
                    password=settings.db_password,
                    dbname=settings.db_name,
                    connect_timeout=CONN_TIMEOUT,
                    sslmode=getattr(settings, "db_sslmode", "require"),
                    keepalives=1,
                    keepalives_idle=30,
                    keepalives_interval=5,
                    keepalives_count=3,
                )
    return _pool


def _is_conn_usable(conn) -> bool:
    if conn.closed:
        return False
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.autocommit = False
        return True
    except (OperationalError, InterfaceError):
        return False


def _get_fresh_conn(p):
    conn = p.getconn()
    if not _is_conn_usable(conn):
        try:
            p.putconn(conn, close=True)
        except Exception:
            pass
        conn = p.getconn()
        if not _is_conn_usable(conn):
            try:
                p.putconn(conn, close=True)
            except Exception:
                pass
            raise OperationalError("Could not obtain a usable connection from the pool")
    return conn


@contextmanager
def get_conn():
    p = _get_pool()
    conn = None
    broken = False

    for attempt in range(MAX_RETRIES):
        try:
            conn = _get_fresh_conn(p)
            break
        except (OperationalError, InterfaceError):
            if conn:
                try:
                    p.putconn(conn, close=True)
                except Exception:
                    pass
                conn = None
            if attempt < MAX_RETRIES - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            raise

    if conn is None:
        raise OperationalError("Failed to acquire a database connection")

    try:
        yield conn
        conn.commit()
    except (OperationalError, InterfaceError):
        broken = True
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            p.putconn(conn, close=broken)
        except Exception:
            pass


def close_pool():
    global _pool
    if _pool:
        try:
            _pool.closeall()
        except Exception:
            pass
        _pool = None