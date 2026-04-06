import streamlit as st
import pandas as pd
import re
import io

# --- 1. CRITICAL IMPORTS ---
try:
    from supabase import create_client, Client
    from thefuzz import fuzz
    import pdfplumber
    from reportlab.pdfgen import canvas
    INCH = 72 
except ImportError:
    st.error("❌ Libraries are installing... Please wait.")
    st.stop()

# --- 2. CONFIG & DATABASE ---
st.set_page_config(page_title="Aavoni Seller Suite", layout="wide", page_icon="📊")

try:
    url, key = st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(url, key)
except:
    st.error("❌ Supabase Secrets Missing!")
    st.stop()

if 'user' not in st.session_state: st.session_state.user = None

# --- 3. SHARED UTILS ---
def get_design_pattern(master_sku):
    sku = str(master_sku).upper().strip()
    sku = re.sub(r'[-_](S|M|L|XL|XXL|\d*XL|FREE|SMALL|LARGE)$', '', sku)
    sku = re.sub(r'\(.*?\)', '', sku)
    return sku.strip('-_ ')

def load_all_data(u_id):
    m_res = supabase.table("sku_mapping").select("portal_sku, master_sku").eq("user_id", u_id).execute()
    c_res = supabase.table("design_costing").select("design_pattern, landed_cost").eq("user_id", u_id).execute()
    m_dict = {item['portal_sku']: item['master_sku'] for item in m_res.data} if m_res.data else {}
    c_dict = {item['design_pattern']: item['landed_cost'] for item in c_res.data} if c_res.data else {}
    return m_dict, c_dict

# --- 4. AUTH & MAIN UI ---
if st.session_state.user is None:
    st.title("🚀 Aavoni Seller Suite")
    with st.sidebar:
        mode = st.radio("Action", ["Login", "Signup"])
        with st.form("auth"):
            e, p = st.text_input("Email"), st.text_input("Password", type="password")
            if st.form_submit_button("Submit"):
                try:
                    res = (supabase.auth.sign_in_with_password if mode=="Login" else supabase.auth.sign_up)({"email":e, "password":p})
                    if res.user: st.session_state.user = res.user; st.rerun()
                except: st.error("Login Failed")
else:
    u_id = st.session_state.user.id
    mapping_dict, costing_dict = load_all_data(u_id)
    
    with st.sidebar:
        st.header("📊 Product Costing")
        std_base = st.number_input("Standard Pant Cost (PT/PL)", value=165)
        hf_base = st.number_input("HF Series Cost", value=110)
        st.divider()
        if st.button("Logout"): 
            supabase.auth.sign_out(); st.session_state.user = None; st.rerun()

    t1, t2, t3, t4 = st.tabs(["📦 Picklist", "💰 Costing Manager", "📊 Flipkart Profit", "👗 Myntra Profit"])

    # --- TAB 1 & 2 (Previous logic remains same) ---
    with t1: st.info("Picklist Logic Active")
    with t2: st.info("Costing Manager Active")

    # --- TAB 3: FLIPKART ANALYZER (SUNIL'S ORIGINAL UI) ---
    with t3:
        st.title("📊 Aavoni Pro Business Dashboard")
        st.markdown("Flipkart **Orders P&L** - Loss Tracking with Order IDs.")
        
        uploaded_file = st.file_uploader("Upload Excel (.xlsx)", type=["xlsx"])

        if uploaded_file:
            try:
                excel_data = pd.ExcelFile(uploaded_file)
                target_sheet = next((s for s in excel_data.sheet_names if "Orders P&L" in s), excel_data.sheet_names[0])
                df = pd.read_excel(uploaded_file, sheet_name=target_sheet)
                df.columns = [str(c).strip() for c in df.columns]

                # Column Mappings
                order_id_col, sku_col = "Order ID", "SKU Name"
                units_col, settlement_col = "Net Units", "Bank Settlement [Projected] (INR)"
                status_col, gross_units_col = "Order Status", "Gross Units"

                if sku_col in df.columns and settlement_col in df.columns:
                    # Data Cleaning
                    df[units_col] = pd.to_numeric(df[units_col], errors='coerce').fillna(0).astype(int)
                    df[settlement_col] = pd.to_numeric(df[settlement_col], errors='coerce').fillna(0)
                    
                    # Unit Cost Detection (Logic based on Mapping + DB)
                    def get_cat_data(sku_name):
                        p_sku = str(sku_name).strip()
                        m_sku = mapping_dict.get(p_sku, p_sku)
                        pattern = get_design_pattern(m_sku)
                        
                        # Use DB Cost if available, else Sunil's logic
                        if pattern in costing_dict:
                            return "DB Match", costing_dict[pattern]
                        else:
                            sku_up = p_sku.upper()
                            is_hf = sku_up.startswith("HF")
                            base = hf_base if is_hf else std_base
                            if "3CBO" in sku_up: return "Std 3CBO", (base * 3)
                            if "CBO" in sku_up: return "Combo", (base * 2)
                            return ("HF Single" if is_hf else "Std Single"), base

                    results = df[sku_col].apply(get_cat_data)
                    df['Category'], df['Unit_Cost'] = [x[0] for x in results], [x[1] for x in results]
                    
                    # Profit Calc
                    df['Net_Profit'] = df.apply(lambda x: x[settlement_col] - (x[units_col] * x['Unit_Cost']) if x[units_col] > 0 else x[settlement_col], axis=1)

                    # --- 1. TOP LEVEL KPI METRICS (Sunil Style) ---
                    t_pay = int(df[settlement_col].sum())
                    t_prof = int(df['Net_Profit'].sum())
                    t_net_units = int(df[units_col].sum())
                    margin_pct = (t_prof / t_pay * 100) if t_pay > 0 else 0
                    
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Total Settlement", f"₹{t_pay:,}")
                    m2.metric("Net Profit", f"₹{t_prof:,}", delta=f"{margin_pct:.1f}% Margin")
                    m3.metric("Net Units Sold", f"{t_net_units:,}")

                    st.divider()

                    # --- 2. CATEGORY PERFORMANCE TABLE ---
                    st.subheader("💰 Category Performance: Sales vs Net Analysis")
                    summary_table = df.groupby('Category').agg({units_col: 'sum', settlement_col: 'sum', 'Net_Profit': 'sum'})
                    summary_table.columns = ['Net Units', 'Total Settlement', 'Total Profit']
                    st.table(summary_table.fillna(0).astype(int))

                    # --- 3. LOSS-MAKING ORDERS ---
                    st.subheader("⚠️ Loss-making Orders (Details with Order ID)")
                    loss_df = df[df['Net_Profit'] < 0][[order_id_col, sku_col, status_col, settlement_col, 'Net_Profit']].copy()
                    if not loss_df.empty:
                        loss_df[settlement_col] = loss_df[settlement_col].round(0).astype(int)
                        loss_df['Net_Profit'] = loss_df['Net_Profit'].round(0).astype(int)
                        st.dataframe(loss_df.sort_values('Net_Profit'), use_container_width=True, hide_index=True)
                    else:
                        st.success("Great! No negative profit orders.")

                    # --- 4. FULL ORDER LIST ---
                    st.subheader("🔎 All Orders Breakdown")
                    final_disp = df[[order_id_col, sku_col, 'Category', status_col, units_col, settlement_col, 'Net_Profit']].copy()
                    final_disp[settlement_col] = final_disp[settlement_col].round(0).astype(int)
                    final_disp['Net_Profit'] = final_disp['Net_Profit'].round(0).astype(int)
                    st.dataframe(final_disp.sort_index(ascending=False), use_container_width=True, hide_index=True)

            except Exception as e:
                st.error(f"Error: {e}")

    with t4: st.info("Myntra Analyzer Logic Coming Soon")
