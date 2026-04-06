# FULL UPDATED SCRIPT WITH TRIAL SYSTEM

import streamlit as st
import pandas as pd
import re
import io
from datetime import datetime

from supabase import create_client
from thefuzz import fuzz
import pdfplumber
from reportlab.pdfgen import canvas

INCH = 72

st.set_page_config(page_title="Aavoni Seller Suite", layout="wide", page_icon="📊")

# --- SUPABASE ---
url, key = st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)

if 'user' not in st.session_state:
    st.session_state.user = None

# --- PLAN SYSTEM ---
def get_user_plan(u_id):
    res = supabase.table("users_plan").select("*").eq("user_id", u_id).execute()
    return res.data[0] if res.data else None

# --- SKU CLEAN ---
def get_design_pattern(master_sku):
    sku = str(master_sku).upper().strip()
    sku = re.sub(r'[-_ ]?(S|M|L|XL|XXL|XXXL|\\d+XL|FREE)$', '', sku)
    sku = re.sub(r'\\(.*?\\)', '', sku)
    return sku.strip('-_ ')

# --- LOAD DATA (CACHED) ---
@st.cache_data(ttl=300)
def load_all_data(u_id):
    m_res = supabase.table("sku_mapping").select("portal_sku, master_sku").eq("user_id", u_id).execute()
    i_res = supabase.table("master_inventory").select("master_sku").eq("user_id", u_id).execute()
    c_res = supabase.table("design_costing").select("design_pattern, landed_cost").eq("user_id", u_id).execute()

    m_dict = {i['portal_sku'].upper(): i['master_sku'] for i in m_res.data} if m_res.data else {}
    c_dict = {i['design_pattern']: i['landed_cost'] for i in c_res.data} if c_res.data else {}
    m_list = [i['master_sku'].upper() for i in i_res.data] if i_res.data else []

    return m_dict, c_dict, m_list

# --- PDF ---
def generate_pdf(df):
    buffer = io.BytesIO()
    w, h = 4 * INCH, 6 * INCH
    c = canvas.Canvas(buffer, pagesize=(w, h))

    y = h - 40
    c.setFont("Helvetica-Bold", 12)

    df = df.sort_values(by="Master_SKU")

    for _, row in df.iterrows():
        if y < 40:
            c.showPage()
            y = h - 40
        c.drawString(20, y, str(row['Master_SKU'])[:25])
        c.drawString(w-60, y, str(row['Qty']))
        y -= 15

    c.save()
    buffer.seek(0)
    return buffer

# --- AUTH ---
if st.session_state.user is None:
    st.title("Login")

    with st.form("auth"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")

        if st.form_submit_button("Login"):
            res = supabase.auth.sign_in_with_password({"email": email, "password": password})
            if res.user:
                st.session_state.user = res.user
                st.rerun()
else:
    u_id = st.session_state.user.id

    # --- TRIAL CHECK ---
    plan_data = get_user_plan(u_id)

    if plan_data:
        expiry = datetime.fromisoformat(plan_data['expiry_date'].replace("Z", ""))
        now = datetime.utcnow()

        remaining = expiry - now
        days_left = int(remaining.total_seconds() / 86400)

        if days_left > 0:
            st.sidebar.success(f"🟢 Trial Active: {days_left} days left")
            st.sidebar.info(f"Ends on: {expiry.date()}")
        else:
            st.sidebar.error("🔴 Trial Expired")
            st.stop()
    else:
        st.sidebar.error("No Plan Found")
        st.stop()

    mapping_dict, costing_dict, master_options = load_all_data(u_id)

    st.title("📦 Picklist")

    files = st.file_uploader("Upload Orders", accept_multiple_files=True)

    if files:
        data = []

        for f in files:
            if f.name.endswith(".csv"):
                df = pd.read_csv(f)
                col = df.columns[0]
                for s in df[col].dropna():
                    data.append({'Portal_SKU': str(s).upper(), 'Qty': 1})

        df = pd.DataFrame(data)

        if st.button("Generate Picklist"):
            df['Master_SKU'] = df['Portal_SKU'].map(mapping_dict)
            ready = df.dropna(subset=['Master_SKU'])

            if not ready.empty:
                summary = ready.groupby('Master_SKU')['Qty'].sum().reset_index()
                pdf = generate_pdf(summary)
                st.download_button("Download", pdf, "picklist.pdf")

    if st.button("Logout"):
        supabase.auth.sign_out()
        st.session_state.user = None
        st.rerun()
