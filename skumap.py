import streamlit as st
import pandas as pd
import re
import io
from datetime import datetime, date

# --- 1. CRITICAL IMPORTS ---
try:
    from supabase import create_client, Client
    from thefuzz import fuzz
    import pdfplumber
    from reportlab.pdfgen import canvas
    import openpyxl
    INCH = 72 
except ImportError:
    st.error("❌ Libraries missing. Run: pip install supabase thefuzz pdfplumber reportlab openpyxl")
    st.stop()

# --- 2. CONFIG & DATABASE ---
st.set_page_config(page_title="Aavoni Seller Suite", layout="wide", page_icon="👗")

try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error("❌ Supabase Secrets Missing!")
    st.stop()

if 'user' not in st.session_state:
    st.session_state.user = None

# --- 3. SHARED UTILS ---
def get_design_pattern(master_sku):
    sku = str(master_sku).upper().strip()
    sku = re.sub(r'[-_](S|M|L|XL|XXL|\d*XL|FREE|SMALL|LARGE)$', '', sku)
    sku = re.sub(r'\(.*?\)', '', sku)
    return sku.strip('-_ ')

def load_all_data(u_id):
    try:
        m_res = supabase.table("sku_mapping").select("portal_sku, master_sku").eq("user_id", u_id).execute()
        i_res = supabase.table("master_inventory").select("master_sku").eq("user_id", u_id).execute()
        c_res = supabase.table("design_costing").select("design_pattern, landed_cost").eq("user_id", u_id).execute()
        p_res = supabase.table("profiles").select("*").eq("id", u_id).execute()
        
        m_dict = {item['portal_sku']: item['master_sku'] for item in m_res.data} if m_res.data else {}
        c_dict = {item['design_pattern']: item['landed_cost'] for item in c_res.data} if c_res.data else {}
        m_list = [i['master_sku'].upper() for i in i_res.data] if i_res.data else []
        profile = p_res.data[0] if p_res.data else None
        
        return m_dict, c_dict, m_list, profile
    except:
        return {}, {}, [], None

def generate_4x6_pdf(df):
    buffer = io.BytesIO()
    w, h = 4 * INCH, 6 * INCH
    c = canvas.Canvas(buffer, pagesize=(w, h))
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(w/2, h - 30, "AAVONI PICKLIST")
    c.line(20, h-40, w-20, h-40)
    y = h - 60
    for _, row in df.iterrows():
        if y < 40:
            c.showPage()
            y = h - 40
        c.setFont("Helvetica-Bold", 10)
        c.drawString(30, y, str(row['Master_SKU'])[:25])
        c.drawRightString(w-30, y, str(row['Qty']))
        y -= 15
    c.save()
    buffer.seek(0)
    return buffer

# --- 4. AUTH UI ---
if st.session_state.user is None:
    st.title("🚀 Aavoni Seller Suite")
    with st.sidebar:
        mode = st.radio("Action", ["Login", "Signup"])
        with st.form("auth"):
            e, p = st.text_input("Email"), st.text_input("Password", type="password")
            if st.form_submit_button("Submit"):
                try:
                    res = (supabase.auth.sign_in_with_password if mode=="Login" else supabase.auth.sign_up)({"email":e, "password":p})
                    if res.session: st.session_state.user = res.user; st.rerun()
                except Exception as ex: st.error(f"Error: {ex}")
else:
    u_id = st.session_state.user.id
    mapping_dict, costing_dict, master_options, profile = load_all_data(u_id)
    
    with st.sidebar:
        st.header("👗 Aavoni Admin")
        if profile and profile.get('plan_expiry'):
            exp_dt = datetime.strptime(profile['plan_expiry'], '%Y-%m-%d').date()
            days_left = (exp_dt - date.today()).days
            st.success(f"🎁 Trial: {max(0, days_left)} Days Left")
        
        st.divider()
        if st.button("Logout"): 
            supabase.auth.sign_out(); st.session_state.user = None; st.rerun()

    # --- MAIN TABS ---
    t0, t1, t2, t3, t4 = st.tabs(["🏠 Home", "📦 Picklist", "💰 Costing", "📊 Flipkart", "👗 Myntra"])

    # --- TAB 0: HOMEPAGE (Good Looking) ---
    with t0:
        st.title(f"Welcome back, {st.session_state.user.email.split('@')[0].capitalize()}! 👋")
        st.markdown("### Powering your E-commerce Business with Aavoni")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.info("#### 📦 Smart Picklist\nUpload your portal orders and get a thermal-ready 4x6 PDF in seconds. No more manual sorting.")
        with col2:
            st.success("#### 💰 Costing Manager\nManage design-wise landed costs. Track Kurta sets vs Kurtis automatically with pattern matching.")
        with col3:
            st.warning("#### 📊 P&L Analytics\nDeep dive into Flipkart and Myntra settlements. Know exactly how much you earn after COGS.")
        
        st.divider()
        st.write("#### 🛠️ Quick Start Guide")
        st.write("1. **Sync Inventory:** Go to 'Picklist' tab and upload your Master SKU list.\n2. **Map SKUs:** Upload orders; if new SKUs appear, map them once and forget.\n3. **Set Costs:** Update landed costs in 'Costing' to see accurate profit reports.")

    # --- TAB 1: PICKLIST ---
    with t1:
        st.header("Order Processing & Picklist")
        with st.expander("📥 Master Inventory Sync"):
            m_f = st.file_uploader("Upload Master SKU CSV", type=['csv'], key="m_sync")
            if m_f and st.button("Sync Now"):
                df_m = pd.read_csv(m_f)
                rows = [{"user_id": u_id, "master_sku": str(s).upper().strip()} for s in df_m.iloc[:,0].dropna().unique()]
                supabase.table("master_inventory").upsert(rows, on_conflict="user_id, master_sku").execute()
                st.success("Master Inventory Updated!"); st.rerun()

        files = st.file_uploader("Upload Orders (CSV/PDF)", type=["csv", "pdf"], accept_multiple_files=True)
        if files:
            orders_list = []
            for f in files:
                if f.name.endswith('.csv'):
                    df_c = pd.read_csv(f)
                    df_c.columns = [c.lower().strip() for c in df_c.columns]
                    sku_col = None
                    if 'seller sku code' in df_c.columns: sku_col = 'seller sku code'
                    else: sku_col = next((c for c in df_c.columns if any(x in c for x in ['sku', 'seller_sku', 'item sku']) and 'myntra' not in c), None)
                    
                    if sku_col:
                        for s in df_c[sku_col].dropna(): 
                            orders_list.append({'Portal_SKU': str(s).strip().upper(), 'Qty': 1})
                elif f.name.endswith('.pdf'):
                    with pdfplumber.open(f) as pdf:
                        for page in pdf.pages:
                            table = page.extract_table()
                            if table:
                                for row in table[1:]:
                                    if row and row[0]: orders_list.append({'Portal_SKU': str(row[0]).strip().upper(), 'Qty': 1})
            
            if orders_list:
                df_ord = pd.DataFrame(orders_list)
                if st.button("🖨️ Generate 4x6 Picklist PDF"):
                    df_ord['Master_SKU'] = df_ord['Portal_SKU'].map(mapping_dict)
                    ready = df_ord.dropna(subset=['Master_SKU'])
                    if not ready.empty:
                        summary = ready.groupby('Master_SKU')['Qty'].sum().reset_index()
                        pdf = generate_4x6_pdf(summary)
                        st.download_button("📥 Download PDF", pdf, f"Picklist_{date.today()}.pdf")
                    else: st.error("No SKUs mapped. Map them below first.")

                unmapped = [s for s in df_ord['Portal_SKU'].unique() if s not in mapping_dict]
                if unmapped:
                    st.subheader("🔍 New SKU Mappings")
                    map_rows = []
                    for s in unmapped:
                        best, score = "Select", 0
                        for opt in master_options:
                            sc = fuzz.token_set_ratio(s, opt)
                            if sc > score: score, best = sc, opt
                        map_rows.append({"Confirm": (score > 90), "Portal SKU": s, "Master SKU": best})
                    edited = st.data_editor(pd.DataFrame(map_rows), column_config={"Master SKU": st.column_config.SelectboxColumn(options=master_options)}, hide_index=True)
                    if st.button("Save Mappings"):
                        to_db = [{"user_id": u_id, "portal_sku": r['Portal SKU'], "master_sku": r['Master SKU']} for _, r in edited.iterrows() if r['Confirm']]
                        if to_db:
                            supabase.table("sku_mapping").upsert(to_db, on_conflict="user_id, portal_sku").execute()
                            st.success("Saved!"); st.rerun()

    # --- TAB 2: COSTING ---
    with t2:
        st.header("💰 Costing Manager")
        col_c1, col_c2 = st.columns(2)
        kurti_base = col_c1.number_input("Default Kurti Cost", value=250)
        set_base = col_c2.number_input("Default Set Cost", value=450)
        all_designs = sorted(list(set([get_design_pattern(s) for s in master_options])))
        with st.form("cost_form"):
            sel = st.selectbox("Select Design Pattern", options=all_designs)
            new_val = st.number_input("Landed Cost", value=float(costing_dict.get(sel, 0.0)))
            if st.form_submit_button("Save Costing"):
                supabase.table("design_costing").upsert({"user_id": u_id, "design_pattern": sel, "landed_cost": new_val}, on_conflict="user_id, design_pattern").execute()
                st.success("Cost Saved!"); st.rerun()
        st.dataframe(pd.DataFrame(list(costing_dict.items()), columns=['Design', 'Cost']), use_container_width=True)

    # --- TAB 3: FLIPKART ---
    with t3:
        st.header("📊 Flipkart Profitability")
        fk_file = st.file_uploader("Upload Flipkart Orders Excel", type=["xlsx"], key="fk_pnl")
        if fk_file:
            df_fk = pd.read_excel(fk_file)
            sku_col, sett_col = "SKU Name", "Bank Settlement [Projected] (INR)"
            if sku_col in df_fk.columns and sett_col in df_fk.columns:
                def calc_profit(row):
                    p_sku = str(row[sku_col]).upper()
                    m_sku = mapping_dict.get(p_sku, p_sku)
                    pat = get_design_pattern(m_sku)
                    cost = costing_dict.get(pat, set_base if any(x in m_sku for x in ["SET", "KURTA", "CBO"]) else kurti_base)
                    return row[sett_col] - cost
                df_fk['Profit'] = df_fk.apply(calc_profit, axis=1)
                st.metric("Total P&L (Selected Data)", f"₹{int(df_fk['Profit'].sum()):,}")
                st.dataframe(df_fk[[sku_col, sett_col, 'Profit']], use_container_width=True)

    # --- TAB 4: MYNTRA ---
    with t4:
        st.header("👗 Myntra Smart P&L")
        m_files = st.file_uploader("Upload Myntra Reports (Flow & Settlements)", type=['csv'], accept_multiple_files=True, key="mynt_pnl")
        if len(m_files) >= 2:
            flow_df, sett_list = None, []
            for f in m_files:
                tdf = pd.read_csv(f)
                tdf.columns = [c.lower().strip() for c in tdf.columns]
                if 'sale_order_code' in tdf.columns: flow_df = tdf
                if 'total_actual_settlement' in tdf.columns: sett_list.append(tdf)
            if flow_df is not None and sett_list:
                s_sum = pd.concat(sett_list).groupby('order_release_id')['total_actual_settlement'].sum().reset_index()
                final = pd.merge(flow_df, s_sum, left_on='sale_order_code', right_on='order_release_id', how='left')
                final['Settlement'] = pd.to_numeric(final['total_actual_settlement'], errors='coerce').fillna(0)
                st.metric("Myntra Net Payout", f"₹{int(final['Settlement'].sum()):,}")
                st.dataframe(final[['sale_order_code', 'order_item_status', 'Settlement']], use_container_width=True)
