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
        
        m_dict = {item['portal_sku']: item['master_sku'] for item in m_res.data} if m_res.data else {}
        c_dict = {item['design_pattern']: item['landed_cost'] for item in c_res.data} if c_res.data else {}
        m_list = [i['master_sku'].upper() for i in i_res.data] if i_res.data else []
        
        return m_dict, c_dict, m_list
    except:
        return {}, {}, []

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
    mapping_dict, costing_dict, master_options = load_all_data(u_id)
    
    with st.sidebar:
        st.header("👗 Aavoni Admin")
        if st.button("Logout"): 
            supabase.auth.sign_out(); st.session_state.user = None; st.rerun()

    tabs = st.tabs(["🏠 Home", "📦 Picklist", "💰 Costing", "📊 Flipkart", "👗 Myntra"])

    with tabs[0]:
        st.title(f"Aavoni Dashboard")
        st.write("Use the tabs above to manage your business.")
        m1, m2 = st.columns(2)
        m1.metric("Mapped SKUs", len(mapping_dict))
        m2.metric("Saved Costs", len(costing_dict))

    # --- TAB 1: PICKLIST ---
    with tabs[1]:
        st.header("Order Processing")
        m_f = st.file_uploader("Upload Master SKU CSV", type=['csv'], key="m_up")
        if m_f and st.button("Sync Master"):
            df_m = pd.read_csv(m_f)
            rows = [{"user_id": u_id, "master_sku": str(s).upper().strip()} for s in df_m.iloc[:,0].dropna().unique()]
            supabase.table("master_inventory").upsert(rows, on_conflict="user_id, master_sku").execute()
            st.success("Synced!"); st.rerun()

        files = st.file_uploader("Upload Orders", type=["csv", "pdf"], accept_multiple_files=True, key="ord_up")
        if files:
            orders = []
            for f in files:
                if f.name.endswith('.csv'):
                    df_c = pd.read_csv(f)
                    df_c.columns = [c.lower().strip() for c in df_c.columns]
                    col = 'seller sku code' if 'seller sku code' in df_c.columns else next((c for c in df_c.columns if any(x in c for x in ['sku', 'seller_sku']) and 'myntra' not in c), None)
                    if col:
                        for s in df_c[col].dropna(): orders.append({'Portal_SKU': str(s).strip().upper(), 'Qty': 1})
            if orders:
                df_o = pd.DataFrame(orders)
                if st.button("Generate Picklist"):
                    df_o['Master_SKU'] = df_o['Portal_SKU'].map(mapping_dict)
                    ready = df_o.dropna(subset=['Master_SKU'])
                    if not ready.empty:
                        pdf = generate_4x6_pdf(ready.groupby('Master_SKU')['Qty'].sum().reset_index())
                        st.download_button("Download PDF", pdf, "picklist.pdf")

    # --- TAB 2: COSTING ---
    with tabs[2]:
        st.header("Costing Manager")
        kurti_base = st.number_input("Kurti Base Cost", value=250)
        set_base = st.number_input("Set Base Cost", value=450)
        all_patterns = sorted(list(set([get_design_pattern(s) for s in master_options])))
        with st.form("c_form"):
            sel = st.selectbox("Design", options=all_patterns)
            val = st.number_input("Cost", value=float(costing_dict.get(sel, 0.0)))
            if st.form_submit_button("Save"):
                supabase.table("design_costing").upsert({"user_id": u_id, "design_pattern": sel, "landed_cost": val}, on_conflict="user_id, design_pattern").execute()
                st.success("Saved!"); st.rerun()
        st.dataframe(pd.DataFrame(list(costing_dict.items()), columns=['Pattern', 'Cost']), use_container_width=True)

    # --- TAB 3: FLIPKART (FIXED) ---
    with tabs[3]:
        st.header("Flipkart P&L")
        fk_file = st.file_uploader("Upload Flipkart Orders", type=["xlsx"], key="fk_p")
        if fk_file:
            df_fk = pd.read_excel(fk_file)
            sku_col, set_col = "SKU Name", "Bank Settlement [Projected] (INR)"
            
            if sku_col in df_fk.columns and set_col in df_fk.columns:
                def get_profit(row):
                    p_sku = str(row[sku_col]).upper()
                    m_sku = mapping_dict.get(p_sku, p_sku)
                    pat = get_design_pattern(m_sku)
                    cost = costing_dict.get(pat, set_base if any(x in m_sku for x in ["SET", "KURTA"]) else kurti_base)
                    return row[set_col] - cost

                df_fk['Profit'] = df_fk.apply(get_profit, axis=1)
                st.metric("Flipkart Net Profit", f"₹{int(df_fk['Profit'].sum()):,}")
                st.dataframe(df_fk[[sku_col, set_col, 'Profit']], use_container_width=True)

    # --- TAB 4: MYNTRA (FIXED & COSTING ADDED) ---
    with tabs[4]:
        st.header("Myntra Smart P&L")
        m_files = st.file_uploader("Upload Myntra CSVs (Flow + Settlements)", type=['csv'], accept_multiple_files=True, key="my_p")
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
                
                # Myntra Costing Logic
                def get_myntra_profit(row):
                    p_sku = str(row.get('seller_sku_code', '')).upper()
                    m_sku = mapping_dict.get(p_sku, p_sku)
                    pat = get_design_pattern(m_sku)
                    cost = costing_dict.get(pat, set_base if any(x in m_sku for x in ["SET", "KURTA"]) else kurti_base)
                    # Only subtract cost if item is delivered/settled
                    return row['Settlement'] - cost if row['Settlement'] > 0 else 0

                final['Profit'] = final.apply(get_myntra_profit, axis=1)
                st.metric("Myntra Net Profit", f"₹{int(final['Profit'].sum()):,}")
                st.dataframe(final[['sale_order_code', 'seller_sku_code', 'Settlement', 'Profit']], use_container_width=True)
