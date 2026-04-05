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
st.set_page_config(page_title="Aavoni Pick List PRO", layout="wide", page_icon="📦")

st.markdown("""
    <style>
    .stMetric { background-color: #ffffff; padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); border-left: 5px solid #007bff; }
    div.stButton > button:first-child { background-color: #007bff; color: white; border-radius: 8px; font-weight: bold; width: 100%; }
    </style>
    """, unsafe_allow_html=True)

# --- CONSTANTS ---
SHEET_ID = "1VZ5QLBQwH_r8kNSsUFacrS7_VSMJ556vO8C53s8Jwr0"
COLOR_KEYWORDS = {
    "ROYAL BLUE": "Teal Blue", "ROYALBLUE": "Teal Blue", "TEAL": "Teal Blue", "RB": "Teal Blue",
    "SKY BLUE": "Sky Blue", "SKY": "Sky Blue", "SB": "Sky Blue",
    "BLACK": "Black", "BLK": "Black", "WHITE": "White", "WHT": "White",
    "BEIGE": "Beige", "BG": "Beige", "BEG": "Beige", "RANI": "Rani", "PINK": "Rani",
    "MAROON": "Maroon", "MRN": "Maroon", "OLIVE": "Olive", "NAVY": "Navy", "YELLOW": "Yellow", 
    "GREY": "Grey", "BLUE": "Blue", "GREEN": "Green", "RUST": "Rust"
}
SIZE_ORDER = ["S","M","L","XL","XXL","2XL","3XL","4XL","5XL","6XL","7XL","8XL","9XL","10XL", "Free"]

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

# --- COMBO & EXTRACTION HELPERS (SUNIL'S LOGIC) ---
def extract_size(sku):
    sku = str(sku).upper().strip().replace("_", " ").replace("-", " ")
    match = re.search(r'(\d{1,2}XL|XXL|XL|L|M|S)$', sku)
    if not match: match = re.search(r'\b(\d{1,2}XL|XXL|XL|L|M|S)\b', sku)
    return match.group(1) if match else "Free"

def extract_colors(sku):
    sku_clean = str(sku).upper().replace("_", " ").replace("-", " ").strip()
    if "CBO" in sku_clean:
        match = re.search(r'\(?(.*?)\)?', sku_clean)
        if match:
            parts = match.group(1).replace(" ", "").split("+")
            final_colors = []
            for p in parts:
                for key, val in COLOR_KEYWORDS.items():
                    if key.replace(" ","") in p: final_colors.append(val); break
            return list(dict.fromkeys(final_colors)) if final_colors else ["Unknown"]
    for key, val in COLOR_KEYWORDS.items():
        if re.search(rf'\b{key}\b', sku_clean): return [val]
    return ["Unknown"]

def get_category(sku):
    sku = str(sku).upper()
    if sku.startswith("HF"): return "HF"
    if sku.startswith("PL"): return "PLAZZO"
    return "TROUSER"

# --- DATA PROCESSING ---
def load_db_data():
    try:
        gc = get_gspread_client()
        sh = gc.open_by_key(SHEET_ID)
        worksheet = sh.get_worksheet(0)
        records = worksheet.get_all_records()
        return pd.DataFrame(records), worksheet
    except:
        return pd.DataFrame(columns=['Portal_SKU', 'Master_SKU']), None

# --- PDF GENERATOR (SUNIL'S LAYOUT) ---
def create_pdf(dataframe):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=(3*inch, 5*inch), rightMargin=0.03*inch, leftMargin=0.03*inch, topMargin=0.1*inch, bottomMargin=0.1*inch)
    elements, styles = [], getSampleStyleSheet()
    cell_style = styles['Normal'].clone('CellStyle'); cell_style.alignment = TA_CENTER; cell_style.fontSize = 7
    
    elements.append(Paragraph(f"<b>AAVONI PICK LIST</b>", cell_style))
    elements.append(Paragraph(f"<font size=5>{datetime.now().strftime('%d-%m %H:%M')} | Total: {int(dataframe['Qty'].sum())}</font>", cell_style))
    
    data = [["Cat", "Color", "Size", "Qty", "Sh"]]
    for _, row in dataframe.iterrows():
        data.append([row["Category"], Paragraph(str(row['Color']), cell_style), row["Size"], int(row["Qty"]), ""])
    
    table = Table(data, colWidths=[0.8*inch, 1.05*inch, 0.5*inch, 0.35*inch, 0.3*inch])
    table.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), rl_colors.black), ('TEXTCOLOR',(0,0),(-1,0), rl_colors.white), ('GRID', (0,0), (-1,-1), 0.2, rl_colors.grey), ('FONTSIZE', (0,0), (-1,-1), 7), ('ALIGN', (0,0), (-1,-1), 'CENTER')]))
    elements.append(table); doc.build(elements); buffer.seek(0)
    return buffer

# --- MAIN APP ---
st.title("📦 Aavoni Pick List PRO")

db_df, ws = load_db_data()

with st.sidebar:
    st.header("⚙️ Settings")
    uploaded_files = st.file_uploader("Upload Portal Orders (CSV)", type=["csv"], accept_multiple_files=True)
    if st.button("🔄 Sync with Google Sheet"): st.rerun()
    st.markdown('<div style="background:linear-gradient(135deg, #007bff, #6610f2); color: white; padding: 10px; border-radius: 8px; text-align: center; font-weight: bold;">👨‍💻 Developed by Sunil</div>', unsafe_allow_html=True)

if uploaded_files:
    all_orders = []
    for f in uploaded_files:
        df = pd.read_csv(f)
        cols = {c.lower().replace(" ", "_"): c for c in df.columns}
        s_col = next((cols[k] for k in ['sku', 'seller_sku', 'listing_id'] if k in cols), None)
        q_col = next((cols[k] for k in ['quantity', 'qty'] if k in cols), None)
        if s_col:
            temp = pd.DataFrame({'SKU': df[s_col].astype(str), 'Qty': pd.to_numeric(df[q_col], errors='coerce').fillna(1) if q_col else 1})
            all_orders.append(temp)
    
    if all_orders:
        raw_df = pd.concat(all_orders)
        
        # Mapping Logic
        mapping_dict = dict(zip(db_df['Portal_SKU'].astype(str), db_df['Master_SKU'].astype(str)))
        
        # Process each row: If mapped, use Master_SKU, else use Sunil's Combo Logic
        processed_rows = []
        unmapped_skus = []

        for _, row in raw_df.iterrows():
            sku = row['SKU']
            qty = row['Qty']
            
            if sku in mapping_dict:
                master_sku = mapping_dict[sku]
                processed_rows.append({'Category': get_category(master_sku), 'Color': extract_colors(master_sku)[0], 'Size': extract_size(master_sku), 'Qty': qty})
            else:
                # Sunil's Combo Separator Logic
                cats = get_category(sku)
                sizes = extract_size(sku)
                colors_list = extract_colors(sku)
                for c in colors_list:
                    processed_rows.append({'Category': cats, 'Color': c, 'Size': sizes, 'Qty': qty})
                unmapped_skus.append(sku)

        final_df = pd.DataFrame(processed_rows).groupby(['Category', 'Color', 'Size'], as_index=False)['Qty'].sum()
        
        # Display Metrics
        m1, m2 = st.columns(2)
        m1.metric("📦 Total Pieces", int(final_df['Qty'].sum()))
        m2.metric("📂 Files Uploaded", len(uploaded_files))

        st.subheader("📋 Final Consolidated Picklist")
        st.dataframe(final_df.sort_values(['Category', 'Color']), use_container_width=True, hide_index=True)

        # Download Buttons
        c1, c2 = st.columns(2)
        with c1:
            pdf_file = create_pdf(final_df)
            st.download_button("📄 Download 3x5 PDF", data=pdf_file, file_name="Aavoni_PickList.pdf")
        with c2:
            excel_buf = io.BytesIO()
            final_df.to_excel(excel_buf, index=False)
            st.download_button("📥 Download Excel", data=excel_buf.getvalue(), file_name="PickList.xlsx")

        # Review Section for Unmapped
        if unmapped_skus:
            st.divider()
            st.subheader("🔍 New SKUs Detected (Need Mapping)")
            unique_unmapped = list(set(unmapped_skus))
            m_options = sorted(db_df['Master_SKU'].unique().tolist())
            
            review_df = pd.DataFrame([{'Confirm': False, 'Portal SKU': s, 'Master SKU': 'Select'} for s in unique_unmapped])
            edited = st.data_editor(review_df, column_config={"Master SKU": st.column_config.SelectboxColumn(options=m_options)}, hide_index=True)
            
            if st.button("Save New Mappings to Sheet"):
                to_save = edited[edited['Confirm'] == True]
                if not to_save.empty and ws:
                    ws.append_rows([[r['Portal SKU'], r['Master SKU']] for _, r in to_save.iterrows()])
                    st.success("Google Sheet Updated!"); st.rerun()
