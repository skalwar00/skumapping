import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import base64
import json
import re
import io
import pdfplumber
from datetime import datetime
from thefuzz import fuzz

# PDF Report Libraries
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors as rl_colors
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER

# --- CONFIG & STYLING ---
st.set_page_config(page_title="Aavoni Pro: Universal Picklist", layout="wide", page_icon="📦")

# Professional Sidebar Branding
st.markdown("""
    <style>
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border-left: 5px solid #007bff; }
    div.stButton > button:first-child { background-color: #007bff; color: white; border-radius: 6px; font-weight: bold; }
    .status-box { padding: 10px; border-radius: 5px; margin-bottom: 10px; font-weight: 500; }
    </style>
    """, unsafe_allow_html=True)

# --- CONSTANTS & DB CONNECTION ---
SHEET_ID = "1VZ5QLBQwH_r8kNSsUFacrS7_VSMJ556vO8C53s8Jwr0"

def get_gsheet_client():
    try:
        encoded_key = st.secrets["gcp_service_account"]["encoded_key"]
        creds_info = json.loads(base64.b64decode(encoded_key).decode("utf-8"))
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_info, scopes=scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Database Connection Error: {e}")
        st.stop()

@st.cache_data(ttl=60)
def load_db():
    try:
        gc = get_gsheet_client()
        sh = gc.open_by_key(SHEET_ID)
        ws = sh.get_worksheet(0)
        df = pd.DataFrame(ws.get_all_records())
        return df if not df.empty else pd.DataFrame(columns=['Portal_SKU', 'Master_SKU']), ws
    except:
        return pd.DataFrame(columns=['Portal_SKU', 'Master_SKU']), None

# --- EXTRACTION LOGIC (UNIVERSAL) ---
def clean_sku_for_cat(sku):
    sku = str(sku).upper().replace("-", " ").replace("_", " ")
    parts = sku.split()
    return parts[0][:6] if parts else "ITEM"

def extract_size_universal(sku):
    sku = str(sku).upper().strip()
    match = re.search(r'[-_\s](S|M|L|XL|XXL|\dXL)$', sku)
    if not match: match = re.search(r'\b(S|M|L|XL|XXL|\dXL)\b', sku)
    return match.group(1) if match else "Free"

# --- PDF PARSER (MEESHO MANIFEST) ---
def parse_meesho_pdf(pdf_file):
    all_rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                df_page = pd.DataFrame(table[1:], columns=table[0])
                # Clean column names
                df_page.columns = [str(c).upper().replace("\n", " ").strip() for c in df_page.columns]
                
                # Dynamic Column Detection for Meesho
                s_col = next((c for c in df_page.columns if any(k in c for k in ['SKU', 'PRODUCT', 'SELLER'])), None)
                q_col = next((c for c in df_page.columns if any(k in c for k in ['QTY', 'QUANTITY'])), None)
                
                if s_col and q_col:
                    for _, row in df_page.iterrows():
                        if row[s_col]:
                            all_rows.append({
                                'SKU': str(row[s_col]).strip(),
                                'Qty': pd.to_numeric(row[q_col], errors='coerce') or 1
                            })
    return pd.DataFrame(all_rows) if all_rows else pd.DataFrame()

# --- PDF REPORT GENERATOR ---
def create_report_pdf(df):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=(3*inch, 5*inch), margin=0.05*inch)
    elements, styles = [], getSampleStyleSheet()
    styleN = styles['Normal'].clone('styleN'); styleN.fontSize = 7; styleN.alignment = TA_CENTER
    elements.append(Paragraph(f"<b>AAVONI PRO PICKLIST</b>", styleN))
    elements.append(Paragraph(f"<font size=5>{datetime.now().strftime('%d-%m %H:%M')}</font>", styleN))
    
    data = [["Cat", "Size", "Qty", "Check"]]
    for _, row in df.iterrows():
        data.append([row["Category"], row["Size"], int(row["Qty"]), "[ ]"])
    
    t = Table(data, colWidths=[1.1*inch, 0.7*inch, 0.5*inch, 0.5*inch])
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),rl_colors.black),('TEXTCOLOR',(0,0),(-1,0),rl_colors.white),('GRID',(0,0),(-1,-1),0.2,rl_colors.grey),('ALIGN',(0,0),(-1,-1),'CENTER')]))
    elements.append(t); doc.build(elements); buffer.seek(0)
    return buffer

# --- MAIN UI ---
st.title("🌍 Aavoni Universal Pro Tool")

db_df, ws = load_db()
master_options = sorted([str(m).strip().upper() for m in db_df['Master_SKU'].unique() if str(m).strip() != ""])

with st.sidebar:
    st.header("🏢 Seller Dashboard")
    st.info(f"Connected Sheet: ...{SHEET_ID[-6:]}")
    if st.button("🔄 Refresh Data"): st.rerun()
    
    # Step 1: Master Upload (Commercial requirement)
    with st.expander("📥 Master Inventory Upload"):
        m_file = st.file_uploader("Upload Master SKU File", type=['csv', 'xlsx'])
        if m_file:
            m_df = pd.read_csv(m_file) if m_file.name.endswith('.csv') else pd.read_excel(m_file)
            m_col = st.selectbox("Select Master SKU Column", m_df.columns)
            if st.button("Add Master SKUs"):
                new_ones = [str(s).strip().upper() for s in m_df[m_col].dropna().unique() if str(s).strip().upper() not in master_options]
                if new_ones and ws:
                    ws.append_rows([["", s] for s in new_ones])
                    st.success(f"{len(new_ones)} New SKUs Added!"); st.rerun()

st.subheader("📤 Upload Portal Orders")
col_a, col_b = st.columns(2)
with col_a:
    csv_files = st.file_uploader("Upload CSV/Excel (Flipkart/Generic)", type=["csv", "xlsx"], accept_multiple_files=True)
with col_b:
    pdf_files = st.file_uploader("Upload Meesho Manifest (PDF)", type=["pdf"], accept_multiple_files=True)

all_orders = []

# Process CSV/Excel
if csv_files:
    for f in csv_files:
        df_t = pd.read_csv(f) if f.name.endswith('.csv') else pd.read_excel(f)
        cols = {c.lower().strip().replace(" ", "_"): c for c in df_t.columns}
        s_col = next((cols[k] for k in ['sku', 'seller_sku', 'listing_id', 'product_id'] if k in cols), None)
        q_col = next((cols[k] for k in ['qty', 'quantity', 'ordered_quantity'] if k in cols), None)
        if s_col:
            all_orders.append(pd.DataFrame({'SKU': df_t[s_col].astype(str).str.strip(), 'Qty': pd.to_numeric(df_t[q_col], errors='coerce').fillna(1)}))

# Process PDF (Meesho)
if pdf_files:
    for f in pdf_files:
        pdf_df = parse_meesho_pdf(f)
        if not pdf_df.empty: all_orders.append(pdf_df)

if all_orders:
    raw_df = pd.concat(all_orders)
    mapping_dict = dict(zip(db_df['Portal_SKU'].astype(str), db_df['Master_SKU'].astype(str)))
    
    processed = []
    unmapped = []
    
    for _, row in raw_df.iterrows():
        sku = str(row['SKU']).strip()
        qty = row['Qty']
        
        if sku in mapping_dict:
            m_sku = mapping_dict[sku]
            processed.append({'Category': clean_sku_for_cat(m_sku), 'Size': extract_size_universal(m_sku), 'Qty': qty, 'Status': 'Mapped'})
        else:
            processed.append({'Category': clean_sku_for_cat(sku), 'Size': extract_size_universal(sku), 'Qty': qty, 'Status': 'New'})
            unmapped.append(sku)

    final_df = pd.DataFrame(processed).groupby(['Category', 'Size'], as_index=False)['Qty'].sum()
    
    # Metrics
    c1, c2, c3 = st.columns(3)
    c1.metric("📦 Total Pieces", int(final_df['Qty'].sum()))
    c2.metric("🆕 New SKUs", len(set(unmapped)))
    c3.metric("📂 Files", len(all_orders))

    st.subheader("📋 Picklist")
    st.dataframe(final_df, use_container_width=True, hide_index=True)

    # Downloads
    d1, d2 = st.columns(2)
    with d1: st.download_button("📄 Download 3x5 PDF Report", create_report_pdf(final_df), "Picklist.pdf", use_container_width=True)
    with d2:
        buf = io.BytesIO(); final_df.to_excel(buf, index=False)
        st.download_button("📥 Download Excel File", buf.getvalue(), "Picklist.xlsx", use_container_width=True)

    # 4. REVIEW & MAPPING
    if unmapped and master_options:
        st.divider()
        st.subheader("🔍 Mapping Required for New SKUs")
        unique_new = sorted(list(set(unmapped)))
        
        # Smart Matching for suggestions
        review_list = []
        for s in unique_new:
            # Simple fuzzy match to suggest from master
            sugg, score = "Select", 0
            for m in master_options:
                sc = fuzz.token_set_ratio(s.upper(), m.upper())
                if sc > score: score, sugg = sc, m
            review_list.append({'Confirm': (score > 88), 'Portal SKU': s, 'Master SKU': sugg if score > 70 else master_options[0]})

        edited = st.data_editor(pd.DataFrame(review_list), column_config={"Master SKU": st.column_config.SelectboxColumn(options=master_options)}, hide_index=True)
        
        if st.button("🚀 Save New Mappings"):
            to_save = edited[edited['Confirm'] == True]
            if not to_save.empty and ws:
                ws.append_rows([[r['Portal SKU'], r['Master SKU']] for _, r in to_save.iterrows()])
                st.success("Database Updated!"); st.rerun()

else:
    st.info("👋 Hey Sunil! Shuru karne ke liye upar files upload karein (CSV, Excel ya Meesho PDF).")
