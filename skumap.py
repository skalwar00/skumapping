import streamlit as st
import pandas as pd
from thefuzz import fuzz
import re
import os

# --- PAGE SETUP ---
st.set_page_config(page_title="Aavoni Pro Multi-Channel Tool", layout="wide")

MAPPING_FILE = "master_mapping.csv"

# Session State for Master Data
if 'master_df' not in st.session_state:
    if os.path.exists(MAPPING_FILE):
        st.session_state.master_df = pd.read_csv(MAPPING_FILE)
    else:
        st.session_state.master_df = pd.DataFrame(columns=['Portal_SKU', 'Master_SKU'])

# --- CORE LOGIC FUNCTIONS ---
def get_attributes(sku_text):
    sku_text = str(sku_text).upper()
    sizes = ['S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL', '6XL', '7XL', '8XL']
    found_size = next((s for s in sizes if re.search(rf'\b{s}\b', sku_text)), None)
    colors_list = ['BLACK', 'WHITE', 'BEIGE', 'BLUE', 'RED', 'GREEN', 'PINK', 'NAVY', 'MAROON', 'GREY', 'YELLOW']
    found_colors = [c for c in colors_list if c in sku_text]
    return found_size, found_colors

def smart_hybrid_matcher(new_sku, master_options):
    new_sku_str = str(new_sku).upper()
    found_size, found_colors = get_attributes(new_sku_str)
    filtered_options = master_options
    
    if found_size:
        filtered_options = [m for m in filtered_options if found_size in str(m).upper()]
    if found_colors:
        filtered_options = [m for m in filtered_options if all(color in str(m).upper() for color in found_colors)]

    if filtered_options:
        best_match = None
        highest_score = 0
        for opt in filtered_options:
            score = fuzz.token_set_ratio(new_sku_str, str(opt).upper())
            if score > highest_score:
                highest_score = score
                best_match = opt
        if highest_score > 75:
            return best_match, f"{highest_score}% (Attr Match)"
            
    return "Select Manually", "No Match"

# --- SIDEBAR: MASTER INVENTORY MANAGEMENT ---
with st.sidebar:
    st.header("📦 Master Inventory")
    
    # Option 1: Manual Single Entry
    with st.expander("Add Single SKU"):
        new_m_sku = st.text_input("Master SKU Name")
        if st.button("Add Single"):
            if new_m_sku:
                new_m_sku = new_m_sku.strip().upper()
                if new_m_sku not in st.session_state.master_df['Master_SKU'].unique():
                    new_row = pd.DataFrame({'Portal_SKU': [None], 'Master_SKU': [new_m_sku]})
                    st.session_state.master_df = pd.concat([st.session_state.master_df, new_row], ignore_index=True)
                    st.session_state.master_df.to_csv(MAPPING_FILE, index=False)
                    st.success("Added!")
                else: st.warning("Exists!")

    st.divider()

    # Option 2: Bulk Upload Master SKUs (NEW FEATURE)
    with st.expander("Bulk Upload Master List"):
        st.write("Upload CSV/Excel with a column named **'Master_SKU'**")
        master_file = st.file_uploader("Upload Master File", type=['csv', 'xlsx'])
        if master_file:
            if master_file.name.endswith('.csv'):
                bulk_df = pd.read_csv(master_file)
            else:
                bulk_df = pd.read_excel(master_file)
            
            # Check for column
            target_col = next((c for c in bulk_df.columns if 'master' in c.lower()), None)
            
            if target_col and st.button("Import All SKUs"):
                new_skus = bulk_df[target_col].dropna().unique()
                existing_skus = st.session_state.master_df['Master_SKU'].unique()
                
                to_add_list = [s.strip().upper() for s in new_skus if s.strip().upper() not in existing_skus]
                
                if to_add_list:
                    new_rows = pd.DataFrame({'Portal_SKU': [None]*len(to_add_list), 'Master_SKU': to_add_list})
                    st.session_state.master_df = pd.concat([st.session_state.master_df, new_rows], ignore_index=True)
                    st.session_state.master_df.to_csv(MAPPING_FILE, index=False)
                    st.success(f"Successfully added {len(to_add_list)} new Master SKUs!")
                    st.rerun()
                else:
                    st.info("No new SKUs found in file.")
            elif not target_col:
                st.error("Column 'Master_SKU' not found!")

    st.divider()
    if st.button("Clear Mapping Database"):
        if os.path.exists(MAPPING_FILE):
            os.remove(MAPPING_FILE)
            st.session_state.master_df = pd.DataFrame(columns=['Portal_SKU', 'Master_SKU'])
            st.rerun()

# --- MAIN UI ---
st.title("🚀 Aavoni Smart Picklist PRO")

files = st.file_uploader("Upload Portal Orders (FK, Meesho, Myntra)", type="csv", accept_multiple_files=True)

if files:
    orders_list = []
    for f in files:
        df = pd.read_csv(f)
        cols = {c.lower().replace(" ", "_"): c for c in df.columns}
        s_col = next((cols[k] for k in ['sku', 'seller_sku', 'product_id'] if k in cols), None)
        q_col = next((cols[k] for k in ['quantity', 'qty', 'item_qty'] if k in cols), None)
        
        if s_col:
            t_df = pd.DataFrame()
            t_df['Portal_SKU'] = df[s_col].astype(str)
            t_df['Qty'] = pd.to_numeric(df[q_col], errors='coerce').fillna(1) if q_col else 1
            orders_list.append(t_df)

    if orders_list:
        combined = pd.concat(orders_list, ignore_index=True)
        unique_skus = combined['Portal_SKU'].unique()
        
        # 1. Check Database (Exact Match)
        db_mapped = st.session_state.master_df.dropna(subset=['Portal_SKU'])
        mapped_dict = dict(zip(db_mapped['Portal_SKU'], db_mapped['Master_SKU']))
        
        unmapped = [s for s in unique_skus if s not in mapped_dict]

        if unmapped:
            st.subheader("🔍 Map New Portal SKUs")
            m_options = sorted(st.session_state.master_df['Master_SKU'].dropna().unique().tolist())
            
            if not m_options:
                st.error("Sidebar mein pehle Master SKUs upload karein!")
            else:
                review_data = []
                for s in unmapped:
                    sugg, info = smart_hybrid_matcher(s, m_options)
                    review_data.append({"Confirm": False, "Portal SKU": s, "Master SKU": sugg, "Logic": info})
                
                edited = st.data_editor(pd.DataFrame(review_data), column_config={
                    "Confirm": st.column_config.CheckboxColumn(default=False),
                    "Master SKU": st.column_config.SelectboxColumn(options=m_options)
                }, disabled=["Portal SKU", "Logic"], hide_index=True)
                
                if st.button("Confirm & Save Mapping"):
                    to_save = edited[edited['Confirm'] == True]
                    if not to_save.empty:
                        new_entries = to_save[['Portal SKU', 'Master SKU']].rename(columns={'Portal SKU': 'Portal_SKU'})
                        st.session_state.master_df = pd.concat([st.session_state.master_df, new_entries], ignore_index=True)
                        st.session_state.master_df.to_csv(MAPPING_FILE, index=False)
                        st.rerun()
        
        # --- PICKLIST DISPLAY ---
        st.subheader("📋 Picklist Result")
        final_mapping = dict(zip(st.session_state.master_df['Portal_SKU'], st.session_state.master_df['Master_SKU']))
        combined['Master_SKU'] = combined['Portal_SKU'].map(final_mapping)
        
        ready = combined.dropna(subset=['Master_SKU'])
        if not ready.empty:
            summary = ready.groupby('Master_SKU')['Qty'].sum().reset_index().sort_values('Qty', ascending=False)
            c1, c2 = st.columns([3, 1])
            with c1: st.table(summary)
            with c2:
                st.metric("Total Items", int(summary['Qty'].sum()))
                st.download_button("Download CSV", summary.to_csv(index=False).encode('utf-8'), "Aavoni_Picklist.csv")
        else:
            st.info("Pehle portal SKUs ko Master SKU se link (map) karein.")
