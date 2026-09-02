"""
app.py — OPX Operations Intelligence Platform (v4.5 - Welcome & Dynamic Themes)
Main entrance splits dynamically into ZOP (Yellow) or Afora (Green) workspaces.
"""
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import json
import os
import sqlite3

from database_loader import load_orders, load_tickets, save_orders, save_tickets, get_database_stats, init_db
from engine_loader import process_pipeline, generate_dynamic_periods, load_delivered, load_tickets_raw
from engine_analytics import (
    compute_brand_summary, compute_product_summary,
    compute_cohort_report, compute_weekly_trends, top_kpis, raw_esc,
    compute_subcat_summary, HIGH_SUBCATS
)
from engine_export import generate_excel_report

st.set_page_config(
    page_title="OPX Operations Intelligence",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 1. INITIALIZE DATABASE ──
init_db()
db_stats = get_database_stats()

# ── DATABASE QUALITY HEALTH & SELF-HEALING CHECK ──
@st.cache_data(show_spinner=False)
def check_db_health(tickets_last_updated):
    if db_stats["total_tickets"] == 0:
        return False
    conn = sqlite3.connect("operations.db")
    try:
        df = pd.read_sql_query("SELECT DISTINCT raw_subcat FROM tickets", conn)
        unique_subcats = set(df["raw_subcat"].dropna().unique())
        valid_unique_subcats = {s for s in unique_subcats if s.strip() and s.lower() not in ("nan", "none", "null")}
        if valid_unique_subcats and valid_unique_subcats.issubset({"POST_DELIVERY", "PRE_DELIVERY"}):
            return True
    except Exception:
        pass
    finally:
        conn.close()
    return False

corrupt_db_flag = check_db_health(db_stats['tickets_last_updated'])
if corrupt_db_flag:
    if os.path.exists("operations.db"):
        try:
            os.remove("operations.db")
            st.cache_data.clear()
            st.rerun()
        except Exception:
            pass

# ── INITIALIZE PORTAL SELECTION STATE ──
if "marketplace" not in st.session_state:
    st.session_state["marketplace"] = None

# ── 2. PORTAL SELECTION GATEWAY (WELCOME SCREEN) ──
if st.session_state["marketplace"] is None:
    # Full screen layout styling for split cards
    st.markdown("""
    <div style="text-align: center; margin-top: 5vh; margin-bottom: 5vh;">
        <h1 style="color: #FFFFFF; font-weight: 800; font-size: 38px; letter-spacing: 0.05em; margin: 0;">SELECT OPERATIONS PORTAL</h1>
        <p style="color: #64748B; font-size: 14px; font-weight: 500; margin-top: 8px;">Switch workspaces instantly based on your target segment analysis.</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    with col1:
        # ZOP Card Matching Image Colors (Bright Yellow)
        st.markdown("""
        <div style="background-color: #FFF41A; padding: 4rem 2rem; border-radius: 20px; text-align: center; border: 2px solid #E4DA15; box-shadow: 0 10px 30px rgba(255, 244, 26, 0.15); margin-bottom: 20px;">
            <h2 style="color: #000000; font-family: 'Inter', sans-serif; font-weight: 900; font-size: 64px; margin: 0; letter-spacing: -0.05em; line-height: 1.1;">Zop</h2>
            <p style="color: #1A1A1A; font-weight: 700; font-size: 13px; text-transform: uppercase; letter-spacing: 0.15em; margin-top: 15px;">Core Deliveries & Direct Logistics</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("🔌 Access ZOP Workplace", use_container_width=True, key="access_zop_btn"):
            st.session_state["marketplace"] = "ZOP"
            st.rerun()
            
    with col2:
        # Afora Card Matching Image Colors (Soft Light Green)
        st.markdown("""
        <div style="background-color: #C6E2A3; padding: 4rem 2rem; border-radius: 20px; text-align: center; border: 2px solid #B0CC8E; box-shadow: 0 10px 30px rgba(198, 226, 163, 0.15); margin-bottom: 20px;">
            <h2 style="color: #000000; font-family: 'Inter', sans-serif; font-weight: 900; font-size: 64px; margin: 0; letter-spacing: -0.05em; line-height: 1.1;">afora</h2>
            <p style="color: #2D2D2D; font-weight: 700; font-size: 13px; text-transform: uppercase; letter-spacing: 0.15em; margin-top: 15px;">Alternative Marketplace Integrator</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("🔌 Access Afora Workplace", use_container_width=True, key="access_afora_btn"):
            st.session_state["marketplace"] = "Afora"
            st.rerun()
            
    st.stop() # Stop rendering the main dashboard if no workspace is selected

# ── 3. DYNAMIC PORTAL ACCENT THEME DESIGNER ──
if st.session_state["marketplace"] == "ZOP":
    theme_accent = "#FFF41A" # Zop Yellow Accent
    theme_accent_light = "rgba(255, 244, 26, 0.12)"
    theme_border = "rgba(255, 244, 26, 0.25)"
    theme_glow = "0 4px 20px rgba(255, 244, 26, 0.12)"
else:
    theme_accent = "#C6E2A3" # Afora Pastel Green Accent
    theme_accent_light = "rgba(198, 226, 163, 0.12)"
    theme_border = "rgba(198, 226, 163, 0.25)"
    theme_glow = "0 4px 20px rgba(198, 226, 163, 0.12)"

# Dynamic custom theme injection
st.markdown(f"""
<style>
html, body, [data-testid="stAppViewContainer"] {{
    background: #080B11 !important;
    font-family: 'Inter', sans-serif !important;
    color: #E2E8F0 !important;
}}
.kpi-card {{
    background: rgba(17, 24, 39, 0.7) !important;
    backdrop-filter: blur(12px);
    border: 1px solid {theme_border} !important;
    border-radius: 12px !important;
    padding: 1.25rem;
    margin-bottom: 1rem;
    transition: all 0.2s ease-in-out;
}}
.kpi-card:hover {{
    transform: translateY(-2px);
    border-color: {theme_accent} !important;
    box-shadow: {theme_glow} !important;
}}
.kpi-card.blue {{ border-left: 4px solid {theme_accent} !important; }}
.badge {{
    color: {theme_accent} !important;
    border-color: {theme_border} !important;
}}
button[kind="secondary"] {{
    border-color: {theme_border} !important;
    color: {theme_accent} !important;
}}
</style>
""", unsafe_allow_html=True)

# ── 4. SIDEBAR CONFIGURATIONS & INTERFACE ──
with st.sidebar:
    st.markdown(f"""
    <div style="display: flex; align-items: center; gap: 14px; margin-bottom: 1.5rem; margin-top: 1rem;">
        <svg width="46" height="46" viewBox="0 0 46 46" fill="none" style="filter: drop-shadow(0px 0px 8px {theme_accent});">
            <path d="M23 2C32 2 39 5 39 12V24C39 31.5 32.5 38 23 44C13.5 38 7 31.5 7 24V12C7 5 14 2 23 2Z" fill="#0F172A" stroke="{theme_accent}" stroke-width="2"/>
            <text x="50%" y="58%" dominant-baseline="middle" text-anchor="middle" font-family="'Inter', sans-serif" font-weight="900" font-size="11" fill="#FFFFFF">OPX</text>
        </svg>
        <div>
            <h2 style="margin:0; font-size:18px; font-weight:700; color:#FFFFFF; letter-spacing:0.05em; line-height:1.2;">OPX</h2>
            <p style="margin:0; font-size:9px; color:#64748B; font-weight:600; text-transform:uppercase;">{st.session_state["marketplace"]} Workspace</p>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    st.divider()
    view_mode = st.radio("Select Console Portal", ["📈 Public Dashboard", "🔐 Admin Control Panel"], index=0)
    
    st.divider()
    
    # Marketplace Fast Switcher
    st.markdown("**Active Portal Workspace**")
    switch_mkt = st.selectbox("Active Workspace", ["ZOP", "Afora"], index=0 if st.session_state["marketplace"] == "ZOP" else 1)
    if switch_mkt != st.session_state["marketplace"]:
        st.session_state["marketplace"] = switch_mkt
        st.rerun()
        
    if st.button("🔙 Switch to Entrance Hub", use_container_width=True):
        st.session_state["marketplace"] = None
        st.rerun()

    st.divider()
    if view_mode == "📈 Public Dashboard":
        st.markdown("**Severity Threshold Metrics**")
        with st.expander("Configure Matrix Thresholds"):
            crit_del = st.number_input("Critical Min Deliveries", value=300, step=50)
            crit_esc = st.number_input("Critical Min Esc %", value=7.0, step=0.5)
            crit_tix = st.number_input("Critical Min Tickets", value=25, step=5)
            high_del = st.number_input("High Min Deliveries", value=200, step=50)
            high_esc = st.number_input("High Min Esc %", value=5.0, step=0.5)
            med_del  = st.number_input("Medium Min Deliveries", value=100, step=25)
            med_esc  = st.number_input("Medium Min Esc %", value=3.0, step=0.5)

        st.divider()
        ai_on = st.toggle("Enable AI Analysis Panel", value=False)
        api_key = ""
        if ai_on:
            try:
                api_key = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
            except:
                api_key = ""
            if not api_key:
                api_key = st.text_input("GCP Gemini API Key", type="password")
    else:
        st.markdown("**Database Statistics**")
        st.metric("Total Orders In DB", f"{db_stats['total_orders']:,}")
        st.metric("Total Tickets In DB", f"{db_stats['total_tickets']:,}")
        st.caption(f"Orders Updated: {db_stats['orders_last_updated']}")
        st.caption(f"Tickets Updated: {db_stats['tickets_last_updated']}")

    st.divider()
    st.caption("v4.5 • Dynamic Theme Edition")

def kpi(label, value, sub="", color="blue"):
    st.markdown(f"""
    <div class="kpi-card {color}">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem;">
            <span style="font-size: 11px; font-weight: 700; color: #94A3B8; text-transform: uppercase;">{label}</span>
        </div>
        <h3 style="font-size: 26px; font-weight: 800; color: #F8FAFC; margin: 0;">{value}</h3>
        <p style="font-size: 10px; color: #64748B; margin: 4px 0 0 0;">{sub}</p>
    </div>
    """, unsafe_allow_html=True)

# ── PIPELINE CALCULATIONS ENGINE RUNNER WITH TIMESTAMP HASHING ──
@st.cache_data(show_spinner=False)
def run_pipeline_cached(orders_updated, tickets_updated, app_version="v4.5"):
    del_df_raw = load_orders()
    tick_df_raw = load_tickets()
    
    # ── SELF-HEALING FALLBACK FOR OLD DATABASES ──
    # If users run this updated version against an existing SQLite file without marketplace columns,
    # we automatically heal the tables on-the-fly to prevent any SQL schema errors.
    if not del_df_raw.empty and "marketplace" not in del_df_raw.columns:
        is_a_del = del_df_raw["order_id"].astype(str).str.upper().str.contains("AFORA", na=False)
        del_df_raw["marketplace"] = np.where(is_a_del, "Afora", "ZOP")
        
    if not tick_df_raw.empty and "marketplace" not in tick_df_raw.columns:
        is_a_tick = tick_df_raw["order_id"].astype(str).str.upper().str.contains("AFORA", na=False)
        tick_df_raw["marketplace"] = np.where(is_a_tick, "Afora", "ZOP")
        
    return process_pipeline(del_df_raw, tick_df_raw)

# ── COLD START DATA VALIDATOR ──
if db_stats["total_orders"] == 0 or db_stats["total_tickets"] == 0:
    if view_mode == "📈 Public Dashboard":
        st.markdown("## 📦 OPX")
        st.caption("Operations Intelligence Platform")
        st.warning("⚠️ No operational data loaded in SQLite database yet. Please select '🔐 Admin Control Panel' in the sidebar to upload files.")
        st.stop()

# ── INGESTION LAYER (ADMIN CONTROL PANEL VIEW) ──
if view_mode == "🔐 Admin Control Panel":
    st.markdown("## 🔐 Admin Database Control Panel")
    admin_password = st.text_input("Enter Admin Access Password", type="password")
    if admin_password != st.secrets.get("ADMIN_PASSWORD", "admin123"):
        if admin_password:
            st.error("❌ Access denied. Incorrect Admin Password.")
        st.stop()
        
    st.success("🔓 Access Granted. Administrative functions unlocked.")
    st.divider()
    
    imp_col1, imp_col2 = st.columns(2)
    with imp_col1:
        st.markdown("### 📥 Import Orders")
        orders_file = st.file_uploader("Upload Delivered Orders Sheet", type=["xlsx", "xls", "csv"], key="orders_up")
        if orders_file and st.button("🚀 Process & Import Orders", use_container_width=True):
            try:
                with st.spinner("Processing Orders data and updating SQLite..."):
                    raw_df = pd.read_csv(orders_file) if orders_file.name.endswith(".csv") else pd.read_excel(orders_file)
                    orders_df = load_delivered(raw_df)
                    save_orders(orders_df)
                st.success(f"✅ Imported {len(orders_df):,} Order rows successfully!")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"❌ Orders Import Failed: {e}")
                
    with imp_col2:
        st.markdown("### 📥 Import Tickets")
        tickets_file = st.file_uploader("Upload Tickets Dump Sheet", type=["xlsx", "xls", "csv"], key="tickets_up")
        if tickets_file and st.button("🚀 Process & Import Tickets", use_container_width=True):
            try:
                with st.spinner("Processing Tickets data and updating SQLite..."):
                    raw_df = pd.read_csv(tickets_file) if tickets_file.name.endswith(".csv") else pd.read_excel(tickets_file)
                    tickets_df = load_tickets_raw(raw_df)
                    save_tickets(tickets_df)
                st.success(f"✅ Imported {len(tickets_df):,} Ticket rows successfully!")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"❌ Tickets Import Failed: {e}")
                
    st.divider()
    if st.button("🚨 Purge & Reset Database", use_container_width=True):
        if os.path.exists("operations.db"):
            os.remove("operations.db")
            st.success("🔥 Local database deleted!")
            st.cache_data.clear()
            st.rerun()
    st.stop()

# ── RUN CALCULATIONS (INSTANT FROM CACHE) ──
try:
    D = run_pipeline_cached(db_stats["orders_last_updated"], db_stats["tickets_last_updated"])
except Exception as e:
    st.error(f"❌ Pipeline Execution Error: {e}")
    st.stop()

del_df = D["del_df"]
tick_df = D["tick_df"]
registry = D["registry"]
redist_sum = D["redist_summary"]

orig = D.get("original_ticket_count", 0)
final_c = D.get("final_ticket_count", 0)
val_ok = D.get("validation_ok", False)

# ── BIFURCATE DATA BASED ON SELECTION ──
selected_mkt = st.session_state["marketplace"]
f_del_mkt = del_df[del_df["marketplace"] == selected_mkt].copy()
f_tick_mkt = tick_df[tick_df["marketplace"] == selected_mkt].copy()

# Pre-calculate period lists for filtered marketplace
period_options = generate_dynamic_periods(f_del_mkt, "raw_date")
available_months = sorted(f_del_mkt["Delivery Month Sort"].dropna().unique())

# ── TIME INTELLIGENCE & FILTER INTERFACE ──
st.markdown("### 📊 Time Intelligence Filter")
selected_period = st.selectbox("Select Filter Period", period_options)

# Vectorized Date Slicing (Instant)
if selected_period == "All Data":
    f_del = f_del_mkt.copy()
    f_tick = f_tick_mkt.copy()
else:
    if "," in selected_period:
        try:
            parsed_date_str = str(pd.to_datetime(selected_period, format="%B %d, %Y").date())
            f_del = f_del_mkt[f_del_mkt["Delivery Date"] == parsed_date_str].copy()
            f_tick = f_tick_mkt[f_tick_mkt["Ticket Date"] == parsed_date_str].copy()
        except Exception:
            f_del = f_del_mkt[f_del_mkt["Delivery Month"] == selected_period].copy()
            f_tick = f_tick_mkt[f_tick_mkt["Ticket Month"] == selected_period].copy()
    else:
        f_del = f_del_mkt[f_del_mkt["Delivery Month"] == selected_period].copy()
        f_tick = f_tick_mkt[f_tick_mkt["Ticket Month"] == selected_period].copy()

# ── OPERATIONS UNIVERSE SEGMENT SELECTOR ──
st.markdown("### 🔍 Segment Category Filter")
analysis_mode = st.radio(
    "Active Segment Filter",
    ["Post Delivery", "Pre Delivery", "Combined"],
    horizontal=True
)

if analysis_mode == "Post Delivery":
    f_del_universe = f_del[f_del["is_delivered"] == True].copy()
    f_tick_universe = f_tick[f_tick["ticket_category"] == "POST_DELIVERY"].copy()
elif analysis_mode == "Pre Delivery":
    f_del_universe = f_del.copy()
    f_tick_universe = f_tick[f_tick["ticket_category"] == "PRE_DELIVERY"].copy()
else:
    f_del_universe = f_del.copy()
    f_tick_universe = f_tick.copy()

# ── CALCULATE ACTIVE VARIABLES SAFELY FOR GENERAL SCOPE ──
status_col = "order_status" if "order_status" in f_del.columns else None
v_orders_filter = len(f_del)
v_delivered_rows = len(f_del[f_del[status_col].astype(str).str.strip().str.lower() == "delivered"]) if status_col else len(f_del)
v_all_status_rows = len(f_del)
v_post_tickets = len(f_tick[f_tick["ticket_category"] == "POST_DELIVERY"])
v_pre_tickets = len(f_tick[f_tick["ticket_category"] == "PRE_DELIVERY"])

v_post_esc = f"{v_post_tickets:,} / {v_delivered_rows:,} = {round((v_post_tickets / max(v_delivered_rows, 1)) * 100, 2)}%"
v_pre_esc = f"{v_pre_tickets:,} / {v_all_status_rows:,} = {round((v_pre_tickets / max(v_all_status_rows, 1)) * 100, 2)}%"

# ── RUN SEGMENT ANALYTICS (KEYWORD PARAMS SAFE) ──
brand_sum = compute_brand_summary(
    del_df=f_del_universe, 
    tick_df=f_tick_universe, 
    analysis_mode=analysis_mode,
    crit_del=int(crit_del),
    crit_esc=float(crit_esc),
    crit_tix=int(crit_tix),
    high_del=int(high_del),
    high_esc=float(high_esc),
    med_del=int(med_del),
    med_esc=float(med_esc)
)
prod_sum = compute_product_summary(
    del_df=f_del_universe, 
    tick_df=f_tick_universe, 
    analysis_mode=analysis_mode,
    crit_del=int(crit_del),
    crit_esc=float(crit_esc),
    crit_tix=int(crit_tix),
    high_del=int(high_del),
    high_esc=float(high_esc),
    med_del=int(med_del),
    med_esc=float(med_esc)
)
cohort_report = compute_cohort_report(f_del_universe, f_tick_universe)
weeks_list = sorted(f_del_universe["Delivery Week"].unique())
weekly_trends = compute_weekly_trends(f_del_universe, f_tick_universe, weeks_list)
subcat_sum = compute_subcat_summary(f_tick_universe)

# Single Source of Truth KPIs
overall_orders_count = len(f_del_universe)
overall_tickets_count = len(f_tick_universe)
overall_esc_rate = round((overall_tickets_count / max(overall_orders_count, 1)) * 100, 2)

subcat_col = "subcat_final" if "subcat_final" in f_tick_universe.columns else "raw_subcat"
defect_tickets_count = len(f_tick_universe[f_tick_universe[subcat_col].isin(HIGH_SUBCATS)]) if not f_tick_universe.empty else 0
overall_defect_rate = round((defect_tickets_count / max(overall_orders_count, 1)) * 100, 2)

kpis = top_kpis(brand_sum, prod_sum, subcat_sum, f_tick_universe, f_del_universe, weeks_list)

# ── HISTORICAL MOVEMENT COMPARISON ──
comp_df_brand = pd.DataFrame()
comp_df_prod = pd.DataFrame()
has_comparison = len(available_months) >= 2

if has_comparison:
    m_names = [pd.to_datetime(m + "-01", format="%Y-%m-%d", errors="coerce") for m in available_months]
    m_names = [d.strftime("%B %Y") if pd.notna(d) else str(d) for d in m_names]
    month_a = m_names[-2]
    month_b = m_names[-1]
    
    del_a = f_del_mkt[f_del_mkt["Delivery Month"] == month_a]
    tick_a = f_tick_mkt[f_tick_mkt["Delivery Month"] == month_a]
    del_b = f_del_mkt[f_del_mkt["Delivery Month"] == month_b]
    tick_b = f_tick_mkt[f_tick_mkt["Delivery Month"] == month_b]
    
    brand_a = compute_brand_summary(del_df=del_a, tick_df=tick_a, analysis_mode=analysis_mode, crit_del=crit_del, crit_esc=crit_esc, crit_tix=crit_tix, high_del=high_del, high_esc=high_esc, med_del=med_del, med_esc=med_esc).set_index("brand")
    brand_b = compute_brand_summary(del_df=del_b, tick_df=tick_b, analysis_mode=analysis_mode, crit_del=crit_del, crit_esc=crit_esc, crit_tix=crit_tix, high_del=high_del, high_esc=high_esc, med_del=med_del, med_esc=med_esc).set_index("brand")
    
    comp_df_brand = pd.DataFrame(index=sorted(list(set(brand_a.index) | set(brand_b.index))))
    comp_df_brand["Month A Esc %"] = comp_df_brand.index.map(brand_a["esc_pct"]).fillna(0.0)
    comp_df_brand["Month B Esc %"] = comp_df_brand.index.map(brand_b["esc_pct"]).fillna(0.0)
    comp_df_brand["Esc % Difference"] = (comp_df_brand["Month B Esc %"] - comp_df_brand["Month A Esc %"]).round(2)
    comp_df_brand["Esc Movement Status"] = comp_df_brand["Esc % Difference"].apply(
        lambda x: "🚨 INCREASE" if x > 1.0 else "✅ DECREASE" if x < -1.0 else "→ STABLE"
    )
    comp_df_brand = comp_df_brand.reset_index().rename(columns={"index": "Brand"})

    prod_a = compute_product_summary(del_df=del_a, tick_df=tick_a, analysis_mode=analysis_mode, crit_del=crit_del, crit_esc=crit_esc, crit_tix=crit_tix, high_del=high_del, high_esc=high_esc, med_del=med_del, med_esc=med_esc).set_index("brand_product")
    prod_b = compute_product_summary(del_df=del_b, tick_df=tick_b, analysis_mode=analysis_mode, crit_del=crit_del, crit_esc=crit_esc, crit_tix=crit_tix, high_del=high_del, high_esc=high_esc, med_del=med_del, med_esc=med_esc).set_index("brand_product")
    
    comp_df_prod = pd.DataFrame(index=sorted(list(set(prod_a.index) | set(prod_b.index))))
    comp_df_prod["Month A Esc %"] = comp_df_prod.index.map(prod_a["esc_pct"]).fillna(0.0)
    comp_df_prod["Month B Esc %"] = comp_df_prod.index.map(prod_b["esc_pct"]).fillna(0.0)
    comp_df_prod["Esc % Difference"] = (comp_df_prod["Month B Esc %"] - comp_df_prod["Month A Esc %"]).round(2)
    comp_df_prod["Esc Movement Status"] = comp_df_prod["Esc % Difference"].apply(
        lambda x: "🚨 INCREASE" if x > 1.0 else "✅ DECREASE" if x < -1.0 else "→ STABLE"
    )
    comp_df_prod = comp_df_prod.reset_index().rename(columns={"index": "brand_product"})
    comp_df_prod["Brand"] = comp_df_prod["brand_product"].apply(lambda x: x.split(" | ")[0] if " | " in str(x) else str(x))
    comp_df_prod["Product"] = comp_df_prod["brand_product"].apply(lambda x: x.split(" | ")[1] if " | " in str(x) else "")
    comp_df_prod = comp_df_prod[["Brand", "Product", "Month A Esc %", "Month B Esc %", "Esc % Difference", "Esc Movement Status"]]

# ── KPI METRICS DISPLAY ──
st.markdown(f"### 📊 Active Segment {st.session_state['marketplace'].upper()} Performance Overview")
if analysis_mode == "Combined":
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1: kpi("Delivered Orders", f"{v_delivered_rows:,}", "Post Denominator", "blue")
    with c2: kpi("Total Orders", f"{v_all_status_rows:,}", "Pre Denominator", "blue")
    with c3: kpi("Post Tickets", f"{v_post_tickets:,}", "Post Numerator", "orange")
    with c4: kpi("Pre Tickets", f"{v_pre_tickets:,}", "Pre Numerator", "orange")
    with c5: kpi("Post Escalation %", f"{v_post_esc.split(' = ')[1]}", "Post Tickets ÷ Delivered", "amber" if v_post_tickets/max(v_delivered_rows,1)*100 >= 3.0 else "green")
    with c6: kpi("Pre Escalation %", f"{v_pre_esc.split(' = ')[1]}", "Pre Tickets ÷ Total", "amber" if v_pre_tickets/max(v_all_status_rows,1)*100 >= 3.0 else "green")
else:
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: kpi("Delivered Orders" if analysis_mode == "Post Delivery" else "Total Orders", f"{overall_orders_count:,}", "Orders count", "blue")
    with c2: kpi("Tickets", f"{overall_tickets_count:,}", "Total support requests", "orange")
    with c3: kpi("Escalation %", f"{overall_esc_rate}%", "Tickets ÷ orders", "amber" if overall_esc_rate >= 3.0 else "green")
    with c4: kpi("Defect %", f"{overall_defect_rate}%", "Quality issues ÷ orders", "purple")
    with c5: kpi("Peak Week", str(kpis['spike_week']), "Highest volume week", "green")

st.divider()

# ── EXECUTIVE RISK OVERVIEW ROWS ──
c_left, c_right = st.columns(2)
with c_left:
    st.markdown('**Top Escalation Risk Brand Profiles**')
    if not brand_sum.empty:
        for _, row in brand_sum.head(3).iterrows():
            esc_val = row['esc_pct']
            risk_class = "critical-alert kpi-card" if esc_val >= crit_esc else "kpi-card"
            badge = "CRITICAL" if esc_val >= crit_esc else "HIGH" if esc_val >= high_esc else "MEDIUM" if esc_val >= med_esc else "LOW"
            accent_color = "#EF4444" if esc_val >= crit_esc else "#F97316" if esc_val >= high_esc else "#F59E0B" if esc_val >= med_esc else "#22C55E"
            
            st.markdown(f"""
            <div class="{risk_class}" style="border-left: 4px solid {accent_color} !important;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <b style="color: #F8FAFC; font-size: 14px;">{row['brand']}</b>
                    <span class="badge" style="color:{accent_color}">{badge}</span>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-top: 8px;">
                    <span style="font-size: 12px; color: #94A3B8;">Primary Issue: <strong>{row['Top Escalation Driver']}</strong></span>
                    <span style="color: #F8FAFC; font-size: 13px;"><b>{row['esc_pct']:.2f}%</b> Esc (<b>{int(row['tickets']):,}</b> tix)</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

with c_right:
    st.markdown('**Top Support Driver Subcategories**')
    if not subcat_sum.empty:
        for _, row in subcat_sum.head(3).iterrows():
            tier = row['tier']
            accent_color = "#EF4444" if tier == "HIGH" else "#F59E0B" if tier == "MEDIUM" else "#22C55E"
            st.markdown(f"""
            <div class="kpi-card" style="border-left: 4px solid {accent_color} !important;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <b style="color: #F8FAFC; font-size: 14px;">{row['subcat_final']}</b>
                    <span class="badge" style="color:{accent_color}">{tier} SEVERITY</span>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-top: 8px;">
                    <span style="font-size: 12px; color: #94A3B8;">Volume Share</span>
                    <span style="color: #F8FAFC; font-size: 13px;"><b>{row['count']:,}</b> tickets (<b>{row['pct']:.1f}%</b>)</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

# ── TAB SYSTEM ──
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "🏷️ Brand Intel", "📦 Product Intel", "📅 Weekly Trends",
    "📊 Issue Breakdown", "📈 Month Comparison", "📋 Validation Panel", "🗺️ Redistribution Audit", "🤖 AI Insights"
])

# TAB 1: Brand Intel
with tab1:
    b_fa, b_fb, b_fc = st.columns(3)
    with b_fa:
        b_imp_f = st.multiselect("Impact Level Filter", ["CRITICAL", "HIGH", "MEDIUM", "LOW"], default=["CRITICAL", "HIGH", "MEDIUM", "LOW"])
    with b_fb:
        b_sort_choice = st.selectbox("Sort Matrix By", ["Highest Tickets", "Lowest Tickets", "Highest Esc %", "Lowest Esc %"])
    with b_fc:
        b_min_del = st.number_input("Minimum Orders Threshold", value=0, step=50)
        
    disp_b = brand_sum[brand_sum["impact"].isin(b_imp_f)].copy() if not brand_sum.empty else pd.DataFrame()
    if b_min_del > 0 and not disp_b.empty:
        disp_b = disp_b[disp_b["delivered"] >= b_min_del]
        
    if not disp_b.empty:
        if b_sort_choice == "Highest Tickets": disp_b = disp_b.sort_values("tickets", ascending=False)
        elif b_sort_choice == "Lowest Tickets": disp_b = disp_b.sort_values("tickets", ascending=True)
        elif b_sort_choice == "Highest Esc %": disp_b = disp_b.sort_values("esc_pct", ascending=False)
        elif b_sort_choice == "Lowest Esc %": disp_b = disp_b.sort_values("esc_pct", ascending=True)

        if analysis_mode == "Combined":
            st.dataframe(disp_b[["brand", "delivered_pre", "delivered_post", "tickets_pre", "tickets_post", "pre_esc_pct", "post_esc_pct", "post_defect_rate", "impact"]], use_container_width=True)
        else:
            st.dataframe(disp_b[["brand", "delivered", "tickets", "esc_pct", "defect_rate", "weighted_esc", "confidence", "Top Escalation Driver", "impact"]], use_container_width=True)

    st.markdown('**Individual Brand Analyzer**')
    if not brand_sum.empty:
        sel_b = st.selectbox("Select Brand Profile", sorted(brand_sum["brand"].unique()))
        b_row = brand_sum[brand_sum["brand"] == sel_b].iloc[0]
        
        bd1, bd2, bd3 = st.columns(3)
        with bd1: kpi("Orders Count", f"{int(b_row['delivered']):,}", color="blue")
        with bd2: kpi("Tickets Count", f"{int(b_row['tickets']):,}", color="red")
        with bd3: kpi("Escalation Rate %", f"{b_row['esc_pct']:.2f}%", color="amber")

# TAB 2: Product Intel
with tab2:
    p_fa, p_fb = st.columns(2)
    with p_fa:
        p_brand_f = st.multiselect("Filter by Brand Profiles", sorted(prod_sum["brand"].unique()) if not prod_sum.empty else [])
    with p_fb:
        p_imp_f = st.multiselect("Filter by Product Impact", ["CRITICAL", "HIGH", "MEDIUM", "LOW"], default=["CRITICAL", "HIGH", "MEDIUM", "LOW"])
        
    disp_p = prod_sum[prod_sum["impact"].isin(p_imp_f)].copy() if not prod_sum.empty else pd.DataFrame()
    if p_brand_f and not disp_p.empty:
        disp_p = disp_p[disp_p["brand"].isin(p_brand_f)]
        
    if not disp_p.empty:
        if analysis_mode == "Combined":
            st.dataframe(disp_p[["brand", "canonical_product", "delivered_pre", "delivered_post", "tickets_pre", "tickets_post", "pre_esc_pct", "post_esc_pct", "Ticket Aging Category", "impact"]], use_container_width=True)
        else:
            st.dataframe(disp_p[["brand", "canonical_product", "delivered", "tickets", "esc_pct", "Primary Ticket Source Month", "Same Month Tickets", "Previous Month Tickets", "Older Tickets", "Ticket Aging Category", "impact"]], use_container_width=True)

    with st.expander("View Normalization Mapping Logs", expanded=False):
        if hasattr(registry, "debug_log") and registry.debug_log:
            st.dataframe(pd.DataFrame(registry.debug_log), use_container_width=True, height=350)

# TAB 3: Weekly Trends
with tab3:
    if not weekly_trends.empty: st.dataframe(weekly_trends, use_container_width=True)

# TAB 4: Issue Breakdown
with tab4:
    if not subcat_sum.empty: st.dataframe(subcat_sum, use_container_width=True)

# TAB 5: Month Comparison
with tab5:
    if not cohort_report.empty: st.dataframe(cohort_report, use_container_width=True)
    if has_comparison and not comp_df_brand.empty:
        st.dataframe(comp_df_brand, use_container_width=True)

# TAB 6: Validation Panel
with tab6:
    st.markdown("**Operational Ticket Ledger Balance Audit**")
    v1, v2, v3, v4 = st.columns(4)
    with v1: kpi("Raw Ingested Tickets", f"{orig:,}", color="blue")
    with v2: kpi("Final Processed Tickets", f"{final_c:,}", color="green" if val_ok else "red")
    with v3: kpi("Brand Unmapped", f"{D['n_unmapped_brand']:,}", color="purple")
    with v4: kpi("Ledger Sync Check", "PASS ✅" if val_ok else "FAIL ❌", color="green" if val_ok else "red")

# TAB 7: Redistribution Audit
with tab7:
    if not redist_sum.empty: st.dataframe(redist_sum, use_container_width=True)

# TAB 8: AI Insights
with tab8:
    if not ai_on:
        st.info("AI Analysis is deactivated. Toggle 'Enable AI Analysis' in the sidebar.")
    elif not api_key:
        st.warning("Please enter your Google Gemini API Key in the sidebar.")
    else:
        st.write("AI analysis modules loaded and ready.")
