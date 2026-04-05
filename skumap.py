import streamlit as st
import pandas as pd
from thefuzz import process, fuzz
import re
import os

# --- PAGE SETUP ---
st.set_page_config(page_title="Aavoni Smart Picklist Pro", layout="wide")

MAPPING_FILE = "master_mapping.csv"

# Session State for Mapping Data
if 'master_df' not in st.session_state:
    if os.path.exists(MAPPING_FILE):
        st.session_state.master_df = pd.read_csv(MAPPING_FILE)
    else:
        st.session_state.master_df = pd.DataFrame(columns=['Portal_SKU', 'Master_SKU'])

# --- HELPER FUNCTIONS ---

def clean_sku(sku_text):
    """Spaces, Hyphens, and Underscores ko remove karta hai matching ke liye"""
    if pd.isna(sku_text): 
        return ""
    cleaned = re.sub(r'[-_\s]+', '', str(sku_text).upper())
    return cleaned

def hybrid_sku_matcher(new_sku, master_options):
    """Size/Color Hard Filter + Fuzzy match on cleaned strings"""
    new_sku_str = str(new_sku).upper()
    cleaned_new = clean_sku(new_sku)
    
    # 1. Size Extraction
    sizes = ['S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL', '6XL', '7XL', '8XL']
    found_size = next((s for s in sizes if re.search(rf'\b{s}\b', new_sku_str)), None)
    
    # 2. Color Extraction
    colors = ['BLACK', 'WHITE', 'BLUE', 'RED', 'GREEN', 'PINK', 'YELLOW', 'NAVY', 'MAROON', 'GREY']
    found_color = next((c for c in colors if c in new_sku_str), None)

    # 3. Filtering Master List
    filtered_options = master_options
    
    if found_size:
        filtered_options = [m for m in filtered_options if re.search(rf'\b{found_size}\b', str(m).upper())]
    
    if found_color:
        filtered_options = [m for m in filtered_options if found_color in str(m).upper()]

    # 4. Final Smart Match
    if filtered_options:
        best_match = None
        highest_score = 0
        
        for m_option in filtered_options:
            m_cleaned = clean_sku(m_option)
            score = fuzz.ratio(cleaned_new, m_cleaned)
            if score > highest_score:
                highest_score = score
                best_match = m_option
        
        if highest_score > 85:
            return best_match, f"{highest_score}% (Strict Match)"
            
    return "Select Manually", "0% (Mismatch)"

# --- SIDEBAR ---
with st.sidebar:
    st.header("📦 Master Inventory")
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
    
    st.divider()
    if st.button("Clear All Mappings"):
        if os.path.exists(MAPPING_FILE):
            os.remove(MAPPING_FILE)
            st.session_state.master_df = pd.DataFrame(columns=['Portal_SKU', 'Master_SKU'])
            st.rerun()

# --- MAIN UI ---
st.title("🚀 Aavoni Smart Picklist PRO")

uploaded_files = st.file_uploader("Upload CSV Files", type="csv", accept_multiple_files=True)

if uploaded_files:
    all_orders = []
    for file in uploaded_files:
        df = pd.read_csv(file)
        cols = {c.lower().replace(" ", "_"): c for c in df.columns}
        
        sku_col = next((cols[k] for k in ['sku', 'seller_sku', 'product_id', 'item_id'] if k in cols), None)
        qty_col = next((cols[k] for k in ['quantity', 'qty', 'item_qty', 'order_qty'] if k in cols), None)
        
        if sku_col:
            temp_df = pd.DataFrame()
            temp_df['Portal_SKU'] = df[sku_col].astype(str)
            temp_df['Qty'] = pd.to_numeric(df[qty_col], errors='coerce').fillna(1) if qty_col else 1
            temp_df['Source'] = file.name
            all_orders.append(temp_df)

    if all_orders:
        combined_df = pd.concat(all_orders, ignore_index=True)
        unique_portal_skus = combined_df['Portal_SKU'].unique()
        
        mapped_list = st.session_state.master_df['Portal_SKU'].dropna().unique().tolist()
        unmapped_skus = [sku for sku in unique_portal_skus if sku not in mapped_list]

        if unmapped_skus:
            st.subheader("🔍 Review & Link New SKUs")
            master_options = sorted(st.session_state.master_df['Master_SKU'].dropna().unique().tolist())
            
            if not master_options:
                st.error("Sidebar se Master SKU add karein!")
            else:
                mapping_table_data = []
                for sku in unmapped_skus:
                    suggested, conf = hybrid_sku_matcher(sku, master_options)
                    mapping_table_data.append({
                        "Confirm": False,
                        "Portal SKU (Found)": sku,
                        "Master SKU Selection": suggested,
                        "Match Detail": conf
                    })
                
                edited_df = st.data_editor(
                    pd.DataFrame(mapping_table_data),
                    column_config={
                        "Confirm": st.column_config.CheckboxColumn(default=False),
                        "Master SKU Selection": st.column_config.SelectboxColumn(options=master_options)
                    },
                    disabled=["Portal SKU (Found)", "Match Detail"],
                    hide_index=True,
                    key="mapping_editor"
                )
                
                if st.button("Save Selected Mappings"):
                    confirmed = edited_df[edited_df['Confirm'] == True]
                    if not confirmed.empty:
                        new_links = confirmed[['Portal SKU (Found)', 'Master SKU Selection']].rename(
                            columns={'Portal SKU (Found)': 'Portal_SKU', 'Master SKU Selection': 'Master_SKU'}
                        )
                        st.session_state.master_df = pd.concat([st.session_state.master_df, new_links], ignore_index=True)
                        st.session_state.master_df.to_csv(MAPPING_FILE, index=False)
                        st.success("Mappings Saved!")
                        st.rerun()
                    else:
                        st.warning("Please tick 'Confirm' to save.")
        
        else:
            # --- FINAL OUTPUT SECTION ---
            st.subheader("📋 Consolidated Picklist")
            final_merged = pd.merge(combined_df, st.session_state.master_df, on='Portal_SKU', how='left')
            summary = final_merged.groupby('Master_SKU')['Qty'].sum().reset_index().sort_values('Qty', ascending=False)
            
            col_res, col_metric = st.columns([3, 1])
            with col_res:
                st.table(summary)
            
            with col_metric:
                total_qty = int(summary['Qty'].sum())
                st.metric("Total Pcs", total_qty)
                csv_data = summary.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Download CSV", csv_data, "Picklist.csv", "text/csv")

            with st.expander("Detailed View"):
                st.dataframe(final_merged[['Source', 'Portal_SKU', 'Master_SKU', 'Qty']])
