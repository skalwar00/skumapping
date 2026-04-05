import streamlit as st
import pandas as pd
from thefuzz import process

# 1. Mock Data (Aap isse apni CSV se load karenge)
if 'master_mapping' not in st.session_state:
    st.session_state.master_mapping = pd.DataFrame({
        'Portal_SKU': ['fk-blue-pala', 'msh-cotton-red'],
        'Master_SKU': ['AV-PL-BLU-M', 'AV-KRT-RED-L']
    })

st.title("Aavoni Smart SKU Mapper")

# 2. File Upload
uploaded_file = st.file_uploader("Upload Portal Order File (CSV)", type="csv")

if uploaded_file:
    df_orders = pd.read_csv(uploaded_file)
    unique_portal_skus = df_orders['SKU'].unique()
    
    # 3. Identify New (Unmapped) SKUs
    existing_portal_skus = st.session_state.master_mapping['Portal_SKU'].tolist()
    new_skus = [sku for sku in unique_portal_skus if sku not in existing_portal_skus]

    if new_skus:
        st.warning(f"Found {len(new_skus)} new SKUs. Please review and confirm:")
        
        # Suggestions list banane ke liye
        suggestions_data = []
        master_list = st.session_state.master_mapping['Master_SKU'].unique().tolist()

        for sku in new_skus:
            # Fuzzy matching to suggest best Master SKU
            suggested_master, score = process.extractOne(sku, master_list)
            suggestions_data.append({
                "Select": True,  # Default selection
                "Portal SKU (New)": sku,
                "Suggested Master SKU": suggested_master,
                "Match Score": f"{score}%"
            })

        # 4. Interactive Table with Selection/Deselection
        # st.data_editor se user toggle kar sakta hai aur manually change bhi kar sakta hai
        edited_df = st.data_editor(
            pd.DataFrame(suggestions_data),
            column_config={
                "Select": st.column_config.CheckboxColumn(default=True),
                "Suggested Master SKU": st.column_config.SelectboxColumn(options=master_list)
            },
            disabled=["Portal SKU (New)", "Match Score"],
            hide_index=True
        )

        # 5. Bulk Confirmation Button
        if st.button("Confirm & Update Master List"):
            confirmed_mappings = edited_df[edited_df['Select'] == True]
            
            if not confirmed_mappings.empty:
                new_rows = confirmed_mappings[['Portal SKU (New)', 'Suggested Master SKU']].rename(
                    columns={'Portal SKU (New)': 'Portal_SKU', 'Suggested Master SKU': 'Master_SKU'}
                )
                
                # Update Session State (In reality, save to CSV here)
                st.session_state.master_mapping = pd.concat([st.session_state.master_mapping, new_rows], ignore_index=True)
                st.success(f"Successfully mapped {len(confirmed_mappings)} SKUs!")
                st.rerun() # Refresh to process orders with new mapping
            else:
                st.error("No SKUs selected for mapping.")
    else:
        st.success("All SKUs are already mapped. Generating Picklist...")
        # Yahan aapka standard picklist generation logic chalega
