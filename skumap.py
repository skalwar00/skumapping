import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import base64
import json
from thefuzz import fuzz
import re

# --- PAGE SETUP ---
st.set_page_config(page_title="Aavoni Smart Picklist PRO", layout="wide")

# --- GOOGLE SHEETS CONNECTION ---
def get_gspread_client():
    try:
        encoded_key = st.secrets["gcp_service_account"]["encoded_key"]
        decoded_key = base64.b64decode(encoded_key).decode("utf-8")
        creds_info = json.loads(decoded_key)
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Connection Error: {e}")
        st.stop()

# --- CONFIGURATION ---
SHEET_ID = "1VZ5QLBQwH_r8kNSsUFacrS7_VSMJ556vO8C53s8Jwr0" 

try:
    gc = get_gspread_client()
    sh = gc.open_by_key(SHEET_ID)
    worksheet = sh.get_worksheet(0)
except Exception as e:
    st.error(f"❌ Google Sheet Connection Issue: {e}")
    st.stop()

# --- DATA FUNCTIONS ---
def load_data():
    try:
        records = worksheet.get_all_records()
        df = pd.DataFrame(records)
        return df if not df.empty else pd.DataFrame(columns=['Portal_SKU', 'Master_SKU'])
    except:
        return pd.DataFrame(columns=['Portal_SKU', 'Master_SKU'])

def save_mapping(p_sku, m_sku):
    worksheet.append_row([str(p_sku).strip(), str(m_sku).strip()])

# --- MATCHING LOGIC ---
def smart_hybrid_matcher(new_sku, master_options):
    new_sku_str = str(new_sku).upper()
    if not master_options: return "Select Manually", 0
    best_m, high_s = "Select Manually", 0
    for opt in master_options:
        score = fuzz.token_set_ratio(new_sku_str, str(opt).upper())
        if score > high_s: high_s, best_m = score, opt
    return best_m, high_s

# --- APP UI ---
st.title("🚀 Aavoni Smart Picklist PRO")

# 1. MASTER INVENTORY UPLOAD SECTION
with st.expander("📥 Step 1: Upload Master Inventory (CSV/XLSX)", expanded=False):
    m_file = st.file_uploader("Apni Master SKU file yahan upload karein", type=['csv', 'xlsx'], key="master_up")
    if m_file:
        df_m = pd.read_csv(m_file) if m_file.name.endswith('.csv') else pd.read_excel(m_file)
        # Find SKU column
        m_col = next((c for c in df_m.columns if 'master' in c.lower() or 'sku' in c.lower()), df_m.columns[0])
        st.write(f"Detected Master Column: **{m_col}**")
        
        if st.button("Add to Google Sheet"):
            new_skus = df_m[m_col].dropna().unique()
            current_master = load_data()['Master_SKU'].tolist()
            added_count = 0
            for sku in new_skus:
                if str(sku).strip() not in current_master:
                    save_mapping("", sku)
                    added_count += 1
            st.success(f"Done! {added_count} naye Master SKUs add ho gaye.")
            st.rerun()

st.divider()

# 2. PORTAL ORDERS UPLOAD
st.subheader("📤 Step 2: Upload Portal Orders")
files = st.file_uploader("Flipkart/Meesho reports upload karein", type="csv", accept_multiple_files=True)

if files:
    orders_list = []
    for f in files:
        df = pd.read_csv(f)
        cols = {str(c).lower().strip().replace(" ", "_"): c for c in df.columns}
        s_keys = ['sku', 'seller_sku', 'listing_id', 'product_id', 'order_item_sku', 'external_id']
        q_keys = ['quantity', 'qty', 'ordered_quantity']
        
        s_col = next((cols[k] for k in s_keys if k in cols), None)
        q_col = next((cols[k] for k in q_keys if k in cols), None)
        
        if s_col:
            t_df = pd.DataFrame()
            t_df['Portal_SKU'] = df[s_col].astype(str).str.strip()
            t_df['Qty'] = pd.to_numeric(df[q_col], errors='coerce').fillna(1) if q_col else 1
            orders_list.append(t_df)
    
    if orders_list:
        combined = pd.concat(orders_list, ignore_index=True)
        current_db = load_data()
        
        # Create Mapping Dictionary
        active_map = current_db[current_db['Portal_SKU'].astype(str).str.strip() != ""].copy()
        mapping_dict = dict(zip(active_map['Portal_SKU'].astype(str), active_map['Master_SKU'].astype(str)))
        
        # 1. PICKLIST
        combined['Master_SKU'] = combined['Portal_SKU'].map(mapping_dict)
        ready = combined.dropna(subset=['Master_SKU'])
        
        st.subheader("📋 Final Picklist")
        if not ready.empty:
            summary = ready.groupby('Master_SKU')['Qty'].sum().reset_index().sort_values('Qty', ascending=False)
            st.dataframe(summary, use_container_width=True)
            st.download_button("📥 Download Picklist", summary.to_csv(index=False).encode('utf-8'), "Picklist.csv")
        else:
            st.info("Abhi tak koi item match nahi hua.")

        st.divider()

        # 2. REVIEW & LINK
        unmapped = [s for s in combined['Portal_SKU'].unique() if str(s) not in mapping_dict]
        if unmapped:
            st.subheader("🔍 Review New Portal SKUs")
            m_options = sorted(current_db['Master_SKU'].unique().tolist())
            
            if m_options:
                review_data = []
                for s in unmapped:
                    sugg, score = smart_hybrid_matcher(s, m_options)
                    review_data.append({"Confirm": (score >= 90), "Portal SKU": s, "Master SKU": sugg, "Match": f"{score}%"})
                
                edited = st.data_editor(pd.DataFrame(review_data), key="editor_v7", hide_index=True)
                
                if st.button("Save Selected Mappings"):
                    to_save = edited[edited['Confirm'] == True]
                    for _, row in to_save.iterrows():
                        save_mapping(row['Portal SKU'], row['Master SKU'])
                    st.success("Saved! Refreshing...")
                    st.rerun()
            else:
                st.warning("Master Inventory khali hai! Upar 'Step 1' se file upload karein.")
