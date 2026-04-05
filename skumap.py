import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from thefuzz import fuzz
import re

# --- PAGE SETUP ---
st.set_page_config(page_title="Aavoni Smart Picklist PRO", layout="wide")

# --- GOOGLE SHEETS CONNECTION ---
def get_gspread_client():
    try:
        # Secrets se credentials uthana
        creds_info = dict(st.secrets["gcp_service_account"])
        
        # KEY FIX: Kisi bhi tarah ke format issue ko handle karna
        if "private_key" in creds_info:
            # Newlines aur extra spaces saaf karna
            creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n").strip()
            
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Connection Error: {e}")
        st.info("Check karein ki Secrets mein [gcp_service_account] sahi se bhara hai.")
        st.stop()

# --- CONFIGURATION ---
# Yahan apni Google Sheet ki ID daalein
SHEET_ID = "YOUR_GOOGLE_SHEET_ID_HERE" 

try:
    gc = get_gspread_client()
    sh = gc.open_by_key(SHEET_ID)
    worksheet = sh.get_worksheet(0)
except Exception as e:
    st.error(f"❌ Google Sheet Connect nahi ho rahi: {e}")
    st.stop()

# --- DATA FUNCTIONS ---
def load_data():
    records = worksheet.get_all_records()
    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=['Portal_SKU', 'Master_SKU'])
    return df

def save_mapping(p_sku, m_sku):
    worksheet.append_row([str(p_sku).strip(), str(m_sku).strip()])

# --- LOGIC FUNCTIONS ---
def get_attributes(sku_text):
    sku_text = str(sku_text).upper()
    sizes = ['S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL', '6XL', '7XL', '8XL', '10XL']
    found_size = next((s for s in sizes if re.search(rf'\b{s}\b', sku_text)), None)
    colors = ['BLACK', 'WHITE', 'BEIGE', 'BLUE', 'RED', 'GREEN', 'PINK', 'NAVY', 'MAROON', 'GREY', 'TEAL']
    found_colors = [c for c in colors if c in sku_text]
    return found_size, found_colors

def smart_hybrid_matcher(new_sku, master_options):
    new_sku_str = str(new_sku).upper()
    f_size, f_colors = get_attributes(new_sku_str)
    
    filtered = master_options
    if f_size: filtered = [m for m in filtered if f_size in str(m).upper()]
    if f_colors: filtered = [m for m in filtered if all(c in str(m).upper() for c in f_colors)]

    if filtered:
        best_m, high_s = None, 0
        for opt in filtered:
            score = fuzz.token_set_ratio(new_sku_str, str(opt).upper())
            if score > high_s: high_s, best_m = score, opt
        if high_s > 65: return best_m, high_s
    return "Select Manually", 0

# --- APP START ---
st.title("🚀 Aavoni Smart Picklist PRO (Cloud DB)")

# Load mappings into session
if 'master_df' not in st.session_state or st.sidebar.button("🔄 Sync Sheet"):
    st.session_state.master_df = load_data()

# --- SIDEBAR ---
with st.sidebar:
    st.header("📦 Master Inventory")
    with st.expander("Bulk Upload Master SKUs"):
        m_file = st.file_uploader("Upload Master CSV/Excel", type=['csv', 'xlsx'])
        if m_file and st.button("Import Master"):
            df_m = pd.read_csv(m_file) if m_file.name.endswith('.csv') else pd.read_excel(m_file)
            m_col = next((c for c in df_m.columns if 'master' in c.lower() or 'sku' in c.lower()), df_m.columns[0])
            new_ms = [str(s).strip().upper() for s in df_m[m_col].dropna().unique()]
            
            existing_ms = st.session_state.master_df['Master_SKU'].tolist()
            count = 0
            for m in new_ms:
                if m not in existing_ms:
                    save_mapping("", m)
                    count += 1
            st.success(f"Added {count} new Master SKUs!")
            st.rerun()

# --- MAIN UI ---
files = st.file_uploader("Upload Portal Orders (Flipkart/Meesho/Myntra)", type="csv", accept_multiple_files=True)

if files:
    orders_list = []
    for f in files:
        df = pd.read_csv(f)
        clean_cols = {str(c).lower().strip().replace(" ", "_"): c for c in df.columns}
        s_col = next((clean_cols[k] for k in ['sku', 'seller_sku', 'product_id', 'listing_id', 'order_item_sku'] if k in clean_cols), None)
        q_col = next((clean_cols[k] for k in ['quantity', 'qty', 'item_qty'] if k in clean_cols), None)
        
        if s_col:
            t_df = pd.DataFrame()
            t_df['Portal_SKU'] = df[s_col].astype(str).str.strip()
            t_df['Qty'] = pd.to_numeric(df[q_col], errors='coerce').fillna(1) if q_col else 1
            orders_list.append(t_df)

    if orders_list:
        combined = pd.concat(orders_list, ignore_index=True)
        
        # Fresh data check
        current_db = load_data()
        active_map = current_db[current_db['Portal_SKU'] != ""].copy()
        mapping_dict = dict(zip(active_map['Portal_SKU'].astype(str), active_map['Master_SKU'].astype(str)))
        
        # 1. PICKLIST SECTION
        combined['Master_SKU'] = combined['Portal_SKU'].map(mapping_dict)
        ready = combined.dropna(subset=['Master_SKU'])
        
        st.subheader("📋 Consolidated Picklist (Ready)")
        if not ready.empty:
            summary = ready.groupby('Master_SKU')['Qty'].sum().reset_index().sort_values('Qty', ascending=False)
            st.dataframe(summary, use_container_width=True)
            
            c1, c2 = st.columns([1, 4])
            c1.metric("Total Pieces", int(summary['Qty'].sum()))
            c2.download_button("📥 Download CSV", summary.to_csv(index=False).encode('utf-8'), "Aavoni_Picklist.csv")
        else:
            st.info("No items mapped. Link them below.")

        st.divider()

        # 2. REVIEW SECTION
        unmapped = [s for s in combined['Portal_SKU'].unique() if s not in mapping_dict]
        if unmapped:
            st.subheader("🔍 Review New Mappings")
            m_options = sorted(current_db['Master_SKU'].unique().tolist())
            
            if m_options:
                review_data = []
                for s in unmapped:
                    sugg, score = smart_hybrid_matcher(s, m_options)
                    review_data.append({"Confirm": (score >= 90), "Portal SKU": s, "Master SKU": sugg, "Match": f"{score}%"})
                
                edited = st.data_editor(pd.DataFrame(review_data), column_config={
                    "Confirm": st.column_config.CheckboxColumn(),
                    "Master SKU": st.column_config.SelectboxColumn(options=m_options)
                }, disabled=["Portal SKU", "Match"], hide_index=True, key="gsheet_v5")
                
                if st.button("Save Selected Mappings"):
                    to_save = edited[edited['Confirm'] == True]
                    if not to_save.empty:
                        for _, row in to_save.iterrows():
                            save_mapping(row['Portal SKU'], row['Master SKU'])
                        st.success("Google Sheets Updated!")
                        st.rerun()
            else:
                st.error("Master list khali hai. Sidebar se upload karein.")
