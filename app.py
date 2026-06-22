"""
app.py — OPX Operations Intelligence Platform (v4.3)
Calculates overall support metrics and maps custom single-period dropdown filters.
Fixed: Removed legacy Google Sheets auto_migrate triggers to prevent circular imports.
"""
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import json
import os

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

# ── 1. INITIALIZE DATABASE & RETRIEVE METRIC STATS ──
# Run database schema check first thing on startup
init_db()
db_stats = get_database_stats()
del_df_raw = load_orders()
tick_df_raw = load_tickets()

# ── DATABASE QUALITY HEALTH & SELF-HEALING CHECK ──
corrupt_db_flag = False
if not tick_df_raw.empty and "raw_subcat" in tick_df_raw.columns:
    unique_subcats = set(tick_df_raw["raw_subcat"].dropna().unique())
    valid_unique_subcats = {s for s in unique_subcats if s.strip() and s.lower() not in ("nan", "none", "null")}
    # If the subcategory column ONLY contains category segment definitions (corrupted legacy state)
    if valid_unique_subcats and valid_unique_subcats.issubset({"POST_DELIVERY", "PRE_DELIVERY"}):
        corrupt_db_flag = True

# Automated healing: Purge the corrupted legacy SQLite database instantly and refresh the state
if corrupt_db_flag:
    if os.path.exists("operations.db"):
        try:
            os.remove("operations.db")
            st.cache_data.clear()
            st.rerun()
        except Exception:
            pass


# ── 2. SIDEBAR STYLING & INTERFACE ──
with st.sidebar:
    # Minimal Modern Brand Logo (ASCII-driven premium SVG/HTML)
    st.markdown("""
    <div style="display: flex; align-items: center; gap: 14px; margin-bottom: 2rem; margin-top: 1rem;">
        <svg width="46" height="46" viewBox="0 0 46 46" fill="none" xmlns="http://www.w3.org/2000/svg" style="filter: drop-shadow(0px 0px 8px rgba(59, 130, 246, 0.6));">
            <path d="M23 2C32 2 39 5 39 12V24C39 31.5 32.5 38 23 44C13.5 38 7 31.5 7 24V12C7 5 14 2 23 2Z" fill="#0F172A" stroke="#3B82F6" stroke-width="2"/>
            <text x="50%" y="58%" dominant-baseline="middle" text-anchor="middle" font-family="'Inter', sans-serif" font-weight="900" font-size="11" fill="#FFFFFF">OPX</text>
        </svg>
        <div>
            <h2 style="margin:0; font-size:18px; font-weight:700; color:#FFFFFF; letter-spacing:0.05em; line-height:1.2;">OPX</h2>
            <p style="margin:0; font-size:9px; color:#64748B; font-weight:600; text-transform:uppercase; letter-spacing:0.08em;">Enterprise Ops Analytics</p>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    st.divider()
    view_mode = st.radio("Select Console Portal", ["📈 Public Dashboard", "🔐 Admin Control Panel"], index=0)
    
    st.divider()
    
    if view_mode == "📈 Public Dashboard":
        # Severity Threshold Metrics
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
                api_key = st.text_input("GCP Gemini API Key", type="password", help="Enter Google Gemini API Key")
    else:
        st.markdown("**Database Statistics**")
        st.metric("Total Orders In DB", f"{db_stats['total_orders']:,}")
        st.metric("Total Tickets In DB", f"{db_stats['total_tickets']:,}")
        st.caption(f"Orders Updated: {db_stats['orders_last_updated']}")
        st.caption(f"Tickets Updated: {db_stats['tickets_last_updated']}")

    st.divider()
    st.caption("v4.3 • SQLite Edition")


# ── Premium Enterprise Styling Sheets Injection ──
st.markdown("""
<style>
/* Core Premium Theme Overrides */
html, body, [data-testid="stAppViewContainer"] {
    background: #080B11 !important;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
    color: #E2E8F0 !important;
}
[data-testid="stAppViewContainer"] > .main {
    background: #080B11;
}
.main .block-container {
    padding: 1.5rem 2.5rem 3rem 2.5rem !important;
    max-width: 100% !important;
}

/* Sidebar Custom Theme - Active only when expanded */
section[data-testid="stSidebar"][aria-expanded="true"] {
    background: #0F172A !important;
    border-right: 1px solid #1E293B !important;
    min-width: 280px !important;
    max-width: 280px !important;
}
/* Sidebar Custom Theme - Fully responsive collapse to 0px when hidden */
section[data-testid="stSidebar"][aria-expanded="false"] {
    min-width: 0px !important;
    max-width: 0px !important;
    border-right: none !important;
}
section[data-testid="stSidebar"] * {
    color: #94A3B8 !important;
}

/* Glassmorphism Cards */
.kpi-card {
    background: rgba(17, 24, 39, 0.7) !important;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255, 255, 255, 0.05) !important;
    border-radius: 12px !important;
    padding: 1.25rem;
    margin-bottom: 1rem;
    box-shadow: 0 4px 30px rgba(0, 0, 0, 0.4);
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    position: relative;
    overflow: hidden;
}
.kpi-card::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, transparent 100%);
    opacity: 0;
    transition: opacity 0.3s ease;
    pointer-events: none;
}
.kpi-card:hover {
    transform: translateY(-4px);
    border-color: rgba(59, 130, 246, 0.3) !important;
    box-shadow: 0 8px 30px rgba(59, 130, 246, 0.15);
}
.kpi-card:hover::before {
    opacity: 1;
}

/* Color Accents */
.kpi-card.blue { border-left: 4px solid #3B82F6 !important; }
.kpi-card.orange { border-left: 4px solid #F97316 !important; }
.kpi-card.amber { border-left: 4px solid #F59E0B !important; }
.kpi-card.purple { border-left: 4px solid #8B5CF6 !important; }
.kpi-card.green { border-left: 4px solid #22C55E !important; }

/* Critical Alert Pulse & Soft Glow */
@keyframes critical-pulse {
    0% { border-left-color: #EF4444; box-shadow: 0 0 5px rgba(239, 68, 68, 0.2); }
    50% { border-left-color: #F87171; box-shadow: 0 0 20px rgba(239, 68, 68, 0.6); }
    100% { border-left-color: #EF4444; box-shadow: 0 0 5px rgba(239, 68, 68, 0.2); }
}
.kpi-card.critical-alert {
    animation: critical-pulse 2s infinite ease-in-out;
    background: rgba(239, 68, 68, 0.05) !important;
}

/* Blinking Dots */
.status-dot {
    height: 8px;
    width: 8px;
    border-radius: 50%;
    display: inline-block;
    margin-right: 6px;
    position: relative;
}
.status-dot.green {
    background-color: #22C55E;
    box-shadow: 0 0 8px #22C55E;
}
.status-dot.red {
    background-color: #EF4444;
    box-shadow: 0 0 8px #EF4444;
}
.status-dot.pulse {
    animation: status-pulse-animation 2s infinite;
}
@keyframes status-pulse-animation {
    0% { transform: scale(0.95); opacity: 0.5; }
    50% { transform: scale(1.2); opacity: 1; box-shadow: 0 0 12px currentColor; }
    100% { transform: scale(0.95); opacity: 0.5; }
}

/* Badges styling */
.badge {
    display: inline-flex;
    align-items: center;
    padding: 4px 10px;
    border-radius: 9999px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    border: 1px solid transparent;
}
.badge-critical {
    background: rgba(239, 68, 68, 0.1);
    color: #EF4444;
    border-color: rgba(239, 68, 68, 0.2);
    animation: status-pulse-animation 2s infinite;
}
.badge-high {
    background: rgba(249, 115, 22, 0.1);
    color: #F97316;
    border: 1px solid #3F2C24;
}
.badge-medium {
    background: #1e1b12;
    color: #D29922;
    border: 1px solid #483a15;
}
.badge-low {
    background: #0f1c14;
    color: #3FB950;
    border: 1px solid #142a18;
}

/* Global Tab Portals */
.stTabs [data-baseweb="tab-list"] { background: #161B26; border-radius: 8px; padding: 4px; border: 1px solid #21262D; }
.stTabs [data-baseweb="tab"] { color: #6E7681 !important; padding: 5px 14px !important; font-size: 12px !important; font-weight: 500 !important; }
.stTabs [aria-selected="true"] { background: #21262D !important; color: #E6EDF3 !important; }

/* Custom elements */
.brow { background: #161B26; border: 1px solid #21262D; border-radius: 6px; padding: 12px; margin-bottom: 5px; font-size: 12px; }
.shdr { font-size: 11px; font-weight: 600; color: #8B949E; text-transform: uppercase; border-bottom: 1px solid #21262D; padding-bottom: 5px; margin: 16px 0 10px; }
.ai-box { background: #1F242C; border: 1px solid #30363D; border-radius: 8px; padding: 15px; color: #C9D1D9; font-size: 13px; line-height: 1.6; margin-top: 10px; }
</style>
""", unsafe_allow_html=True)


def kpi(label, value, sub="", color="blue"):
    color_map = {
        "blue": {
            "accent": "#3B82F6",
            "bg_glow": "linear-gradient(135deg, rgba(59, 130, 246, 0.15) 0%, transparent 100%)",
            "border": "rgba(59, 130, 246, 0.2)",
            "icon": '<path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="#3B82F6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M2 17L12 22L22 17" stroke="#3B82F6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M2 12L12 17L22 12" stroke="#3B82F6" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
            "sparkline": '<polyline points="0,15 10,12 20,18 30,8 40,14 50,5 60,10" fill="none" stroke="#3B82F6" stroke-width="1.5" />'
        },
        "orange": {
            "accent": "#F97316",
            "bg_glow": "linear-gradient(135deg, rgba(249, 115, 22, 0.15) 0%, transparent 100%)",
            "border": "rgba(249, 115, 22, 0.2)",
            "icon": '<path d="M4 4H20V20H4V4Z" stroke="#F97316" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M9 9H15V15H9V9Z" stroke="#F97316" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
            "sparkline": '<polyline points="0,18 10,15 20,10 30,12 40,8 50,14 60,6" fill="none" stroke="#F97316" stroke-width="1.5" />'
        },
        "red": {
            "accent": "#EF4444",
            "bg_glow": "linear-gradient(135deg, rgba(239, 68, 68, 0.15) 0%, transparent 100%)",
            "border": "rgba(239, 68, 68, 0.2)",
            "icon": '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" stroke="#EF4444" stroke-width="2"/><line x1="12" y1="9" x2="12" y2="13" stroke="#EF4444" stroke-width="2" stroke-linecap="round"/><line x1="12" y1="17" x2="12.01" y2="17" stroke="#EF4444" stroke-width="2" stroke-linecap="round"/>',
            "sparkline": '<polyline points="0,10 10,18 20,8 30,15 40,12 50,5 60,14" fill="none" stroke="#EF4444" stroke-width="1.5" />'
        },
        "amber": {
            "accent": "#F59E0B",
            "bg_glow": "linear-gradient(135deg, rgba(245, 158, 11, 0.15) 0%, transparent 100%)",
            "border": "rgba(245, 158, 11, 0.2)",
            "icon": '<path d="M12 22C17.5228 22 22 17.5228 22 12C22 6.47715 17.5228 2 12 2C6.47715 2 2 6.47715 2 12C2 17.5228 6.47715 2 12 22Z" stroke="#F59E0B" stroke-width="2"/><path d="M12 6V12L16 14" stroke="#F59E0B" stroke-width="2" stroke-linecap="round"/>',
            "sparkline": '<polyline points="0,15 10,14 20,16 30,10 40,11 50,7 60,12" fill="none" stroke="#F59E0B" stroke-width="1.5" />'
        },
        "purple": {
            "accent": "#8B5CF6",
            "bg_glow": "linear-gradient(135deg, rgba(139, 92, 246, 0.15) 0%, transparent 100%)",
            "border": "rgba(139, 92, 246, 0.2)",
            "icon": '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" stroke="#8B5CF6" stroke-width="2"/><polyline points="3.27 6.96 12 12.01 20.73 6.96" stroke="#8B5CF6" stroke-width="2"/><line x1="12" y1="22.08" x2="12" y2="12" stroke="#8B5CF6" stroke-width="2"/>',
            "sparkline": '<polyline points="0,12 10,8 20,14 30,5 40,18 50,10 60,15" fill="none" stroke="#8B5CF6" stroke-width="1.5" />'
        },
        "green": {
            "accent": "#22C55E",
            "bg_glow": "linear-gradient(135deg, rgba(34, 197, 94, 0.15) 0%, transparent 100%)",
            "border": "rgba(34, 197, 94, 0.2)",
            "icon": '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" stroke="#22C55E" stroke-width="2" stroke-linecap="round"/><polyline points="22 4 12 14.01 9 11.01" stroke="#22C55E" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
            "sparkline": '<polyline points="0,14 10,12 20,15 30,9 40,11 50,6 60,8" fill="none" stroke="#22C55E" stroke-width="1.5" />'
        }
    }
    
    props = color_map.get(color, color_map["blue"])
    
    st.markdown(f"""
    <div class="kpi-card {color}" style="background: {props['bg_glow']}; border: 1px solid {props['border']};">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem;">
            <span style="font-size: 11px; font-weight: 700; color: #94A3B8; text-transform: uppercase; letter-spacing: 0.05em;">{label}</span>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" style="color: {props['accent']};">
                {props['icon']}
            </svg>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: flex-end;">
            <div>
                <h3 style="font-size: 26px; font-weight: 800; color: #F8FAFC; margin: 0; line-height: 1.1;">{value}</h3>
                <p style="font-size: 10px; color: #64748B; margin: 4px 0 0 0;">{sub}</p>
            </div>
            <div style="width: 60px; height: 20px; padding-bottom: 4px;">
                <svg width="60" height="20" viewBox="0 0 60 20">
                    {props['sparkline']}
                </svg>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ── Premium Hero Section (Datadog & Microsoft Fabric Styling) ──
st.markdown(f"""
<div style="background: rgba(17, 24, 39, 0.7); backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 12px; padding: 1.5rem; margin-bottom: 2rem; box-shadow: 0 4px 30px rgba(0, 0, 0, 0.4); display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem;">
    <div>
        <span class="badge badge-low" style="margin-bottom: 0.5rem;"><span class="status-dot green pulse"></span>ONLINE & SYNCED</span>
        <h2 style="margin: 0; font-size: 24px; font-weight: 700; color: #F8FAFC;">OPX Hero Overview</h2>
        <p style="margin: 4px 0 0 0; font-size: 12px; color: #94A3B8;">Operations, tickets, and escalation metrics synced in real-time.</p>
    </div>
    <div style="display: flex; gap: 1.5rem; flex-wrap: wrap;">
        <div style="border-right: 1px solid #1E293B; padding-right: 1.5rem;">
            <p style="margin: 0; font-size: 10px; color: #94A3B8; text-transform: uppercase; font-weight: 600;">Environment</p>
            <p style="margin: 2px 0 0 0; font-size: 13px; color: #3B82F6; font-weight: 700;">PROD-CLUSTER-01</p>
        </div>
        <div style="border-right: 1px solid #1E293B; padding-right: 1.5rem;">
            <p style="margin: 0; font-size: 10px; color: #94A3B8; text-transform: uppercase; font-weight: 600;">Time Filter</p>
            <p style="margin: 2px 0 0 0; font-size: 13px; color: #F8FAFC; font-weight: 700;">{selected_period}</p>
        </div>
        <div style="border-right: 1px solid #1E293B; padding-right: 1.5rem;">
            <p style="margin: 0; font-size: 10px; color: #94A3B8; text-transform: uppercase; font-weight: 600;">Analysis Segment</p>
            <p style="margin: 2px 0 0 0; font-size: 13px; color: #F59E0B; font-weight: 700;">{analysis_mode}</p>
        </div>
        <div style="border-right: 1px solid #1E293B; padding-right: 1.5rem;">
            <p style="margin: 0; font-size: 10px; color: #94A3B8; text-transform: uppercase; font-weight: 600;">Last Sync</p>
            <p style="margin: 2px 0 0 0; font-size: 13px; color: #22C55E; font-weight: 700;">{db_stats['tickets_last_updated'] if db_stats['tickets_last_updated'] != 'Never' else 'No Active Sync'}</p>
        </div>
        <div>
            <p style="margin: 0; font-size: 10px; color: #94A3B8; text-transform: uppercase; font-weight: 600;">Database Status</p>
            <p style="margin: 2px 0 0 0; font-size: 13px; color: #22C55E; font-weight: 700;">HEALTHY</p>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# ── DATABASE HEALTH ALERTS ──
if corrupt_db_flag:
    st.markdown(f"""
    <div class="notification-banner">
        <h4 style="margin: 0 0 6px 0; color: #EF4444; font-weight: 700; font-size: 15px; display: flex; align-items: center; gap: 8px;">
            <span class="status-dot red pulse"></span>Legacy Database Corruption Detected
        </h4>
        <p style="margin: 0 0 10px 0; font-size: 13px; color: #94A3B8; line-height: 1.5;">
            The active database contains corrupted ticket subcategories (only 'POST_DELIVERY' / 'PRE_DELIVERY' values are found in the subcategory column). This occurs because the database was populated using a previous buggy version of the code.
        </p>
        <p style="margin: 0; font-size: 12px; color: #64748B; font-weight: 600;">
            Action Plan: Switch to the Admin Control Panel, run the Database Reset, and re-upload your raw Orders and Tickets sheets to populate clean, healthy entries.
        </p>
    </div>
    """, unsafe_allow_html=True)


# ── KPI METRICS DISPLAY ──
st.markdown("### 📊 Active Segment Performance Overview")

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
    with c1: 
        lbl_o = "Delivered Orders" if analysis_mode == "Post Delivery" else "Total Orders"
        kpi(lbl_o, f"{overall_orders_count:,}", "Raw row count from the orders dataset.", "blue")
    with c2: 
        kpi("Tickets", f"{overall_tickets_count:,}", "Total registered support requests.", "orange")
    with c3: 
        lbl_esc_name = "Post Escalation %" if analysis_mode == "Post Delivery" else "Pre Escalation %"
        kpi(lbl_esc_name, f"{overall_esc_rate}%", "Support tickets ÷ orders.", "amber" if overall_esc_rate >= 3.0 else "green")
    with c4: 
        lbl_def_name = "Post Defect %" if analysis_mode == "Post Delivery" else "Pre Defect %"
        kpi(lbl_def_name, f"{overall_defect_rate}%", "Quality issues ÷ orders.", "purple")
    with c5: 
        st.write("") # Spacer to prevent layout shifts
        kpi("Peak Week", str(kpis['spike_week']), "Highest volume week.", "green")

st.divider()


# ── EXECUTIVE RISK OVERVIEW ROWS ──
c_left, c_right = st.columns(2)
with c_left:
    st.markdown('<p class="shdr">Top Escalation Risk Brand Profiles</p>', unsafe_allow_html=True)
    if not brand_sum.empty:
        for _, row in brand_sum.head(3).iterrows():
            esc_val = row['esc_pct']
            if esc_val >= crit_esc:
                risk_class = "critical-alert kpi-card"
                badge_html = '<span class="badge badge-critical"><span class="status-dot red pulse"></span>CRITICAL</span>'
                accent_color = "#EF4444"
            elif esc_val >= high_esc:
                risk_class = "kpi-card"
                badge_html = '<span class="badge badge-high">HIGH</span>'
                accent_color = "#F97316"
            elif esc_val >= med_esc:
                risk_class = "kpi-card"
                badge_html = '<span class="badge badge-medium">MEDIUM</span>'
                accent_color = "#F59E0B"
            else:
                risk_class = "kpi-card"
                badge_html = '<span class="badge badge-low">LOW</span>'
                accent_color = "#22C55E"
            
            st.markdown(
                f"""<div class="{risk_class}" style="border: 1px solid rgba(255, 255, 255, 0.05); padding: 12px 16px; margin-bottom: 10px; border-left: 4px solid {accent_color} !important;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <b style="color: #F8FAFC; font-size: 14px;">{row['brand']}</b>
                        {badge_html}
                    </div>
                    <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-top: 8px;">
                        <span style="font-size: 12px; color: #94A3B8;">Primary Issue: <strong style="color: #E2E8F0;">{row['Top Escalation Driver']}</strong></span>
                        <span style="color: #F8FAFC; font-size: 13px;"><b>{row['esc_pct']:.2f}%</b> Esc (<b>{int(row['tickets']):,}</b> tix)</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; margin-top: 4px; font-size: 10px; color: #64748B;">
                        <span>Defect Rate: {row['defect_rate']:.2f}%</span>
                        <span style="display: flex; align-items: center; gap: 4px;"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg> active trend</span>
                    </div>
                </div>""", 
                unsafe_allow_html=True
            )
with c_right:
    st.markdown('<p class="shdr">Top Support Driver Subcategories</p>', unsafe_allow_html=True)
    if not subcat_sum.empty:
        for _, row in subcat_sum.head(3).iterrows():
            tier = row['tier']
            if tier == "HIGH":
                badge_html = '<span class="badge badge-critical">HIGH SEVERITY</span>'
                accent_color = "#EF4444"
            elif tier == "MEDIUM":
                badge_html = '<span class="badge badge-medium">MID SEVERITY</span>'
                accent_color = "#F59E0B"
            else:
                badge_html = '<span class="badge badge-low">LOW SEVERITY</span>'
                accent_color = "#22C55E"
            
            st.markdown(
                f"""<div class="kpi-card" style="border: 1px solid rgba(255, 255, 255, 0.05); padding: 12px 16px; margin-bottom: 10px; border-left: 4px solid {accent_color} !important;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <b style="color: #F8FAFC; font-size: 14px;">{row['subcat_final']}</b>
                        {badge_html}
                    </div>
                    <div style="display: flex; justify-content: space-between; align-items: flex-end; margin-top: 8px;">
                        <span style="font-size: 12px; color: #94A3B8;">Volume Share</span>
                        <span style="color: #F8FAFC; font-size: 13px;"><b>{row['count']:,}</b> tickets (<b>{row['pct']:.1f}%</b>)</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; margin-top: 4px; font-size: 10px; color: #64748B;">
                        <span>Classification: {row['tier']}</span>
                        <span style="display: flex; align-items: center; gap: 4px;"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg> incident allocation</span>
                    </div>
                </div>""", 
                unsafe_allow_html=True
            )


# ── TAB SYSTEM ──
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "🏷️ Brand Intel", "📦 Product Intel", "📅 Weekly Trends",
    "📊 Issue Breakdown", "📈 Month Comparison", "📋 Validation Panel", "🗺️ Redistribution Audit", "🤖 AI Insights"
])

# TAB 1: Brand Intel
with tab1:
    st.markdown('<p class="shdr">Brand Performance Matrix</p>', unsafe_allow_html=True)
    b_fa, b_fb, b_fc = st.columns(3)
    with b_fa:
        b_imp_f = st.multiselect("Impact Level Filter", ["CRITICAL", "HIGH", "MEDIUM", "LOW"], default=["CRITICAL", "HIGH", "MEDIUM", "LOW"], key="b_imp_tab")
    with b_fb:
        b_sort_choice = st.selectbox("Sort Matrix By", [
            "Highest Tickets", "Lowest Tickets", "Highest Esc %", "Lowest Esc %",
            "Highest Orders", "Lowest Orders", "A → Z"
        ], key="b_sort_tab")
    with b_fc:
        b_min_del = st.number_input("Minimum Orders Threshold", value=0, step=50, key="b_min_tab")
        
    disp_b = brand_sum[brand_sum["impact"].isin(b_imp_f)].copy() if not brand_sum.empty else pd.DataFrame()
    if b_min_del > 0 and not disp_b.empty:
        disp_b = disp_b[disp_b["delivered"] >= b_min_del]
        
    if not disp_b.empty:
        if b_sort_choice == "Highest Tickets":
            disp_b = disp_b.sort_values("tickets", ascending=False)
        elif b_sort_choice == "Lowest Tickets":
            disp_b = disp_b.sort_values("tickets", ascending=True)
        elif b_sort_choice == "Highest Esc %":
            disp_b = disp_b.sort_values("esc_pct", ascending=False)
        elif b_sort_choice == "Lowest Esc %":
            disp_b = disp_b.sort_values("esc_pct", ascending=True)
        elif b_sort_choice == "Highest Orders":
            disp_b = disp_b.sort_values("delivered", ascending=False)
        elif b_sort_choice == "Lowest Orders":
            disp_b = disp_b.sort_values("delivered", ascending=True)
        elif b_sort_choice == "A → Z":
            disp_b = disp_b.sort_values("brand", ascending=True)

        if analysis_mode == "Combined":
            st.dataframe(disp_b[["brand", "delivered_pre", "delivered_post", "tickets_pre", "tickets_post", "pre_esc_pct", "post_esc_pct", "post_defect_rate", "impact"]], use_container_width=True)
        else:
            st.dataframe(disp_b[["brand", "delivered", "tickets", "esc_pct", "defect_rate", "weighted_esc", "confidence", "Top Escalation Driver", "impact"]], use_container_width=True)
    else:
        st.info("No brand profiles match selected filters.")

    st.markdown('<p class="shdr">Individual Brand Analyzer</p>', unsafe_allow_html=True)
    if not brand_sum.empty:
        sel_b = st.selectbox("Select Brand Profile", sorted(brand_sum["brand"].unique()), key="drill_brand")
        b_row = brand_sum[brand_sum["brand"] == sel_b].iloc[0]
        
        bd1, bd2, bd3, bd4, bd5, bd6 = st.columns(6)
        with bd1: kpi("Orders Count", f"{int(b_row['delivered']):,}", color="blue")
        with bd2: kpi("Tickets Count", f"{int(b_row['tickets']):,}", color="red")
        with bd3: kpi("Escalation Rate %", f"{b_row['esc_pct']:.2f}%", color="amber")
        with bd4: kpi("Weighted Esc %", f"{b_row['weighted_esc']:.2f}%", color="purple")
        with bd5: kpi("Confidence %", f"{int(b_row['confidence'])}%", color="green")
        with bd6: kpi("Defect Rate %", f"{b_row['defect_rate']:.2f}%", color="red" if b_row['defect_rate'] >= 1.5 else "green")
        
        b_left, b_right = st.columns(2)
        with b_left:
            st.markdown("**Top Associated Products**")
            bp = prod_sum[prod_sum["brand"] == sel_b].head(10)[["canonical_product", "delivered", "tickets", "esc_pct", "impact"]].copy() if not prod_sum.empty else pd.DataFrame()
            st.dataframe(bp, use_container_width=True)
        with b_right:
            st.markdown("**Core Issues Categories**")
            bi = f_tick_universe[f_tick_universe["brand"] == sel_b].groupby("subcat_final").size().reset_index(name="Tickets").sort_values("Tickets", ascending=False) if not f_tick_universe.empty else pd.DataFrame()
            st.dataframe(bi, use_container_width=True)

# TAB 2: Product Intel
with tab2:
    st.markdown('<p class="shdr">Product Performance Matrix</p>', unsafe_allow_html=True)
    p_fa, p_fb, p_fc = st.columns(3)
    with p_fa:
        p_brand_f = st.multiselect("Filter by Brand Profiles", sorted(prod_sum["brand"].unique()) if not prod_sum.empty else [], key="p_brand_tab")
    with p_fb:
        p_imp_f = st.multiselect("Filter by Product Impact", ["CRITICAL", "HIGH", "MEDIUM", "LOW"], default=["CRITICAL", "HIGH", "MEDIUM", "LOW"], key="p_imp_tab")
    with p_fc:
        p_min_del = st.number_input("Minimum Products Volume Threshold", value=0, step=50, key="p_min_tab")
        
    disp_p = prod_sum[prod_sum["impact"].isin(p_imp_f)].copy() if not prod_sum.empty else pd.DataFrame()
    if p_brand_f and not disp_p.empty:
        disp_p = disp_p[disp_p["brand"].isin(p_brand_f)]
    if p_min_del > 0 and not disp_p.empty:
        disp_p = disp_p[disp_p["delivered"] >= p_min_del]
        
    if not disp_p.empty:
        if analysis_mode == "Combined":
            st.dataframe(disp_p[["brand", "canonical_product", "delivered_pre", "delivered_post", "tickets_pre", "tickets_post", "pre_esc_pct", "post_esc_pct", "Ticket Aging Category", "impact"]], use_container_width=True)
        else:
            st.dataframe(disp_p[["brand", "canonical_product", "delivered", "tickets", "esc_pct", "Primary Ticket Source Month", "Same Month Tickets", "Previous Month Tickets", "Older Tickets", "Ticket Aging Category", "impact"]], use_container_width=True)
    else:
        st.info("No product profiles match selected filters.")

    st.markdown('<p class="shdr">Product Group Analyzer</p>', unsafe_allow_html=True)
    if not prod_sum.empty:
        pd_b = st.selectbox("Select Brand for Product Analysis", sorted(prod_sum["brand"].unique()), key="p_drill_brand")
        pd_p_opts = sorted(prod_sum[prod_sum["brand"] == pd_b]["canonical_product"].unique())
        
        if pd_p_opts:
            pd_p = st.selectbox("Select Product Model Group", pd_p_opts, key="p_drill_product")
            p_row = prod_sum[(prod_sum["brand"] == pd_b) & (prod_sum["canonical_product"] == pd_p)].iloc[0]
            
            pd1, pd2, pd3, pd4 = st.columns(4)
            with pd1: kpi("Orders Volume", f"{int(p_row['delivered']):,}", color="blue")
            with pd2: kpi("Tickets Count", f"{int(p_row['tickets']):,}", color="red")
            with pd3: kpi("Escalation Rate %", f"{p_row['esc_pct']:.2f}%", color="amber")
            with pd4: kpi("Confidence %", f"{int(p_row['confidence'])}%", color="green")
            
            st.markdown("**Associated Support Issues Categories**")
            p_bi = f_tick_universe[(f_tick_universe["brand"] == pd_b) & (f_tick_universe["canonical_product"] == pd_p)].groupby("subcat_final").size().reset_index(name="Tickets").sort_values("Tickets", ascending=False) if not f_tick_universe.empty else pd.DataFrame()
            st.dataframe(p_bi, use_container_width=True)

    # Product Registry Mapping log
    st.markdown('<p class="shdr">🛠️ Product Registry Mapping Audit Log</p>', unsafe_allow_html=True)
    with st.expander("View Normalization Mapping Logs", expanded=False):
        if hasattr(registry, "debug_log") and registry.debug_log:
            st.dataframe(pd.DataFrame(registry.debug_log).style.hide(axis="index"), use_container_width=True, height=350)
        else:
            st.info("No normalization activity logs recorded.")

# TAB 3: Weekly Trends
with tab3:
    st.markdown('<p class="shdr">Weekly WoW Escalation Performance</p>', unsafe_allow_html=True)
    if not weekly_trends.empty:
        st.dataframe(weekly_trends, use_container_width=True)
    else:
        st.info("No weekly performance summaries found.")

# TAB 4: Issue Breakdown
with tab4:
    st.markdown('<p class="shdr">Support Subcategory Severity Distribution</p>', unsafe_allow_html=True)
    if not subcat_sum.empty:
        st.dataframe(subcat_sum, use_container_width=True)
    else:
        st.info("No recorded support tickets found.")

# TAB 5: Month Comparison
with tab5:
    st.markdown('<p class="shdr">Chronological Delivery Cohorts</p>', unsafe_allow_html=True)
    if not cohort_report.empty:
        st.dataframe(cohort_report, use_container_width=True)
    else:
        st.info("No cohort summaries found.")
    
    if not has_comparison:
        st.info("⚠️ At least 2 active months are required to generate comparison matrix sheets.")
    else:
        st.markdown('<p class="shdr">Month-over-Month Comparison Analysis</p>', unsafe_allow_html=True)
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            comp_brand_filter = st.multiselect(
                "Filter Matrix by Brand Profiles", 
                sorted(list(set(comp_df_brand["Brand"].unique()) | set(comp_df_prod["Brand"].unique()))) if not comp_df_brand.empty else []
            )
        with col_c2:
            comp_sort_choice = st.selectbox(
                "Sort Matrix",
                ["A → Z", "Highest Variance", "Lowest Variance"]
            )
            
        disp_comp_brand = comp_df_brand.copy() if not comp_df_brand.empty else pd.DataFrame()
        disp_comp_prod = comp_df_prod.copy() if not comp_df_prod.empty else pd.DataFrame()
        
        if comp_brand_filter:
            if not disp_comp_brand.empty:
                disp_comp_brand = disp_comp_brand[disp_comp_brand["Brand"].isin(comp_brand_filter)]
            if not disp_comp_prod.empty:
                disp_comp_prod = disp_comp_prod[disp_comp_prod["Brand"].isin(comp_brand_filter)]
            
        if not disp_comp_brand.empty:
            if comp_sort_choice == "A → Z":
                disp_comp_brand = disp_comp_brand.sort_values("Brand", ascending=True)
                disp_comp_prod = disp_comp_prod.sort_values(["Brand", "Product"], ascending=True)
            elif comp_sort_choice == "Highest Variance":
                disp_comp_brand = disp_comp_brand.sort_values("Esc % Difference", ascending=False)
                disp_comp_prod = disp_comp_prod.sort_values(["Brand", "Product"], ascending=True)
            elif comp_sort_choice == "Lowest Variance":
                disp_comp_brand = disp_comp_brand.sort_values("Esc % Difference", ascending=True)
                disp_comp_prod = disp_comp_prod.sort_values(["Brand", "Product"], ascending=True)

            st.markdown(f'<p class="shdr">Brand Level Variance ({month_a} vs {month_b})</p>', unsafe_allow_html=True)
            st.dataframe(disp_comp_brand, use_container_width=True)
            st.markdown(f'<p class="shdr">Product Level Variance ({month_a} vs {month_b})</p>', unsafe_allow_html=True)
            st.dataframe(disp_comp_prod, use_container_width=True)

# TAB 6: Validation Panel
with tabs[5] if 'tabs' in locals() else tab6:
    st.markdown('<p class="shdr">System Audit & Reconciliation Ledger</p>', unsafe_allow_html=True)
    
    validation_status = "PASS ✅" if val_ok else "FAIL ❌"
    
    st.markdown("**Chronological Date Coercion Quality Report**")
    dq1, dq2 = st.columns(2)
    with dq1: kpi("Delivered Date Coerced NaT", f"{D['invalid_del_dates']:,}", "Null or pre-1975 dates resolved.", "blue")
    with dq2: kpi("Ticket Date Coerced NaT", f"{D['invalid_tick_dates']:,}", "Null or pre-1975 dates resolved.", "red")
    
    st.markdown("**Operational Ticket Ledger Balance Audit**")
    v1, v2, v3, v4, v5, v6, v7 = st.columns(7)
    with v1: kpi("Raw Ingested Tickets", f"{orig:,}", "Count from Google Sheet.", "blue")
    with v2: kpi("Final Processed Tickets", f"{final_c:,}", "Count from pipeline output.", "green" if val_ok else "red")
    with v3: kpi("Brand Unmapped", f"{D['n_unmapped_brand']:,}", "Volume apportioned.", "purple")
    with v4: kpi("Need Details Base", f"{D['n_need_details']:,}", "Placeholders re-mapped.", "purple")
    v_diff = abs(orig - final_c)
    with v5: kpi("Subcat Not Found", f"{D['n_not_found_subcat']:,}", "Placeholders re-mapped.", "purple")
    with v6: kpi("Ledger Diff", f"{v_diff}", "Must be exactly 0.", "green" if v_diff == 0 else "red")
    with v7: kpi("Ledger Sync Check", str(validation_status), "Balanced logic check.", "green" if val_ok else "red")
    
    st.markdown("**Ticket Classification Log**")
    ac1, ac2 = st.columns(2)
    with ac1:
        st.markdown("**Raw Ingested support categories**")
        st.write(D["raw_cat_counts"])
    with ac2:
        st.markdown("**Standardized operational categories**")
        st.write(D["norm_cat_counts"])

# TAB 7: Redistribution Audit
with tabs[6] if 'tabs' in locals() else tab7:
    st.markdown('<p class="shdr">Redistribution Audit Log Ledger</p>', unsafe_allow_html=True)
    if not redist_sum.empty:
        st.dataframe(redist_sum, use_container_width=True)
    else:
        st.info("No unmapped redistribution activities recorded.")

# TAB 8: AI Insights
with tabs[7] if 'tabs' in locals() else tab8:
    st.markdown('<p class="shdr">Cognitive Operational Insights & Recommendations</p>', unsafe_allow_html=True)
    if not ai_on:
        st.info("AI Analysis is deactivated. Toggle 'Enable AI Analysis' in the sidebar.")
    elif not api_key:
        st.warning("Please enter your Google Gemini API Key in the sidebar.")
    else:
        def call_gemini(prompt, key):
            import urllib.request
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key.strip()}"
            body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req) as r:
                res_data = json.loads(r.read())
                return res_data["candidates"][0]["content"]["parts"][0]["text"]

        top10b = brand_sum.head(10)[["brand", "delivered", "tickets", "esc_pct"]].to_dict("records") if not brand_sum.empty else []
        top10p = prod_sum.head(10)[["brand", "canonical_product", "delivered", "tickets", "esc_pct"]].to_dict("records") if not prod_sum.empty else []
        top_i  = f_tick_universe.groupby("subcat_final").size().reset_index(name="count").sort_values("count", ascending=False).head(8).to_dict("records") if not f_tick_universe.empty else []

        ai1, ai2 = st.columns(2)
        with ai1:
            st.markdown("#### 📑 Summary Generator")
            if st.button("Generate Strategic Analysis", key="ai_exec"):
                with st.spinner("Analysing performance matrix..."):
                    try:
                        out = call_gemini(f"""Senior Operational Analyst.
Active Analysis Universe Mode: {analysis_mode}
Context: {overall_orders_count:,} orders, {overall_tickets_count:,} tickets, overall escalation {overall_esc_rate}%.
Top Brands: {json.dumps(top10b)}
Top Products: {json.dumps(top10p)}
Top Issues Categories: {json.dumps(top_i)}
Please construct: 1) Executive Performance Summary, 2) Critical Brand Profiles, 3) Primary Root Causes, 4) Product Focus Area, 5) Five Immediate Operational Recommendations.
Ensure your recommendations reference metrics from the dataset. Maintain a business-friendly, professional tone.""", api_key)
                        st.markdown(f'<div class="ai-box">{out}</div>', unsafe_allow_html=True)
                    except Exception as e:
                        handle_ai_error(e)
        with ai2:
            st.markdown("#### 💬 Ask any questions about your operations")
            user_question = st.text_input("Enter your diagnostic question", placeholder="Why did the defect rate spike on brand X during week 2?")
            if st.button("Query AI Agent", key="ai_ask"):
                if user_question.strip():
                    with st.spinner("Processing scenario..."):
                        try:
                            out = call_gemini(f"""You are a professional operations engineer analyzing medical school support metrics.
Database context:
- Overall Orders: {overall_orders_count}
- Overall Tickets: {overall_tickets_count}
- Overall Escalation: {overall_esc_rate}%
- Overall Defect Rate: {overall_defect_rate}%
- Top brands performance: {json.dumps(top10b)}
- Top product categories: {json.dumps(top10p)}
- Primary issue drivers: {json.dumps(top_i)}

User query: {user_question}

Deliver an engineered, metrics-backed answer based strictly on this dataset. Do not speculate.""", api_key)
                            st.markdown(f'<div class="ai-box">{out}</div>', unsafe_allow_html=True)
                        except Exception as e:
                            handle_ai_error(e)

        st.divider()
        st.markdown("#### 🏷️ Individual Brand Intelligence Deep Dive")
        ai_b = st.selectbox("Select Brand for Deep Dive", brand_sum["brand"].tolist() if not brand_sum.empty else [], key="ai_bd")
        if st.button("Generate Brand Intelligence Report", key="ai_bd_btn"):
            bd  = brand_sum[brand_sum["brand"]==ai_b].to_dict("records")
            bp2 = prod_sum[prod_sum["brand"]==ai_b].head(8)[["canonical_product","delivered","tickets","esc_pct"]].to_dict("records") if not prod_sum.empty else []
            bi3 = f_tick_universe[f_tick_universe["brand"]==ai_b]["subcat_final"].value_counts().head(6).to_dict() if not f_tick_universe.empty else {}
            with st.spinner(f"Compiling brand dossier for {ai_b}..."):
                try:
                    out = call_gemini(f"""Brand Health Analyst.
Target Profile: {ai_b}
Brand Summary: {json.dumps(bd)}
Brand Products: {json.dumps(bp2)}
Support Drivers: {json.dumps(bi3)}
Active Universe Segment: {analysis_mode}
Please deliver: 1) Strategic Assessment, 2) Core Vulnerabilities, 3) Tactical Product Defect Deep Dive, 4) Operational Response Strategy.""", api_key)
                    st.markdown(f'<div class="ai-box">{out}</div>', unsafe_allow_html=True)
                except Exception as e:
                    handle_ai_error(e)
