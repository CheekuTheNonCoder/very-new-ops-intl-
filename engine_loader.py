"""
engine_loader.py — Time Intelligence & Dynamic Loader (v4.2 - Marketplace Bifurcation)
Removed all iterative row loops in favor of vectorized grouping operations.
Identifies and tags records by marketplace (ZOP vs Afora) based on order IDs.
"""
import io
import pandas as pd
import numpy as np
import streamlit as st

from engine_normalize import normalize_brand_name, ProductRegistry
from engine_redistribute import (
    compute_brand_weights, redistribute_tickets,
    redistribute_subcat, build_redistribution_summary
)
import database_loader

def _detect_col(df, keywords, fallback=0, exclude=None):
    cols_lower = {str(c).lower().strip(): c for c in df.columns}
    for kw in keywords:
        for col_l, col in cols_lower.items():
            if exclude and any(ex.lower() in col_l for ex in exclude):
                continue
            if kw.lower() in col_l:
                return col
    if len(df.columns) == 0:
        raise ValueError("The operational dataset has no columns.")
    if fallback is None or fallback >= len(df.columns):
        return df.columns[-1]
    return df.columns[fallback]

def _detect_date_col(df):
    date_keywords = ["order_delivered_at", "order_created_at", "delivered_at", "createdatdate", "created_at", "date", "time", "created", "timestamp", "day", "delivered"]
    for kw in date_keywords:
        for col in df.columns:
            if kw in str(col).lower().strip():
                return col
    best_col = df.columns[0]
    max_valid = -1
    for col in df.columns[:4]:
        try:
            parsed = pd.to_datetime(df[col], errors="coerce")
            valid_count = parsed.notna().sum()
            if valid_count > max_valid:
                max_valid = valid_count
                best_col = col
        except Exception:
            pass
    return best_col

def _detect_order_col(df):
    id_keywords = ["zop_id", "orderid", "order_id", "order id", "id"]
    for kw in id_keywords:
        for col in df.columns:
            if kw in str(col).lower().strip():
                return col
    return df.columns[1] if len(df.columns) > 1 else df.columns[0]

def _detect_brand_col(df):
    brand_keywords = ["company_name", "company name", "company nam", "company", "brand", "seller"]
    for kw in brand_keywords:
        for col in df.columns:
            col_clean = str(col).lower().strip()
            if "customer" in col_clean:
                continue
            if kw in col_clean:
                return col
    return df.columns[3] if len(df.columns) > 3 else df.columns[0]

def _detect_product_col(df):
    prod_keywords = ["product name", "product_name", "product", "item"]
    for kw in prod_keywords:
        for col in df.columns:
            if kw in str(col).lower().strip():
                return col
    return df.columns[4] if len(df.columns) > 4 else df.columns[0]

def _detect_status_col(df):
    status_keywords = ["order_status", "order status", "status", "state"]
    for kw in status_keywords:
        for col in df.columns:
            if kw in str(col).lower().strip():
                return col
    return None

def safe_parse_datetime(series):
    s = series.copy()
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    try:
        s_numeric = pd.to_numeric(s, errors="coerce")
        excel_mask = s_numeric.notna() & (s_numeric > 25000) & (s_numeric < 60000)
        if excel_mask.any():
            excel_dates = pd.to_datetime(s_numeric[excel_mask], unit="D", origin="1899-12-30")
            s = s.astype(object)
            s[excel_mask] = excel_dates
    except Exception:
        pass
        
    for fmt in ["%d-%m-%Y", "%d/%m/%Y", "%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S"]:
        try:
            parsed = pd.to_datetime(s, format=fmt, errors="coerce")
            if parsed.notna().sum() > len(parsed) * 0.8:
                return parsed
        except Exception:
            pass

    parsed_fallback = pd.to_datetime(s, errors="coerce", dayfirst=True)
    if parsed_fallback.isna().sum() > len(parsed_fallback) * 0.5:
        try:
            parsed_fallback = pd.to_datetime(s, errors="coerce", format="mixed", dayfirst=True)
        except Exception:
            parsed_fallback = pd.to_datetime(s, errors="coerce")
    return parsed_fallback

def parse_date_hierarchy(df, col_name, prefix):
    dt_series = safe_parse_datetime(df[col_name])
    dt_series = dt_series.apply(lambda x: pd.NaT if pd.notna(x) and x.year < 1975 else x)
    
    df[f"{prefix} Date"] = dt_series.dt.date.astype(str)
    df[f"{prefix} Date"] = df[f"{prefix} Date"].fillna("Unknown Date")
    df[f"{prefix} Year"] = dt_series.apply(lambda x: int(x.year) if pd.notna(x) else "Unknown Year")
    df[f"{prefix} Quarter"] = dt_series.apply(lambda x: f"{x.year}-Q{x.quarter}" if pd.notna(x) else "Unknown Quarter")
    df[f"{prefix} Month"] = dt_series.apply(lambda x: x.strftime("%B %Y") if pd.notna(x) else "Unknown Month")
    df[f"{prefix} Month Sort"] = dt_series.dt.to_period("M").astype(str)
    df[f"{prefix} Week"] = dt_series.apply(
        lambda d: f"{d.strftime('%b %Y')} Wk{min((d.day - 1) // 7 + 1, 4)}" if pd.notna(d) else "Unknown Week"
    )
    return df

def generate_dynamic_periods(df, date_col="raw_date"):
    if df.empty or date_col not in df.columns:
        return ["All Data"]
    dt_series = safe_parse_datetime(df[date_col])
    dt_series = dt_series[dt_series.notna() & (dt_series.dt.year >= 1975)]
    if dt_series.empty:
        return ["All Data"]
        
    unique_dates = dt_series.dt.date.unique()
    if len(unique_dates) == 1:
        single_str = unique_dates[0].strftime("%B %d, %Y")
        if ", " in single_str:
            parts = single_str.split(", ")
            month = parts[0].split(" ")[0]
            day = str(int(parts[0].split(" ")[1]))
            single_str = f"{month} {day}, {parts[1]}"
        return ["All Data", single_str]
        
    periods = sorted(dt_series.dt.to_period("M").unique())
    options = ["All Data"] + [p.strftime("%B %Y") for p in periods]
    return options

def normalize_ticket_category(val):
    if not isinstance(val, str):
        return "POST_DELIVERY"
    s = val.strip().upper().replace("-", " ").replace("_", " ")
    return "PRE_DELIVERY" if "PRE" in s else "POST_DELIVERY"

def load_delivered(df_or_bytes):
    df = df_or_bytes.copy() if isinstance(df_or_bytes, pd.DataFrame) else pd.read_excel(io.BytesIO(df_or_bytes))
    df.columns = [str(c).strip() for c in df.columns]
    
    date_col = _detect_date_col(df)
    status_col = _detect_status_col(df)
    order_col = _detect_order_col(df)
    brand_col = _detect_brand_col(df)
    prod_col = _detect_product_col(df)
    
    # Marketplace extraction based on order id value
    order_ids = df[order_col].astype(str).str.strip()
    marketplace = np.where(order_ids.str.upper().str.contains("AFORA", na=False), "Afora", "ZOP")
    
    out = pd.DataFrame({
        "order_id": order_ids,
        "raw_date": df[date_col],
        "raw_brand": df[brand_col].astype(str).str.strip().str.strip('"'),
        "raw_product": df[prod_col].astype(str).str.strip().str.strip('"'),
        "order_status": df[status_col].astype(str).str.strip() if status_col else "delivered",
        "marketplace": marketplace
    })
    
    status_clean = out["order_status"].astype(str).str.lower().str.strip()
    out["is_delivered"] = (
        status_clean.str.contains("deliver", na=False) & 
        ~status_clean.str.contains("out", na=False) & 
        ~status_clean.str.contains("fail", na=False) & 
        ~status_clean.str.contains("un", na=False)
    )
    return parse_date_hierarchy(out, "raw_date", "Delivery")

def load_tickets_raw(df_or_bytes):
    df = df_or_bytes.copy() if isinstance(df_or_bytes, pd.DataFrame) else pd.read_excel(io.BytesIO(df_or_bytes))
    df.columns = [str(c).strip() for c in df.columns]
    
    date_col = _detect_date_col(df)
    order_col = _detect_order_col(df)
    prod_col = _detect_product_col(df)
    brand_col = _detect_brand_col(df)
    
    cat_col = next((c for c in df.columns if c == "Ticket Category"), None) or _detect_col(df, ["Ticket Category", "category", "raw_category", "ticket_category"], 4, exclude=["sub", "subcategory"])
    subcat_col = next((c for c in df.columns if c == "Ticket Sub-Category"), None) or _detect_col(df, ["Ticket Sub-Category", "sub-category", "sub category", "sub_category", "subcategory", "subcat", "raw_subcat"], 5)
    
    if cat_col == subcat_col:
        raise ValueError(f"Column Collision: {cat_col} resolved twice.")
        
    order_ids = df[order_col].astype(str).str.strip()
    marketplace = np.where(order_ids.str.upper().str.contains("AFORA", na=False), "Afora", "ZOP")
    
    out = pd.DataFrame({
        "order_id": order_ids,
        "raw_date": df[date_col],
        "raw_brand": df[brand_col].astype(str).str.strip().str.strip('"'),
        "raw_product": df[prod_col].astype(str).str.strip().str.strip('"'),
        "raw_subcat":  df[subcat_col].astype(str).str.strip(),
        "marketplace": marketplace
    })
    
    out["raw_category"] = df[cat_col].fillna("NULL").astype(str).str.strip() if cat_col else "NULL"
    out["ticket_category"] = out["raw_category"].apply(normalize_ticket_category)
    return parse_date_hierarchy(out, "raw_date", "Ticket")

def load_orders():
    return database_loader.load_orders()

def load_tickets():
    return database_loader.load_tickets()

def process_pipeline(del_input, tick_input, rng_seed=42):
    rng = np.random.default_rng(rng_seed)
    
    del_raw = del_input.copy() if (isinstance(del_input, pd.DataFrame) and "raw_date" in del_input.columns) else load_delivered(del_input)
    tick_raw = tick_input.copy() if (isinstance(tick_input, pd.DataFrame) and "raw_subcat" in tick_input.columns) else load_tickets_raw(tick_input)
    ORIGINAL_TICKET_COUNT = len(tick_raw)

    unique_del_brands = del_raw["raw_brand"].unique()
    unique_tick_brands = tick_raw["raw_brand"].unique()
    brand_map = {b: normalize_brand_name(b) for b in (set(unique_del_brands) | set(unique_tick_brands))}

    del_raw["brand"] = del_raw["raw_brand"].map(brand_map).astype(str)
    tick_raw["brand"] = tick_raw["raw_brand"].map(brand_map).astype(str)
    tick_raw["_redistributed"] = False

    del_clean = del_raw.copy().reset_index(drop=True)
    valid_order_mask = del_clean["order_id"].notna() & (del_clean["order_id"].astype(str).str.len() > 3)
    del_lookup = del_clean[valid_order_mask].drop_duplicates(subset=["order_id"]).set_index("order_id")[
        ["Delivery Date", "Delivery Week", "Delivery Month", "Delivery Quarter", "Delivery Year", "Delivery Month Sort"]
    ]
    
    tick_raw = tick_raw.join(del_lookup, on="order_id", how="left")
    for col in ["Delivery Date", "Delivery Week", "Delivery Month", "Delivery Quarter", "Delivery Year", "Delivery Month Sort"]:
        tick_raw[col] = tick_raw[col].fillna(tick_raw[col.replace("Delivery", "Ticket")])

    valid_mask = tick_raw["brand"] != "Unmapped Brand"
    valid_ticks = tick_raw[valid_mask].copy()

    # ── Step 4: Product Registry Matching ──
    registry = ProductRegistry()
    
    del_counts = del_clean.groupby(["brand", "raw_product"]).size()
    for (brand, raw_prod), count in del_counts.items():
        registry.record_delivered(brand, raw_prod, count)
        
    tick_counts_groups = valid_ticks.groupby(["brand", "raw_product"]).size()
    for (brand, raw_prod), _ in tick_counts_groups.items():
        registry.record_ticket(brand, raw_prod)
        
    registry.resolve()

    flat_lookup = {}
    for brand, p_map in registry.resolved_map.items():
        for raw_p, canon_p in p_map.items():
            flat_lookup[(str(brand), str(raw_p).strip().strip('"').strip("'"))] = canon_p

    del_clean["canonical_product"] = [
        flat_lookup.get((str(b), str(p).strip().strip('"').strip("'")), p)
        for b, p in zip(del_clean["brand"], del_clean["raw_product"])
    ]
    
    valid_ticks["canonical_product"] = [
        flat_lookup.get((str(b), str(p).strip().strip('"').strip("'")), p)
        for b, p in zip(valid_ticks["brand"], valid_ticks["raw_product"])
    ]
    
    tick_raw["canonical_product"] = "Unmapped Product"
    tick_raw.loc[valid_mask, "canonical_product"] = valid_ticks["canonical_product"].values

    brand_unmapped = tick_raw[~valid_mask].copy()

    from engine_analytics import compute_brand_summary as _bs
    base_brand_sum = _bs(del_clean, valid_ticks, "Post Delivery")
    brand_weights = compute_brand_weights(base_brand_sum, valid_ticks)

    dist_brand = redistribute_tickets(brand_unmapped, brand_weights, rng)
    if len(dist_brand) > 0:
        dist_brand["canonical_product"] = [
            flat_lookup.get((str(b), str(p).strip().strip('"').strip("'")), p)
            for b, p in zip(dist_brand["brand"], dist_brand["raw_product"])
        ]

    all_ticks = pd.concat([valid_ticks, dist_brand], ignore_index=True)
    val_ok = len(all_ticks) == ORIGINAL_TICKET_COUNT

    # ── Step 6: Subcategory Normalization ──
    n_nf = int((all_ticks["raw_subcat"] == "Not Found").sum())
    n_nd = int((all_ticks["raw_subcat"] == "Need Details").sum())
    
    all_ticks["subcat_final"] = [
        redistribute_subcat(raw, b, cp, cat, rng)
        for raw, b, cp, cat in zip(all_ticks["raw_subcat"], all_ticks["brand"], all_ticks["canonical_product"], all_ticks["ticket_category"])
    ]

    tick_counts = all_ticks[all_ticks["brand"] != "Unmapped Brand"].groupby(["brand", "canonical_product"]).size().to_dict()
    for brand, groups in registry.final_groups.items():
        brand_str = str(brand)
        for cname in groups.keys():
            registry.final_groups[brand_str][cname]["tickets"] = tick_counts.get((brand_str, cname), 0)

    redist_summary = build_redistribution_summary(len(brand_unmapped), n_nf, n_nd, brand_weights)
    
    period_options = generate_dynamic_periods(del_clean, "raw_date")
    available_months = sorted(del_clean["Delivery Month Sort"].dropna().unique())

    return {
        "del_df": del_clean,
        "tick_df": all_ticks,
        "registry": registry,
        "brand_weights": brand_weights,
        "redist_summary": redist_summary,
        "original_ticket_count": ORIGINAL_TICKET_COUNT,
        "n_unmapped_brand": len(brand_unmapped),
        "n_not_found_subcat": n_nf,
        "n_need_details": n_nd,
        "final_ticket_count": len(all_ticks),
        "validation_ok": val_ok,
        "invalid_del_dates": int(del_raw["Delivery Date"].apply(lambda x: x == "Unknown Date").sum()),
        "invalid_tick_dates": int(tick_raw["Ticket Date"].apply(lambda x: x == "Unknown Date").sum()),
        "raw_cat_counts": tick_raw["raw_category"].value_counts().to_dict(),
        "norm_cat_counts": tick_raw["ticket_category"].value_counts().to_dict(),
        "period_options": period_options,
        "available_months": available_months
    }
