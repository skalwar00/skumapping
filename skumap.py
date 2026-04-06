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

if 'user' not in st.session_state: st.session_state.user = None

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
    except: return {}, {}, [], None

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
        st.header("👗 Aavoni")
        if profile and profile.get('plan_expiry'):
            days = (datetime.strptime(profile['plan_expiry'], '%Y-%m-%d').date() - date.today()).days
            st.success(f"🎁 Trial: {max(0, days)} Days Left")
        if st.button("Logout"): 
            supabase.auth.sign_out(); st.session_state.user = None; st.rerun()

    t1, t2, t3, t4 = st.tabs(["📦 Picklist", "💰 Costing", "📊 Flipkart", "👗 Myntra"])

    # --- TAB 1: PICKLIST (Working) ---
    with t1:
        st.header("Order Processing")
        m_f = st.file_uploader("Sync Master SKU", type=['csv'])
        if m_f and st.button("Sync"):
            df_m = pd.read_csv(m_f)
            rows = [{"user_id": u_id, "master_sku": str(s).upper()} for s in df_m.iloc[:,0].dropna().unique()]
            supabase.table("master_inventory").upsert(rows, on_conflict="user_id, master_sku").execute()
            st.success("Synced!"); st.rerun()

    # --- TAB 2: COSTING (Working) ---
    with t2:
        st.header("Costing Manager")
        kurti_base = st.number_input("Kurti Base", value=250)
        set_base = st.number_input("Set Base", value=450)
        # Costing edit form logic...
        st.dataframe(pd.DataFrame(list(costing_dict.items()), columns=['Pattern', 'Cost']))

    # --- TAB 3: FLIPKART (Full Logic) ---
    with t3:
        st.header("Flipkart P&L Analyzer")
        fk_file = st.file_uploader("Upload Flipkart Orders Excel", type=["xlsx"])
        if fk_file:
            df = pd.read_excel(fk_file)
            sku_col, sett_col = "SKU Name", "Bank Settlement [Projected] (INR)"
            if sku_col in df.columns:
                def get_cost(sku):
                    m_sku = mapping_dict.get(str(sku).upper(), str(sku).upper())
                    pat = get_design_pattern(m_sku)
                    return costing_dict.get(pat, set_base if "SET" in m_sku else kurti_base)
                
                df['Unit_Cost'] = df[sku_col].apply(get_cost)
                df['Net_Profit'] = pd.to_numeric(df[sett_col], errors='coerce').fillna(0) - df['Unit_Cost']
                st.metric("Total Profit", f"₹{int(df['Net_Profit'].sum()):,}")
                st.dataframe(df[[sku_col, sett_col, 'Unit_Cost', 'Net_Profit']])

    # --- TAB 4: MYNTRA (Full Logic) ---
    with t4:
        st.header("Myntra Smart P&L")
        m_files = st.file_uploader("Upload Myntra CSVs", type=['csv'], accept_multiple_files=True)
        if len(m_files) >= 2:
            flow_df = None
            fwd_list = []
            for f in m_files:
                temp_df = pd.read_csv(f)
                temp_df.columns = [c.lower().strip() for c in temp_df.columns]
                if 'sale_order_code' in temp_df.columns: flow_df = temp_df
                if 'total_actual_settlement' in temp_df.columns: fwd_list.append(temp_df)
            
            if flow_df is not None and fwd_list:
                sett_df = pd.concat(fwd_list).groupby('order_release_id')['total_actual_settlement'].sum().reset_index()
                final = pd.merge(flow_df, sett_df, left_on='sale_order_code', right_on='order_release_id', how='left')
                final['Settlement'] = pd.to_numeric(final['total_actual_settlement'], errors='coerce').fillna(0)
                st.metric("Myntra Settlement", f"₹{int(final['Settlement'].sum()):,}")
                st.dataframe(final[['sale_order_code', 'order_item_status', 'Settlement']])
