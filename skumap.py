import streamlit as st
import pandas as pd
import re
import io
from datetime import datetime

from supabase import create_client, Client
from thefuzz import fuzz
import pdfplumber
from reportlab.pdfgen import canvas
INCH = 72

st.set_page_config(page_title="Aavoni Seller Suite", layout="wide")

url, key = st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(url, key)

if 'user' not in st.session_state:
    st.session_state.user = None

# ---------------- UTILS ----------------
def get_design_pattern(master_sku):
    sku = str(master_sku).upper().strip()
    sku = re.sub(r'[-_](S|M|L|XL|XXL|FREE)$', '', sku)
    return sku

@st.cache_data(ttl=300)
def load_all_data(u_id):
    m_res = supabase.table("sku_mapping").select("portal_sku, master_sku").eq("user_id", u_id).execute()
    m_dict = {item['portal_sku'].upper(): item['master_sku'] for item in m_res.data} if m_res.data else {}
    return m_dict, {}, []

# ---------------- AUTH ----------------
if st.session_state.user is None:
    st.title("🚀 Aavoni Seller Suite")
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        if res.user:
            st.session_state.user = res.user
            st.rerun()

else:
    u_id = st.session_state.user.id

    # ✅ DATA LOAD
    mapping_dict, costing_dict, master_options = load_all_data(u_id)

    # ---------------- SIDEBAR ----------------
    with st.sidebar:
        if st.button("Logout"):
            supabase.auth.sign_out()
            st.session_state.user = None
            st.rerun()

    # ---------------- TABS ----------------
    t1, t2, t3, t4 = st.tabs([
        "📦 Picklist",
        "💰 Costing Manager",
        "📊 Flipkart Profit",
        "👗 Myntra Profit"
    ])

    # ================= TAB 1 =================
    with t1:
        st.header("Order Processing & Picklist")

        files = st.file_uploader("Upload Orders", accept_multiple_files=True)

        if files:
            orders_data = []

            for f in files:
                if f.name.endswith('.csv'):
                    df_c = pd.read_csv(f)
                    df_c.columns = [c.strip() for c in df_c.columns]

                    # ✅ Myntra Priority SKU
                    sku_c = None
                    for p in ['seller_sku_code','seller sku code','seller_sku','seller sku']:
                        for col in df_c.columns:
                            if col.lower() == p:
                                sku_c = col
                                break
                        if sku_c:
                            break

                    if sku_c is None:
                        sku_c = next((c for c in df_c.columns if 'sku' in c.lower()), None)

                    if sku_c is None:
                        st.error(f"SKU not found: {f.name}")
                        continue

                    qty_c = next((c for c in df_c.columns if 'qty' in c.lower()), None)

                    for _, row in df_c.iterrows():
                        orders_data.append({
                            'Portal_SKU': str(row[sku_c]).upper(),
                            'Qty': int(row[qty_c]) if qty_c else 1
                        })

                elif f.name.endswith('.pdf'):
                    with pdfplumber.open(f) as pdf:
                        for page in pdf.pages:
                            table = page.extract_table()
                            if table:
                                for row in table[1:]:
                                    orders_data.append({'Portal_SKU': str(row[0]).upper(), 'Qty': 1})

            if orders_data:
                st.success(f"Orders Loaded: {len(orders_data)}")

    # --- TAB 2: COSTING MANAGER ---
    with t2:
        st.header("💰 Costing Manager")
        all_master = list(set(mapping_dict.values()))
        all_designs = sorted(list(set([get_design_pattern(s) for s in all_master])))
        missing = [d for d in all_designs if d not in costing_dict]
        if missing: st.warning(f"⚠️ {len(missing)} Designs have missing costing.")
        with st.form("cost_up"):
            col1, col2 = st.columns(2)
            sel = col1.selectbox("Select Design", options=missing + [d for d in all_designs if d in costing_dict])
            new_v = col2.number_input("Landed Cost (₹)", min_value=0.0, value=float(costing_dict.get(sel, 0.0)))
            if st.form_submit_button("Save Costing"):
                supabase.table("design_costing").upsert({"user_id": u_id, "design_pattern": sel, "landed_cost": new_v}, on_conflict="user_id, design_pattern").execute()
                st.success("Saved!"); st.rerun()
        if costing_dict: st.dataframe(pd.DataFrame(list(costing_dict.items()), columns=['Pattern', 'Cost']), use_container_width=True)

    # --- TAB 3: FLIPKART ANALYZER ---
    with t3:
        st.title("📊 Aavoni Pro Business Dashboard")
        uploaded_file = st.file_uploader("Upload Flipkart Orders Excel (.xlsx)", type=["xlsx"])
        if uploaded_file:
            try:
                excel_data = pd.ExcelFile(uploaded_file)
                target_sheet = next((s for s in excel_data.sheet_names if "Orders P&L" in s), excel_data.sheet_names[0])
                df = pd.read_excel(uploaded_file, sheet_name=target_sheet)
                df.columns = [str(c).strip() for c in df.columns]
                sku_col, sett_col = "SKU Name", "Bank Settlement [Projected] (INR)"
                unit_col, id_col, status_col = "Net Units", "Order ID", "Order Status"

                if sku_col in df.columns and sett_col in df.columns:
                    df[unit_col] = pd.to_numeric(df[unit_col], errors='coerce').fillna(0).astype(int)
                    df[sett_col] = pd.to_numeric(df[sett_col], errors='coerce').fillna(0)
                    
                    def get_cat_data(sku_name):
                        p_sku = str(sku_name).strip().upper()
                        m_sku = mapping_dict.get(p_sku, p_sku)
                        pat = get_design_pattern(m_sku)
                        if pat in costing_dict: return "DB Match", costing_dict[pat]
                        is_hf = p_sku.startswith("HF")
                        base = hf_base if is_hf else std_base
                        if "3CBO" in p_sku: return "Combo 3", (base * 3)
                        if "CBO" in p_sku: return "Combo 2", (base * 2)
                        return ("HF Single" if is_hf else "Std Single"), base

                    res = df[sku_col].apply(get_cat_data)
                    df['Category'], df['Unit_Cost'] = [x[0] for x in res], [x[1] for x in res]
                    df['Net_Profit'] = df.apply(lambda x: x[sett_col] - (x[unit_col] * x['Unit_Cost']) if x[unit_col] > 0 else x[sett_col], axis=1)

                    m1, m2, m3 = st.columns(3)
                    t_pay, t_prof = df[sett_col].sum(), df['Net_Profit'].sum()
                    m1.metric("Total Settlement", f"₹{int(t_pay):,}")
                    m2.metric("Net Profit", f"₹{int(t_prof):,}", delta=f"{(t_prof/t_pay*100 if t_pay>0 else 0):.1f}% Margin")
                    m3.metric("Net Units Sold", f"{int(df[unit_col].sum()):,}")

                    st.divider()
                    st.subheader("💰 Category Performance")
                    summary = df.groupby('Category').agg({unit_col: 'sum', sett_col: 'sum', 'Net_Profit': 'sum'})
                    st.table(summary.fillna(0).astype(int))

                    st.subheader("🔎 All Orders Breakdown")
                    final_disp = df[[id_col, sku_col, 'Category', 'Unit_Cost', status_col, unit_col, sett_col, 'Net_Profit']].copy()
                    final_disp[sett_col] = final_disp[sett_col].round(0).astype(int)
                    final_disp['Net_Profit'] = final_disp['Net_Profit'].round(0).astype(int)
                    final_disp['Unit_Cost'] = final_disp['Unit_Cost'].round(0).astype(int)
                    st.dataframe(final_disp.sort_index(ascending=False), use_container_width=True, hide_index=True)

            except Exception as e: st.error(f"Error: {e}")

    with t4:
        st.title("👗 Myntra Smart P&L & Return Analyzer")

    uploaded_files = st.file_uploader(
        "Upload Flow + SKU + Settlement Files",
        type=['csv'],
        accept_multiple_files=True
    )

    def get_final_cost(sku_name):
        sku = str(sku_name).strip()

        # ✅ STEP 1: Mapping apply
        mapped = mapping_dict.get(sku, sku)

        # ✅ STEP 2: Pattern extract
        pattern = get_design_pattern(mapped)

        # ✅ STEP 3: Costing DB check
        if pattern in costing_dict:
            return costing_dict[pattern]

        # ✅ STEP 4: Fallback (tumhara original logic)
        sku_up = sku.upper()
        if sku_up.startswith('HF'):
            return 230 if ('CBO' in sku_up or 'COMBO' in sku_up) else 115
        elif sku_up.startswith('PT'):
            return 330 if ('CBO' in sku_up or 'COMBO' in sku_up) else 165

        return 0

    if st.button("Generate Smart Analysis"):
        if uploaded_files and len(uploaded_files) >= 4:

            flow_df = None
            sku_df = None
            fwd_list = []
            rev_list = []

            # --- FILE DETECTION (UNCHANGED) ---
            for file in uploaded_files:
                df = pd.read_csv(file)
                cols = [c.strip().lower() for c in df.columns]

                if 'sale_order_code' in cols:
                    flow_df = df
                elif 'seller sku code' in cols and 'total_actual_settlement' not in cols:
                    sku_df = df
                elif 'total_actual_settlement' in cols:
                    temp_val = pd.to_numeric(df['total_actual_settlement'], errors='coerce').mean()
                    fname = file.name.lower()

                    if 'reverse' in fname or 'return' in fname or (temp_val is not None and temp_val < 0):
                        rev_list.append(df)
                    else:
                        fwd_list.append(df)

            # --- PROCESS ---
            if flow_df is not None and sku_df is not None:

                final = pd.merge(
                    flow_df,
                    sku_df[['order release id', 'seller sku code']],
                    left_on='sale_order_code',
                    right_on='order release id',
                    how='left'
                )

                fwd_combined = pd.concat(fwd_list, ignore_index=True) if fwd_list else pd.DataFrame()
                rev_combined = pd.concat(rev_list, ignore_index=True) if rev_list else pd.DataFrame()

                fwd_sum = fwd_combined.groupby('order_release_id')['total_actual_settlement'].sum().reset_index() if not fwd_combined.empty else pd.DataFrame()
                rev_sum = rev_combined.groupby('order_release_id')['total_actual_settlement'].sum().reset_index() if not rev_combined.empty else pd.DataFrame()

                final = pd.merge(final, fwd_sum, left_on='sale_order_code', right_on='order_release_id', how='left')
                final.rename(columns={'total_actual_settlement': 'Forward_Amt'}, inplace=True)

                final = pd.merge(final, rev_sum, left_on='sale_order_code', right_on='order_release_id', how='left')
                final.rename(columns={'total_actual_settlement': 'Reverse_Amt'}, inplace=True)

                final['Forward_Amt'] = pd.to_numeric(final['Forward_Amt'], errors='coerce').fillna(0)
                final['Reverse_Amt'] = pd.to_numeric(final['Reverse_Amt'], errors='coerce').fillna(0)

                final['seller sku code'] = final['seller sku code'].fillna("Unknown SKU")
                final['order_item_status'] = final['order_item_status'].fillna("Not Found")

                final['Net_Settlement'] = final['Forward_Amt'] + final['Reverse_Amt']

                # ✅ COSTING (UPDATED HERE)
                final['Unit_Cost'] = final['seller sku code'].apply(get_final_cost)

                final['Total_Cost'] = final.apply(
                    lambda x: x['Unit_Cost'] if str(x['order_item_status']).lower() == 'delivered' else 0,
                    axis=1
                )

                final['Net_Profit'] = final['Net_Settlement'] - final['Total_Cost']

                def label_order(net):
                    if net == 0: return "RTO"
                    if net < 0: return "Customer Return"
                    return "Delivered & Paid"

                final['Order_Type'] = final['Net_Settlement'].apply(label_order)

                # --- DASHBOARD ---
                st.subheader("📊 Summary")

                c1, c2, c3, c4 = st.columns(4)

                total_settlement = final['Net_Settlement'].sum()
                total_profit = final['Net_Profit'].sum()

                c1.metric("Net Payout", f"₹{int(total_settlement):,}")
                c2.metric("Total Cost", f"₹{int(final['Total_Cost'].sum()):,}")
                c3.metric("Net Profit", f"₹{int(total_profit):,}")
                c4.metric("Margin", f"{(total_profit/total_settlement*100 if total_settlement else 0):.1f}%")

                st.divider()

                st.subheader("📦 Orders")
                st.dataframe(
                    final[['sale_order_code', 'seller sku code', 'Order_Type', 'Net_Settlement', 'Net_Profit']],
                    use_container_width=True
                )

                # DOWNLOAD
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    final.to_excel(writer, index=False)

                st.download_button(
                    "📥 Download Excel",
                    data=buffer.getvalue(),
                    file_name="myntra_analysis.xlsx"
                )

                st.success("Done ✅")

            else:
                st.error("Flow / SKU file missing")

        else:
            st.warning("Minimum 4 files upload karo")
