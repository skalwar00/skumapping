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
    st.error("❌ Libraries are installing... Please wait 1-2 minutes.")
    st.stop()

# --- 2. CONFIG & DATABASE ---
st.set_page_config(page_title="Aavoni Seller Suite", layout="wide", page_icon="📦")

try:
    url, key = st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(url, key)
except:
    st.error("❌ Supabase Secrets (URL/KEY) missing in Settings!")
    st.stop()

if 'user' not in st.session_state:
    st.session_state.user = None

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
                    if res.user: 
                        st.session_state.user = res.user
                        st.rerun()
                except: st.error("Authentication Failed")
else:
    # --- USER LOGGED IN: SHOW TABS ---
    u_id = st.session_state.user.id
    mapping_dict, costing_dict = load_all_data(u_id)
    
    with st.sidebar:
        st.header("📊 Default Costing")
        std_base = st.number_input("Standard Pant (PT/PL)", value=165)
        hf_base = st.number_input("HF Series Cost", value=110)
        st.divider()
        if st.button("Logout"): 
            supabase.auth.sign_out()
            st.session_state.user = None
            st.rerun()

    # --- TABS SYSTEM (Main UI) ---
    t1, t2, t3, t4 = st.tabs(["📦 Picklist", "💰 Costing Manager", "📊 Flipkart Profit", "👗 Myntra Profit"])

    # --- TAB 1: PICKLIST ---
    with t1:
        st.header("Order Processing & Picklist")
        st.info("Upload orders (CSV/PDF) to generate 4x6 labels and map new SKUs.")
        # [Aapka Picklist Code yahan continue hoga]

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
                st.success(f"Saved {cp} at ₹{v_in}!"); st.rerun()
        
        if costing_dict:
            st.subheader("Saved Costings")
            st.dataframe(pd.DataFrame(list(costing_dict.items()), columns=['Pattern', 'Cost']), use_container_width=True)

    # --- TAB 3: FLIPKART ANALYZER (SUNIL'S CODE) ---
    with t3:
        st.header("Flipkart Orders P&L")
        uploaded_file = st.file_uploader("Upload Flipkart Orders Excel (.xlsx)", type=["xlsx"])

        if uploaded_file:
            try:
                excel_data = pd.ExcelFile(uploaded_file)
                target_sheet = next((s for s in excel_data.sheet_names if "Orders P&L" in s), excel_data.sheet_names[0])
                df = pd.read_excel(uploaded_file, sheet_name=target_sheet)
                df.columns = [str(c).strip() for c in df.columns]

                sku_col, settlement_col = "SKU Name", "Bank Settlement [Projected] (INR)"
                units_col, order_id_col = "Net Units", "Order ID"
                status_col = "Order Status"

                if sku_col in df.columns and settlement_col in df.columns:
                    df[units_col] = pd.to_numeric(df[units_col], errors='coerce').fillna(0).astype(int)
                    df[settlement_col] = pd.to_numeric(df[settlement_col], errors='coerce').fillna(0)
                    
                    def get_integrated_cost(sku_name):
                        p_sku = str(sku_name).strip()
                        m_sku = mapping_dict.get(p_sku, p_sku)
                        pattern = get_design_pattern(m_sku)
                        
                        if pattern in costing_dict:
                            return "DB Match", costing_dict[pattern]
                        else:
                            sku_up = p_sku.upper()
                            is_hf = sku_up.startswith("HF")
                            base = hf_base if is_hf else std_base
                            if "3CBO" in sku_up: return "Std 3CBO", (base * 3)
                            if "CBO" in sku_up: return "Combo", (base * 2)
                            return "Single", base

                    cost_res = df[sku_col].apply(get_integrated_cost)
                    df['Category'], df['Unit_Cost'] = [x[0] for x in cost_res], [x[1] for x in cost_res]
                    df['Net_Profit'] = df.apply(lambda x: x[settlement_col] - (x[units_col] * x['Unit_Cost']) if x[units_col] > 0 else x[settlement_col], axis=1)

                    # Metrics
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Settlement", f"₹{int(df[settlement_col].sum()):,}")
                    m2.metric("Profit", f"₹{int(df['Net_Profit'].sum()):,}")
                    m3.metric("Units", f"{df[units_col].sum():,}")

                    st.subheader("⚠️ Loss Orders")
                    loss_df = df[df['Net_Profit'] < 0][[order_id_col, sku_col, status_col, settlement_col, 'Net_Profit']]
                    st.dataframe(loss_df, use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"Error: {e}")

    # --- TAB 4: MYNTRA ANALYZER ---
    with t4:
        st.header("Myntra Analyzer")
        st.info("Myntra specific reports can be uploaded here.")
