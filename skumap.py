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
        if "gcp_service_account" not in st.secrets:
            st.error("Secrets mein [gcp_service_account] nahi mila!")
            st.stop()
            
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
# YAHAN APNI ASLI SHEET ID DALEIN (URL se copy karke)
SHEET_ID = "1VZ5QLBQwH_r8kNSsUFacrS7_VSMJ556vO8C53s8Jwr0" 

try:
    gc = get_gspread_client()
    sh = gc.open_by_key(SHEET_ID)
    worksheet = sh.get_worksheet(0)
except Exception as e:
    st.error(f"❌ Google Sheet Connect nahi ho rahi. Check Sheet ID aur Sharing: {e}")
    st.stop()

# --- DATA FUNCTIONS ---
def load_data():
    try:
        records = worksheet.get_all_records()
        if not records:
            return pd.DataFrame(columns=['Portal_SKU', 'Master_SKU'])
        return pd.DataFrame(records)
    except Exception as e:
        st.error(f"Data Load Error: {e}")
        return pd.DataFrame(columns=['Portal_SKU', 'Master_SKU'])

def save_mapping(p_sku, m_sku):
    worksheet.append_row([str(p_sku).strip(), str(m_sku).strip()])

# --- MATCHING LOGIC ---
def get_attributes(sku_text):
    sku_text = str(sku_text).upper()
    sizes = ['S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL', '6XL', '7XL', '8XL', '10XL']
    found_size = next((s for s in sizes if re.search(rf'\b{s}\b', sku_text)), None)
    return found_size

def smart_hybrid_matcher(new_sku, master_options):
    new_sku_str = str(new_sku).upper()
    f_size = get_attributes(new_sku_str)
    filtered = master_options
    if f_size: 
        filtered = [m for m in filtered if f_size in str(m).upper()]
    
    if filtered:
        best_m, high_s = None, 0
        for opt in filtered:
            score = fuzz.token_set_ratio(new_sku_str, str(opt).upper())
            if score > high_s: high_s, best_m = score, opt
        if high_s > 65: return best_m, high_s
    return "Select Manually", 0

# --- APP UI ---
st.title("🚀 Aavoni Smart Picklist PRO")

# Load Initial Data
if 'master_df' not in st.session_state:
    st.session_state.master_df = load_data()

# Sidebar Sync
if st.sidebar.button("🔄 Sync Sheet"):
    st.session_state.master_df = load_data()
    st.sidebar.success("Data Synced!")

# --- FILE UPLOADER ---
files = st.file_uploader("Upload Portal Orders (Flipkart/Meesho/Myntra)", type="csv", accept_multiple_files=True)

if files:
    orders_list = []
    for f in files:
        df = pd.read_csv(f)
        clean_cols = {str(c).lower().strip().replace(" ", "_"): c for c in df.columns}
        s_col = next((clean_cols[k] for k in ['sku', 'seller_sku', 'product_id', 'listing_id'] if k in clean_cols), None)
        q_col = next((clean_cols[k] for k in ['quantity', 'qty', 'item_qty'] if k in clean_cols), None)
        
        if s_col:
            t_df = pd.DataFrame()
            t_df['Portal_SKU'] = df[s_col].astype(str).str.strip()
            t_df['Qty'] = pd.to_numeric(df[q_col], errors='coerce').fillna(1) if q_col else 1
            orders_list.append(t_df)

    if orders_list:
        combined = pd.concat(orders_list, ignore_index=True)
        
        # Fresh Mapping Logic
        current_db = st.session_state.master_df
        active_map = current_db[current_db['Portal_SKU'].astype(str).str.strip() != ""].copy()
        mapping_dict = dict(zip(active_map['Portal_SKU'].astype(str), active_map['Master_SKU'].astype(str)))
        
        # 1. Picklist Display
        combined['Master_SKU'] = combined['Portal_SKU'].map(mapping_dict)
        ready = combined.dropna(subset=['Master_SKU'])
        
        st.subheader("📋 Consolidated Picklist")
        if not ready.empty:
            summary = ready.groupby('Master_SKU')['Qty'].sum().reset_index().sort_values('Qty', ascending=False)
            st.dataframe(summary, use_container_width=True)
            st.download_button("📥 Download CSV", summary.to_csv(index=False).encode('utf-8'), "Aavoni_Picklist.csv")
        else:
            st.info("No items matched. Map new SKUs below.")

        st.divider()

        # 2. Review Section
        unmapped = [s for s in combined['Portal_SKU'].unique() if s not in mapping_dict]
        if unmapped:
            st.subheader("🔍 Review New Mappings")
            m_options = sorted(current_db['Master_SKU'].unique().tolist())
            
            if m_options:
                review_data = []
                for s in unmapped:
                    sugg, score = smart_hybrid_matcher(s, m_options)
                    review_data.append({"Confirm": (score >= 90), "Portal SKU": s, "Master SKU": sugg, "Match": f"{score}%"})
                
                edited = st.data_editor(pd.DataFrame(review_data), key="editor_final")
                
                if st.button("Save Selected Mappings"):
                    to_save = edited[edited['Confirm'] == True]
                    for _, row in to_save.iterrows():
                        save_mapping(row['Portal SKU'], row['Master SKU'])
                    st.success("Google Sheets Updated!")
                    st.session_state.master_df = load_data() # Refresh state
                    st.rerun()
