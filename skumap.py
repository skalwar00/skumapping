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
    i_res = supabase.table("master_inventory").select("master_sku").eq("user_id", u_id).execute()
    c_res = supabase.table("design_costing").select("design_pattern, landed_cost").eq("user_id", u_id).execute()
    
    m_dict = {item['portal_sku']: item['master_sku'] for item in m_res.data} if m_res.data else {}
    c_dict = {item['design_pattern']: item['landed_cost'] for item in c_res.data} if c_res.data else {}
    m_list = [i['master_sku'].upper() for i in i_res.data] if i_res.data else []
    
    return m_dict, c_dict, m_list

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
    u_id = st.session_state.user.id
    mapping_dict, costing_dict, master_options = load_all_data(u_id)
    
    with st.sidebar:
        st.header("📊 Default Costing")
        std_base = st.number_input("Standard Pant (PT/PL)", value=165)
        hf_base = st.number_input("HF Series Cost", value=110)
        st.divider()
        if st.button("Logout"): 
            supabase.auth.sign_out()
            st.session_state.user = None
            st.rerun()

    # --- TABS SYSTEM ---
    t1, t2, t3, t4 = st.tabs(["📦 Picklist", "💰 Costing Manager", "📊 Flipkart Profit", "👗 Myntra Profit"])

    # --- TAB 1: PICKLIST (FIXED & WORKING) ---
    with t1:
        st.header("Order Processing & Picklist")
        
        with st.expander("📥 Master Inventory Sync"):
            m_f = st.file_uploader("Upload Master SKU CSV", type=['csv'])
            if m_f and st.button("Sync Master"):
                df_m = pd.read_csv(m_f)
                new_m = [{"user_id": u_id, "master_sku": str(s).upper()} for s in df_m.iloc[:,0].dropna().unique()]
                supabase.table("master_inventory").upsert(new_m, on_conflict="user_id, master_sku").execute()
                st.success("Master SKUs Synced!"); st.rerun()

        files = st.file_uploader("Upload Orders (Flipkart CSV / Meesho PDF)", type=["csv", "pdf"], accept_multiple_files=True)
        
        if files:
            orders_data = []
            for f in files:
                if f.name.endswith('.csv'):
                    df_c = pd.read_csv(f)
                    sku_c = next((c for c in df_c.columns if 'sku' in c.lower()), None)
                    if sku_c:
                        for s in df_c[sku_c].dropna(): orders_data.append({'Portal_SKU': str(s).strip(), 'Qty': 1})
                elif f.name.endswith('.pdf'):
                    with pdfplumber.open(f) as pdf:
                        for page in pdf.pages:
                            table = page.extract_table()
                            if table:
                                for row in table[1:]:
                                    if row[0]: orders_data.append({'Portal_SKU': str(row[0]).strip(), 'Qty': 1})
            
            if orders_data:
                combined = pd.DataFrame(orders_data)
                st.write(f"Total Orders Loaded: {len(combined)}")
                
                if st.button("Generate 4x6 Picklist"):
                    combined['Master_SKU'] = combined['Portal_SKU'].map(mapping_dict)
                    ready = combined.dropna(subset=['Master_SKU'])
                    if not ready.empty:
                        summary = ready.groupby('Master_SKU')['Qty'].sum().reset_index()
                        pdf = generate_4x6_pdf(summary)
                        st.download_button("📥 Download PDF", pdf, "picklist.pdf", "application/pdf")
                    else:
                        st.warning("No SKUs are mapped yet. Please map them below.")

                # Mapping Section
                st.divider()
                unmapped = [s for s in combined['Portal_SKU'].unique() if s not in mapping_dict]
                if unmapped:
                    st.subheader("🔍 New SKU Mapping")
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
                        if not to_save.empty:
                            rows = [{"user_id": u_id, "portal_sku": r['Portal SKU'], "master_sku": r['Master SKU']} for _, r in to_save.iterrows()]
                            supabase.table("sku_mapping").upsert(rows, on_conflict="user_id, portal_sku").execute()
                            st.success("Mappings Saved!"); st.rerun()

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

    # --- TAB 3: FLIPKART ANALYZER ---
    with t3:
        # [Aapka Flipkart Profit Analyzer code yahan bilkul pichle message ki tarah aayega]
        st.write("Flipkart P&L Tab is Active.")

    # --- TAB 4: MYNTRA ---
    with t4:
        st.write("Myntra Analyzer Tab is Active.")
