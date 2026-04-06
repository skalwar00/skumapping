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

# Link your Supabase here via Streamlit Secrets
try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error("❌ Supabase Secrets Missing! Check Settings > Secrets.")
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
    except Exception as e:
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

# --- 4. AUTHENTICATION UI ---
if st.session_state.user is None:
    st.title("🚀 Aavoni Seller Suite")
    with st.sidebar:
        mode = st.radio("Action", ["Login", "Signup"])
        with st.form("auth"):
            e = st.text_input("Email")
            p = st.text_input("Password", type="password")
            if st.form_submit_button("Submit"):
                try:
                    if mode == "Login":
                        res = supabase.auth.sign_in_with_password({"email": e, "password": p})
                    else:
                        res = supabase.auth.sign_up({"email": e, "password": p})
                        st.info("Signup initiated. Check email or Login if Confirm-Email is OFF.")
                    
                    if res.session:
                        st.session_state.user = res.user
                        st.rerun()
                except Exception as ex:
                    st.error(f"Auth Error: {ex}")
else:
    u_id = st.session_state.user.id
    mapping_dict, costing_dict, master_options, profile = load_all_data(u_id)
    
    # SIDEBAR & STATUS
    with st.sidebar:
        st.header("👗 Aavoni Dashboard")
        st.write(f"Logged in: **{st.session_state.user.email}**")
        if profile and profile.get('plan_expiry'):
            exp_dt = datetime.strptime(profile['plan_expiry'], '%Y-%m-%d').date()
            days_left = (exp_dt - date.today()).days
            if days_left >= 0:
                st.success(f"🎁 Free Trial: {days_left} Days Left")
            else:
                st.error("❌ Trial Expired")
        
        if st.button("Logout"): 
            supabase.auth.sign_out()
            st.session_state.user = None
            st.rerun()

    # TABS SYSTEM
    t1, t2, t3, t4 = st.tabs(["📦 Picklist", "💰 Costing Manager", "📊 Flipkart Profit", "👗 Myntra Profit"])

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
                    sku_col = next((c for c in df_c.columns if any(x in c for x in ['sku', 'seller sku code' 'seller_sku'])), None)
                    if sku_col:
                        for s in df_c[sku_col].dropna(): orders_list.append({'Portal_SKU': str(s).strip().upper(), 'Qty': 1})
                elif f.name.endswith('.pdf'):
                    with pdfplumber.open(f) as pdf:
                        for page in pdf.pages:
                            table = page.extract_table()
                            if table:
                                for row in table[1:]:
                                    if row and row[0]: orders_list.append({'Portal_SKU': str(row[0]).strip().upper(), 'Qty': 1})
            
            if orders_list:
                df_ord = pd.DataFrame(orders_list)
                st.info(f"Orders Found: {len(df_ord)}")
                
                if st.button("Generate 4x6 Picklist"):
                    df_ord['Master_SKU'] = df_ord['Portal_SKU'].map(mapping_dict)
                    ready = df_ord.dropna(subset=['Master_SKU'])
                    if not ready.empty:
                        summary = ready.groupby('Master_SKU')['Qty'].sum().reset_index()
                        pdf = generate_4x6_pdf(summary)
                        st.download_button("📥 Download PDF", pdf, "picklist.pdf")
                    else:
                        st.error("No SKUs mapped. Map them below first.")

                # Auto-Mapping Tool
                unmapped = [s for s in df_ord['Portal_SKU'].unique() if s not in mapping_dict]
                if unmapped:
                    st.divider()
                    st.subheader("🔍 New SKU Mappings")
                    map_rows = []
                    for s in unmapped:
                        best, score = "Select", 0
                        for opt in master_options:
                            sc = fuzz.token_set_ratio(s, opt)
                            if sc > score: score, best = sc, opt
                        map_rows.append({"Confirm": (score > 90), "Portal SKU": s, "Master SKU": best})
                    
                    edited = st.data_editor(pd.DataFrame(map_rows), column_config={"Master SKU": st.column_config.SelectboxColumn(options=master_options)}, hide_index=True)
                    if st.button("Save Selected Mappings"):
                        to_db = [{"user_id": u_id, "portal_sku": r['Portal SKU'], "master_sku": r['Master SKU']} for _, r in edited.iterrows() if r['Confirm']]
                        if to_db:
                            supabase.table("sku_mapping").upsert(to_db, on_conflict="user_id, portal_sku").execute()
                            st.success("Saved!"); st.rerun()

    # --- TAB 2: COSTING ---
    with t2:
        st.header("Costing Manager")
        kurti_base = st.number_input("Default Kurti Cost", value=250)
        set_base = st.number_input("Default Set Cost", value=450)
        
        all_designs = sorted(list(set([get_design_pattern(s) for s in master_options])))
        with st.form("cost_form"):
            sel = st.selectbox("Select Design", options=all_designs)
            new_val = st.number_input("Landed Cost", value=float(costing_dict.get(sel, 0.0)))
            if st.form_submit_button("Save Cost"):
                supabase.table("design_costing").upsert({"user_id": u_id, "design_pattern": sel, "landed_cost": new_val}, on_conflict="user_id, design_pattern").execute()
                st.success("Cost Saved!"); st.rerun()
        st.dataframe(pd.DataFrame(list(costing_dict.items()), columns=['Design', 'Cost']))

    # --- TAB 3: FLIPKART ANALYZER ---
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
                    cost = costing_dict.get(pat, set_base if "SET" in m_sku else kurti_base)
                    return row[sett_col] - cost
                
                df_fk['Profit'] = df_fk.apply(calc_profit, axis=1)
                st.metric("Total P&L", f"₹{int(df_fk['Profit'].sum()):,}")
                st.dataframe(df_fk[[sku_col, sett_col, 'Profit']])

    # --- TAB 4: MYNTRA ANALYZER ---
    with t4:
        st.header("👗 Myntra Smart P&L")
        m_files = st.file_uploader("Upload Myntra Reports (Flow & Settlements)", type=['csv'], accept_multiple_files=True)
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
                st.metric("Myntra Settlement", f"₹{int(final['Settlement'].sum()):,}")
                st.dataframe(final[['sale_order_code', 'order_item_status', 'Settlement']])
