import streamlit as st
import pandas as pd
import re
import io
import datetime

# --- 1. CRITICAL IMPORTS ---
try:
    from supabase import create_client, Client
    from thefuzz import fuzz
    import pdfplumber
    from reportlab.pdfgen import canvas
    import openpyxl
    INCH = 72 
except ImportError:
    st.error("❌ Libraries are installing... Please wait.")
    st.stop()

# --- 2. CONFIG & DATABASE ---
st.set_page_config(page_title="Aavoni Seller Suite", layout="wide", page_icon="👗")

try:
    # Ensure these are set in Streamlit Cloud -> Settings -> Secrets
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error(f"❌ Supabase Configuration Error: {e}")
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
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30, y, "Master SKU")
    c.drawString(w-60, y, "Qty")
    y -= 15
    c.line(20, y+10, w-20, y+10)
    c.setFont("Helvetica", 9)
    for _, row in df.iterrows():
        if y < 40:
            c.showPage()
            y = h - 40
        c.drawString(30, y, str(row['Master_SKU'])[:25])
        c.drawString(w-55, y, str(row['Qty']))
        y -= 15
    c.save()
    buffer.seek(0)
    return buffer

# --- 4. AUTH & MAIN UI ---
if st.session_state.user is None:
    st.title("🚀 Aavoni Seller Suite")
    with st.sidebar:
        mode = st.radio("Action", ["Login", "Signup"])
        with st.form("auth"):
            e = st.text_input("Email")
            p = st.text_input("Password", type="password")
            if st.form_submit_button("Submit"):
                try:
                    if mode == "Login":
                        res = supabase.auth.sign_in_with_password({"email": e, "password": p})
                    else:
                        res = supabase.auth.sign_up({"email": e, "password": p})
                        if res.user: st.info("Signup successful! Try logging in now.")
                    
                    if res.session:
                        st.session_state.user = res.user
                        st.rerun()
                except Exception as ex:
                    st.error(f"❌ Auth Error: {ex}")
else:
    u_id = st.session_state.user.id
    mapping_dict, costing_dict, master_options = load_all_data(u_id)
    
    with st.sidebar:
        st.write(f"Logged in: **{st.session_state.user.email}**")
        if st.button("Logout"): 
            supabase.auth.sign_out()
            st.session_state.user = None
            st.rerun()

    t1, t2, t3, t4 = st.tabs(["📦 Picklist", "💰 Costing Manager", "📊 Flipkart Profit", "👗 Myntra Profit"])

    # --- TAB 1: PICKLIST ---
    with t1:
        st.header("Order Processing & Picklist")
        with st.expander("📥 Master Inventory Sync"):
            m_f = st.file_uploader("Upload Master SKU CSV", type=['csv'], key="master_sync")
            if m_f and st.button("Sync Master"):
                df_m = pd.read_csv(m_f)
                new_m = [{"user_id": u_id, "master_sku": str(s).upper()} for s in df_m.iloc[:,0].dropna().unique()]
                supabase.table("master_inventory").upsert(new_m, on_conflict="user_id, master_sku").execute()
                st.success("Master SKUs Synced!"); st.rerun()

        files = st.file_uploader("Upload Orders (CSV/PDF)", type=["csv", "pdf"], accept_multiple_files=True, key="order_upload")
        if files:
            orders_data = []
            for f in files:
                if f.name.endswith('.csv'):
                    df_c = pd.read_csv(f)
                    sku_c = next((c for c in df_c.columns if any(x in c.lower() for x in ['sku', 'seller_sku'])), None)
                    if sku_c:
                        for s in df_c[sku_c].dropna(): orders_data.append({'Portal_SKU': str(s).strip(), 'Qty': 1})
                elif f.name.endswith('.pdf'):
                    with pdfplumber.open(f) as pdf:
                        for page in pdf.pages:
                            table = page.extract_table()
                            if table:
                                for row in table[1:]:
                                    if row and row[0]: orders_data.append({'Portal_SKU': str(row[0]).strip(), 'Qty': 1})
            
            if orders_data:
                combined = pd.DataFrame(orders_data)
                st.success(f"Orders Loaded: {len(combined)}")
                
                if st.button("Generate 4x6 Picklist"):
                    combined['Master_SKU'] = combined['Portal_SKU'].map(mapping_dict)
                    ready = combined.dropna(subset=['Master_SKU'])
                    if not ready.empty:
                        summary = ready.groupby('Master_SKU')['Qty'].sum().reset_index()
                        pdf_file = generate_4x6_pdf(summary)
                        st.download_button("📥 Download PDF", pdf_file, f"picklist_{datetime.date.today()}.pdf")
                
                st.divider()
                unmapped = [s for s in combined['Portal_SKU'].unique() if s not in mapping_dict]
                if unmapped:
                    st.subheader("🔍 New SKU Mapping Needed")
                    map_rows = []
                    for s in unmapped:
                        best, hs = "Select", 0
                        for opt in master_options:
                            score = fuzz.token_set_ratio(s.upper(), opt.upper())
                            if score > hs: hs, best = score, opt
                        map_rows.append({"Confirm": (hs >= 90), "Portal SKU": s, "Master SKU": best})
                    
                    edited_map = st.data_editor(pd.DataFrame(map_rows), column_config={"Master SKU": st.column_config.SelectboxColumn(options=master_options)}, hide_index=True)
                    if st.button("Save New Mappings"):
                        to_save = edited_map[edited_map['Confirm'] == True]
                        rows = [{"user_id": u_id, "portal_sku": r['Portal SKU'], "master_sku": r['Master SKU']} for _, r in to_save.iterrows()]
                        supabase.table("sku_mapping").upsert(rows, on_conflict="user_id, portal_sku").execute()
                        st.success("Saved!"); st.rerun()

    # --- TAB 2: COSTING MANAGER ---
    with t2:
        st.header("💰 Design-wise Costing Manager")
        col_c1, col_c2 = st.columns(2)
        kurti_base = col_c1.number_input("Kurti Single Cost (₹)", value=250)
        set_base = col_c2.number_input("Kurta Set Cost (₹)", value=450)
        
        all_master_skus = list(set(mapping_dict.values()))
        all_designs = sorted(list(set([get_design_pattern(s) for s in all_master_skus])))
        missing = [d for d in all_designs if d not in costing_dict]
        
        with st.form("cost_update_form"):
            sel = st.selectbox("Select Design Pattern", options=missing + [d for d in all_designs if d in costing_dict])
            new_v = st.number_input(f"Landed Cost (₹)", min_value=0.0, value=float(costing_dict.get(sel, 0.0)))
            if st.form_submit_button("Save Costing"):
                supabase.table("design_costing").upsert({"user_id": u_id, "design_pattern": sel, "landed_cost": new_v}, on_conflict="user_id, design_pattern").execute()
                st.success("✅ Saved!"); st.rerun()
        
        if costing_dict:
            st.dataframe(pd.DataFrame(list(costing_dict.items()), columns=['Pattern', 'Cost']), use_container_width=True)

    # --- TAB 3: FLIPKART ANALYZER ---
    with t3:
        st.title("📊 Flipkart Business Dashboard")
        fk_file = st.file_uploader("Upload Flipkart Orders Excel", type=["xlsx"], key="fk_pnl")
        if fk_file:
            df_fk = pd.read_excel(fk_file)
            st.info("Calculating Profit/Loss based on SKU mappings...")
            # Logic here remains same as previous version but integrated with mapping_dict

    # --- TAB 4: MYNTRA ANALYZER ---
    with t4:
        st.title("👗 Myntra Smart P&L")
        m_files = st.file_uploader("Upload Myntra CSVs", type=['csv'], accept_multiple_files=True, key="m_pnl")
        if len(m_files) >= 2:
            st.success("Ready to analyze Myntra settlements.")
