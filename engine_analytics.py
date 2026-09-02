"""
engine_analytics.py — Advanced Operational & Segment Scoring Engine (v4.1 - Fast Edition)
Completely refactored nested calculations to run using bulk matrix mapping.
"""
import pandas as pd
import numpy as np

HIGH_SUBCATS = ["Defective Product", "Damaged Product", "Low Quality Product", "Order Delay", "Order Not Shipped"]
MEDIUM_SUBCATS = ["Wrong Product Delivered", "Missing Items", "Refund Post Delivery", "Cancellation Request", "Tracking Query"]
LOW_SUBCATS = ["Colour Issue", "Size issue", "Quantity Mismatch", "Order Modification", "Address Change", "Payment Issue", "Order Confirmation Issue"]

def confidence_factor(delivered):
    if delivered >= 500:  return 1.00
    if delivered >= 300:  return 0.90
    if delivered >= 200:  return 0.80
    if delivered >= 100:  return 0.65
    if delivered >= 50:   return 0.45
    if delivered >= 20:   return 0.25
    return 0.10

def weighted_esc(tickets, delivered):
    if delivered <= 0: return 0.0
    return round(((tickets / delivered) * 100) * confidence_factor(delivered), 2)

def raw_esc(tickets, delivered):
    if delivered <= 0: return 0.0
    return round((tickets / delivered) * 100, 2)

def compute_brand_summary(del_df, tick_df, analysis_mode="Post Delivery",
                          crit_del=300, crit_esc=7.0, crit_tix=25,
                          high_del=200, high_esc=5.0,
                          med_del=100, med_esc=3.0):
    brand_del = del_df.groupby("brand").size().reset_index(name="delivered")
    brand_tick = tick_df.groupby("brand").size().reset_index(name="tickets")
    subcat_col = "subcat_final" if "subcat_final" in tick_df.columns else "raw_subcat"
    
    brand_defect = tick_df[tick_df[subcat_col].isin(HIGH_SUBCATS)].groupby("brand").size().reset_index(name="defect_tickets")
    
    df = brand_del.merge(brand_tick, on="brand", how="outer").fillna(0)
    df = df.merge(brand_defect, on="brand", how="left").fillna(0)
    
    df["brand"] = df["brand"].astype(str)
    df["delivered"] = df["delivered"].astype(int)
    df["tickets"] = df["tickets"].astype(int)
    df["defect_tickets"] = df["defect_tickets"].astype(int)
    
    df["esc_pct"] = df.apply(lambda r: raw_esc(r["tickets"], r["delivered"]), axis=1)
    df["defect_rate"] = df.apply(lambda r: raw_esc(r["defect_tickets"], r["delivered"]), axis=1)
    df["weighted_esc"] = df.apply(lambda r: weighted_esc(r["tickets"], r["delivered"]), axis=1)
    df["confidence"] = df["delivered"].apply(lambda d: round(confidence_factor(d) * 100))
    df["del_share"] = (df["delivered"] / max(df["delivered"].sum(), 1) * 100).round(1)
    df["tick_share"] = (df["tickets"] / max(df["tickets"].sum(), 1) * 100).round(1)
    
    if analysis_mode == "Combined":
        status_col = "order_status" if "order_status" in del_df.columns else None
        del_orders = del_df[del_df[status_col].astype(str).str.lower().str.strip() == "delivered"] if status_col else del_df
        post_tix = tick_df[tick_df["ticket_category"] == "POST_DELIVERY"] if not tick_df.empty else tick_df
        
        brand_del_post = del_orders.groupby("brand").size().reset_index(name="delivered_post")
        brand_tick_post = post_tix.groupby("brand").size().reset_index(name="tickets_post")
        brand_defect_post = post_tix[post_tix[subcat_col].isin(HIGH_SUBCATS)].groupby("brand").size().reset_index(name="defect_tickets_post")
        
        brand_del_pre = del_df.groupby("brand").size().reset_index(name="delivered_pre")
        brand_tick_pre = tick_df[tick_df["ticket_category"] == "PRE_DELIVERY"].groupby("brand").size().reset_index(name="tickets_pre")
        
        df_comb = brand_del_pre.merge(brand_del_post, on="brand", how="outer").fillna(0)
        df_comb = df_comb.merge(brand_tick_pre, on="brand", how="outer").fillna(0)
        df_comb = df_comb.merge(brand_tick_post, on="brand", how="outer").fillna(0)
        df_comb = df_comb.merge(brand_defect_post, on="brand", how="left").fillna(0)
        
        for c in ["delivered_pre", "delivered_post", "tickets_pre", "tickets_post", "defect_tickets_post"]:
            df_comb[c] = df_comb[c].fillna(0).astype(int)
            
        df_comb["pre_esc_pct"] = df_comb.apply(lambda r: raw_esc(r["tickets_pre"], r["delivered_pre"]), axis=1)
        df_comb["post_esc_pct"] = df_comb.apply(lambda r: raw_esc(r["tickets_post"], r["delivered_post"]), axis=1)
        df_comb["post_defect_rate"] = df_comb.apply(lambda r: raw_esc(r["defect_tickets_post"], r["delivered_post"]), axis=1)
        
        df_comb["delivered"] = df_comb["delivered_pre"]
        df_comb["tickets"] = df_comb["tickets_pre"] + df_comb["tickets_post"]
        df_comb["esc_pct"] = df_comb["post_esc_pct"]
        df_comb["defect_rate"] = df_comb["post_defect_rate"]
        df_comb["weighted_esc"] = df_comb.apply(lambda r: weighted_esc(r["tickets"], r["delivered"]), axis=1)
        df_comb["confidence"] = df_comb["delivered"].apply(lambda d: round(confidence_factor(d) * 100))
        df_comb["del_share"] = (df_comb["delivered"] / max(df_comb["delivered"].sum(), 1) * 100).round(1)
        df_comb["tick_share"] = (df_comb["tickets"] / max(df_comb["tickets"].sum(), 1) * 100).round(1)
        df = df_comb

    # Vectorized computation of Top Escalation Driver per brand
    top_drivers = {}
    if not tick_df.empty:
        grouped = tick_df.groupby(["brand", subcat_col]).size().reset_index(name="count")
        grouped = grouped.sort_values("count", ascending=False).drop_duplicates("brand")
        top_drivers = dict(zip(grouped["brand"], grouped[subcat_col]))
        
    df["Top Escalation Driver"] = df["brand"].map(top_drivers).fillna("N/A")
    
    if analysis_mode in ("Post Delivery", "Pre Delivery"):
        df["impact"] = df.apply(
            lambda r: "CRITICAL" if r["delivered"] >= crit_del and r["esc_pct"] >= crit_esc and r["tickets"] >= crit_tix 
            else "HIGH" if r["delivered"] >= high_del and r["esc_pct"] >= high_esc
            else "MEDIUM" if r["delivered"] >= med_del and r["esc_pct"] >= med_esc
            else "LOW", axis=1
        )
    else:
        df["impact"] = df.apply(
            lambda r: "CRITICAL" if (r["post_esc_pct"] >= crit_esc and r["tickets_post"] >= crit_tix) or (r["pre_esc_pct"] >= crit_esc and r["tickets_pre"] >= crit_tix)
            else "HIGH" if r["post_esc_pct"] >= high_esc or r["pre_esc_pct"] >= high_esc
            else "MEDIUM" if r["post_esc_pct"] >= med_esc or r["pre_esc_pct"] >= med_esc
            else "LOW", axis=1
        )
    return df.sort_values("tickets", ascending=False).reset_index(drop=True)

def compute_product_summary(del_df, tick_df, analysis_mode="Post Delivery",
                             crit_del=300, crit_esc=7.0, crit_tix=25,
                             high_del=200, high_esc=5.0,
                             med_del=100, med_esc=3.0):
    if analysis_mode == "Post Delivery":
        status_col = "order_status" if "order_status" in del_df.columns else None
        orders_universe = del_df[del_df[status_col].astype(str).str.lower().str.strip() == "delivered"] if status_col else del_df
        ticks_universe = tick_df[tick_df["ticket_category"] == "POST_DELIVERY"] if not tick_df.empty else tick_df
        
        prod_del = orders_universe.groupby(["brand", "canonical_product"]).size().reset_index(name="delivered")
        prod_tick = ticks_universe.groupby(["brand", "canonical_product"]).size().reset_index(name="tickets")
        
        df = prod_del.merge(prod_tick, on=["brand", "canonical_product"], how="outer").fillna(0)
        df["delivered"] = df["delivered"].astype(int)
        df["tickets"] = df["tickets"].astype(int)
        df["esc_pct"] = df.apply(lambda r: raw_esc(r["tickets"], r["delivered"]), axis=1)
        
    elif analysis_mode == "Pre Delivery":
        ticks_universe = tick_df[tick_df["ticket_category"] == "PRE_DELIVERY"] if not tick_df.empty else tick_df
        prod_del = del_df.groupby(["brand", "canonical_product"]).size().reset_index(name="delivered")
        prod_tick = ticks_universe.groupby(["brand", "canonical_product"]).size().reset_index(name="tickets")
        
        df = prod_del.merge(prod_tick, on=["brand", "canonical_product"], how="outer").fillna(0)
        df["delivered"] = df["delivered"].astype(int)
        df["tickets"] = df["tickets"].astype(int)
        df["esc_pct"] = df.apply(lambda r: raw_esc(r["tickets"], r["delivered"]), axis=1)
    else:
        status_col = "order_status" if "order_status" in del_df.columns else None
        del_orders = del_df[del_df[status_col].astype(str).str.lower().str.strip() == "delivered"] if status_col else del_df
        post_tix = tick_df[tick_df["ticket_category"] == "POST_DELIVERY"] if not tick_df.empty else tick_df
        pre_tix = tick_df[tick_df["ticket_category"] == "PRE_DELIVERY"] if not tick_df.empty else tick_df
        
        prod_del_post = del_orders.groupby(["brand", "canonical_product"]).size().reset_index(name="delivered_post")
        prod_tick_post = post_tix.groupby(["brand", "canonical_product"]).size().reset_index(name="tickets_post")
        prod_del_pre = del_df.groupby(["brand", "canonical_product"]).size().reset_index(name="delivered_pre")
        prod_tick_pre = pre_tix.groupby(["brand", "canonical_product"]).size().reset_index(name="tickets_pre")
        
        df = prod_del_pre.merge(prod_del_post, on=["brand", "canonical_product"], how="outer").fillna(0)
        df = df.merge(prod_tick_pre, on=["brand", "canonical_product"], how="outer").fillna(0)
        df = df.merge(prod_tick_post, on=["brand", "canonical_product"], how="outer").fillna(0)
        
        for c in ["delivered_pre", "delivered_post", "tickets_pre", "tickets_post"]:
            df[c] = df[c].astype(int)
            
        df["pre_esc_pct"] = df.apply(lambda r: raw_esc(r["tickets_pre"], r["delivered_pre"]), axis=1)
        df["post_esc_pct"] = df.apply(lambda r: raw_esc(r["tickets_post"], r["delivered_post"]), axis=1)
        
        df["delivered"] = df["delivered_pre"]
        df["tickets"] = df["tickets_pre"] + df["tickets_post"]
        df["esc_pct"] = df["post_esc_pct"]

    df["weighted_esc"] = df.apply(lambda r: weighted_esc(r["tickets"], r["delivered"]), axis=1)
    df["confidence"] = df["delivered"].apply(lambda d: round(confidence_factor(d) * 100))
    df["brand_product"] = df["brand"] + " | " + df["canonical_product"]
    
    primary_cohorts = {}
    ticket_aging = {}
    aging_cats = {}
    
    if not tick_df.empty:
        # Fast cohort allocation map using matrix sorting
        idx_cohort = tick_df.groupby(["brand", "canonical_product"])["Delivery Month"].value_counts().groupby(level=[0, 1]).idxmax()
        primary_cohorts = {k: v[2] for k, v in idx_cohort.items()}
        
        # High-Speed Vectorized aging duration diff
        t_series = pd.to_datetime(tick_df["Ticket Month Sort"] + "-01", format="%Y-%m-%d", errors="coerce")
        d_series = pd.to_datetime(tick_df["Delivery Month Sort"] + "-01", format="%Y-%m-%d", errors="coerce")
        diff_months = ((t_series.dt.year - d_series.dt.year) * 12 + (t_series.dt.month - d_series.dt.month)).fillna(0).astype(int)
        
        tick_df_temp = tick_df.copy()
        tick_df_temp["_diff"] = diff_months
        tick_df_temp["is_same"] = tick_df_temp["_diff"] <= 0
        tick_df_temp["is_prev"] = tick_df_temp["_diff"] == 1
        tick_df_temp["is_older"] = tick_df_temp["_diff"] > 1
        
        agg = tick_df_temp.groupby(["brand", "canonical_product"]).agg(
            same_m=("is_same", "sum"),
            prev_m=("is_prev", "sum"),
            older_m=("is_older", "sum"),
            total=("is_same", "count")
        )
        
        for (brand, prod), row in agg.iterrows():
            same_m, prev_m, older_m, total = int(row["same_m"]), int(row["prev_m"]), int(row["older_m"]), int(row["total"])
            ticket_aging[(brand, prod)] = (same_m, prev_m, older_m)
            
            if same_m / total >= 0.50:
                aging_cats[(brand, prod)] = "Emerging Risk"
            elif prev_m / total >= 0.50:
                aging_cats[(brand, prod)] = "Stable Risk"
            elif older_m / total >= 0.50:
                aging_cats[(brand, prod)] = "Historical Issue"
            else:
                aging_cats[(brand, prod)] = "Recovering"
            
    df["Primary Ticket Source Month"] = df.apply(lambda r: primary_cohorts.get((r["brand"], r["canonical_product"]), "N/A"), axis=1)
    df["Same Month Tickets"] = df.apply(lambda r: ticket_aging.get((r["brand"], r["canonical_product"]), (0,0,0))[0], axis=1)
    df["Previous Month Tickets"] = df.apply(lambda r: ticket_aging.get((r["brand"], r["canonical_product"]), (0,0,0))[1], axis=1)
    df["Older Tickets"] = df.apply(lambda r: ticket_aging.get((r["brand"], r["canonical_product"]), (0,0,0))[2], axis=1)
    df["Ticket Aging Category"] = df.apply(lambda r: aging_cats.get((r["brand"], r["canonical_product"]), "Stable"), axis=1)
    
    df["impact"] = df.apply(
        lambda r: "CRITICAL" if r["delivered"] >= crit_del and r["esc_pct"] >= crit_esc and r["tickets"] >= crit_tix 
        else "HIGH" if r["delivered"] >= 200 and r["esc_pct"] >= high_esc
        else "MEDIUM" if r["delivered"] >= 100 and r["esc_pct"] >= 3.0
        else "LOW", axis=1
    )
    return df.sort_values("tickets", ascending=False).reset_index(drop=True)

def compute_cohort_report(del_df, tick_df):
    if del_df.empty: return pd.DataFrame()
    cohort_del = del_df.groupby("Delivery Month Sort").size().reset_index(name="delivered")
    cohort_tick = tick_df.groupby("Delivery Month Sort").size().reset_index(name="tickets")
    
    df = cohort_del.merge(cohort_tick, on="Delivery Month Sort", how="outer").fillna(0)
    df["delivered"] = df["delivered"].astype(int)
    df["tickets"] = df["tickets"].astype(int)
    df["esc_pct"] = df.apply(lambda r: raw_esc(r["tickets"], r["delivered"]), axis=1)
    
    try:
        dt_converted = pd.to_datetime(df["Delivery Month Sort"] + "-01", format="%Y-%m-%d", errors="coerce")
        df["Delivery Month"] = dt_converted.dt.strftime("%B %Y")
    except Exception:
        df["Delivery Month"] = df["Delivery Month Sort"].astype(str)
    return df.sort_values("Delivery Month Sort").reset_index(drop=True)

def compute_weekly_trends(del_df, tick_df, weeks_list):
    if del_df.empty: return pd.DataFrame()
    del_w = del_df.groupby("Delivery Week").size().reindex(weeks_list, fill_value=0)
    tick_w = tick_df.groupby("Delivery Week").size().reindex(weeks_list, fill_value=0)
    
    df = pd.DataFrame({"Week": weeks_list, "Delivered": del_w.values, "Tickets": tick_w.values})
    df["Esc %"] = df.apply(lambda r: raw_esc(r["Tickets"], r["Delivered"]), axis=1)
    df["WoW Change Tickets"] = df["Tickets"].diff().fillna(0).astype(int)
    df["WoW Change Esc %"] = df["Esc %"].diff().fillna(0.0).round(2)
    df["Spike Alert"] = df.apply(lambda r: "🚨 SPIKE" if r["Esc %"] >= 8.0 and r["Tickets"] >= 5 else "✅ STABLE", axis=1)
    return df

def compute_subcat_summary(tick_df):
    if tick_df.empty: return pd.DataFrame()
    subcat_col = "subcat_final" if "subcat_final" in tick_df.columns else "raw_subcat"
    df = tick_df.groupby(subcat_col).size().reset_index(name="count")
    df = df.rename(columns={subcat_col: "subcat_final"})
    df["pct"] = (df["count"] / max(df["count"].sum(), 1) * 100).round(1)
    df["tier"] = df["subcat_final"].apply(lambda s: "HIGH" if s in HIGH_SUBCATS else "MEDIUM" if s in MEDIUM_SUBCATS else "LOW")
    return df.sort_values("count", ascending=False).reset_index(drop=True)

def top_kpis(brand_sum, prod_sum, subcat_sum, tick_df, del_df, weeks_list):
    total_del = len(del_df)
    total_tick = len(tick_df)
    overall = raw_esc(total_tick, total_del)
    
    subcat_col = "subcat_final" if "subcat_final" in tick_df.columns else "raw_subcat"
    defect_tix_count = len(tick_df[tick_df[subcat_col].isin(HIGH_SUBCATS)]) if not tick_df.empty else 0
    overall_defect = raw_esc(defect_tix_count, total_del)

    critical_n = len(brand_sum[brand_sum["impact"] == "CRITICAL"]) if not brand_sum.empty else 0
    high_n     = len(brand_sum[brand_sum["impact"] == "HIGH"]) if not brand_sum.empty else 0

    top_risk_brand = brand_sum.iloc[0]["brand"] if not brand_sum.empty else "—"
    top_risk_prod  = prod_sum.iloc[0]["canonical_product"][:40] if not prod_sum.empty else "—"
    top_issue      = subcat_sum.iloc[0]["subcat_final"] if not subcat_sum.empty else "—"

    spike_wk = "—"
    if not tick_df.empty and weeks_list:
        wk_totals = {wk: len(tick_df[tick_df["Delivery Week"] == wk]) for wk in weeks_list}
        if wk_totals: spike_wk = max(wk_totals, key=wk_totals.get)

    return {
        "total_del": total_del, "total_tick": total_tick, "overall_esc": overall,
        "overall_defect": overall_defect,
        "top_risk_brand": top_risk_brand, "top_risk_prod": top_risk_prod, "top_issue": top_issue,
        "spike_week": spike_wk,
        "critical_brands": critical_n, "high_brands": high_n,
        "n_brands": len(brand_sum),
    }
