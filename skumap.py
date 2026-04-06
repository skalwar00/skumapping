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
    st.error("❌ Supabase Secrets Missing! Check Settings > Secrets.")
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
        
        m_dict = {item['portal_sku']: item['master_sku'] for item in m_res.data} if m_res.data else {}
        c_dict = {item['design_pattern']: item['landed_cost'] for item in c_res.data} if c_res.data else {}
        m_list = [i['master_sku'].upper() for i in i_res.data] if i_res.data else []
        
        return m_dict, c_dict, m_list
    except:
        return {}, {}, []

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
    mapping_dict, costing_dict, master_options = load_all_data(u_id)
    
    with st.sidebar:
        st.header("👗 Aavoni Admin")
        std_base = st.number_input("Std Pant Cost (PT/PL)", value=165)
        hf_base = st.number_input("HF Series Cost", value=115)
        if st.button("Logout"): 
            supabase.auth.sign_out(); st.session_state.user = None; st.rerun()

    tabs = st.tabs(["🏠 Home", "📦 Picklist", "💰 Costing", "📊 Flipkart P&L", "👗 Myntra P&L"])

    # --- TAB 0: HOME ---
    with tabs[0]:
        st.title("Welcome to Aavoni Dashboard")
        st.write("Manage your Picklists and P&L Analytics in one place.")
        m1, m2 = st.columns(2)
        m1.metric("Mapped SKUs", len(mapping_dict))
        m2.metric("Saved Costs", len(costing_dict))

    # --- TAB 1: PICKLIST (FIXED) ---
    with tabs[1]:
        st.header("Order Processing & Picklist")
        with st.expander("📥 Master SKU Sync"):
            m_f = st.file_uploader("Upload Master SKU CSV", type=['csv'], key="m_sync_picklist")
            if m_f and st.button("Sync Now"):
                df_m = pd.read_csv(m_f)
                rows = [{"user_id": u_id, "master_sku": str(s).upper().strip()} for s in df_m.iloc[:,0].dropna().unique()]
                supabase.table("master_inventory").upsert(rows, on_conflict="user_id, master_sku").execute()
                st.success("Master Inventory Updated!"); st.rerun()

        files = st.file_uploader("Upload Portal Orders (CSV/PDF)", type=["csv", "pdf"], accept_multiple_files=True, key="picklist_upload")
        if files:
            orders_list = []
            for f in files:
                if f.name.endswith('.csv'):
                    df_c = pd.read_csv(f)
                    df_c.columns = [c.lower().strip() for c in df_c.columns]
                    # Priority detection for SKU
                    sku_col = 'seller sku code' if 'seller sku code' in df_c.columns else next((c for c in df_c.columns if any(x in c for x in ['sku', 'seller_sku', 'item sku']) and 'myntra' not in c), None)
                    if sku_col:
                        for s in df_c[sku_col].dropna(): 
                            orders_list.append({'Portal_SKU': str(s).strip().upper(), 'Qty': 1})
                elif f.name.endswith('.pdf'):
                    with pdfplumber.open(f) as pdf:
                        for page in pdf.pages:
                            table = page.extract_table()
                            if table:
                                for row in table[1:]:
                                    if row and row[0]: orders_list.append({'Portal_SKU': str(row[0]).strip().upper(), 'Qty': 1})
            
            if orders_list:
                df_ord = pd.DataFrame(orders_list)
                st.info(f"Orders Found: {len(df_ord)}")
                if st.button("🖨️ Generate 4x6 Picklist PDF"):
                    df_ord['Master_SKU'] = df_ord['Portal_SKU'].map(mapping_dict)
                    ready = df_ord.dropna(subset=['Master_SKU'])
                    if not ready.empty:
                        pdf = generate_4x6_pdf(ready.groupby('Master_SKU')['Qty'].sum().reset_index())
                        st.download_button("📥 Download PDF", pdf, f"Picklist_{date.today()}.pdf")
                    else: st.error("No SKUs mapped. Use the mapping tool below.")

                # Mapping Tool
                unmapped = [s for s in df_ord['Portal_SKU'].unique() if s not in mapping_dict]
                if unmapped:
                    st.divider(); st.subheader("🔍 New SKU Mappings")
                    map_rows = []
                    for s in unmapped:
                        best, score = "Select", 0
                        for opt in master_options:
                            sc = fuzz.token_set_ratio(s, opt)
                            if sc > score: score, best = sc, opt
                        map_rows.append({"Confirm": (score > 90), "Portal SKU": s, "Master SKU": best})
                    edited = st.data_editor(pd.DataFrame(map_rows), column_config={"Master SKU": st.column_config.SelectboxColumn(options=master_options)}, hide_index=True)
                    if st.button("Save Selected Mappings"):
                        to_db = [{"user_id": u_id, "portal_sku": r['Portal SKU'], "master_sku": r['Master SKU']} for _, r in edited.iterrows() if r['Confirm']]
                        if to_db:
                            supabase.table("sku_mapping").upsert(to_db, on_conflict="user_id, portal_sku").execute()
                            st.success("Saved!"); st.rerun()

    # --- TAB 2: COSTING ---
    with tabs[2]:
        st.header("💰 Costing Manager")
        all_designs = sorted(list(set([get_design_pattern(s) for s in master_options])))
        with st.form("cost_form"):
            sel = st.selectbox("Select Design", options=all_designs)
            new_val = st.number_input("Landed Cost", value=float(costing_dict.get(sel, 0.0)))
            if st.form_submit_button("Save Costing"):
                supabase.table("design_costing").upsert({"user_id": u_id, "design_pattern": sel, "landed_cost": new_val}, on_conflict="user_id, design_pattern").execute()
                st.success("Cost Saved!"); st.rerun()
        st.dataframe(pd.DataFrame(list(costing_dict.items()), columns=['Design', 'Cost']), use_container_width=True)

    # --- TAB 3: FLIPKART ---
    with tabs[3]:
        st.header("📊 Flipkart Orders P&L")
        fk_file = st.file_uploader("Upload Flipkart Excel", type=["xlsx"], key="fk_pnl_final")
        if fk_file:
            try:
                excel_data = pd.ExcelFile(fk_file)
                target_sheet = next((s for s in excel_data.sheet_names if "Orders P&L" in s), excel_data.sheet_names[0])
                df_fk = pd.read_excel(fk_file, sheet_name=target_sheet)
                df_fk.columns = [str(c).strip() for c in df_fk.columns]
                sku_col, set_col, units_col = "SKU Name", "Bank Settlement [Projected] (INR)", "Net Units"
                if sku_col in df_fk.columns and set_col in df_fk.columns:
                    def calc_fk(row):
                        p_sku = str(row[sku_col]).upper()
                        m_sku = mapping_dict.get(p_sku, p_sku)
                        pat = get_design_pattern(m_sku)
                        if pat in costing_dict: return costing_dict[pat]
                        is_hf = p_sku.startswith("HF")
                        if "3CBO" in p_sku: return (std_base * 3)
                        if "CBO" in p_sku: return (hf_base*2) if is_hf else (std_base*2)
                        return hf_base if is_hf else std_base
                    df_fk['Profit'] = df_fk.apply(lambda x: x[set_col] - (x.get(units_col, 1) * calc_fk(x)), axis=1)
                    st.metric("Flipkart Net Profit", f"₹{int(df_fk['Profit'].sum()):,}")
                    st.dataframe(df_fk[[sku_col, set_col, 'Profit']], use_container_width=True)
            except Exception as e: st.error(f"Error: {e}")

    # --- TAB 4: MYNTRA ---
    with tabs[4]:
        st.header("Aavoni Myntra Smart Analyzer 🚀")
        m_files = st.file_uploader("Upload Myntra Reports (Flow, SKU, Settlements)", type=['csv'], accept_multiple_files=True, key="myntra_smart_pnl")

        def get_sku_cost_auto(sku_name):
            sku = str(sku_name).upper().strip()
            m_sku = mapping_dict.get(sku, sku)
            pat = get_design_pattern(m_sku)
            if pat in costing_dict: return costing_dict[pat]
            if sku.startswith('HF'): return 230 if 'CBO' in sku else 115
            elif sku.startswith('PT'): return 330 if 'CBO' in sku else 165
            return 0

        if st.button("Generate Smart Myntra Analysis"):
            if len(m_files) >= 4:
                f_df, s_df, fwd_list, rev_list = None, None, [], []
                for f in m_files:
                    tdf = pd.read_csv(f); tdf.columns = [c.strip().lower() for c in tdf.columns]
                    if 'sale_order_code' in tdf.columns: f_df = tdf
                    elif 'seller sku code' in tdf.columns and 'total_actual_settlement' not in tdf.columns: s_df = tdf
                    elif 'total_actual_settlement' in tdf.columns:
                        val = pd.to_numeric(tdf['total_actual_settlement'], errors='coerce').mean()
                        if 'reverse' in f.name.lower() or val < 0: rev_list.append(tdf)
                        else: fwd_list.append(tdf)

                if f_df is not None and s_df is not None:
                    final = pd.merge(f_df, s_df[['order release id', 'seller sku code']], left_on='sale_order_code', right_on='order release id', how='left')
                    fwd = pd.concat(fwd_list).groupby('order_release_id')['total_actual_settlement'].sum().reset_index() if fwd_list else pd.DataFrame(columns=['order_release_id', 'total_actual_settlement'])
                    rev = pd.concat(rev_list).groupby('order_release_id')['total_actual_settlement'].sum().reset_index() if rev_list else pd.DataFrame(columns=['order_release_id', 'total_actual_settlement'])
                    final = pd.merge(final, fwd, left_on='sale_order_code', right_on='order_release_id', how='left').rename(columns={'total_actual_settlement': 'Fwd'})
                    final = pd.merge(final, rev, left_on='sale_order_code', right_on='order_release_id', how='left').rename(columns={'total_actual_settlement': 'Rev'})
                    final[['Fwd', 'Rev']] = final[['Fwd', 'Rev']].fillna(0)
                    final['Net_Settlement'] = final['Fwd'] + final['Rev']
                    final['Unit_Cost'] = final['seller sku code'].apply(get_sku_cost_auto)
                    final['Total_Cost'] = final.apply(lambda x: x['Unit_Cost'] if str(x['order_item_status']).strip().lower() == 'delivered' else 0, axis=1)
                    final['Profit'] = final['Net_Settlement'] - final['Total_Cost']
                    st.metric("Myntra Net Profit", f"₹{int(final['Profit'].sum()):,}")
                    st.dataframe(final[['sale_order_code', 'seller sku code', 'Net_Settlement', 'Profit']], use_container_width=True)
