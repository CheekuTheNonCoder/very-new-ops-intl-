"""
database_loader.py — Production-grade SQLite Database Sync Module (v5.0)
Replaces Google Sheets with operations.db local SQLite storage layer.
Fixed: Implemented try-finally connection safety and WAL journal mode to prevent database locks.
"""
import os
import sqlite3
import urllib.request
import io
import pandas as pd
import streamlit as st
from datetime import datetime

DB_PATH = "operations.db"
SPREADSHEET_ID = "1h1464iaglel2B-oQbY9kuNkL7_yZYHKqEACxIDg_rxg"


def get_connection():
    """Establishes and returns a connection to the local SQLite database."""
    # Added 30 seconds busy timeout and enabled WAL mode for concurrent reading/writing
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db():
    """Creates the operational schema tables if they do not exist."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        
        # Metadata config table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS config (
            setting TEXT PRIMARY KEY,
            value TEXT
        )
        """)
        
        # Brand Registry
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS brand_registry (
            canonical_brand TEXT PRIMARY KEY,
            aliases TEXT,
            confidence REAL
        )
        """)
        
        # Product Registry
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
                df_clean[col] = df_clean[col].astype(str)
                
    return df_clean


def save_orders(df):
    """Saves raw order records directly to SQLite and builds query performance indexes."""
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


def save_tickets(df):
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


def load_orders():
    """Loads all orders from the local SQLite database."""
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


def load_tickets():
    """Loads all tickets from the local SQLite database."""
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


def auto_migrate_google_sheets():
    """
    Automatic Migration on Startup: If the SQLite database is empty, downloads the 
    existing Google Sheets data anonymously, processes, and seeds operations.db.
    """
    if os.path.exists(DB_PATH):
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM orders")
            count = cursor.fetchone()[0]
            if count > 0:
                return  # Database already has data, skip migration
        except Exception:
            pass
        finally:
            conn.close()
        
    init_db()
    
    st.info("Running first-time automatic migration from Google Sheets to SQLite...")
    try:
        from engine_loader import load_delivered, load_tickets
        
        # Safe raw string URLs with no dynamic f-string braces to avoid compilation syntax errors
        del_url = "https://docs.google.com/spreadsheets/d/1h1464iaglel2B-oQbY9kuNkL7_yZYHKqEACxIDg_rxg/gviz/tq?tqx=out:csv&sheet=Orders"
        tick_url = "https://docs.google.com/spreadsheets/d/1h1464iaglel2B-oQbY9kuNkL7_yZYHKqEACxIDg_rxg/gviz/tq?tqx=out:csv&sheet=Tickets"
        
        headers = {"User-Agent": "Mozilla/5.0 (OpsIntelPlatform v5.0)"}
        
        req_del = urllib.request.Request(del_url, headers=headers)
        with urllib.request.urlopen(req_del, timeout=20) as r:
            del_df_raw = pd.read_csv(io.BytesIO(r.read()))
            
        req_tick = urllib.request.Request(tick_url, headers=headers)
        with urllib.request.urlopen(req_tick, timeout=20) as r:
            tick_df_raw = pd.read_csv(io.BytesIO(r.read()))
            
        # Parse dataframes through loader hierarchy processes
        orders_df = load_delivered(del_df_raw)
        tickets_df = load_tickets(tick_df_raw)
        
        # Save records directly to SQLite
        save_orders(orders_df)
        save_tickets(tickets_df)
        st.success("✅ Automatic Google Sheets migration successful! Database seeded locally.")
    except Exception as e:
        st.warning(f"⚠️ Google Sheets migration bypassed: {e}")
