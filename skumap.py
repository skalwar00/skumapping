import streamlit as st
import pandas as pd
from supabase import create_client, Client
from thefuzz import fuzz
import re
import pdfplumber
import io

# --- PAGE SETUP ---
st.set_page_config(page_title="Aavoni Smart Picklist (Supabase)", layout="wide")

# --- SUPABASE CONNECTION ---
# Inhe Streamlit secrets mein add karein: url aur key
try:
    url: str = st.secrets["SUPABASE_URL"]
    key: str = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error("❌ Supabase Credentials missing in secrets!")
    st.stop()

# --- DATA FUNCTIONS (SUPABASE) ---
def load_mapping_db():
    try:
        # Fetching all mappings from Supabase
        res = supabase.table("sku_mapping").select("portal_sku, master_sku").execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame(columns=['portal_sku', 'master_sku'])
    except:
        return pd.DataFrame(columns=['portal_sku', 'master_sku'])

def load_master_inventory():
    try:
        # Fetching all unique master skus
        res = supabase.table("master_inventory").select("master_sku").execute()
        return sorted([item['master_sku'].upper() for item in res.data]) if res.data else []
    except:
        return []

def save_mappings_bulk(rows):
    # rows format: list of dicts [{'portal_sku': '...', 'master_sku': '...'}]
    if rows:
        supabase.table("sku_mapping").upsert(rows, on_conflict="portal_sku").execute()

def save_masters_bulk(sku_list):
    if sku_list:
        data = [{"master_sku": s.upper()} for s in sku_list]
        supabase.table("master_inventory").upsert(data, on_conflict="master_sku").execute()

# --- UTILS ---
def get_sku_size(sku):
    match = re.search(r'\b(\d*XL|L|M|S)\b', str(sku).upper())
    return match.group(1) if match else ""

def clean_sku_for_pattern(sku):
    sku = str(sku).upper()
    patterns = [r'\(.*?\)', r'\b\d*XL\b', r'\b[SML]\b', r'[-_]\s*$', r'\s+']
    for p in patterns:
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

# --- MEESHO PDF EXTRACTOR ---
def extract_meesho_pdf(pdf_file):
    data = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2: continue
                sku_idx = size_idx = qty_idx = None
                for i, row in enumerate(table):
                    row_str = " ".join([str(c).lower() for c in row if c])
                    if 'sku' in row_str and ('qty' in row_str or 'quantity' in row_str):
                        for idx, cell in enumerate(row):
                            c_text = str(cell).lower()
                            if 'sku' in c_text: sku_idx = idx
                            if 'size' in c_text: size_idx = idx
                            if 'qty' in c_text or 'quantity' in c_text: qty_idx = idx
                        header_idx = i
                        break
                if sku_idx is not None:
                    for row in table[header_idx + 1:]:
                        if not row[sku_idx]: continue
                        raw_sku = str(row[sku_idx]).strip()
                        size = str(row[size_idx]).strip() if size_idx is not None else ""
                        qty_val = 1
                        if qty_idx is not None:
                            nums = re.findall(r'\d+', str(row[qty_idx]))
                            qty_val = int(nums[0]) if nums else 1
                        data.append({'Portal_SKU': f"{raw_sku} {size}".strip(), 'Qty': qty_val})
    return pd.DataFrame(data)

# --- SIDEBAR & SETTINGS ---
current_mapping = load_mapping_db()
all_masters = load_master_inventory()

with st.sidebar:
    st.header("⚙️ Supabase Settings")
    with st.expander("📥 Update Master Inventory"):
        m_file = st.file_uploader("Upload Master CSV/Excel", type=['csv', 'xlsx'])
        if m_file:
            df_m = pd.read_csv(m_file) if m_file.name.endswith('.csv') else pd.read_excel(m_file)
            m_col = next((c for c in df_m.columns if 'master' in c.lower() or 'sku' in c.lower()), df_m.columns[0])
            if st.button("Sync to Supabase"):
                new_list = df_m[m_col].dropna().unique().tolist()
                save_masters_bulk(new_list)
                st.success("Master Inventory Updated!")
                st.rerun()

# --- MAIN APP ---
st.title("🚀 Aavoni Smart Picklist (Supabase Edition)")

files = st.file_uploader("Upload Orders (Flipkart CSV / Meesho PDF)", type=["csv", "pdf"], accept_multiple_files=True)

if files:
    orders_list = []
    for f in files:
        if f.name.endswith('.pdf'):
            pdf_df = extract_meesho_pdf(f)
            if not pdf_df.empty: orders_list.append(pdf_df)
        else:
            df = pd.read_csv(f)
            cols = {str(c).lower().strip().replace(" ", "_"): c for c in df.columns}
            s_col = next((cols[k] for k in ['sku', 'seller_sku', 'seller_sku_code'] if k in cols), None)
            q_col = next((cols[k] for k in ['quantity', 'qty', 'total_quantity'] if k in cols), None)
            if s_col:
                qty_data = pd.to_numeric(df[q_col], errors='coerce').fillna(1) if q_col else 1
                orders_list.append(pd.DataFrame({'Portal_SKU': df[s_col].astype(str).str.strip(), 'Qty': qty_data}))

    if orders_list:
        combined = pd.concat(orders_list, ignore_index=True)
        m_dict = dict(zip(current_mapping['portal_sku'].astype(str), current_mapping['master_sku'].astype(str)))
        
        combined['Master_SKU'] = combined['Portal_SKU'].map(m_dict)
        ready = combined.dropna(subset=['Master_SKU'])
        
        if not ready.empty:
            st.subheader("📋 Final Picklist")
            summary = ready.groupby('Master_SKU')['Qty'].sum().reset_index().sort_values('Qty', ascending=False)
            st.dataframe(summary, use_container_width=True)

        st.divider()

        unmapped = [s for s in combined['Portal_SKU'].unique() if str(s) not in m_dict]
        if unmapped:
            st.warning(f"Found {len(unmapped)} New SKUs.")
            if 'temp_res' not in st.session_state:
                res = []
                for s in unmapped:
                    sugg, score = smart_hybrid_matcher(s, all_masters)
                    res.append({"Confirm": (score >= 90), "Portal SKU": s, "Master SKU": sugg})
                st.session_state.temp_res = pd.DataFrame(res)

            edited_df = st.data_editor(
                st.session_state.temp_res,
                column_config={"Master SKU": st.column_config.SelectboxColumn(options=all_masters)},
                hide_index=True, key="sb_editor"
            )

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Apply Pattern (Size-to-Size)"):
                    new_temp = edited_df.copy()
                    learning = {}
                    for i, row in edited_df.iterrows():
                        if row['Master SKU'] != st.session_state.temp_res.iloc[i]['Master SKU']:
                            learning[clean_sku_for_pattern(row['Portal SKU'])] = clean_sku_for_pattern(row['Master SKU'])
                    if learning:
                        for i, row in new_temp.iterrows():
                            pb = clean_sku_for_pattern(row['Portal SKU'])
                            if pb in learning:
                                sz, mb = get_sku_size(row['Portal SKU']), learning[pb]
                                new_val = f"{mb}-{sz}" if sz else mb
                                if new_val in all_masters:
                                    new_temp.at[i, 'Master SKU'] = new_val
                                    new_temp.at[i, 'Confirm'] = True
                        st.session_state.temp_res = new_temp
                        st.rerun()

            with col2:
                if st.button("Save to Supabase"):
                    to_save = edited_df[edited_df['Confirm'] == True]
                    if not to_save.empty:
                        rows = [{"portal_sku": str(r['Portal SKU']), "master_sku": str(r['Master SKU'])} for _, r in to_save.iterrows()]
                        save_mappings_bulk(rows)
                        st.success("Database Updated!")
                        del st.session_state.temp_res
                        st.rerun()
