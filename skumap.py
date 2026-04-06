import streamlit as st
import pandas as pd
import re
import io
from datetime import datetime, date

# --- 1. CONFIG & DB ---
st.set_page_config(page_title="Aavoni Seller Suite", layout="wide", page_icon="👗")

try:
    from supabase import create_client, Client
    url, key = st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]
    supabase = create_client(url, key)
except:
    st.error("Check Supabase Secrets!")
    st.stop()

if 'user' not in st.session_state: st.session_state.user = None

# --- 2. UTILS ---
def get_design_pattern(master_sku):
    sku = str(master_sku).upper().strip()
    sku = re.sub(r'[-_](S|M|L|XL|XXL|\d*XL|FREE|SMALL|LARGE)$', '', sku)
    return sku.strip('-_ ')

def load_all_data(u_id):
    m_res = supabase.table("sku_mapping").select("portal_sku, master_sku").eq("user_id", u_id).execute()
    i_res = supabase.table("master_inventory").select("master_sku").eq("user_id", u_id).execute()
    c_res = supabase.table("design_costing").select("design_pattern, landed_cost").eq("user_id", u_id).execute()
    m_dict = {item['portal_sku']: item['master_sku'] for item in m_res.data} if m_res.data else {}
    c_dict = {item['design_pattern']: item['landed_cost'] for item in c_res.data} if c_res.data else {}
    m_list = [i['master_sku'].upper() for i in i_res.data] if i_res.data else []
    return m_dict, c_dict, m_list

# --- 3. AUTH ---
if st.session_state.user is None:
    st.title("🚀 Aavoni Seller Suite")
    with st.sidebar:
        mode = st.radio("Action", ["Login", "Signup"])
        with st.form("auth"):
            e, p = st.text_input("Email"), st.text_input("Password", type="password")
            if st.form_submit_button("Submit"):
                try:
                    res = (supabase.auth.sign_in_with_password if mode=="Login" else supabase.auth.sign_up)({"email":e, "password":p})
                    if res.session: st.session_state.user = res.user; st.rerun()
                except Exception as ex: st.error(f"Error: {ex}")
else:
    u_id = st.session_state.user.id
    mapping_dict, costing_dict, master_options = load_all_data(u_id)
    
    with st.sidebar:
        st.header("📊 Product Costing")
        std_base = st.number_input("Standard Pant Cost (PT/PL)", value=165)
        hf_base = st.number_input("HF Series Cost", value=110)
        if st.button("Logout"): 
            supabase.auth.sign_out(); st.session_state.user = None; st.rerun()

    tabs = st.tabs(["🏠 Home", "📦 Picklist", "💰 Costing", "📊 Flipkart P&L", "👗 Myntra"])

    # --- TABS 0, 1, 2 (Shared Logic) ---
    with tabs[0]: st.title("Aavoni Dashboard"); st.write("Select a tab to begin.")
    with tabs[1]: st.header("Picklist Generator") # Standard Picklist Logic
    with tabs[2]: st.header("Costing Manager") # Standard Costing Logic

    # --- TAB 3: FLIPKART (YOUR MODIFIED SCRIPT) ---
    with tabs[3]:
        st.header("📊 Flipkart Orders P&L")
        uploaded_file = st.file_uploader("Upload Flipkart Excel (.xlsx)", type=["xlsx"], key="fk_pnl_unique")

        if uploaded_file:
            try:
                excel_data = pd.ExcelFile(uploaded_file)
                target_sheet = next((s for s in excel_data.sheet_names if "Orders P&L" in s), excel_data.sheet_names[0])
                df = pd.read_excel(uploaded_file, sheet_name=target_sheet)
                df.columns = [str(c).strip() for c in df.columns]

                # Mapping columns from your script
                order_id_col, sku_col, units_col = "Order ID", "SKU Name", "Net Units"
                settlement_col, status_col, gross_units_col = "Bank Settlement [Projected] (INR)", "Order Status", "Gross Units"

                if sku_col in df.columns and settlement_col in df.columns:
                    df[units_col] = pd.to_numeric(df[units_col], errors='coerce').fillna(0).astype(int)
                    df[settlement_col] = pd.to_numeric(df[settlement_col], errors='coerce').fillna(0)
                    g_cols = [c for c in df.columns if 'Gross Units' in c]
                    df[gross_units_col] = pd.to_numeric(df[g_cols[0]], errors='coerce').fillna(0).astype(int) if g_cols else df[units_col]

                    # Integrated Categorization Logic (Using Supabase Costs if available)
                    def get_cat_data(sku_name):
                        sku = str(sku_name).upper()
                        # Step 1: Check Database mapping first
                        m_sku = mapping_dict.get(sku, sku)
                        pat = get_design_pattern(m_sku)
                        
                        # Step 2: If we have a saved cost in Supabase, use it
                        if pat in costing_dict:
                            return "DB Costed", costing_dict[pat]
                        
                        # Step 3: Fallback to your original logic
                        is_hf = sku.startswith("HF")
                        if "3CBO" in sku: return "Std 3CBO", (std_base * 3)
                        if "CBO" in sku:
                            return ("HF Combo", hf_base * 2) if is_hf else ("Std Combo", std_base * 2)
                        return ("HF Single", hf_base) if is_hf else ("Std Single", std_base)

                    res_cat = df[sku_col].apply(get_cat_data)
                    df['Category'] = [x[0] for x in res_cat]
                    df['Unit_Cost'] = [x[1] for x in res_cat]
                    
                    df['Net_Profit'] = df.apply(lambda x: x[settlement_col] - (x[units_col] * x['Unit_Cost']) if x[units_col] > 0 else x[settlement_col], axis=1)

                    # KPI Metrics
                    t_pay, t_prof = int(df[settlement_col].sum()), int(df['Net_Profit'].sum())
                    t_gross, t_net = int(df[gross_units_col].sum()), int(df[units_col].sum())
                    
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Settlement", f"₹{t_pay:,}")
                    m2.metric("Profit", f"₹{t_prof:,}", delta=f"{(t_prof/t_pay*100 if t_pay>0 else 0):.1f}% Margin")
                    m3.metric("Return Rate", f"{(t_gross-t_net)/t_gross*100 if t_gross>0 else 0:.1f}%")
                    m4.metric("Net Units", f"{t_net:,}")

                    st.subheader("⚠️ Loss-making Orders")
                    loss_df = df[df['Net_Profit'] < 0][[order_id_col, sku_col, status_col, settlement_col, 'Net_Profit']].copy()
                    st.dataframe(loss_df.sort_values('Net_Profit'), use_container_width=True, hide_index=True)

                    st.subheader("🔎 All Orders Breakdown")
                    st.dataframe(df[[order_id_col, sku_col, 'Category', status_col, units_col, settlement_col, 'Net_Profit']], use_container_width=True, hide_index=True)

            except Exception as e: st.error(f"Error: {e}")

    # --- TAB 4: MYNTRA ---
    with tabs[4]: st.header("Myntra Smart P&L") # Myntra Logic
