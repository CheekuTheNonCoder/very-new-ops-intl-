"""
database_loader.py — Local SQLite Database Sync Engine (v5.0)
Responsible only for low-level SQLite database operations.
"""
import os
import sqlite3
import pandas as pd
from datetime import datetime

DB_PATH = "operations.db"


def get_connection():
    """Establishes and returns an optimized connection to the local SQLite database."""
    # Timeout set to 30.0s to prevent concurrent database lock blocks
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    # Enable WAL mode for thread-safe concurrent reading/writing
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db():
    """Creates the operational schema tables and registries if they do not exist."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        
        # Configuration metadata
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS config (
            setting TEXT PRIMARY KEY,
            value TEXT
        )
        """)
        
        # Canonical Brand Registry
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS brand_registry (
            canonical_brand TEXT PRIMARY KEY,
            aliases TEXT,
            confidence REAL
        )
        """)
        
        # Canonical Product Registry
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS product_registry (
            canonical_product TEXT,
            brand TEXT,
            variants TEXT,
            sku TEXT,
            confidence REAL,
            PRIMARY KEY (canonical_product, brand)
        )
        """)
        conn.commit()
    finally:
        conn.close()


def sanitize_for_sqlite(df):
    """
    Sanitizes all columns of a DataFrame to ensure they are 100% compatible with SQLite.
    Converts category, Period, tz-aware datetimes, and complex object columns cleanly to standard string text.
    """
    df_clean = df.copy()
    for col in df_clean.columns:
        # Convert categoricals cleanly to string
        if isinstance(df_clean[col].dtype, pd.CategoricalDtype):
            df_clean[col] = df_clean[col].astype(str)
            continue
            
        # Convert standard datetimes to ISO formatted strings
        if pd.api.types.is_datetime64_any_dtype(df_clean[col]):
            df_clean[col] = df_clean[col].dt.strftime("%Y-%m-%d %H:%M:%S").fillna("")
            continue
            
        # Standardize object/mixed columns safely to text strings or clean floats
        if pd.api.types.is_object_dtype(df_clean[col]):
            try:
                # Try parsing numeric entries (like numeric Order IDs or counts)
                df_clean[col] = pd.to_numeric(df_clean[col])
            except Exception:
                # Cast all other mixed object items safely to text strings
                df_clean[col] = df_clean[col].apply(lambda x: "" if pd.isna(x) else str(x))
                
    return df_clean


def save_orders_to_db(df):
    """Saves orders DataFrame directly to SQLite and builds query performance indexes."""
    init_db()
    conn = get_connection()
    try:
        # Sanitize dataframe first to secure 100% ingestion success in SQLite
        df_clean = sanitize_for_sqlite(df)
        df_clean.to_sql("orders", conn, if_exists="replace", index=False)
        
        cursor = conn.cursor()
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_id ON orders (order_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_brand ON orders (brand)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (order_status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_del_month ON orders (\"Delivery Month\")")
        
        cursor.execute("INSERT OR REPLACE INTO config (setting, value) VALUES ('orders_last_updated', ?)", 
                       (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
        conn.commit()
    finally:
        conn.close()


def save_tickets_to_db(df):
    """Saves tickets DataFrame directly to SQLite and applies database indexes."""
    init_db()
    conn = get_connection()
    try:
        # Sanitize dataframe first to secure 100% ingestion success in SQLite
        df_clean = sanitize_for_sqlite(df)
        df_clean.to_sql("tickets", conn, if_exists="replace", index=False)
        
        cursor = conn.cursor()
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tickets_order_id ON tickets (order_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tickets_brand ON tickets (brand)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tickets_cat ON tickets (ticket_category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tickets_tick_month ON tickets (\"Ticket Month\")")
        
        cursor.execute("INSERT OR REPLACE INTO config (setting, value) VALUES ('tickets_last_updated', ?)", 
                       (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
        conn.commit()
    finally:
        conn.close()


def load_raw_orders_from_db():
    """Loads raw orders from the SQLite database."""
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    conn = get_connection()
    try:
        df = pd.read_sql_query("SELECT * FROM orders", conn)
    except Exception:
        df = pd.DataFrame()
    finally:
        conn.close()
    return df


def load_raw_tickets_from_db():
    """Loads raw tickets from the SQLite database."""
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    conn = get_connection()
    try:
        df = pd.read_sql_query("SELECT * FROM tickets", conn)
    except Exception:
        df = pd.DataFrame()
    finally:
        conn.close()
    return df


def get_database_stats():
    """Fetches real-time database counts and update timestamps."""
    stats = {
        "total_orders": 0,
        "total_tickets": 0,
        "orders_last_updated": "Never",
        "tickets_last_updated": "Never"
    }
    if not os.path.exists(DB_PATH):
        return stats
        
    conn = get_connection()
    try:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM orders")
            stats["total_orders"] = cursor.fetchone()[0]
        except Exception:
            pass
            
        try:
            cursor.execute("SELECT COUNT(*) FROM tickets")
            stats["total_tickets"] = cursor.fetchone()[0]
        except Exception:
            pass
            
        try:
            cursor.execute("SELECT value FROM config WHERE setting = 'orders_last_updated'")
            row = cursor.fetchone()
            if row:
                stats["orders_last_updated"] = row[0]
        except Exception:
            pass
            
        try:
            cursor.execute("SELECT value FROM config WHERE setting = 'tickets_last_updated'")
            row = cursor.fetchone()
            if row:
                stats["tickets_last_updated"] = row[0]
        except Exception:
            pass
    finally:
        conn.close()
    return stats
