import streamlit as st
import pandas as pd
from supabase import create_client, Client
from thefuzz import fuzz
import re
import pdfplumber

# --- PAGE CONFIG ---
st.set_page_config(page_title="Smart Picklist Pro", layout="wide")

# --- SUPABASE CONNECTION ---
url: str = st.secrets["SUPABASE_URL"]
key: str = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(url, key)

# --- AUTHENTICATION & SESSION ---
if 'user' not in st.session_state:
    st.session_state.user = None

def login_ui():
    st.sidebar.title("🔐 Seller Login")
    email = st.sidebar.text_input("Email")
    password = st.sidebar.text_input("Password", type="password")
    if st.sidebar.button("Login"):
        try:
            res = supabase.auth.sign_in_with_password({"email": email, "password": password})
            st.session_state.user = res.user
            st.rerun()
        except Exception as e:
            st.sidebar.error("Invalid Credentials")

def logout():
    supabase.auth.sign_out()
    st.session_state.user = None
    st.rerun()

# --- CREDIT SYSTEM LOGIC ---
def get_user_credits(user_id):
    res = supabase.table("profiles").select("credits").eq("id", user_id).single().execute()
    return res.data['credits'] if res.data else 0

def deduct_credits(user_id, order_count):
    # 400 orders = 100 credits => 4 orders = 1 credit
    credits_to_deduct = (order_count // 4) + (1 if order_count % 4 > 0 else 0)
    current = get_user_credits(user_id)
    
    if current >= credits_to_deduct:
        new_bal = current - credits_to_deduct
        supabase.table("profiles").update({"credits": new_bal}).eq("id", user_id).execute()
        return True, new_bal
    return False, current

# --- DATA FUNCTIONS ---
def load_user_data(user_id):
    maps = supabase.table("sku_mapping").select("portal_sku, master_sku").eq("user_id", user_id).execute()
    masters = supabase.table("master_inventory").select("master_sku").eq("user_id", user_id).execute()
    return pd.DataFrame(maps.data), [m['master_sku'] for m in masters.data]

# --- MAIN APP LOGIC ---
if st.session_state.user is None:
    st.title("🚀 Welcome to Smart Picklist Pro")
    st.info("Please login from the sidebar to access your dashboard.")
    login_ui()
else:
    user = st.session_state.user
    user_id = user.id
    user_credits = get_user_credits(user_id)

    # Sidebar
    st.sidebar.success(f"Logged in as: {user.email}")
    st.sidebar.metric("Available Credits", user_credits)
    if st.sidebar.button("Logout"): logout()

    # Master Upload (Sidebar)
    with st.sidebar.expander("📥 Sync Master Inventory"):
        m_file = st.file_uploader("Upload Master SKU CSV", type=['csv'])
        if m_file:
            df_m = pd.read_csv(m_file)
            if st.button("Save Master List"):
                new_list = [{"user_id": user_id, "master_sku": s.upper()} for s in df_m.iloc[:,0].dropna().unique()]
                supabase.table("master_inventory").upsert(new_list, on_conflict="user_id, master_sku").execute()
                st.success("Master SKUs Synced!")

    # Main Screen
    st.title("📦 Smart Picklist Pro")
    current_maps, master_options = load_user_data(user_id)

    files = st.file_uploader("Upload Portal Orders", type=["csv", "pdf"], accept_multiple_files=True)

    if files:
        # (Processing logic same as previous: extract_meesho_pdf, etc.)
        # Maan lijiye 'combined' dataframe ban gaya hai orders ka
        order_count = 10  # Dummy count for example
        
        st.subheader(f"Processing {order_count} Orders...")
        
        if st.button("Generate Picklist & Deduct Credits"):
            success, rem_credits = deduct_credits(user_id, order_count)
            if success:
                st.success(f"Picklist Generated! Credits remaining: {rem_credits}")
                # Show dataframe summary here
            else:
                st.error(f"Insufficient Credits! You have {user_credits}, but need more for {order_count} orders.")
