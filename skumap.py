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
        # Fresh data fetch from Sheet
        records = worksheet.get_all_records()
        return pd.DataFrame(records) if records else pd.DataFrame(columns=['Portal_SKU', 'Master_SKU'])
    except:
        return pd.DataFrame(columns=['Portal_SKU', 'Master_SKU'])

def bulk_save_to_gsheet(rows):
    if rows:
        worksheet.append_rows(rows)

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

# Data Refresh
current_db = load_data()
# Master options for dropdown (Unique)
all_master_options = sorted([str(m).strip().upper() for m in current_db['Master_SKU'].unique() if str(m).strip() != ""])

# 1. MASTER INVENTORY UPLOAD
with st.expander("📥 Step 1: Upload Master Inventory (Duplicate Check Active)"):
    m_file = st.file_uploader("Master SKU file upload karein", type=['csv', 'xlsx'], key="m_up")
    if m_file:
        df_m = pd.read_csv(m_file) if m_file.name.endswith('.csv') else pd.read_excel(m_file)
        m_col = next((c for c in df_m.columns if 'master' in c.lower() or 'sku' in c.lower()), df_m.columns[0])
        
        if st.button("Clean & Add Master SKUs"):
            # Uploaded file ke unique SKUs
            new_skus_from_file = set([str(sku).strip().upper() for sku in df_m[m_col].dropna().unique()])
            
            # Sheet mein pehle se maujood SKUs
            existing_masters = set(all_master_options)
            
            # Sirf wo jo sheet mein nahi hain
            rows_to_add = [["", sku] for sku in new_skus_from_file if sku not in existing_masters]
            
            if rows_to_add:
                bulk_save_to_gsheet(rows_to_add)
                st.success(f"Naye {len(rows_to_add)} SKUs add ho gaye! Duplicates skip kar diye gaye.")
                st.rerun()
            else:
                st.info("Saare SKUs pehle se hi Sheet mein hain. Kuch bhi naya add nahi kiya gaya.")

st.divider()

# 2. PORTAL ORDERS UPLOAD
st.subheader("📤 Step 2: Upload Portal Orders")
files = st.file_uploader("Reports upload karein", type="csv", accept_multiple_files=True)

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
            t_df = pd.DataFrame({'Portal_SKU': df[s_col].astype(str).str.strip(), 
                                 'Qty': pd.to_numeric(df[q_col], errors='coerce').fillna(1) if q_col else 1})
            orders_list.append(t_df)

    if orders_list:
        combined = pd.concat(orders_list, ignore_index=True)
        # Refresh mapped data
        active_map = current_db[current_db['Portal_SKU'].astype(str).str.strip() != ""].copy()
        m_dict = dict(zip(active_map['Portal_SKU'].astype(str), active_map['Master_SKU'].astype(str)))
        
        # PICKLIST
        combined['Master_SKU'] = combined['Portal_SKU'].map(m_dict)
        ready = combined.dropna(subset=['Master_SKU'])
        
        if not ready.empty:
            st.subheader("📋 Final Picklist")
            summary = ready.groupby('Master_SKU')['Qty'].sum().reset_index().sort_values('Qty', ascending=False)
            st.dataframe(summary, use_container_width=True)
            st.download_button("📥 Download Picklist", summary.to_csv(index=False).encode('utf-8'), "Aavoni_Picklist.csv")

        # REVIEW SECTION
        unmapped = [s for s in combined['Portal_SKU'].unique() if str(s) not in m_dict]
        if unmapped and all_master_options:
            st.subheader("🔍 Review & Link New SKUs")
            review_data = []
            for s in unmapped:
                sugg, score = smart_hybrid_matcher(s, all_master_options)
                review_data.append({"Confirm": (score >= 90), "Portal SKU": s, "Master SKU": sugg, "Match": f"{score}%"})
            
            edited = st.data_editor(
                pd.DataFrame(review_data),
                column_config={
                    "Confirm": st.column_config.CheckboxColumn(),
                    "Master SKU": st.column_config.SelectboxColumn("Master SKU", options=all_master_options, required=True),
                    "Portal SKU": st.column_config.TextColumn(disabled=True),
                    "Match": st.column_config.TextColumn(disabled=True)
                },
                hide_index=True,
                key="editor_final_v10"
            )
            
            if st.button("Save Selected Mappings"):
                to_save = edited[edited['Confirm'] == True]
                if not to_save.empty:
                    # Double check duplicates in mapping before saving
                    existing_portal_skus = set(current_db['Portal_SKU'].astype(str).tolist())
                    rows_to_save = []
                    for _, r in to_save.iterrows():
                        if str(r['Portal SKU']) not in existing_portal_skus:
                            rows_to_save.append([str(r['Portal SKU']), str(r['Master SKU'])])
                    
                    if rows_to_save:
                        bulk_save_to_gsheet(rows_to_save)
                        st.success(f"Saved {len(rows_to_save)} new links!")
                        st.rerun()
                    else:
                        st.warning("Ye mappings pehle se sheet mein hain!")
