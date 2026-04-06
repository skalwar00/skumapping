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
    st.error("❌ Supabase Secrets Missing! Check Settings > Secrets.")
    st.stop()

if 'user' not in st.session_state:
    st.session_state.user = None

# --- 3. SHARED UTILS ---
def get_design_pattern(master_sku):
    sku = str(master_sku).upper().strip()
    # Removes size tags like -S, -XL, -3XL
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
                    if mode == "Login":
                        res = supabase.auth.sign_in_with_password({"email": e, "password": p})
                    else:
                        res = supabase.auth.sign_up({"email": e, "password": p})
                    if res.session:
                        st.session_state.user = res.user
                        st.rerun()
                except Exception as ex:
                    st.error(f"Error: {ex}")
else:
    u_id = st.session_state.user.id
    mapping_dict, costing_dict, master_options, profile = load_all_data(u_id)
    
    with st.sidebar:
        st.header("👗 Aavoni Admin")
        if profile and profile.get('plan_expiry'):
            exp_dt = datetime.strptime(profile['plan_expiry'], '%Y-%m-%d').date()
            days_left = (exp_dt - date.today()).days
            if days_left >= 0:
                st.success(f"🎁 Trial: {days_left} Days Left")
            else:
                st.error("❌ Trial Expired")
        
        st.divider()
        if st.button("Logout"): 
            supabase.auth.sign_out()
            st.session_state.user = None
            st.rerun()

    # --- TABS SYSTEM ---
    tabs = st.tabs(["🏠 Home", "📦 Picklist", "💰 Costing", "📊 Flipkart", "👗 Myntra"])

    # --- TAB 0: HOME ---
    with tabs[0]:
        st.title(f"Welcome, {st.session_state.user.email.split('@')[0].capitalize()}! 👋")
        st.markdown("### Aavoni Business Dashboard")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.info("#### 📦 Picklist Generator\nCreate thermal labels and automate SKU mapping for Flipkart & Myntra.")
        with col2:
            st.success("#### 💰 Costing Manager\nSet landed costs per design. Supports Kurta sets & Kurtis via pattern detection.")
        with col3:
            st.warning("#### 📊 Profit Analytics\nUpload portal reports to see net payout and P&L after production costs.")
        
        st.divider()
        st.write("#### ⚡ Data Summary")
        m1, m2, m3 = st.columns(3)
        m1.metric("Mapped SKUs", len(mapping_dict))
        m2.metric("Saved Designs", len(costing_dict))
        m3.metric("Inventory Items", len(master_options))

    # --- TAB 1: PICKLIST ---
    with tabs[1]:
        st.header("Order Processing")
        with st.expander("📥 Master SKU Sync"):
            m_f = st.file_uploader("Upload Master SKU CSV", type=['csv'], key="m_sync")
            if m_f and st.button("Sync Now"):
                df_m = pd.read_csv(m_f)
                rows = [{"user_id": u_id, "master_sku": str(s).upper().strip()} for s in df_m.iloc[:,0].dropna().unique()]
                supabase.table("master_inventory").upsert(rows, on_conflict="user_id, master_sku").execute()
                st.success("Inventory Synced!"); st.rerun()

        files = st.file_uploader("Upload Orders (CSV/PDF)", type=["csv", "pdf"], accept_multiple_files=True)
        if files:
            orders = []
            for f in files:
                if f.name.endswith('.csv'):
                    df_c = pd.read_csv(f)
                    df_c.columns = [c.lower().strip() for c in df_c.columns]
                    # Priority: Seller SKU Code for Myntra
                    sku_col = 'seller sku code' if 'seller sku code' in df_c.columns else next((c for c in df_c.columns if any(x in c for x in ['sku', 'seller_sku', 'item sku']) and 'myntra' not in c), None)
                    if sku_col:
                        for s in df_c[sku_col].dropna(): 
                            orders.append({'Portal_SKU': str(s).strip().upper(), 'Qty': 1})
                elif f.name.endswith('.pdf'):
                    with pdfplumber.open(f) as pdf:
                        for page in pdf.pages:
                            table = page.extract_table()
                            if table:
                                for row in table[1:]:
                                    if row and row[0]: orders.append({'Portal_SKU': str(row[0]).strip().upper(), 'Qty': 1})
            
            if orders:
                df_ord = pd.DataFrame(orders)
                if st.button("🖨️ Generate 4x6 Picklist"):
                    df_ord['Master_SKU'] = df_ord['Portal_SKU'].map(mapping_dict)
                    ready = df_ord.dropna(subset=['Master_SKU'])
                    if not ready.empty:
                        pdf = generate_4x6_pdf(ready.groupby('Master_SKU')['Qty'].sum().reset_index())
                        st.download_button("📥 Download PDF", pdf, f"Picklist_{date.today()}.pdf")
                
                # Mapping Tool
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
    with tabs[2]:
        st.header("💰 Costing")
        kurti_base = st.number_input("Default Kurti Cost", value=250)
        set_base = st.number_input("Default Set Cost", value=450)
        all_designs = sorted(list(set([get_design_pattern(s) for s in master_options])))
        with st.form("cost_form"):
            sel = st.selectbox("Design Pattern", options=all_designs)
            val = st.number_input("Landed Cost", value=float(costing_dict.get(sel, 0.0)))
            if st.form_submit_button("Save Cost"):
                supabase.table("design_costing").upsert({"user_id": u_id, "design_pattern": sel, "landed_cost": val}, on_conflict="user_id, design_pattern").execute()
                st.success("Cost Saved!"); st.rerun()
        st.dataframe(pd.DataFrame(list(costing_dict.items()), columns=['Design', 'Cost']), use_container_width=True)

    # --- TAB 3: FLIPKART ---
    with tabs[3]:
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
                st.metric("Total Profit", f"₹{int(df_fk['Profit'].sum()):,}")
                st.dataframe(df_fk[[sku_col, sett_col, 'Profit']], use_container_width=True)

    # --- TAB 4: MYNTRA ---
    with tabs[4]:
        st.header("👗 Myntra Smart P&L")
        m_files = st.file_uploader("Upload Myntra Reports", type=['csv'], accept_multiple_files=True, key="my_pnl")
        if len(m_files) >= 2:
            f_df, s_list = None, []
            for f in m_files:
                tdf = pd.read_csv(f)
                tdf.columns = [c.lower().strip() for c in tdf.columns]
                if 'sale_order_code' in tdf.columns: f_df = tdf
                if 'total_actual_settlement' in tdf.columns: s_list.append(tdf)
            if f_df is not None and s_list:
                s_sum = pd.concat(s_list).groupby('order_release_id')['total_actual_settlement'].sum().reset_index()
                final = pd.merge(f_df, s_sum, left_on='sale_order_code', right_on='order_release_id', how='left')
                final['Settlement'] = pd.to_numeric(final['total_actual_settlement'], errors='coerce').fillna(0)
                st.metric("Net Settlement", f"₹{int(final['Settlement'].sum()):,}")
                st.dataframe(final[['sale_order_code', 'order_item_status', 'Settlement']], use_container_width=True)
