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

# PDF Report Generation
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors as rl_colors
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER

# --- CONFIG & UI STYLING ---
st.set_page_config(page_title="Aavoni Pro: Multi-Portal Picklist", layout="wide", page_icon="📦")

st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); border-left: 5px solid #007bff; }
    div.stButton > button:first-child { background-color: #007bff; color: white; border-radius: 6px; font-weight: bold; height: 3em; }
    .css-10trblm { color: #007bff; } /* Header color */
    </style>
    """, unsafe_allow_html=True)

# --- CONSTANTS & DATABASE ---
SHEET_ID = "1VZ5QLBQwH_r8kNSsUFacrS7_VSMJ556vO8C53s8Jwr0"

def get_gsheet_client():
    try:
        encoded_key = st.secrets["gcp_service_account"]["encoded_key"]
        creds_info = json.loads(base64.b64decode(encoded_key).decode("utf-8"))
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        return gspread.authorize(Credentials.from_service_account_info(creds_info, scopes=scope))
    except Exception as e:
        st.error(f"⚠️ Connection Error: {e}"); st.stop()

@st.cache_data(ttl=30)
def load_db():
    try:
        gc = get_gsheet_client()
        sh = gc.open_by_key(SHEET_ID)
        ws = sh.get_worksheet(0)
        data = ws.get_all_records()
        return pd.DataFrame(data) if data else pd.DataFrame(columns=['Portal_SKU', 'Master_SKU']), ws
    except:
        return pd.DataFrame(columns=['Portal_SKU', 'Master_SKU']), None

# --- CORE LOGIC FUNCTIONS ---

def get_universal_cat(sku):
    sku = str(sku).upper().replace("-", " ").replace("_", " ")
    parts = sku.split()
    return parts[0][:8] if parts else "ITEM"

def extract_size(sku):
    sku = str(sku).upper().strip()
    match = re.search(r'[-_\s](S|M|L|XL|XXL|\dXL)$', sku)
    if not match: match = re.search(r'\b(S|M|L|XL|XXL|\dXL)\b', sku)
    return match.group(1) if match else "Free"

# --- MEESHO PDF PARSER (SKU + SIZE MERGE) ---
def parse_meesho_pdf(pdf_file):
    rows = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table: continue
                df_p = pd.DataFrame(table[1:], columns=table[0])
                df_p.columns = [str(c).upper().replace("\n", " ").strip() for c in df_p.columns]
                
                # Identify Columns
                s_col = next((c for c in df_p.columns if any(k in c for k in ['SKU', 'PRODUCT', 'SELLER'])), None)
                q_col = next((c for c in df_p.columns if any(k in c for k in ['QTY', 'QUANTITY'])), None)
                z_col = next((c for c in df_p.columns if 'SIZE' in c), None)
                
                if s_col and q_col:
                    for _, row in df_p.iterrows():
                        base_sku = str(row[s_col]).strip().upper()
                        size_val = str(row[z_col]).strip().upper() if z_col and row[z_col] else ""
                        
                        # Smart Merge: SKU + Size (Avoid double size if already in SKU)
                        if size_val and size_val not in base_sku:
                            final_sku = f"{base_sku}-{size_val}"
                        else:
                            final_sku = base_sku
                        
                        if base_sku and base_sku != 'NONE':
                            rows.append({
                                'SKU': final_sku,
                                'Qty': pd.to_numeric(row[q_col], errors='coerce') or 1
                            })
    return pd.DataFrame(rows)

# --- PDF GENERATOR (3x5 INCH) ---
def generate_pdf_report(df):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=(3*inch, 5*inch), margin=0.05*inch)
    elements, styles = [], getSampleStyleSheet()
    sN = styles['Normal'].clone('sN'); sN.fontSize = 7; sN.alignment = TA_CENTER
    
    elements.append(Paragraph(f"<b>AAVONI PRO PICKLIST</b>", sN))
    elements.append(Paragraph(f"<font size=5>{datetime.now().strftime('%d/%m %H:%M')}</font>", sN))
    
    t_data = [["Category", "Size", "Qty", "Done"]]
    for _, r in df.iterrows():
        t_data.append([r["Category"], r["Size"], int(r["Qty"]), "[ ]"])
    
    table = Table(t_data, colWidths=[1.1*inch, 0.7*inch, 0.5*inch, 0.5*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),rl_colors.black),
        ('TEXTCOLOR',(0,0),(-1,0),rl_colors.white),
        ('GRID',(0,0),(-1,-1),0.2,rl_colors.grey),
        ('FONTSIZE',(0,0),(-1,-1),7),
        ('ALIGN',(0,0),(-1,-1),'CENTER')
    ]))
    elements.append(table); doc.build(elements); buf.seek(0)
    return buf

# --- MAIN APP UI ---
st.title("🌍 Aavoni Universal Pro Tool")

db_df, ws = load_db()
master_list = sorted([str(m).strip().upper() for m in db_df['Master_SKU'].unique() if str(m).strip() != ""])

with st.sidebar:
    st.header("⚙️ Dashboard Settings")
    if st.button("🔄 Sync Database"): st.rerun()
    
    with st.expander("📥 Master SKU Upload"):
        m_file = st.file_uploader("First-time Master SKU File", type=['csv', 'xlsx'])
        if m_file:
            m_df = pd.read_csv(m_file) if m_file.name.endswith('.csv') else pd.read_excel(m_file)
            m_col = st.selectbox("Select Master SKU Column", m_df.columns)
            if st.button("Bulk Add Master SKUs"):
                new_m = [str(s).strip().upper() for s in m_df[m_col].dropna().unique() if str(s).strip().upper() not in master_list]
                if new_m and ws:
                    ws.append_rows([["", s] for s in new_m])
                    st.success(f"{len(new_m)} Master SKUs added!"); st.rerun()

st.subheader("📤 Step 1: Upload Portal Files")
c1, c2 = st.columns(2)
with c1:
    f_csv = st.file_uploader("Upload Flipkart/CSV Files", type=['csv', 'xlsx'], accept_multiple_files=True)
with c2:
    f_pdf = st.file_uploader("Upload Meesho Manifests (PDF)", type=['pdf'], accept_multiple_files=True)

all_orders = []

# Process CSV/XLSX
if f_csv:
    for f in f_csv:
        df_t = pd.read_csv(f) if f.name.endswith('.csv') else pd.read_excel(f)
        cols = {c.lower().strip().replace(" ", "_"): c for c in df_t.columns}
        s_col = next((cols[k] for k in ['sku', 'seller_sku', 'listing_id', 'product_id'] if k in cols), None)
        q_col = next((cols[k] for k in ['qty', 'quantity', 'ordered_quantity'] if k in cols), None)
        if s_col:
            all_orders.append(pd.DataFrame({'SKU': df_t[s_col].astype(str).str.strip().upper(), 'Qty': pd.to_numeric(df_t[q_col], errors='coerce').fillna(1)}))

# Process PDF
if f_pdf:
    for f in f_pdf:
        pdf_res = parse_meesho_pdf(f)
        if not pdf_res.empty: all_orders.append(pdf_res)

if all_orders:
    raw_orders = pd.concat(all_orders)
    map_dict = dict(zip(db_df['Portal_SKU'].astype(str), db_df['Master_SKU'].astype(str)))
    
    processed_list = []
    need_mapping = []
    
    for _, row in raw_orders.iterrows():
        sku = str(row['SKU']).strip()
        if sku in map_dict:
            m_sku = map_dict[sku]
            processed_list.append({'Category': get_universal_cat(m_sku), 'Size': extract_size(m_sku), 'Qty': row['Qty']})
        else:
            processed_list.append({'Category': get_universal_cat(sku), 'Size': extract_size(sku), 'Qty': row['Qty']})
            need_mapping.append(sku)

    final_df = pd.DataFrame(processed_list).groupby(['Category', 'Size'], as_index=False)['Qty'].sum()
    
    # Dashboard Metrics
    m1, m2, m3 = st.columns(3)
    m1.metric("📦 Total Qty", int(final_df['Qty'].sum()))
    m2.metric("🆕 New SKUs", len(set(need_mapping)))
    m3.metric("📂 Files", len(all_orders))

    st.subheader("📋 Consolidated Picklist")
    st.dataframe(final_df.sort_values('Category'), use_container_width=True, hide_index=True)

    # Downloads
    d1, d2 = st.columns(2)
    with d1: st.download_button("📄 PDF Report (3x5)", generate_pdf_report(final_df), "PickList.pdf", use_container_width=True)
    with d2:
        xlsx_buf = io.BytesIO(); final_df.to_excel(xlsx_buf, index=False)
        st.download_button("📥 Excel File", xlsx_buf.getvalue(), "PickList.xlsx", use_container_width=True)

    # Step 2: Mapping Section
    if need_mapping and master_list:
        st.divider()
        st.subheader("🔍 Review & Link New SKUs")
        unique_new = sorted(list(set(need_mapping)))
        
        # Fuzzy Auto-Suggestion
        review_rows = []
        for s in unique_new:
            best_m, best_s = master_list[0], 0
            for m in master_list:
                score = fuzz.token_set_ratio(s, m)
                if score > best_s: best_s, best_m = score, m
            review_rows.append({'Save': (best_s > 88), 'Portal SKU': s, 'Master SKU': best_m})

        edited = st.data_editor(pd.DataFrame(review_rows), column_config={"Master SKU": st.column_config.SelectboxColumn(options=master_list)}, hide_index=True)
        
        if st.button("🚀 Update Mappings to Google Sheet"):
            to_save = edited[edited['Save'] == True]
            if not to_save.empty and ws:
                ws.append_rows([[r['Portal SKU'], r['Master SKU']] for _, r in to_save.iterrows()])
                st.success("Database Updated Successfully!"); st.rerun()

else:
    st.info("👋 Hey Sunil! Start by uploading your portal files (CSV/Excel) or Meesho Manifests (PDF).")
