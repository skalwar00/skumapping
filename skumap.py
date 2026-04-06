import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import base64
import json
from thefuzz import fuzz
import re
import pdfplumber
import io

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
        return pd.DataFrame(records) if records else pd.DataFrame(columns=['Portal_SKU', 'Master_SKU'])
    except:
        return pd.DataFrame(columns=['Portal_SKU', 'Master_SKU'])

def bulk_save_to_gsheet(rows):
    if rows:
        worksheet.append_rows(rows)

# --- MEESHO PDF EXTRACTOR (SKU + SIZE ONLY) ---
def extract_meesho_pdf(pdf_file):
    data = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue
                
                sku_idx = size_idx = qty_idx = None
                header_row_index = -1

                # Dynamic Header Search
                for i, row in enumerate(table):
                    row_str = " ".join([str(cell).lower() for cell in row if cell])
                    if 'sku' in row_str and ('qty' in row_str or 'quantity' in row_str):
                        header_row_index = i
                        for idx, cell in enumerate(row):
                            c_text = str(cell).lower()
                            if 'sku' in c_text: sku_idx = idx
                            if 'size' in c_text: size_idx = idx
                            if 'qty' in c_text or 'quantity' in c_text: qty_idx = idx
                        break
                
                if sku_idx is not None:
                    for row in table[header_row_index + 1:]:
                        if not row[sku_idx]: continue
                        
                        raw_sku = str(row[sku_idx]).strip()
                        size = str(row[size_idx]).strip() if size_idx is not None else ""
                        
                        qty_val = 1
                        if qty_idx is not None:
                            qty_text = str(row[qty_idx])
                            nums = re.findall(r'\d+', qty_text)
                            qty_val = int(nums[0]) if nums else 1

                        full_portal_sku = f"{raw_sku} {size}".strip()
                        data.append({'Portal_SKU': full_portal_sku, 'Qty': qty_val})
    return pd.DataFrame(data)

def clean_sku_for_pattern(sku):
    sku = str(sku).upper()
    patterns_to_remove = [r'\(.*\)', r'\bS\b', r'\bM\b', r'\bL\b', r'\bXL\b', r'\b\d*XL\b', r'-\s*$', r'_\s*$']
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

# 1. MASTER INVENTORY UPLOAD
with st.expander("📥 Step 1: Upload Master Inventory"):
    m_file = st.file_uploader("Master SKU file upload", type=['csv', 'xlsx'])
    if m_file:
        df_m = pd.read_csv(m_file) if m_file.name.endswith('.csv') else pd.read_excel(m_file)
        m_col = next((c for c in df_m.columns if 'master' in c.lower() or 'sku' in c.lower()), df_m.columns[0])
        if st.button("Add Master SKUs"):
            new_skus = set([str(sku).strip().upper() for sku in df_m[m_col].dropna().unique()])
            existing = set(all_master_options)
            rows = [["", s] for s in new_skus if s not in existing]
            if rows: 
                bulk_save_to_gsheet(rows)
                st.success("Master List Updated!")
                st.rerun()

st.divider()

# 2. PORTAL ORDERS UPLOAD
files = st.file_uploader("Upload Portal Orders (Flipkart CSV / Meesho PDF)", type=["csv", "pdf"], accept_multiple_files=True)

if files:
    orders_list = []
    for f in files:
        if f.name.endswith('.pdf'):
            with st.spinner(f"Processing Meesho PDF: {f.name}..."):
                pdf_df = extract_meesho_pdf(f)
                if not pdf_df.empty: orders_list.append(pdf_df)
        else:
            df = pd.read_csv(f)
            cols = {str(c).lower().strip().replace(" ", "_"): c for c in df.columns}
            
            # --- UPDATED CSV KEYWORDS ---
            s_col = next((cols[k] for k in ['sku', 'seller_sku', 'seller_sku_code', 'listing_id', 'product_id'] if k in cols), None)
            q_col = next((cols[k] for k in ['quantity', 'qty', 'ordered_quantity', 'total_quantity'] if k in cols), None)
            
            if s_col:
                orders_list.append(pd.DataFrame({
                    'Portal_SKU': df[s_col].astype(str).str.strip(), 
                    'Qty': pd.to_numeric(df[q_col], errors='coerce').fillna(1)
                }))
            else:
                st.error(f"❌ '{f.name}' mein SKU column nahi mila. Header check karein.")

    if orders_list:
        combined = pd.concat(orders_list, ignore_index=True)
        active_map = current_db[current_db['Portal_SKU'].astype(str).str.strip() != ""].copy()
        m_dict = dict(zip(active_map['Portal_SKU'].astype(str), active_map['Master_SKU'].astype(str)))
        
        combined['Master_SKU'] = combined['Portal_SKU'].map(m_dict)
        ready = combined.dropna(subset=['Master_SKU'])
        
        if not ready.empty:
            st.subheader("📋 Final Picklist")
            summary = ready.groupby('Master_SKU')['Qty'].sum().reset_index().sort_values('Qty', ascending=False)
            st.dataframe(summary, use_container_width=True)

        st.divider()

        # 3. REVIEW & LINK
        unmapped = [s for s in combined['Portal_SKU'].unique() if str(s) not in m_dict]
        if unmapped:
            st.warning(f"Found {len(unmapped)} New SKUs.")
            
            if 'temp_review_df' not in st.session_state:
                review_data = []
                for s in unmapped:
                    sugg, score = smart_hybrid_matcher(s, all_master_options)
                    review_data.append({"Confirm": (score >= 90), "Portal SKU": s, "Master SKU": sugg, "Match Score": f"{score}%"})
                st.session_state.temp_review_df = pd.DataFrame(review_data)

            edited_df = st.data_editor(
                st.session_state.temp_review_df,
                column_config={
                    "Confirm": st.column_config.CheckboxColumn(),
                    "Master SKU": st.column_config.SelectboxColumn(options=all_master_options),
                },
                hide_index=True, key="aavoni_editor"
            )

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Apply Pattern to All Sizes"):
                    learning_dict = {}
                    for i, row in edited_df.iterrows():
                        if row['Master SKU'] != st.session_state.temp_review_df.iloc[i]['Master SKU']:
                            pattern = clean_sku_for_pattern(row['Portal SKU'])
                            learning_dict[pattern] = row['Master SKU']
                    
                    if learning_dict:
                        for i, row in edited_df.iterrows():
                            pat = clean_sku_for_pattern(row['Portal SKU'])
                            if pat in learning_dict:
                                edited_df.at[i, 'Master SKU'] = learning_dict[pat]
                                edited_df.at[i, 'Confirm'] = True
                        st.session_state.temp_review_df = edited_df
                        st.rerun()

            with col2:
                if st.button("Save & Update Picklist"):
                    to_save = edited_df[edited_df['Confirm'] == True]
                    if not to_save.empty:
                        rows = [[str(r['Portal SKU']), str(r['Master SKU'])] for _, r in to_save.iterrows()]
                        bulk_save_to_gsheet(rows)
                        st.success("Mapping Saved!")
                        del st.session_state.temp_review_df
                        st.rerun()
