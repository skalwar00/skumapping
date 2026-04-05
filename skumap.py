import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from thefuzz import fuzz
import re

# --- GOOGLE SHEETS SETUP ---
# Secrets se credentials uthana
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
client = gspread.authorize(creds)

# Sheet ID yahan apni daalein
SHEET_ID = "YOUR_GOOGLE_SHEET_ID_HERE" 
sheet = client.open_by_key(SHEET_ID).sheet1

def load_gsheet_data():
    data = sheet.get_all_records()
    return pd.DataFrame(data)

def save_to_gsheet(portal_sku, master_sku):
    sheet.append_row([portal_sku, master_sku])

# --- APP LOGIC ---
st.set_page_config(page_title="Aavoni Google Sheets Edition", layout="wide")

# Initial Load from Google Sheets
if 'master_df' not in st.session_state or st.sidebar.button("🔄 Sync with Google Sheet"):
    st.session_state.master_df = load_gsheet_data()

# ... (Purana attribute extraction aur matcher logic yahan rahega) ...

# --- MAIN UI ---
st.title("🚀 Aavoni Smart Picklist (Google Sheets Edition)")

files = st.file_uploader("Upload Portal Orders", type="csv", accept_multiple_files=True)

if files:
    # ... (File processing logic same rahega) ...
    
    if orders_list:
        combined = pd.concat(orders_list, ignore_index=True)
        
        # Latest Mappings
        current_mappings = load_gsheet_data()
        mapping_dict = dict(zip(current_mappings['Portal_SKU'].astype(str), current_mappings['Master_SKU']))
        
        combined['Master_SKU'] = combined['Portal_SKU'].map(mapping_dict)
        
        # 1. PICKLIST SECTION
        ready = combined.dropna(subset=['Master_SKU'])
        if not ready.empty:
            st.subheader("📋 Consolidated Picklist")
            summary = ready.groupby('Master_SKU')['Qty'].sum().reset_index()
            st.dataframe(summary, use_container_width=True)
            st.download_button("📥 Download CSV", summary.to_csv(index=False).encode('utf-8'), "Aavoni_Picklist.csv")

        st.divider()

        # 2. REVIEW & SAVE TO GSHEET
        unmapped = [s for s in combined['Portal_SKU'].unique() if s not in mapping_dict]
        if unmapped:
            st.subheader("🔍 Review New Mappings")
            # Master Options list (sirf Master_SKU column se)
            m_options = sorted(current_mappings['Master_SKU'].unique().tolist())
            
            review_data = []
            for s in unmapped:
                sugg, score = smart_hybrid_matcher(s, m_options)
                review_data.append({"Confirm": (score >= 90), "Portal SKU": s, "Master SKU": sugg})
            
            edited = st.data_editor(pd.DataFrame(review_data), key="gsheet_editor")
            
            if st.button("Confirm & Save to Google Sheets"):
                to_save = edited[edited['Confirm'] == True]
                for _, row in to_save.iterrows():
                    save_to_gsheet(row['Portal SKU'], row['Master SKU'])
                st.success("Data Saved to Google Sheets Permanentally!")
                st.rerun()
