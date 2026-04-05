import streamlit as st
import pandas as pd
from thefuzz import process
import re
import os

# --- PAGE SETUP ---
st.set_page_config(page_title="Aavoni Hybrid Picklist Pro", layout="wide")

MAPPING_FILE = "master_mapping.csv"

# Session State for Mapping Data
if 'master_df' not in st.session_state:
    if os.path.exists(MAPPING_FILE):
        st.session_state.master_df = pd.read_csv(MAPPING_FILE)
    else:
        st.session_state.master_df = pd.DataFrame(columns=['Portal_SKU', 'Master_SKU'])

# --- HYBRID SUGGESTION ENGINE ---
def hybrid_sku_matcher(new_sku, master_options):
    """
    Step 1: Extract Size and Color.
    Step 2: Filter Master list for Hard Match.
    Step 3: Fuzzy Match only on filtered list.
    """
    new_sku = str(new_sku).upper()
    
    # 1. Size Extraction (Add more if needed)
    sizes = ['S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL', '6XL', '7XL', '8XL']
    found_size = next((s for s in sizes if re.search(rf'\b{s}\b', new_sku)), None)
    
    # 2. Color Extraction (Add your main colors here)
    colors = ['BLACK', 'WHITE', 'BLUE', 'RED', 'GREEN', 'PINK', 'YELLOW', 'NAVY', 'MAROON', 'GREY']
    found_color = next((c for c in colors if c in new_sku), None)

    # 3. Filtering
    filtered_options = master_options
    if found_size:
        filtered_options = [m for m in filtered_options if found_size in str(m).upper()]
    if found_color:
        filtered_options = [m for m in filtered_options if found_color in str(m).upper()]

    # 4. Fuzzy Match
    if filtered_options:
        suggested, score = process.extractOne(new_sku, filtered_options)
        if score > 80: # 80% confidence threshold
            return suggested, f"{score}% (Smart Match)"
            
    return "Select Manually", "0% (No Match)"

# --- SIDEBAR: NEW MASTER SKU ---
with st.sidebar:
    st.header("📦 Inventory Setup")
    new_m_sku = st.text_input("Add New Master SKU", placeholder="e.g. PANT-WHITE-7XL")
    if st.button("Add to Master"):
        if new_m_sku:
            new_m_sku = new_m_sku.strip().upper()
            if new_m_sku not in st.session_state.master_df['Master_SKU'].unique():
                new_row = pd.DataFrame({'Portal_SKU': [None], 'Master_SKU': [new_m_sku]})
                st.session_state.master_df = pd.concat([st.session_state.master_df, new_row], ignore_index=True)
                st.session_state.master_df.to_csv(MAPPING_FILE, index=False)
                st.success(f"Added {new_m_sku}")
            else:
                st.warning("Already Exists!")

# --- MAIN UI ---
st.title("🚀 Aavoni Hybrid Smart Picklist")

uploaded_files = st.file_uploader("Upload Portal CSVs", type="csv", accept_multiple_files=True)

if uploaded_files:
    all_orders = []
    for file in uploaded_files:
        df = pd.read_csv(file)
        # Basic standardization
        cols = {c.lower().replace(" ", "_"): c for c in df.columns}
        sku_col = next((cols[k] for k in ['sku', 'seller_sku', 'product_id'] if k in cols), None)
        qty_col = next((cols[k] for k in ['quantity', 'qty', 'item_qty'] if k in cols), None)
        
        if sku_col:
            temp_df = pd.DataFrame()
            temp_df['Portal_SKU'] = df[sku_col].astype(str)
            temp_df['Qty'] = df[qty_col] if qty_col else 1
            all_orders.append(temp_df)

    if all_orders:
        combined_df = pd.concat(all_orders, ignore_index=True)
        unique_portal_skus = combined_df['Portal_SKU'].unique()
        
        mapped_list = st.session_state.master_df['Portal_SKU'].dropna().unique().tolist()
        unmapped_skus = [sku for sku in unique_portal_skus if sku not in mapped_list]

        if unmapped_skus:
            st.subheader("🔍 Review New SKU Mappings")
            master_options = sorted(st.session_state.master_df['Master_SKU'].dropna().unique().tolist())
            
            mapping_data = []
            for sku in unmapped_skus:
                suggested, confidence = hybrid_sku_matcher(sku, master_options)
                mapping_data.append({
                    "Confirm": False,  # Safety: Must manually tick
                    "Portal SKU (New)": sku,
                    "Master SKU Selection": suggested,
                    "Confidence": confidence
                })
            
            edited_df = st.data_editor(
                pd.DataFrame(mapping_data),
                column_config={
                    "Confirm": st.column_config.CheckboxColumn(default=False),
                    "Master SKU Selection": st.column_config.SelectboxColumn(options=master_options)
                },
                disabled=["Portal SKU (New)", "Confidence"],
                hide_index=True
            )
            
            if st.button("Save & Link SKUs"):
                confirmed = edited_df[edited_df['Confirm'] == True]
                if not confirmed.empty:
                    new_mappings = confirmed[['Portal SKU (New)', 'Master SKU Selection']].rename(
                        columns={'Portal SKU (New)': 'Portal_SKU', 'Master SKU Selection': 'Master_SKU'}
                    )
                    st.session_state.master_df = pd.concat([st.session_state.master_df, new_mappings], ignore_index=True)
                    st.session_state.master_df.to_csv(MAPPING_FILE, index=False)
                    st.rerun()
                else:
                    st.error("Please tick 'Confirm' for the rows you want to save.")
        
        else:
            # --- FINAL OUTPUT ---
            st.subheader("📋 Consolidated Picklist")
            final_merged = pd.merge(combined_df, st.session_state.master_df, on='Portal_SKU', how='left')
            summary = final_merged.groupby('Master_SKU')['Qty'].sum().reset_index().sort_values('Qty', ascending=False)
            
            st.dataframe(summary, use_container_width=True)
            st.download_button("Download CSV", summary.to_csv(index=False).encode('utf-8'), "Aavoni_Picklist.csv")
