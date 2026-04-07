import streamlit as st
import pandas as pd
import re
import io
from datetime import datetime, timedelta, timezone

# --- 1. CRITICAL IMPORTS ---
try:
    from supabase import create_client, Client
    from thefuzz import fuzz
    import pdfplumber
    from reportlab.pdfgen import canvas
    INCH = 72 
except ImportError:
    st.error("❌ Libraries are installing... Please wait.")
    st.stop()

# --- 2. CONFIG & DATABASE ---
st.set_page_config(page_title="Aavoni Seller Suite", layout="wide", page_icon="📊")

# --- SECRETS CHECK ---
if "SUPABASE_URL" not in st.secrets or "SUPABASE_KEY" not in st.secrets:
    st.error("❌ Supabase Secrets Missing! Check Settings > Secrets.")
    st.stop()

try:
    url = st.secrets["SUPABASE_URL"].strip()
    key = st.secrets["SUPABASE_KEY"].strip()
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error(f"❌ Connection Error: {e}")
    st.stop()

if 'user' not in st.session_state: 
    st.session_state.user = None

# --- 3. SHARED UTILS (New Versions) ---
def get_design_pattern(master_sku):
    sku = str(master_sku).upper().strip()
    sku = re.sub(r'[-_](S|M|L|XL|XXL|\d*XL|FREE|SMALL|LARGE)$', '', sku)
    sku = re.sub(r'\(.*?\)', '', sku)
    return sku.strip('-_ ')

@st.cache_data(ttl=300)
def load_all_data(u_id):
    try:
        m_res = supabase.table("sku_mapping").select("portal_sku, master_sku").eq("user_id", u_id).execute()
        i_res = supabase.table("master_inventory").select("master_sku").eq("user_id", u_id).execute()
        c_res = supabase.table("design_costing").select("design_pattern, landed_cost").eq("user_id", u_id).execute()
        
        m_dict = {item['portal_sku'].upper(): item['master_sku'] for item in m_res.data} if m_res.data else {}
        c_dict = {item['design_pattern']: item['landed_cost'] for item in c_res.data} if c_res.data else {}
        m_list = [i['master_sku'].upper() for i in i_res.data] if i_res.data else []
        
        return m_dict, c_dict, m_list
    except:
        return {}, {}, []

def get_user_plan(u_id):
    try:
        res = supabase.table("users_plan").select("*").eq("user_id", u_id).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        return None

def login_signup_ui():
    st.title("🚀 Aavoni Seller Suite")
    with st.sidebar:
        mode = st.radio("Action", ["Login", "Signup"])
        with st.form("auth"):
            e = st.text_input("Email").strip()
            p = st.text_input("Password", type="password")
            if st.form_submit_button("Submit"):
                if not e or len(p) < 6:
                    st.error("Enter valid email and password (min 6 chars)")
                    return
                try:
                    credentials = {"email": e, "password": p}
                    if mode == "Signup":
                        res = supabase.auth.sign_up(credentials)
                        if res.user:
                            trial_expiry = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
                            supabase.table("users_plan").upsert({
                                "user_id": res.user.id,
                                "plan_type": "trial",
                                "expiry_date": trial_expiry
                            }).execute()
                            st.session_state.user = res.user
                            st.rerun()
                    else:
                        res = supabase.auth.sign_in_with_password(credentials)
                        if res.user:
                            st.session_state.user = res.user
                            st.rerun()
                        else: st.error("Invalid Login")
                except Exception as ex:
                    st.error(f"❌ Auth Error: {ex}")

# --- 4. MAIN EXECUTION ---
if st.session_state.user is None:
    login_signup_ui()
else:
    u_id = st.session_state.user.id
    plan_data = get_user_plan(u_id)

    if plan_data:
        # Timezone fix for Python 3.12
        expiry_str = plan_data['expiry_date'].replace("Z", "+00:00")
        expiry = datetime.fromisoformat(expiry_str)
        now = datetime.now(timezone.utc)
        
        remaining = expiry - now
        days_left = remaining.days

        if days_left >= 0:
            st.sidebar.success(f"🟢 Trial Active: {max(0, days_left)} days left")
        else:
            st.sidebar.error("🔴 Trial Expired")
            if st.sidebar.button("Logout"):
                st.session_state.user = None
                st.rerun()
            st.stop()
    else:
        st.sidebar.error("❌ No Plan Found")
        st.stop()

    mapping_dict, costing_dict, master_options = load_all_data(u_id)
    
    with st.sidebar:
        if st.button("Logout"):
            supabase.auth.sign_out()
            st.session_state.user = None
            st.rerun()

    # --- AB YAHAN SE AAPKE PURANE TABS START HONGE ---

# --- YOUR EXISTING TABS LOGIC CONTINUES BELOW ---

    t1, t2, t3, t4 = st.tabs(["📦 Picklist", "💰 Costing Manager", "📊 Flipkart Profit", "👗 Myntra Profit"])

    # --- TAB 1: PICKLIST ---
    with t1:
        st.header("Order Processing & Picklist")
        with st.expander("📥 Master Inventory Sync"):
            m_f = st.file_uploader("Upload Master SKU CSV", type=['csv'])
            if m_f and st.button("Sync Master"):
                df_m = pd.read_csv(m_f)
                new_m = [{"user_id": u_id, "master_sku": str(s).upper()} for s in df_m.iloc[:,0].dropna().unique()]
                supabase.table("master_inventory").upsert(new_m, on_conflict="user_id, master_sku").execute()
                st.success("Master SKUs Synced!"); st.rerun()

        files = st.file_uploader("Upload Orders (Flipkart CSV / Meesho PDF)", type=["csv", "pdf"], accept_multiple_files=True)
        if files:
            orders_data = []
            for f in files:
                if f.name.endswith('.csv'):
                    df_c = pd.read_csv(f)
                    preferred = ["SELLER_SKU_CODE"]
                    sku_c = next((c for c in df_c.columns if c.upper() in map(str.upper, preferred)), None)
                    
                             # Step 2: fallback to other SKU columns if SELLER_SKU_CODE not found
                    if not sku_c:
                        fallback = ["SELLER_SKU", "SKU_CODE", "SKU"]
                        sku_c = next((c for c in df_c.columns if c.upper() in map(str.upper, fallback)), None)
                    if sku_c:
                        for s in df_c[sku_c].dropna(): orders_data.append({'Portal_SKU': str(s).upper(), 'Qty': 1})
                elif f.name.endswith('.pdf'):
                    with pdfplumber.open(f) as pdf:
                        for page in pdf.pages:
                            table = page.extract_table()
                            if table:
                                for row in table[1:]:
                                    if row and row[0]: orders_data.append({'Portal_SKU': str(row[0]).upper(), 'Qty': 1})
            if orders_data:
                combined = pd.DataFrame(orders_data)
                st.success(f"Orders Loaded: {len(combined)}")
                if st.button("Generate 4x6 Picklist"):
                    combined['Master_SKU'] = combined['Portal_SKU'].map(mapping_dict)
                    ready = combined.dropna(subset=['Master_SKU'])
                    if not ready.empty:
                        summary = ready.groupby('Master_SKU')['Qty'].sum().reset_index()
                        pdf = generate_4x6_pdf(summary)
                        st.download_button("📥 Download PDF", pdf, "picklist.pdf", "application/pdf")
                
                st.divider()
                unmapped = [s for s in combined['Portal_SKU'].unique() if s not in mapping_dict]
                if unmapped:
                    st.subheader("🔍 New SKU Mapping")
                    map_rows = []
                    for s in unmapped:
                        best, hs = "Select", 0
                        for opt in master_options:
                            score = fuzz.token_set_ratio(s.upper(), opt.upper())
                            if score > hs: hs, best = score, opt
                        map_rows.append({"Confirm": (hs >= 90), "Portal SKU": s, "Master SKU": best})
                    edited_map = st.data_editor(pd.DataFrame(map_rows), column_config={"Master SKU": st.column_config.SelectboxColumn(options=master_options)}, hide_index=True)
                    if st.button("Save Mappings"):
                        to_save = edited_map[edited_map['Confirm'] == True]
                        rows = [{"user_id": u_id, "portal_sku": r['Portal SKU'], "master_sku": r['Master SKU']} for _, r in to_save.iterrows()]
                        supabase.table("sku_mapping").upsert(rows, on_conflict="user_id, portal_sku").execute()
                        st.success("Saved!"); st.rerun()

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
            mapped = mapping_dict.get(sku.upper(), sku)
            pattern = get_design_pattern(mapped)
            if pattern in costing_dict:
                return costing_dict[pattern]
            sku_up = sku.upper()
            if sku_up.startswith('HF'):
                return 230 if ('CBO' in sku_up or 'COMBO' in sku_up) else 115
            elif sku_up.startswith('PT'):
                return 330 if ('CBO' in sku_up or 'COMBO' in sku_up) else 165
            return 0

        # --- FIX: Sabhi logic button ke andar honi chahiye ---
        if st.button("Generate Smart Analysis"):
            if uploaded_files and len(uploaded_files) >= 3: # 3-4 files check

                flow_df = None
                sku_df = None
                fwd_list = []
                rev_list = []

                # --- FILE DETECTION ---
                for file in uploaded_files:
                    df = pd.read_csv(file)
                    # Column names ko clean karna zaroori hai KeyError se bachne ke liye
                    df.columns = [c.strip().lower() for c in df.columns]
                    cols = df.columns

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
                    # Merge logic (Lower case handles spaces/casing issues)
                    final = pd.merge(
                        flow_df,
                        sku_df[['order release id', 'seller sku code']].drop_duplicates(),
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
                    final['Net_Settlement'] = final['Forward_Amt'] + final['Reverse_Amt']
                    
                    final['seller sku code'] = final['seller sku code'].fillna("Unknown SKU")
                    final['order_item_status'] = final['order_item_status'].fillna("Not Found")

                    # COSTING
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
                    st.dataframe(final[['sale_order_code', 'seller sku code', 'Order_Type', 'Net_Settlement', 'Net_Profit']], use_container_width=True)

                    # DOWNLOAD
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                        final.to_excel(writer, index=False)
                    st.download_button("📥 Download Excel", data=buffer.getvalue(), file_name="myntra_analysis.xlsx")
                    st.success("Done ✅")
                else:
                    st.error("Flow / SKU file missing. Check column names.")
            else:
                st.warning("Kam se kam 3-4 files upload karein (Flow, SKU, Settlements)")
