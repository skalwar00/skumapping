import streamlit as st
import pandas as pd
import re
import io
from datetime import datetime, date

# --- 1. CRITICAL IMPORTS ---
try:
    from supabase import create_client, Client
    from thefuzz import fuzz
    import pdfplumber
    from reportlab.pdfgen import canvas
    import openpyxl
    INCH = 72 
except ImportError:
    st.error("❌ Libraries missing. Run: pip install supabase thefuzz pdfplumber reportlab openpyxl")
    st.stop()

# --- 2. CONFIG & DATABASE ---
st.set_page_config(page_title="Aavoni Seller Suite", layout="wide", page_icon="👗")

try:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error("❌ Supabase Secrets Missing!")
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
    try:
        m_res = supabase.table("sku_mapping").select("portal_sku, master_sku").eq("user_id", u_id).execute()
        i_res = supabase.table("master_inventory").select("master_sku").eq("user_id", u_id).execute()
        c_res = supabase.table("design_costing").select("design_pattern, landed_cost").eq("user_id", u_id).execute()
        p_res = supabase.table("profiles").select("*").eq("id", u_id).execute()
        
        m_dict = {item['portal_sku']: item['master_sku'] for item in m_res.data} if m_res.data else {}
        c_dict = {item['design_pattern']: item['landed_cost'] for item in c_res.data} if c_res.data else {}
        m_list = [i['master_sku'].upper() for i in i_res.data] if i_res.data else []
        profile = p_res.data[0] if p_res.data else None
        
        return m_dict, c_dict, m_list, profile
    except:
        return {}, {}, [], None

def generate_4x6_pdf(df):
    buffer = io.BytesIO()
    w, h = 4 * INCH, 6 * INCH
    c = canvas.Canvas(buffer, pagesize=(w, h))
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(w/2, h - 30, "AAVONI PICKLIST")
    c.line(20, h-40, w-20, h-40)
    y = h - 60
    for _, row in df.iterrows():
        if y < 40:
            c.showPage()
            y = h - 40
        c.setFont("Helvetica-Bold", 10)
        c.drawString(30, y, str(row['Master_SKU'])[:25])
        c.drawRightString(w-30, y, str(row['Qty']))
        y -= 15
    c.save()
    buffer.seek(0)
    return buffer

# --- 4. AUTH UI ---
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
    mapping_dict, costing_dict, master_options, profile = load_all_data(u_id)
    
    with st.sidebar:
        st.header("👗 Aavoni Admin")
        std_base = st.number_input("Std Pant Cost (PT/PL)", value=165)
        hf_base = st.number_input("HF Series Cost", value=110)
        if profile and profile.get('plan_expiry'):
            exp_dt = datetime.strptime(profile['plan_expiry'], '%Y-%m-%d').date()
            days_left = (exp_dt - date.today()).days
            st.success(f"🎁 Trial: {max(0, days_left)} Days Left")
        if st.button("Logout"): 
            supabase.auth.sign_out(); st.session_state.user = None; st.rerun()

    tabs = st.tabs(["🏠 Home", "📦 Picklist", "💰 Costing", "📊 Flipkart P&L", "👗 Myntra"])

    # --- TAB 0: HOME ---
    with tabs[0]:
        st.title(f"Welcome, {st.session_state.user.email.split('@')[0].capitalize()}!")
        st.write("Aavoni Business Intelligence Dashboard is ready.")
        m1, m2 = st.columns(2)
        m1.metric("Mapped SKUs", len(mapping_dict))
        m2.metric("Saved Costs", len(costing_dict))

    # --- TAB 1: PICKLIST ---
    with tabs[1]:
        st.header("Order Processing")
        with st.expander("📥 Master SKU Sync"):
            m_f = st.file_uploader("Upload Master SKU CSV", type=['csv'], key="m_up")
            if m_f and st.button("Sync Now"):
                df_m = pd.read_csv(m_f)
                rows = [{"user_id": u_id, "master_sku": str(s).upper().strip()} for s in df_m.iloc[:,0].dropna().unique()]
                supabase.table("master_inventory").upsert(rows, on_conflict="user_id, master_sku").execute()
                st.success("Synced!"); st.rerun()

        files = st.file_uploader("Upload Orders", type=["csv", "pdf"], accept_multiple_files=True, key="ord_up")
        if files:
            orders = []
            for f in files:
                if f.name.endswith('.csv'):
                    df_c = pd.read_csv(f)
                    df_c.columns = [c.lower().strip() for c in df_c.columns]
                    col = 'seller sku code' if 'seller sku code' in df_c.columns else next((c for c in df_c.columns if any(x in c for x in ['sku', 'seller_sku']) and 'myntra' not in c), None)
                    if col:
                        for s in df_c[col].dropna(): orders.append({'Portal_SKU': str(s).strip().upper(), 'Qty': 1})
            if orders:
                df_o = pd.DataFrame(orders)
                if st.button("Generate 4x6 Picklist"):
                    df_o['Master_SKU'] = df_o['Portal_SKU'].map(mapping_dict)
                    ready = df_o.dropna(subset=['Master_SKU'])
                    if not ready.empty:
                        pdf = generate_4x6_pdf(ready.groupby('Master_SKU')['Qty'].sum().reset_index())
                        st.download_button("Download PDF", pdf, "picklist.pdf")

    # --- TAB 2: COSTING ---
    with tabs[2]:
        st.header("Costing Manager")
        all_pats = sorted(list(set([get_design_pattern(s) for s in master_options])))
        with st.form("cost_form"):
            sel = st.selectbox("Select Design", options=all_pats)
            val = st.number_input("Landed Cost", value=float(costing_dict.get(sel, 0.0)))
            if st.form_submit_button("Save Cost"):
                supabase.table("design_costing").upsert({"user_id": u_id, "design_pattern": sel, "landed_cost": val}, on_conflict="user_id, design_pattern").execute()
                st.success("Saved!"); st.rerun()
        st.dataframe(pd.DataFrame(list(costing_dict.items()), columns=['Pattern', 'Cost']), use_container_width=True)

    # --- TAB 3: FLIPKART (YOUR MODIFIED SCRIPT) ---
    with tabs[3]:
        st.header("📊 Flipkart Orders P&L")
        fk_file = st.file_uploader("Upload Flipkart Orders Excel", type=["xlsx"], key="fk_pnl_unique")
        if fk_file:
            try:
                excel_data = pd.ExcelFile(fk_file)
                target_sheet = next((s for s in excel_data.sheet_names if "Orders P&L" in s), excel_data.sheet_names[0])
                df_fk = pd.read_excel(fk_file, sheet_name=target_sheet)
                df_fk.columns = [str(c).strip() for c in df_fk.columns]

                sku_col, sett_col, units_col = "SKU Name", "Bank Settlement [Projected] (INR)", "Net Units"
                order_id_col, status_col, gross_units_col = "Order ID", "Order Status", "Gross Units"

                if sku_col in df_fk.columns and sett_col in df_fk.columns:
                    df_fk[units_col] = pd.to_numeric(df_fk[units_col], errors='coerce').fillna(0).astype(int)
                    df_fk[sett_col] = pd.to_numeric(df_fk[sett_col], errors='coerce').fillna(0)
                    g_cols = [c for c in df_fk.columns if 'Gross Units' in c]
                    df_fk[gross_units_col] = pd.to_numeric(df_fk[g_cols[0]], errors='coerce').fillna(0).astype(int) if g_cols else df_fk[units_col]

                    def get_fk_cost(sku_name):
                        sku = str(sku_name).upper()
                        m_sku = mapping_dict.get(sku, sku)
                        pat = get_design_pattern(m_sku)
                        if pat in costing_dict: return "DB", costing_dict[pat]
                        is_hf = sku.startswith("HF")
                        if "3CBO" in sku: return "Std 3CBO", (std_base * 3)
                        if "CBO" in sku: return ("HF Combo", hf_base*2) if is_hf else ("Std Combo", std_base*2)
                        return ("HF Single", hf_base) if is_hf else ("Std Single", std_base)

                    res_fk = df_fk[sku_col].apply(get_fk_cost)
                    df_fk['Category'], df_fk['Unit_Cost'] = [x[0] for x in res_fk], [x[1] for x in res_fk]
                    df_fk['Net_Profit'] = df_fk.apply(lambda x: x[sett_col] - (x[units_col] * x['Unit_Cost']) if x[units_col] > 0 else x[sett_col], axis=1)

                    t_pay, t_prof = int(df_fk[sett_col].sum()), int(df_fk['Net_Profit'].sum())
                    t_gross, t_net = int(df_fk[gross_units_col].sum()), int(df_fk[units_col].sum())
                    
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Settlement", f"₹{t_pay:,}")
                    m2.metric("Profit", f"₹{t_prof:,}", delta=f"{(t_prof/t_pay*100 if t_pay>0 else 0):.1f}%")
                    m3.metric("Return Rate", f"{(t_gross-t_net)/t_gross*100 if t_gross>0 else 0:.1f}%")
                    m4.metric("Net Units", f"{t_net:,}")

                    st.subheader("⚠️ Loss-making Orders")
                    st.dataframe(df_fk[df_fk['Net_Profit'] < 0][[order_id_col, sku_col, status_col, sett_col, 'Net_Profit']], use_container_width=True, hide_index=True)
            except Exception as e: st.error(f"Flipkart Error: {e}")

    # --- TAB 4: MYNTRA ---
with tabs[4]:
    st.header("👗 Myntra Smart P&L")
    m_files = st.file_uploader("Upload Myntra Reports", type=['csv'], accept_multiple_files=True, key="my_pnl_final")
    
    if len(m_files) >= 2:
        flow_df, sett_list = None, []
        for f in m_files:
            tdf = pd.read_csv(f)
            # Normalizing column names to avoid KeyErrors
            tdf.columns = [c.lower().strip().replace(" ", "_") for c in tdf.columns]
            if 'sale_order_code' in tdf.columns: flow_df = tdf
            if 'total_actual_settlement' in tdf.columns: sett_list.append(tdf)
        
        if flow_df is not None and sett_list:
            # Settlement Merge Logic
            s_sum = pd.concat(sett_list).groupby('order_release_id')['total_actual_settlement'].sum().reset_index()
            final = pd.merge(flow_df, s_sum, left_on='sale_order_code', right_on='order_release_id', how='left')
            final['total_actual_settlement'] = pd.to_numeric(final['total_actual_settlement'], errors='coerce').fillna(0)
            
            # Detect SKU Column
            m_sku_col = next((c for c in final.columns if 'seller_sku' in c), None)

            # --- AUTOMATIC COSTING LOGIC START ---
            def get_myntra_cost(row):
                if not m_sku_col: return 0
                p_sku = str(row[m_sku_col]).upper()
                
                # 1. Check if SKU is mapped to a Master SKU
                m_sku = mapping_dict.get(p_sku, p_sku)
                pat = get_design_pattern(m_sku)
                
                # 2. Try to fetch from Database (costing_dict)
                if pat in costing_dict:
                    return costing_dict[pat]
                
                # 3. Fallback to Default Logic (If not in DB)
                # Agar "SET" ya "KURTA" hai toh 450, warna 250
                if any(x in m_sku for x in ["SET", "KURTA"]):
                    return 450 
                return 250
            # --- AUTOMATIC COSTING LOGIC END ---

            final['Unit_Cost'] = final.apply(get_myntra_cost, axis=1)
            
            # Profit = Settlement - Cost (Sirf settled items ke liye)
            final['Profit'] = final.apply(
                lambda x: x['total_actual_settlement'] - x['Unit_Cost'] if x['total_actual_settlement'] > 0 else 0, 
                axis=1
            )

            # Top Metric
            st.metric("Myntra Net Profit", f"₹{int(final['Profit'].sum()):,}")
            
            # Display Table
            display_cols = ['sale_order_code', 'total_actual_settlement', 'Unit_Cost', 'Profit']
            if m_sku_col: display_cols.insert(1, m_sku_col)
            
            st.dataframe(final[display_cols], use_container_width=True, hide_index=True)
        else:
            st.warning("Please upload both 'Flow' and 'Settlement' CSV files.")
