import pandas as pd
import re
import io
import streamlit as st

st.set_page_config(page_title="Campaign KPI Analyzer", layout="wide")

# ---------- Helpers ----------
def norm_phone(x):
    s = "".join(ch for ch in str(x) if ch.isdigit())
    if s.startswith("974"): return s
    if len(s) == 8: return "974"+s
    return s

def compute_kpis(buyers, reach, start=None, end=None, item_filter=None):
    # expected cols: buyers: phone_number, order_id, created_at, item_name, quantity, total_spent
    buyers = buyers.copy()
    reach  = reach.copy()

    # normalize phones
    buyers["_phone"] = buyers["phone_number"].map(norm_phone)
    reach["_phone"]  = reach["phone_number"].map(norm_phone)

    # optional item filter (e.g., brand/sku substring)
    if item_filter:
        buyers = buyers[buyers["item_name"].str.contains(item_filter, case=False, na=False)]

    # date window
    buyers["created_at"] = pd.to_datetime(buyers["created_at"], errors="coerce")
    if start: buyers = buyers[buyers["created_at"] >= pd.to_datetime(start)]
    if end:   buyers = buyers[buyers["created_at"] <= pd.to_datetime(end)]

    reach_u  = reach["_phone"].nunique()
    buyers_u = buyers["_phone"].nunique()

    # match conversions
    conv = buyers.merge(reach[["_phone"]].drop_duplicates(), on="_phone", how="inner")
    conv_u = conv["_phone"].nunique()
    conv_rate = (conv_u / reach_u * 100) if reach_u else 0

    total_revenue = conv["total_spent"].sum(min_count=1) or 0
    total_orders  = conv["order_id"].nunique()
    total_units   = conv["quantity"].sum(min_count=1) or 0
    aov = (total_revenue / total_orders) if total_orders else 0

    # repeat buyers among converts
    rb = conv.groupby("_phone")["order_id"].nunique()
    repeat_count = int((rb > 1).sum())
    repeat_rate  = (repeat_count / conv_u * 100) if conv_u else 0

    # by-day trend
    by_day = (conv.assign(day=conv["created_at"].dt.date)
                    .groupby("day", as_index=False)
                    .agg(orders=("order_id","nunique"),
                         buyers=(" _phone".strip(),"nunique"),
                         revenue=("total_spent","sum")))

    kpis = {
        "Reached (unique)": f"{reach_u:,}",
        "Matched buyers (unique)": f"{conv_u:,}",
        "Conversion rate %": f"{conv_rate:.2f}",
        "Total revenue (QAR)": f"{total_revenue:,.2f}",
        "Total orders": f"{total_orders:,}",
        "Total units": f"{total_units:,}",
        "AOV (QAR/order)": f"{aov:,.2f}",
        "Repeat buyers (count)": f"{repeat_count}",
        "Repeat buyer rate %": f"{repeat_rate:.1f}",
    }
    return kpis, conv, by_day

def df_to_csv_download(df, filename, label):
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(label=label, data=csv, file_name=filename, mime="text/csv")

# ---------- UI ----------
st.title("📣 Campaign KPI Analyzer")

col_uploads = st.columns(2)
with col_uploads[0]:
    reach_file = st.file_uploader("Upload REACH file (Excel/CSV)", type=["xlsx","xls","csv"])
with col_uploads[1]:
    buyers_file = st.file_uploader("Upload SALES/BUYERS file (CSV/Excel)", type=["csv","xlsx","xls"])

col_opts = st.columns(3)
with col_opts[0]:
    campaign_name = st.text_input("Campaign name (optional)", value="Campaign")
with col_opts[1]:
    start_date = st.date_input("Start date (optional)", value=None)
with col_opts[2]:
    end_date = st.date_input("End date (optional)", value=None)

item_filter = st.text_input("Filter by item/brand name (optional, e.g., 'Auracos')", value="")

# load data
def load_df(file):
    if file is None: return None
    if file.name.lower().endswith(".csv"):
        return pd.read_csv(file)
    return pd.read_excel(file)

reach_df  = load_df(reach_file)
buyers_df = load_df(buyers_file)

st.markdown("---")

if reach_df is not None and buyers_df is not None:
    # column hints
    needed_buyers = {"phone_number", "order_id", "created_at", "item_name", "quantity", "total_spent"}
    needed_reach  = {"phone_number"}

    # light validation
    missing_b = needed_buyers - set(map(str, buyers_df.columns))
    missing_r = needed_reach  - set(map(str, reach_df.columns))
    if missing_b:
        st.error(f"Buyers file missing columns: {', '.join(missing_b)}")
    elif missing_r:
        st.error(f"Reach file missing columns add column: {', '.join(missing_r)}")
    else:
        kpis, conv, by_day = compute_kpis(
            buyers_df, reach_df,
            start=start_date if start_date else None,
            end=end_date if end_date else None,
            item_filter=item_filter.strip() or None
        )

        st.subheader("KPI Summary")
        k_cols = st.columns(3)
        keys = list(kpis.keys())
        for i, k in enumerate(keys):
            with k_cols[i % 3]:
                st.metric(k, kpis[k])

        st.markdown("### Converted Customers (matched)")
        st.dataframe(conv[["_phone","order_id","created_at","item_name","quantity","total_spent"]]
                        .sort_values(["created_at","_phone"]))
        df_to_csv_download(conv, f"{campaign_name}_converted_customers.csv", "Download converted customers CSV")

        st.markdown("### Daily Trend")
        st.dataframe(by_day)
        df_to_csv_download(by_day, f"{campaign_name}_daily_conversions.csv", "Download daily conversions CSV")

        # KPI CSV
        kpi_df = pd.DataFrame({"Metric": list(kpis.keys()), "Value": list(kpis.values())})
        df_to_csv_download(kpi_df, f"{campaign_name}_kpis.csv", "Download KPI summary CSV")

else:
    st.info("Upload both files to compute KPIs.")
