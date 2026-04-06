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

# --- 4. AUTH ---
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
        st.header("👗 Aavoni Dashboard")
        if profile and profile.get('plan_expiry'):
            exp_dt = datetime.strptime(profile['plan_expiry'], '%Y-%m-%d').date()
            days_left = (exp_dt - date.today()).days
            st.success(f"🎁 Trial: {max(0, days_left)} Days Left")
        if st.button("Logout"): 
            supabase.auth.sign_out(); st.session_state.user = None; st.rerun()

    t1, t2, t3, t4 = st.tabs(["📦 Picklist", "💰 Costing", "📊 Flipkart", "👗 Myntra"])

    with t1:
        st.header("Order Processing")
        files = st.file_uploader("Upload Orders", type=["csv", "pdf"], accept_multiple_files=True)
        if files:
            orders_list = []
            for f in files:
                if f.name.endswith('.csv'):
                    df_c = pd.read_csv(f)
                    df_c.columns = [c.lower().strip() for c in df_c.columns]
                    
                    # Fix: df_temp replaced with df_c
                    sku_col = None
                    if 'seller sku code' in df_c.columns:
                        sku_col = 'seller sku code'
                    else:
                        sku_col = next((c for c in df_c.columns if any(x in c for x in ['sku', 'seller_sku'])), None)
                    
                    if sku_col:
                        for s in df_c[sku_col].dropna(): 
                            orders_list.append({'Portal_SKU': str(s).strip().upper(), 'Qty': 1})
            
            if orders_list:
                df_ord = pd.DataFrame(orders_list)
                if st.button("Generate Picklist"):
                    df_ord['Master_SKU'] = df_ord['Portal_SKU'].map(mapping_dict)
                    ready = df_ord.dropna(subset=['Master_SKU'])
                    if not ready.empty:
                        pdf = generate_4x6_pdf(ready.groupby('Master_SKU')['Qty'].sum().reset_index())
                        st.download_button("Download PDF", pdf, "picklist.pdf")
