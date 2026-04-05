import streamlit as st
import pandas as pd
from thefuzz import fuzz
import re
import os

# --- PAGE SETUP ---
st.set_page_config(page_title="Aavoni Pro Multi-Channel Tool", layout="wide")

MAPPING_FILE = "master_mapping.csv"

# Load Master Mapping (Permanent Database)
if 'master_df' not in st.session_state:
    if os.path.exists(MAPPING_FILE):
        st.session_state.master_df = pd.read_csv(MAPPING_FILE)
    else:
        st.session_state.master_df = pd.DataFrame(columns=['Portal_SKU', 'Master_SKU'])

# --- CORE LOGIC FUNCTIONS ---

def get_attributes(sku_text):
    """SKU se Size aur saare Colors extract karta hai"""
    sku_text = str(sku_text).upper()
    
    # 1. Size Extraction
    sizes = ['S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL', '6XL', '7XL', '8XL']
    found_size = next((s for s in sizes if re.search(rf'\b{s}\b', sku_text)), None)
    
    # 2. Color Extraction (Multiple Colors support for Combos)
    colors_list = ['BLACK', 'WHITE', 'BEIGE', 'BLUE', 'RED', 'GREEN', 'PINK', 'NAVY', 'MAROON', 'GREY', 'YELLOW']
    found_colors = [c for c in colors_list if c in sku_text]
    
    return found_size, found_colors

def smart_hybrid_matcher(new_sku, master_options):
    """
    Step 1: Size/Color Filter (Strict)
    Step 2: Fuzzy Match on filtered results
    """
    new_sku_str = str(new_sku).upper()
    found_size, found_colors = get_attributes(new_sku_str)
    
    filtered_options = master_options
    
    # Size Priority: Agar 7XL hai toh sirf 7XL dikhao
    if found_size:
        filtered_options = [m for m in filtered_options if found_size in str(m).upper()]
    
    # Color/Combo Priority: Saare colors match hone chahiye (e.g., Beige AND Black)
    if found_colors:
        filtered_options = [
            m for m in filtered_options 
            if all(color in str(m).upper() for color in found_colors)
        ]

    # Fuzzy match only on the highly relevant list
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

# --- SIDEBAR ---
with st.sidebar:
    st.header("📦 Master Inventory")
    new_m_sku = st.text_input("New Master SKU (e.g. PANT-BEIGE-BLACK-7XL)")
    if st.button("Add to Master"):
        if new_m_sku:
            new_m_sku = new_m_sku.strip().upper()
            if new_m_sku not in st.session_state.master_df['Master_SKU'].unique():
                new_row = pd.DataFrame({'Portal_SKU': [None], 'Master_SKU': [new_m_sku]})
                st.session_state.master_df = pd.concat([st.session_state.master_df, new_row], ignore_index=True)
                st.session_state.master_df.to_csv(MAPPING_FILE, index=False)
                st.success(f"Added {new_m_sku}")
            else: st.warning("Exists!")

# --- MAIN UI ---
st.title("🚀 Aavoni Smart Picklist PRO")

files = st.file_uploader("Upload Portal CSVs", type="csv", accept_multiple_files=True)

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
        
        # --- CASCADING LOGIC START ---
        # 1. Check Database first (Strict Match)
        db_mapped = st.session_state.master_df.dropna(subset=['Portal_SKU'])
        mapped_dict = dict(zip(db_mapped['Portal_SKU'], db_mapped['Master_SKU']))
        
        unmapped = [s for s in unique_skus if s not in mapped_dict]

        if unmapped:
            st.subheader("🔍 Review New SKU Mappings")
            m_options = sorted(st.session_state.master_df['Master_SKU'].dropna().unique().tolist())
            
            review_data = []
            for s in unmapped:
                sugg, info = smart_hybrid_matcher(s, m_options)
                review_data.append({"Confirm": False, "Portal SKU": s, "Master SKU": sugg, "Logic": info})
            
            edited = st.data_editor(pd.DataFrame(review_data), column_config={
                "Confirm": st.column_config.CheckboxColumn(default=False),
                "Master SKU": st.column_config.SelectboxColumn(options=m_options)
            }, disabled=["Portal SKU", "Logic"], hide_index=True)
            
            if st.button("Confirm & Save to Database"):
                to_save = edited[edited['Confirm'] == True]
                if not to_save.empty:
                    new_entries = to_save[['Portal SKU', 'Master SKU']].rename(columns={'Portal SKU': 'Portal_SKU'})
                    st.session_state.master_df = pd.concat([st.session_state.master_df, new_entries], ignore_index=True)
                    st.session_state.master_df.to_csv(MAPPING_FILE, index=False)
                    st.rerun()
        
        # --- FINAL PICKLIST (Consolidated) ---
        st.subheader("📋 Consolidated Picklist")
        # Apply Mappings
        final_mapping = dict(zip(st.session_state.master_df['Portal_SKU'], st.session_state.master_df['Master_SKU']))
        combined['Master_SKU'] = combined['Portal_SKU'].map(final_mapping)
        
        # Display only fully mapped items
        ready = combined.dropna(subset=['Master_SKU'])
        summary = ready.groupby('Master_SKU')['Qty'].sum().reset_index().sort_values('Qty', ascending=False)
        
        c1, c2 = st.columns([3, 1])
        with c1: st.table(summary)
        with c2:
            st.metric("Total Items", int(summary['Qty'].sum()))
            st.download_button("Download CSV", summary.to_csv(index=False).encode('utf-8'), "Aavoni_Picklist.csv")
