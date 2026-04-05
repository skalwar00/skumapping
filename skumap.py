import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import base64
import json
import re
import io
from datetime import datetime
from thefuzz import fuzz

# PDF Libraries
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors as rl_colors
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER

# --- CONFIG & STYLING ---
st.set_page_config(page_title="Aavoni Universal Pro", layout="wide", page_icon="📦")

# --- CONSTANTS ---
SHEET_ID = "1VZ5QLBQwH_r8kNSsUFacrS7_VSMJ556vO8C53s8Jwr0"
COLOR_KEYWORDS = {
    "BLUE": "Blue", "ROYAL": "Royal Blue", "SKY": "Sky Blue", "BLK": "Black", "BLACK": "Black",
    "WHT": "White", "WHITE": "White", "RED": "Red", "MRN": "Maroon", "MAROON": "Maroon",
    "PNK": "Pink", "PINK": "Pink", "YLW": "Yellow", "YELLOW": "Yellow", "GRN": "Green", "GREEN": "Green"
}
SIZE_ORDER = ["S","M","L","XL","XXL","2XL","3XL","4XL","5XL","6XL","7XL","8XL","Free"]

# --- CONNECTION ---
def get_gspread_client():
    try:
        encoded_key = st.secrets["gcp_service_account"]["encoded_key"]
        creds_info = json.loads(base64.b64decode(encoded_key).decode("utf-8"))
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        return gspread.authorize(Credentials.from_service_account_info(creds_info, scopes=scope))
    except Exception as e:
        st.error(f"Credentials Error: {e}"); st.stop()

@st.cache_data(ttl=60)
def load_db():
    try:
        gc = get_gspread_client()
        sh = gc.open_by_key(SHEET_ID)
        ws = sh.get_worksheet(0)
        df = pd.DataFrame(ws.get_all_records())
        return df if not df.empty else pd.DataFrame(columns=['Portal_SKU', 'Master_SKU']), ws
    except:
        return pd.DataFrame(columns=['Portal_SKU', 'Master_SKU']), None

# --- HELPERS ---
def extract_size(sku):
    sku = str(sku).upper().strip()
    match = re.search(r'[-_\s](S|M|L|XL|XXL|\dXL)$', sku)
    if not match: match = re.search(r'\b(S|M|L|XL|XXL|\dXL)\b', sku)
    return match.group(1) if match else "Free"

def get_cat(sku):
    sku = str(sku).upper().replace("-", " ").replace("_", " ")
    return sku.split()[0][:6] if sku.split() else "Item"

# --- PDF GENERATOR ---
def create_pdf(df):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=(3*inch, 5*inch), margin=0.05*inch)
    elements, styles = [], getSampleStyleSheet()
    styleN = styles['Normal'].clone('styleN'); styleN.fontSize = 7; styleN.alignment = TA_CENTER
    elements.append(Paragraph(f"<b>AAVONI UNIVERSAL LIST</b>", styleN))
    data = [["Cat", "Color", "Size", "Qty", "Sh"]]
    for _, row in df.iterrows():
        data.append([row["Category"], Paragraph(str(row['Color']), styleN), row["Size"], int(row["Qty"]), ""])
    t = Table(data, colWidths=[0.7*inch, 1.1*inch, 0.5*inch, 0.4*inch, 0.3*inch])
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),rl_colors.black),('TEXTCOLOR',(0,0),(-1,0),rl_colors.white),('GRID',(0,0),(-1,-1),0.2,rl_colors.grey),('ALIGN',(0,0),(-1,-1),'CENTER')]))
    elements.append(t); doc.build(elements); buffer.seek(0)
    return buffer

# --- MAIN APP ---
st.title("🌍 Aavoni Universal Pro")

db_df, ws = load_db()
all_masters = sorted([str(m).strip().upper() for m in db_df['Master_SKU'].unique() if str(m).strip() != ""])

# 1. MASTER UPLOAD SECTION
with st.expander("📥 Step 1: Upload Master Inventory (First Time Setup)"):
    m_file = st.file_uploader("Upload Master SKU File (CSV/XLSX)", type=['csv', 'xlsx'], key="master_file")
    if m_file:
        m_df = pd.read_csv(m_file) if m_file.name.endswith('.csv') else pd.read_excel(m_file)
        m_col = st.selectbox("Select Master SKU Column", m_df.columns)
        if st.button("Add to Master Inventory"):
            new_list = set([str(s).strip().upper() for s in m_df[m_col].dropna().unique()])
            rows_to_add = [["", sku] for sku in new_list if sku not in all_masters]
            if rows_to_add and ws:
                ws.append_rows(rows_to_add)
                st.success(f"Success! {len(rows_to_add)} New SKUs added."); st.rerun()
            else: st.info("No new SKUs found.")

st.divider()

# 2. PORTAL ORDERS
st.subheader("📤 Step 2: Upload Portal Orders")
files = st.file_uploader("Upload Portal CSVs", type="csv", accept_multiple_files=True)

if files:
    orders = []
    for f in files:
        df_t = pd.read_csv(f)
        cols = {c.lower().strip().replace(" ", "_"): c for c in df_t.columns}
        s_col = next((cols[k] for k in ['sku', 'seller_sku', 'listing_id', 'product_id'] if k in cols), None)
        q_col = next((cols[k] for k in ['qty', 'quantity', 'ordered_quantity'] if k in cols), None)
        if s_col:
            orders.append(pd.DataFrame({'SKU': df_t[s_col].astype(str).str.strip(), 'Qty': pd.to_numeric(df_t[q_col], errors='coerce').fillna(1)}))

    if orders:
        raw_df = pd.concat(orders)
        mapping_dict = dict(zip(db_df['Portal_SKU'].astype(str), db_df['Master_SKU'].astype(str)))
        
        processed = []
        unmapped = []
        for _, row in raw_df.iterrows():
            sku = row['SKU']
            if sku in mapping_dict:
                m_sku = mapping_dict[sku]
                processed.append({'Category': get_cat(m_sku), 'Color': 'Mapped', 'Size': extract_size(m_sku), 'Qty': row['Qty']})
            else:
                processed.append({'Category': get_cat(sku), 'Color': 'New', 'Size': extract_size(sku), 'Qty': row['Qty']})
                unmapped.append(sku)

        final_df = pd.DataFrame(processed).groupby(['Category', 'Color', 'Size'], as_index=False)['Qty'].sum()
        
        st.subheader("📋 Picklist Preview")
        st.dataframe(final_df, use_container_width=True, hide_index=True)
        
        c1, c2 = st.columns(2)
        with c1: st.download_button("📄 Download PDF (3x5)", create_pdf(final_df), "PickList.pdf", use_container_width=True)
        with c2:
            buf = io.BytesIO(); final_df.to_excel(buf, index=False)
            st.download_button("📥 Download Excel", buf.getvalue(), "PickList.xlsx", use_container_width=True)

        # 3. REVIEW SECTION
        if unmapped and all_masters:
            st.divider()
            st.subheader("🔍 Map New Portal SKUs")
            unique_new = list(set(unmapped))
            review_df = pd.DataFrame([{'Confirm': False, 'Portal SKU': s, 'Master SKU': all_masters[0] if all_masters else ""} for s in unique_new])
            edited = st.data_editor(review_df, column_config={"Master SKU": st.column_config.SelectboxColumn(options=all_masters)}, hide_index=True)
            
            if st.button("Save New Mappings"):
                to_save = edited[edited['Confirm'] == True]
                if not to_save.empty and ws:
                    ws.append_rows([[r['Portal SKU'], r['Master SKU']] for _, r in to_save.iterrows()])
                    st.success("Mappings Saved!"); st.rerun()
