import streamlit as st
import pandas as pd
import re
import io
from datetime import datetime, date

# --- 1. LIBRARIES ---
try:
    from supabase import create_client, Client
    from thefuzz import fuzz
    from reportlab.pdfgen import canvas
    import pdfplumber
    INCH = 72 
except ImportError:
    st.error("Missing Libraries! Run: pip install supabase thefuzz reportlab pdfplumber")
    st.stop()

# --- 2. CONFIG & DB ---
st.set_page_config(page_title="Aavoni Seller Suite", layout="wide", page_icon="👗")

try:
    url, key = st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]
    supabase = create_client(url, key)
except:
    st.error("Supabase Secrets Missing!")
    st.stop()

if 'user' not in st.session_state: st.session_state.user = None

# --- 3. SHARED UTILS ---
def get_design_pattern(master_sku):
    sku = str(master_sku).upper().strip()
    sku = re.sub(r'[-_](S|M|L|XL|XXL|\d*XL|FREE|SMALL|LARGE)$', '', sku)
    sku = re.sub(r'\(.*?\)', '', sku)
    return sku.strip('-_ ')

def load_all_data(u_id):
    # Default values taaki crash na ho
    m_dict, c_dict, m_list, u_prof = {}, {}, [], None
    
    try:
        # Tables fetch karna individually taaki ek fail ho toh baaki chalein
        m_res = supabase.table("sku_mapping").select("portal_sku, master_sku").eq("user_id", u_id).execute()
        m_dict = {item['portal_sku']: item['master_sku'] for item in m_res.data} if m_res.data else {}
        
        i_res = supabase.table("master_inventory").select("master_sku").eq("user_id", u_id).execute()
        m_list = [i['master_sku'].upper() for i in i_res.data] if i_res.data else []
        
        c_res = supabase.table("design_costing").select("design_pattern, landed_cost").eq("user_id", u_id).execute()
        c_dict = {item['design_pattern']: item['landed_cost'] for item in c_res.data} if c_res.data else {}
        
        p_res = supabase.table("profiles").select("*").eq("id", u_id).execute()
        u_prof = p_res.data[0] if p_res.data else None
    except Exception as e:
        st.sidebar.warning(f"Data Sync Warning: {e}")
        
    return m_dict, c_dict, m_list, u_prof

def generate_4x6_pdf(df):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(4*INCH, 6*INCH))
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(2*INCH, 5.6*INCH, "AAVONI PICKLIST")
    y = 5.2*INCH
    for _, row in df.iterrows():
        if y < 50: c.showPage(); y = 5.6*INCH
        c.setFont("Helvetica", 11)
        c.drawString(30, y, f"{str(row['Master_SKU'])[:22]}")
        c.drawRightString(4*INCH-30, y, f"Qty: {row['Qty']}")
        y -= 25
    c.save(); buffer.seek(0)
    return buffer

# --- 4. MAIN APP ---
if st.session_state.user is None:
    st.title("🚀 Aavoni Seller Suite")
    with st.sidebar:
        mode = st.radio("Mode", ["Login", "Signup"])
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
        st.header("👗 Admin Panel")
        
        # --- TRIAL LOGIC (SAFE VERSION) ---
        if profile and profile.get('plan_expiry'):
            try:
                exp = datetime.strptime(str(profile['plan_expiry']), '%Y-%m-%d').date()
                days = (exp - date.today()).days
                if days >= 0: st.success(f"🎁 Trial: {days} Days Left")
                else: st.error("❌ Trial Expired")
            except: st.info("🎁 Plan: Active")
        else:
            st.info("🎁 Free Trial: Active")
        
        st.divider()
        std_base = st.number_input("Std Pant Cost", value=165)
        hf_base = st.number_input("HF Series Cost", value=115)
        if st.button("Logout"): 
            supabase.auth.sign_out(); st.session_state.user = None; st.rerun()

    tabs = st.tabs(["🏠 Home", "📦 Picklist", "💰 Costing", "📊 Flipkart P&L", "👗 Myntra P&L"])

    # --- TAB 1: PICKLIST ---
    with tabs[1]:
        st.header("📦 Order Processing")
        files = st.file_uploader("Upload Orders", type=["csv"], accept_multiple_files=True, key="pk_tool")
        if files:
            orders = []
            for f in files:
                df_c = pd.read_csv(f)
                df_c.columns = [c.lower().strip() for c in df_c.columns]
                # Sabse pehle Myntra priority, phir generic SKU
                col = 'seller sku code' if 'seller sku code' in df_c.columns else next((c for c in df_c.columns if 'sku' in c and 'myntra' not in c), None)
                if col:
                    for s in df_c[col].dropna(): orders.append({'Portal_SKU': str(s).strip().upper(), 'Qty': 1})
            
            if orders:
                df_o = pd.DataFrame(orders)
                if st.button("Generate Picklist"):
                    df_o['Master_SKU'] = df_o['Portal_SKU'].map(mapping_dict)
                    ready = df_o.dropna(subset=['Master_SKU'])
                    if not ready.empty:
                        pdf = generate_4x6_pdf(ready.groupby('Master_SKU')['Qty'].sum().reset_index())
                        st.download_button("Download PDF", pdf, "Aavoni_Picklist.pdf")
                    else: st.warning("SKUs not mapped! Use Costing/Mapping first.")

    # --- TAB 4: MYNTRA ---
    with tabs[4]:
        st.header("Myntra Analyzer 🚀")
        m_files = st.file_uploader("Upload Reports", type=['csv'], accept_multiple_files=True, key="myntra_tool")
        
        def get_myntra_cost(sku_name):
            sku = str(sku_name).upper()
            m_sku = mapping_dict.get(sku, sku)
            pat = get_design_pattern(m_sku)
            if pat in costing_dict: return costing_dict[pat]
            if sku.startswith('HF'): return (hf_base * 2) if 'CBO' in sku else hf_base
            return (std_base * 2) if 'CBO' in sku else std_base

        if st.button("Analyze Myntra"):
            if len(m_files) >= 4:
                f_df, s_df, fwd, rev = None, None, [], []
                for f in m_files:
                    tdf = pd.read_csv(f); tdf.columns = [c.strip().lower() for c in tdf.columns]
                    if 'sale_order_code' in tdf.columns: f_df = tdf
                    elif 'seller sku code' in tdf.columns and 'total_actual_settlement' not in tdf.columns: s_df = tdf
                    elif 'total_actual_settlement' in tdf.columns:
                        v = pd.to_numeric(tdf['total_actual_settlement'], errors='coerce').mean()
                        if 'reverse' in f.name.lower() or v < 0: rev.append(tdf)
                        else: fwd.append(tdf)
                
                if f_df is not None and s_df is not None:
                    final = pd.merge(f_df, s_df[['order release id', 'seller sku code']], left_on='sale_order_code', right_on='order release id', how='left')
                    f_sum = pd.concat(fwd).groupby('order_release_id')['total_actual_settlement'].sum().reset_index() if fwd else pd.DataFrame(columns=['order_release_id', 'total_actual_settlement'])
                    r_sum = pd.concat(rev).groupby('order_release_id')['total_actual_settlement'].sum().reset_index() if rev else pd.DataFrame(columns=['order_release_id', 'total_actual_settlement'])
                    
                    final = pd.merge(final, f_sum, left_on='sale_order_code', right_on='order_release_id', how='left').rename(columns={'total_actual_settlement': 'Fwd'})
                    final = pd.merge(final, r_sum, left_on='sale_order_code', right_on='order_release_id', how='left').rename(columns={'total_actual_settlement': 'Rev'})
                    final[['Fwd', 'Rev']] = final[['Fwd', 'Rev']].fillna(0)
                    final['Net_Settlement'] = final['Fwd'] + final['Rev']
                    final['seller sku code'] = final['seller sku code'].fillna("UNKNOWN")
                    final['Unit_Cost'] = final['seller sku code'].apply(get_myntra_cost)
                    final['Total_Cost'] = final.apply(lambda x: x['Unit_Cost'] if str(x['order_item_status']).strip().lower() == 'delivered' else 0, axis=1)
                    final['Profit'] = final['Net_Settlement'] - final['Total_Cost']
                    
                    st.metric("Net Profit", f"₹{int(final['Profit'].sum()):,}")
                    st.dataframe(final[['sale_order_code', 'seller sku code', 'order_item_status', 'Net_Settlement', 'Profit']], use_container_width=True)
