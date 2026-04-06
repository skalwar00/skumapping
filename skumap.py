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
        # --- FIXED: Profile Fetching for Trial ---
        p_res = supabase.table("profiles").select("*").eq("id", u_id).execute()
        
        m_dict = {item['portal_sku']: item['master_sku'] for item in m_res.data} if m_res.data else {}
        c_dict = {item['design_pattern']: item['landed_cost'] for item in c_res.data} if c_res.data else {}
        m_list = [i['master_sku'].upper() for i in i_res.data] if i_res.data else []
        u_profile = p_res.data[0] if p_res.data else None
        
        return m_dict, c_dict, m_list, u_profile
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
    # --- FIXED: Receiving Profile Data ---
    mapping_dict, costing_dict, master_options, profile = load_all_data(u_id)
    
    with st.sidebar:
        st.header("👗 Aavoni Admin")
        
        # --- FIXED: Trial Countdown Logic ---
        if profile and profile.get('plan_expiry'):
            try:
                # Handle both string and date formats
                expiry_val = profile['plan_expiry']
                exp_dt = datetime.strptime(expiry_val, '%Y-%m-%d').date() if isinstance(expiry_val, str) else expiry_val
                days_left = (exp_dt - date.today()).days
                if days_left >= 0:
                    st.success(f"🎁 Free Trial: {days_left} Days Left")
                else:
                    st.error("❌ Trial Expired")
            except:
                st.info("🎁 Free Trial: Active")
        else:
            st.info("🎁 Free Trial: Active")

        st.divider()
        std_base = st.number_input("Std Pant Cost (PT/PL)", value=165)
        hf_base = st.number_input("HF Series Cost", value=115)
        
        if st.button("Logout"): 
            supabase.auth.sign_out(); st.session_state.user = None; st.rerun()

    # --- TABS SYSTEM ---
    tabs = st.tabs(["🏠 Home", "📦 Picklist", "💰 Costing", "📊 Flipkart P&L", "👗 Myntra P&L"])

    # --- TAB 0: HOME ---
    with tabs[0]:
        st.title(f"Welcome, {st.session_state.user.email.split('@')[0].capitalize()}!")
        m1, m2 = st.columns(2)
        m1.metric("Mapped SKUs", len(mapping_dict))
        m2.metric("Saved Costs", len(costing_dict))

    # --- TAB 1: PICKLIST ---
    with tabs[1]:
        st.header("Order Processing & Picklist")
        with st.expander("📥 Master SKU Sync"):
            m_f = st.file_uploader("Upload Master SKU CSV", type=['csv'], key="m_up_pk")
            if m_f and st.button("Sync Now"):
                df_m = pd.read_csv(m_f)
                rows = [{"user_id": u_id, "master_sku": str(s).upper().strip()} for s in df_m.iloc[:,0].dropna().unique()]
                supabase.table("master_inventory").upsert(rows, on_conflict="user_id, master_sku").execute()
                st.success("Master Inventory Updated!"); st.rerun()

        files = st.file_uploader("Upload Orders", type=["csv", "pdf"], accept_multiple_files=True, key="ord_up_pk")
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

    # --- TAB 3 & 4: P&L Logic as per your previous working scripts ---
    # (Flipkart and Myntra tabs will now use std_base/hf_base from Sidebar)
