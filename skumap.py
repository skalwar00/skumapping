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

# --- CONFIGURATION (YOUR PERMANENT SHEET ID) ---
SHEET_ID = "1VZ5QLBQwH_r8kNSsUFacrS7_VSMJ556vO8C53s8Jwr0" 

try:
    gc = get_gspread_client()
    sh = gc.open_by_key(SHEET_ID)
    worksheet = sh.get_worksheet(0)
except Exception as e:
    st.error(f"❌ Google Sheet Connection Issue: {e}")
    st.info("Check karein ki picklist@sound-habitat-492421-d0.iam.gserviceaccount.com ko Sheet par Editor access diya hai ya nahi.")
    st.stop()

# --- DATA FUNCTIONS ---
def load_data():
    try:
        records = worksheet.get_all_records()
        df = pd.DataFrame(records)
        if df.empty:
            return pd.DataFrame(columns=['Portal_SKU', 'Master_SKU'])
        return df
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
        if score > high_s:
            high_s, best_m = score, opt
            
    return best_m, high_s

# --- APP UI ---
st.title("🚀 Aavoni Smart Picklist PRO")

if 'master_df' not in st.session_state:
    st.session_state.master_df = load_data()

if st.sidebar.button("🔄 Sync Sheet"):
    st.session_state.master_df = load_data()
    st.sidebar.success("Synced!")

files = st.file_uploader("Upload Portal Orders (Flipkart/Meesho/Myntra)", type="csv", accept_multiple_files=True)

if files:
    orders_list = []
    for f in files:
        df = pd.read_csv(f)
        # --- SMART COLUMN DETECTION ---
        cols = {str(c).lower().strip().replace(" ", "_"): c for c in df.columns}
        
        # Extended list of SKU keys
        sku_keys = ['sku', 'seller_sku', 'product_id', 'listing_id', 'order_item_sku', 'item_sku', 'external_id']
        qty_keys = ['quantity', 'qty', 'item_qty', 'ordered_quantity', 'order_item_quantity']
        
        s_col = next((cols[k] for k in sku_keys if k in cols), None)
        q_col = next((cols[k] for k in qty_keys if k in cols), None)
        
        if s_col:
            t_df = pd.DataFrame()
            t_df['Portal_SKU'] = df[s_col].astype(str).str.strip()
            t_df['Qty'] = pd.to_numeric(df[q_col], errors='coerce').fillna(1) if q_col else 1
            orders_list.append(t_df)
        else:
            st.error(f"❌ File '{f.name}' mein SKU column nahi mila! Columns found: {list(df.columns)}")

    if orders_list:
        combined = pd.concat(orders_list, ignore_index=True)
        
        # Fresh Database
        current_db = load_data()
        active_map = current_db[current_db['Portal_SKU'].astype(str).str.strip() != ""].copy()
        mapping_dict = dict(zip(active_map['Portal_SKU'].astype(str), active_map['Master_SKU'].astype(str)))
        
        # 1. PICKLIST
        combined['Master_SKU'] = combined['Portal_SKU'].map(mapping_dict)
        ready = combined.dropna(subset=['Master_SKU'])
        
        st.subheader("📋 Consolidated Picklist (Mapped)")
        if not ready.empty:
            summary = ready.groupby('Master_SKU')['Qty'].sum().reset_index().sort_values('Qty', ascending=False)
            st.dataframe(summary, use_container_width=True)
            st.metric("Total Pieces", int(summary['Qty'].sum()))
            st.download_button("📥 Download Picklist CSV", summary.to_csv(index=False).encode('utf-8'), "Aavoni_Picklist.csv")
        else:
            st.info("Abhi tak koi item match nahi hua. Niche Review section check karein.")

        st.divider()

        # 2. REVIEW NEW MAPPINGS
        unique_portal_skus = combined['Portal_SKU'].unique()
        unmapped = [s for s in unique_portal_skus if str(s) not in mapping_dict]
        
        if unmapped:
            st.subheader("🔍 Review & Link New SKUs")
            m_options = sorted(current_db['Master_SKU'].unique().tolist())
            
            if m_options:
                review_data = []
                for s in unmapped:
                    sugg, score = smart_hybrid_matcher(s, m_options)
                    review_data.append({"Confirm": (score >= 90), "Portal SKU": s, "Master SKU": sugg, "Match": f"{score}%"})
                
                edited = st.data_editor(
                    pd.DataFrame(review_data), 
                    column_config={
                        "Confirm": st.column_config.CheckboxColumn(),
                        "Master SKU": st.column_config.SelectboxColumn(options=m_options)
                    }, 
                    disabled=["Portal SKU", "Match"], 
                    hide_index=True, 
                    key="mapping_editor_final"
                )
                
                if st.button("Save New Links to Google Sheet"):
                    to_save = edited[edited['Confirm'] == True]
                    if not to_save.empty:
                        for _, row in to_save.iterrows():
                            save_mapping(row['Portal SKU'], row['Master SKU'])
                        st.success("Google Sheets Updated! Refreshing...")
                        st.rerun()
            else:
                st.error("Google Sheet mein Master SKUs nahi mile. Sheet check karein!")
