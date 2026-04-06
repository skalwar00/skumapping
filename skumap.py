import streamlit as st
import pandas as pd
import re
import io

# --- 1. CRITICAL IMPORTS & CONFIG ---
try:
    from supabase import create_client, Client
    from thefuzz import fuzz
    import pdfplumber
    from reportlab.pdfgen import canvas
    INCH = 72 
except ImportError:
    st.error("❌ Libraries are installing... Please wait 1-2 minutes.")
    st.stop()

st.set_page_config(page_title="Aavoni Seller Suite", layout="wide", page_icon="📦")

# --- 2. DATABASE CONNECTION ---
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
    # Size patterns hatayein (PT001-BLACK-S -> PT001-BLACK)
    sku = re.sub(r'[-_](S|M|L|XL|XXL|\d*XL|FREE|SMALL|LARGE)$', '', sku)
    sku = re.sub(r'\(.*?\)', '', sku)
    return sku.strip('-_ ')

def load_all_data(u_id):
    m_res = supabase.table("sku_mapping").select("portal_sku, master_sku").eq("user_id", u_id).execute()
    c_res = supabase.table("design_costing").select("design_pattern, landed_cost").eq("user_id", u_id).execute()
    m_dict = {item['portal_sku']: item['master_sku'] for item in m_res.data} if m_res.data else {}
    c_dict = {item['design_pattern']: item['landed_cost'] for item in c_res.data} if c_res.data else {}
    return m_dict, c_dict

# --- 4. AUTH LOGIC ---
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
                except: st.error("Authentication Failed")
else:
    u_id = st.session_state.user.id
    mapping_dict, costing_dict = load_all_data(u_id)
    
    # --- SIDEBAR (Costing Defaults) ---
    with st.sidebar:
        st.header("📊 Default Product Costing")
        std_base = st.number_input("Standard Pant Cost (PT/PL)", value=165)
        hf_base = st.number_input("HF Series Cost", value=110)
        st.divider()
        if st.button("Logout"): 
            supabase.auth.sign_out(); st.session_state.user = None; st.rerun()

    # --- MAIN TABS ---
    t1, t2, t3, t4 = st.tabs(["📦 Picklist", "💰 Costing Manager", "📊 Flipkart Profit", "👗 Myntra Profit"])

    # --- TAB 1: PICKLIST (Logic already exists in your workflow) ---
    with t1:
        st.header("Order Processing & Picklist")
        st.info("Use this tab to upload orders and generate 4x6 labels.")

    # --- TAB 2: COSTING MANAGER ---
    with t2:
        st.header("Design-wise Landed Cost")
        with st.form("cost_add"):
            c1, c2 = st.columns(2)
            p_in = c1.text_input("Design Pattern (e.g. PT001-BLACK)")
            v_in = c2.number_input("Cost (₹)", min_value=0.0)
            if st.form_submit_button("Save to Database"):
                cp = get_design_pattern(p_in)
                supabase.table("design_costing").upsert({"user_id": u_id, "design_pattern": cp, "landed_cost": v_in}, on_conflict="user_id, design_pattern").execute()
                st.success(f"Saved {cp}!"); st.rerun()

    # --- TAB 3: FLIPKART ANALYZER (SUNIL'S CODE INTEGRATED) ---
    with t3:
        st.header("Flipkart Orders P&L - Real-time Analysis")
        uploaded_file = st.file_uploader("Upload Flipkart Orders P&L Excel (.xlsx)", type=["xlsx"])

        if uploaded_file:
            try:
                excel_data = pd.ExcelFile(uploaded_file)
                target_sheet = next((s for s in excel_data.sheet_names if "Orders P&L" in s), excel_data.sheet_names[0])
                df = pd.read_excel(uploaded_file, sheet_name=target_sheet)
                df.columns = [str(c).strip() for c in df.columns]

                # Column Definitions
                sku_col, settlement_col = "SKU Name", "Bank Settlement [Projected] (INR)"
                units_col, order_id_col = "Net Units", "Order ID"
                status_col, gross_units_col = "Order Status", "Gross Units"

                if sku_col in df.columns and settlement_col in df.columns:
                    df[units_col] = pd.to_numeric(df[units_col], errors='coerce').fillna(0).astype(int)
                    df[settlement_col] = pd.to_numeric(df[settlement_col], errors='coerce').fillna(0)
                    
                    # Logic to find Unit Cost based on DB or Defaults
                    def get_integrated_cost(sku_name):
                        p_sku = str(sku_name).strip()
                        m_sku = mapping_dict.get(p_sku, p_sku) # Use mapping or self
                        pattern = get_design_pattern(m_sku)
                        
                        # 1. Check in Database Costing first
                        if pattern in costing_dict:
                            cost = costing_dict[pattern]
                            cat = "DB Match"
                        else:
                            # 2. Use Sunil's Default Logic if not in DB
                            sku_upper = p_sku.upper()
                            is_hf = sku_upper.startswith("HF")
                            base = hf_base if is_hf else std_base
                            cat = ("HF" if is_hf else "Std")
                            
                            if "3CBO" in sku_upper: cost, cat = (base * 3), cat + " 3CBO"
                            elif "CBO" in sku_upper: cost, cat = (base * 2), cat + " Combo"
                            else: cost, cat = base, cat + " Single"
                        
                        return cat, cost

                    cost_results = df[sku_col].apply(get_integrated_cost)
                    df['Category'] = [x[0] for x in cost_results]
                    df['Unit_Cost'] = [x[1] for x in cost_results]
                    
                    # Profit Calc
                    df['Net_Profit'] = df.apply(lambda x: x[settlement_col] - (x[units_col] * x['Unit_Cost']) if x[units_col] > 0 else x[settlement_col], axis=1)

                    # KPI Metrics
                    m1, m2, m3, m4 = st.columns(4)
                    t_pay, t_prof = int(df[settlement_col].sum()), int(df['Net_Profit'].sum())
                    m1.metric("Total Settlement", f"₹{t_pay:,}")
                    m2.metric("Net Profit", f"₹{t_prof:,}", delta=f"{(t_prof/t_pay*100 if t_pay>0 else 0):.1f}% Margin")
                    
                    # Category Table
                    st.subheader("💰 Performance Summary")
                    summary = df.groupby('Category').agg({units_col: 'sum', settlement_col: 'sum', 'Net_Profit': 'sum'})
                    st.table(summary.fillna(0).astype(int))

                    # Loss Orders
                    st.subheader("⚠️ Loss-making Orders")
                    loss_df = df[df['Net_Profit'] < 0][[order_id_col, sku_col, status_col, settlement_col, 'Net_Profit']].copy()
                    st.dataframe(loss_df.sort_values('Net_Profit'), use_container_width=True, hide_index=True)

            except Exception as e:
                st.error(f"Error in Processing: {e}")

    # --- TAB 4: MYNTRA (Placeholder for next step) ---
    with t4:
        st.header("Myntra Analyzer")
        st.info("Myntra Settlement logic will be similar to Flipkart but with Myntra specific column names.")
