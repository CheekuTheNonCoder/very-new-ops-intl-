"""
diagnose_brand_overlap.py

Standalone diagnostic — run this on YOUR machine (not on the deployed app)
directly against your raw Orders and Tickets Excel files. It uses the exact
same column-detection and brand-normalization logic as the dashboard, and
prints out exactly which brands overlap and which don't — so we can see
whether this is a data problem or an app/deployment problem.

Usage:
    pip install pandas openpyxl rapidfuzz --break-system-packages
    python diagnose_brand_overlap.py "orders.xlsx" "tickets.xlsx"
"""
import sys
import pandas as pd

# --- import the same detection/normalization logic used by the app ---
from engine_loader import _detect_brand_col, _detect_product_col
from engine_normalize import normalize_brand_name


def main(orders_path, tickets_path):
    orders_df = pd.read_excel(orders_path)
    tickets_df = pd.read_excel(tickets_path)
    orders_df.columns = [str(c).strip() for c in orders_df.columns]
    tickets_df.columns = [str(c).strip() for c in tickets_df.columns]

    o_brand_col = _detect_brand_col(orders_df)
    t_brand_col = _detect_brand_col(tickets_df)

    print(f"\nDetected ORDERS brand column   -> '{o_brand_col}'")
    print(f"Detected TICKETS brand column  -> '{t_brand_col}'\n")

    orders_df["raw_brand"] = orders_df[o_brand_col].astype(str).str.strip().str.strip('"')
    tickets_df["raw_brand"] = tickets_df[t_brand_col].astype(str).str.strip().str.strip('"')

    orders_df["brand"] = orders_df["raw_brand"].apply(normalize_brand_name)
    tickets_df["brand"] = tickets_df["raw_brand"].apply(normalize_brand_name)

    order_counts = orders_df["brand"].value_counts()
    ticket_counts = tickets_df["brand"].value_counts()

    order_brands = set(order_counts.index)
    ticket_brands = set(ticket_counts.index)

    overlap = order_brands & ticket_brands
    only_tickets = ticket_brands - order_brands
    only_orders = order_brands - ticket_brands

    print(f"Distinct normalized brands in ORDERS:  {len(order_brands)}")
    print(f"Distinct normalized brands in TICKETS: {len(ticket_brands)}")
    print(f"Brands present in BOTH:                {len(overlap)}")
    print(f"Brands ONLY in tickets (delivered=0):   {len(only_tickets)}")
    print(f"Brands ONLY in orders (tickets=0):      {len(only_orders)}\n")

    print("=" * 70)
    print("TOP 15 TICKET BRANDS WITH ZERO MATCHING ORDERS (the real bug list):")
    print("=" * 70)
    top_broken = ticket_counts[ticket_counts.index.isin(only_tickets)].head(15)
    for brand, cnt in top_broken.items():
        # show a sample raw value so we can see what the source text looks like
        sample_raw = tickets_df[tickets_df["brand"] == brand]["raw_brand"].iloc[0]
        print(f"  {cnt:>5} tickets | normalized='{brand}' | sample raw value='{sample_raw}'")

    print("\n" + "=" * 70)
    print("TOP 10 BRANDS THAT DO OVERLAP CORRECTLY (sanity check):")
    print("=" * 70)
    overlap_ticket_counts = ticket_counts[ticket_counts.index.isin(overlap)].head(10)
    for brand, cnt in overlap_ticket_counts.items():
        print(f"  {cnt:>5} tickets | delivered={order_counts.get(brand, 0):>5} | brand='{brand}'")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python diagnose_brand_overlap.py <orders_file.xlsx> <tickets_file.xlsx>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])