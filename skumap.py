import streamlit as st
import pandas as pd
import re
import io
import time
from datetime import datetime, timedelta, timezone
import extra_streamlit_components as stx

# --- CONFIG ---
st.set_page_config(page_title="Smart Ecom Suite", layout="wide")

# --- AUTH CONFIG ---
ACCESS_KEY = "sb-access-token"
REFRESH_KEY = "sb-refresh-token"

if 'cookie_manager' not in st.session_state:
    st.session_state.cookie_manager = stx.CookieManager(key="auth")

cookie_manager = st.session_state.cookie_manager

# --- IMPORTS ---
from supabase import create_client, Client

# --- SUPABASE ---
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(url, key)

# --- SESSION ---
if 'user' not in st.session_state:
    st.session_state.user = None

# --- SAVE SESSION ---
def save_session(session):
    st.session_state.user = session.user

    cookie_manager.set(
        ACCESS_KEY,
        session.access_token,
        expires_at=(datetime.now(timezone.utc) + timedelta(days=7)).timestamp()
    )

    cookie_manager.set(
        REFRESH_KEY,
        session.refresh_token,
        expires_at=(datetime.now(timezone.utc) + timedelta(days=7)).timestamp()
    )

# --- CHECK LOGIN ---
def check_persistent_login():
    # Already logged
    if st.session_state.get("user"):
        cookies = cookie_manager.get_all()
        if cookies.get(ACCESS_KEY):
            return True

    # Load cookies
    cookies = cookie_manager.get_all()
    if not cookies:
        time.sleep(1)
        cookies = cookie_manager.get_all()

    access_token = cookies.get(ACCESS_KEY)
    refresh_token = cookies.get(REFRESH_KEY)

    if access_token:
        try:
            res = supabase.auth.get_user(access_token)
            if res.user:
                st.session_state.user = res.user
                return True
        except:
            pass

    if refresh_token:
        try:
            new_session = supabase.auth.refresh_session(refresh_token)
            if new_session.session:
                save_session(new_session.session)
                return True
        except:
            pass

    return False

# --- LOGIN UI ---
def login_ui():
    st.title("Login")

    email = st.text_input("Email")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        res = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })

        if res.user:
            save_session(res.session)
            st.rerun()

# --- LOGOUT ---
def logout():
    # Supabase logout
    try:
        supabase.auth.sign_out()
    except:
        pass

    # Delete cookies (IMPORTANT)
    cookie_manager.delete(ACCESS_KEY)
    cookie_manager.delete(REFRESH_KEY)

    # Clear full session
    for key in list(st.session_state.keys()):
        del st.session_state[key]

    # Small delay (important for cookie clear)
    time.sleep(0.5)

    st.success("Logged out ✅")
    time.sleep(0.5)

    st.rerun()

# --- ENTRY ---
if not check_persistent_login():
    login_ui()
    st.stop()

# --- USER ---
u_id = st.session_state.user.id

# --- LOAD DATA ---
@st.cache_data
def load_user_data(u_id):
    try:
        map_res = supabase.table("sku_mapping").select("*").eq("user_id", u_id).execute()
        mapping_dict = {i['portal_sku']: i['master_sku'] for i in map_res.data} if map_res.data else {}

        cost_res = supabase.table("design_costing").select("*").eq("user_id", u_id).execute()
        costing_dict = {i['design_pattern']: i['landed_cost'] for i in cost_res.data} if cost_res.data else {}

        master_res = supabase.table("master_inventory").select("master_sku").eq("user_id", u_id).execute()
        master_list = [i['master_sku'] for i in master_res.data] if master_res.data else []

        return mapping_dict, costing_dict, master_list

    except:
        return {}, {}, []

mapping_dict, costing_dict, master_options = load_user_data(u_id)
master_set = set(master_options)

# --- HELPERS ---
def get_design_pattern(sku):
    return re.sub(r'[-_ ]?(S|M|L|XL|XXL)$', '', str(sku).upper())

# --- SIDEBAR ---
with st.sidebar:
    st.button("Logout", on_click=logout)

# --- MAIN UI ---
st.title("📊 Smart Dashboard")

t1, t2, t3, t4 = st.tabs(["📦 Picklist", "💰 Costing Manager", "📊 Flipkart Profit", "👗 Myntra Profit"])

with t1:
        st.header("All Portals Picklist")
        with st.expander("📥 Master Inventory & Backup"):
            m_tab1, m_tab2 = st.tabs(["Inventory Sync", "Mapping Backup"])
            with m_tab1:
                m_f = st.file_uploader("Upload Master SKU CSV", type=['csv'])
                if m_f and st.button("🚀 Sync Master"):
                    df_m = pd.read_csv(m_f)
                    new_m = [{"user_id": u_id, "master_sku": str(s).upper().strip()} for s in df_m.iloc[:,0].dropna().unique()]
                    supabase.table("master_inventory").upsert(new_m, on_conflict="user_id, master_sku").execute()
                    st.cache_data.clear(); st.success("Master Synced!"); st.rerun()
            with m_tab2:
                current_maps = supabase.table("sku_mapping").select("portal_sku, master_sku").eq("user_id", u_id).execute()
                if current_maps.data:
                    st.download_button("📥 Backup CSV", pd.DataFrame(current_maps.data).to_csv(index=False).encode('utf-8'), "sku_mapping.csv")

        files = st.file_uploader("Upload Orders", type=["csv", "pdf"], accept_multiple_files=True)
        if files:
            orders_data = []
            for f in files:
                if f.name.endswith('.csv'):
                    df_c = pd.read_csv(f)
                    df_c.columns = [c.upper() for c in df_c.columns]
                    sku_c = next((c for c in ["SELLER_SKU_CODE", "SELLER_SKU", "SKU_CODE", "SKU"] if c in df_c.columns), None)
                    if sku_c:
                        for s in df_c[sku_c].dropna(): orders_data.append({'Portal_SKU': str(s).upper(), 'Qty': 1})
                elif f.name.endswith('.pdf'):
                    with pdfplumber.open(f) as pdf:
                        for page in pdf.pages:
                            page_text = (page.extract_text() or "").upper()
                            if "PICKLIST" in page_text:
                                table = page.extract_table()
                                if table:
                                    for row in table[1:]:
                                        if row and len(row) >= 2:
                                            sku = str(row[0]).upper().strip()
                                            try: qty = int(float(str(row[-1]).strip())) if row[-1] else 1
                                            except: qty = 1
                                            orders_data.append({'Portal_SKU': sku, 'Qty': qty})
            
            if orders_data:
                combined = pd.DataFrame(orders_data)
                st.info(f"Orders Loaded: {len(combined)}")
                if st.button("Generate Picklist"):
                    combined['Master_SKU'] = combined['Portal_SKU'].map(mapping_dict)
                    ready = combined.dropna(subset=['Master_SKU'])
                    if not ready.empty:
                        summary = ready.groupby('Master_SKU')['Qty'].sum().reset_index()
                        st.download_button("📥 Download Picklist", generate_4x6_pdf(summary), "picklist.pdf")

                st.divider()
                unmapped = [s for s in combined['Portal_SKU'].unique() if s not in mapping_dict]
                if unmapped:
                    st.subheader("🔍 Smart SKU Mapping")
                    p_res = supabase.table("pattern_mapping").select("portal_base, master_base").eq("user_id", u_id).execute()
                    pattern_memory = {item['portal_base']: item['master_base'] for item in p_res.data} if p_res.data else {}
                    
                    map_rows = []
                    for s in unmapped:
                        best, hs, m_type = "Select", 0, "Fuzzy"
                        p_base = get_design_pattern(s)
                        if p_base in pattern_memory:
                            m_base = pattern_memory[p_base]
                            size = get_smart_suffix(s)
                            suggested = f"{m_base}-{size}" if size else m_base
                            if suggested in master_set: best, hs, m_type = suggested, 100, "Learned"
                            elif m_base in master_set: best, hs, m_type = m_base, 95, "Pattern Only"
                        
                        if hs < 92:
                            for opt in master_options:
                                score = fuzz.token_set_ratio(s.upper(), opt.upper())
                                if score > hs: hs, best = score, opt
                        
                        map_rows.append({"Confirm": (hs >= 92), "Portal SKU": s, "Master SKU": best, "Match %": hs, "Mode": m_type})
                    
                    edited_map = st.data_editor(pd.DataFrame(map_rows), column_config={
                        "Match %": st.column_config.ProgressColumn(format="%d%%", min_value=0, max_value=100),
                        "Master SKU": st.column_config.SelectboxColumn(options=master_options)
                    }, hide_index=True)

                    if st.button("💾 Save & Learn"):
                        to_save = edited_map[edited_map['Confirm'] == True]
                        if not to_save.empty:
                            rows = [{"user_id": u_id, "portal_sku": r['Portal SKU'], "master_sku": r['Master SKU']} for _, r in to_save.iterrows()]
                            supabase.table("sku_mapping").upsert(rows).execute()
                            p_rows = []
                            seen = set()
                            for _, r in to_save.iterrows():
                                pb, mb = get_design_pattern(r['Portal SKU']), get_design_pattern(r['Master SKU'])
                                if pb not in seen:
                                    p_rows.append({"user_id": u_id, "portal_base": pb, "master_base": mb})
                                    seen.add(pb)
                            if p_rows:
                                supabase.table("pattern_mapping").upsert(p_rows, on_conflict="user_id, portal_base").execute()
                            st.cache_data.clear(); st.success("Saved!"); st.rerun()

    # --- TAB 2: COSTING MANAGER ---
with t2:
        st.header("💰 Costing Manager")
        # Yahan hum current mapping list se unique designs nikalte hain
        all_master = list(set(mapping_dict.values()))
        all_designs = sorted(list(set([get_design_pattern(s) for s in all_master])))
        
        if not all_designs:
            st.warning("⚠️ Pehle SKUs map karein taaki designs list ban sake.")
        else:
            with st.form("cost_up"):
                col1, col2 = st.columns(2)
                sel = col1.selectbox("Select Design", options=all_designs)
                new_v = col2.number_input("Landed Cost (₹)", min_value=0.0, value=float(costing_dict.get(sel, 0.0)))
                if st.form_submit_button("Save Costing"):
                    supabase.table("design_costing").upsert({"user_id": u_id, "design_pattern": sel, "landed_cost": new_v}).execute()
                    st.cache_data.clear()
                    st.success(f"Saved: {sel} at ₹{new_v}")
                    st.rerun()
            
            if costing_dict:
                st.dataframe(pd.DataFrame(list(costing_dict.items()), columns=['Pattern', 'Cost']), use_container_width=True)

    # --- TAB 3 & 4: YOUR REMAINING LOGIC ---
    # (Note: In tabs ke andar bhi costing_dict aur mapping_dict ka hi use karein jo upar se aa rahe hain)

    # --- TAB 3: FLIPKART ANALYZER ---
with t3:
        st.title("📊 Flipkart P/L")
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
