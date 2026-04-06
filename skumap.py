import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import base64
import json
from thefuzz import fuzz
import re
import pdfplumber

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

SHEET_ID = "1VZ5QLBQwH_r8kNSsUFacrS7_VSMJ556vO8C53s8Jwr0" 
try:
    gc = get_gspread_client()
    sh = gc.open_by_key(SHEET_ID)
    worksheet = sh.get_worksheet(0)
except Exception as e:
    st.error(f"❌ Google Sheet Connection Issue: {e}")
    st.stop()

# --- UTILITY FUNCTIONS ---
def load_data():
    try:
        records = worksheet.get_all_records()
        return pd.DataFrame(records) if records else pd.DataFrame(columns=['Portal_SKU', 'Master_SKU'])
    except:
        return pd.DataFrame(columns=['Portal_SKU', 'Master_SKU'])

def bulk_save_to_gsheet(rows):
    if rows: worksheet.append_rows(rows)

# --- SMART SIZE DETECTION ---
def get_sku_size(sku):
    """Portal SKU se exact size nikalne ke liye (S, M, L, XL, 2XL... 6XL)"""
    # Regex for sizes like 4XL, 6XL, XL, L, M, S
    match = re.search(r'\b(\d*XL|L|M|S)\b', str(sku).upper())
    return match.group(1) if match else ""

def clean_sku_for_pattern(sku):
    """Pattern learning ke liye SKU se size aur brackets hatana"""
    sku = str(sku).upper()
    patterns_to_remove = [
        r'\(.*?\)',                 # Brackets aur unke andar ka text
        r'\b\d*XL\b',               # 2XL to 6XL
        r'\b[SML]\b',               # S, M, L
        r'[-_]\s*$',                # Last symbols
    ]
    for p in patterns_to_remove:
        sku = re.sub(p, '', sku)
    return sku.strip('-_ ')

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

current_db = load_data()
all_master_options = sorted([str(m).strip().upper() for m in current_db['Master_SKU'].unique() if str(m).strip() != ""])

files = st.file_uploader("Upload Portal Orders (CSV/PDF)", type=["csv", "pdf"], accept_multiple_files=True)

if files:
    orders_list = []
    # (File processing logic remains same as previous working version)
    for f in files:
        if f.name.endswith('.pdf'):
            # Meesho PDF Logic
            pass 
        else:
            df = pd.read_csv(f)
            cols = {str(c).lower().strip(): c for c in df.columns}
            s_col = next((cols[k] for k in ['sku', 'seller_sku_code', 'seller_sku'] if k in cols), None)
            if s_col:
                orders_list.append(pd.DataFrame({'Portal_SKU': df[s_col].astype(str).str.strip(), 'Qty': [1]*len(df)}))

    if orders_list:
        combined = pd.concat(orders_list, ignore_index=True)
        active_map = current_db[current_db['Portal_SKU'] != ""].copy()
        m_dict = dict(zip(active_map['Portal_SKU'].astype(str), active_map['Master_SKU'].astype(str)))
        
        unmapped = [s for s in combined['Portal_SKU'].unique() if str(s) not in m_dict]
        
        if unmapped:
            st.warning(f"Found {len(unmapped)} New SKUs.")
            
            if 'temp_review_df' not in st.session_state:
                review_data = []
                for s in unmapped:
                    sugg, score = smart_hybrid_matcher(s, all_master_options)
                    review_data.append({"Confirm": (score >= 90), "Portal SKU": s, "Master SKU": sugg})
                st.session_state.temp_review_df = pd.DataFrame(review_data)

            edited_df = st.data_editor(
                st.session_state.temp_review_df,
                column_config={"Master SKU": st.column_config.SelectboxColumn(options=all_master_options)},
                hide_index=True, key="size_aware_editor"
            )

            # --- UPDATED SIZE-SENSITIVE PATTERN LEARNING ---
            if st.button("Apply Pattern (Size-to-Size)"):
                new_temp = edited_df.copy()
                learning_dict = {}

                # 1. Identify what the user changed manually
                for i, row in edited_df.iterrows():
                    orig_master = st.session_state.temp_review_df.iloc[i]['Master SKU']
                    if row['Master SKU'] != orig_master:
                        base_portal = clean_sku_for_pattern(row['Portal SKU'])
                        base_master = clean_sku_for_pattern(row['Master SKU'])
                        learning_dict[base_portal] = base_master

                # 2. Apply to other rows by adding their specific size
                if learning_dict:
                    for i, row in new_temp.iterrows():
                        p_base = clean_sku_for_pattern(row['Portal SKU'])
                        if p_base in learning_dict:
                            target_size = get_sku_size(row['Portal SKU'])
                            # Create new Master SKU with correct size
                            m_base = learning_dict[p_base]
                            new_val = f"{m_base}-{target_size}" if target_size else m_base
                            
                            if new_val in all_master_options:
                                new_temp.at[i, 'Master SKU'] = new_val
                                new_temp.at[i, 'Confirm'] = True
                    
                    st.session_state.temp_review_df = new_temp
                    st.rerun()

            if st.button("Save Mapping"):
                to_save = edited_df[edited_df['Confirm'] == True]
                if not to_save.empty:
                    rows = [[str(r['Portal SKU']), str(r['Master SKU'])] for _, r in to_save.iterrows()]
                    bulk_save_to_gsheet(rows)
                    st.success("Mapping Saved!")
                    del st.session_state.temp_review_df
                    st.rerun()
