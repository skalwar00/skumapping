import streamlit as st
import pandas as pd
from thefuzz import fuzz
import re
import os

# --- PAGE SETUP ---
st.set_page_config(page_title="Aavoni Smart Picklist Pro", layout="wide")

MAPPING_FILE = "master_mapping.csv"

if 'master_df' not in st.session_state:
    if os.path.exists(MAPPING_FILE):
        st.session_state.master_df = pd.read_csv(MAPPING_FILE)
    else:
        st.session_state.master_df = pd.DataFrame(columns=['Portal_SKU', 'Master_SKU'])

# --- CORE LOGIC FUNCTIONS ---

def get_attributes(sku_text):
    sku_text = str(sku_text).upper()
    sizes = ['S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL', '6XL', '7XL', '8XL', '10XL']
    found_size = next((s for s in sizes if re.search(rf'\b{s}\b', sku_text)), None)
    colors_list = ['BLACK', 'WHITE', 'BEIGE', 'BLUE', 'RED', 'GREEN', 'PINK', 'NAVY', 'MAROON', 'GREY', 'TEAL']
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
        
        if highest_score > 65:
            return best_match, highest_score # Ab hum score bhi return karenge
            
    return "Select Manually", 0

# --- SIDEBAR: MASTER INVENTORY ---
with st.sidebar:
    st.header("📦 Master Inventory")
    
    with st.expander("Bulk Upload Master List"):
        master_file = st.file_uploader("Upload Master CSV/Excel", type=['csv', 'xlsx'])
        if master_file and st.button("Import Master SKUs"):
            bulk_df = pd.read_csv(master_file) if master_file.name.endswith('.csv') else pd.read_excel(master_file)
            target_col = next((c for c in bulk_df.columns if 'master' in c.lower()), None)
            if target_col:
                new_skus = [str(s).strip().upper() for s in bulk_df[target_col].dropna().unique()]
                existing = st.session_state.master_df['Master_SKU'].unique()
                to_add = [s for s in new_skus if s not in existing]
                if to_add:
                    new_rows = pd.DataFrame({'Portal_SKU': [None]*len(to_add), 'Master_SKU': to_add})
                    st.session_state.master_df = pd.concat([st.session_state.master_df, new_rows], ignore_index=True)
                    st.session_state.master_df.to_csv(MAPPING_FILE, index=False)
                    st.success(f"Added {len(to_add)} Master SKUs!")
                    st.rerun()

# --- MAIN UI ---
st.title("🚀 Aavoni Smart Picklist PRO")

files = st.file_uploader("Upload Portal Orders", type="csv", accept_multiple_files=True)

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
        
        db_mapped = st.session_state.master_df.dropna(subset=['Portal_SKU'])
        mapped_dict = dict(zip(db_mapped['Portal_SKU'], db_mapped['Master_SKU']))
        
        # 1. PEHLE: Mapped Items Picklist
        st.subheader("📋 Consolidated Picklist (Ready)")
        combined['Master_SKU'] = combined['Portal_SKU'].map(mapped_dict)
        ready_to_pick = combined.dropna(subset=['Master_SKU'])
        
        if not ready_to_pick.empty:
            summary = ready_to_pick.groupby('Master_SKU')['Qty'].sum().reset_index().sort_values('Qty', ascending=False)
            c1, c2 = st.columns([3, 1])
            with c1: st.table(summary)
            with c2:
                st.metric("Total Pcs", int(summary['Qty'].sum()))
                st.download_button("📥 Download Picklist", summary.to_csv(index=False).encode('utf-8'), "Picklist.csv")

        st.divider()

        # 2. BAAD MEIN: Unmapped Items with Auto-Select
        unmapped = [s for s in unique_skus if s not in mapped_dict]
        if unmapped:
            st.subheader("🔍 Review New Mappings")
            st.info("💡 90% se zyada match hone wale SKUs auto-confirm ho gaye hain.")
            
            m_options = sorted(st.session_state.master_df['Master_SKU'].dropna().unique().tolist())
            if m_options:
                review_data = []
                for s in unmapped:
                    sugg, score = smart_hybrid_matcher(s, m_options)
                    # AUTO SELECT LOGIC: Agar score >= 90 hai toh True, varna False
                    is_auto_confirm = True if score >= 90 else False
                    review_data.append({
                        "Confirm": is_auto_confirm, 
                        "Portal SKU": s, 
                        "Master SKU": sugg, 
                        "Match %": f"{score}%"
                    })
                
                edited = st.data_editor(pd.DataFrame(review_data), column_config={
                    "Confirm": st.column_config.CheckboxColumn(default=False),
                    "Master SKU": st.column_config.SelectboxColumn(options=m_options)
                }, disabled=["Portal SKU", "Match %"], hide_index=True, key="auto_mapper")
                
                if st.button("Confirm & Update Picklist"):
                    to_save = edited[edited['Confirm'] == True]
                    if not to_save.empty:
                        new_entries = to_save[['Portal SKU', 'Master SKU']].rename(columns={'Portal SKU': 'Portal_SKU'})
                        st.session_state.master_df = pd.concat([st.session_state.master_df, new_entries], ignore_index=True)
                        st.session_state.master_df.to_csv(MAPPING_FILE, index=False)
                        st.success("Saved! Refreshing...")
                        st.rerun()
