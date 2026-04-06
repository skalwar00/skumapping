import streamlit as st
import pandas as pd
from supabase import create_client, Client
from thefuzz import fuzz
import re
import pdfplumber
import io
from reportlab.lib.pagesizes import Inch
from reportlab.pdfgen import canvas

# --- PAGE SETUP ---
st.set_page_config(page_title="Smart Picklist Pro", layout="wide")

# --- SUPABASE CONNECTION ---
try:
    url: str = st.secrets["SUPABASE_URL"]
    key: str = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(url, key)
except Exception:
    st.error("❌ Supabase Secrets missing!")
    st.stop()

# --- SESSION STATE ---
if 'user' not in st.session_state:
    st.session_state.user = None

# --- AUTH & DATA FUNCTIONS ---
def get_user_credits(user_id):
    try:
        res = supabase.table("profiles").select("credits").eq("id", user_id).single().execute()
        return res.data['credits'] if res.data else 0
    except: return 0

def deduct_credits(user_id, order_count):
    needed = (order_count // 4) + (1 if order_count % 4 > 0 else 0)
    current = get_user_credits(user_id)
    if current >= needed:
        new_bal = current - needed
        supabase.table("profiles").update({"credits": new_bal}).eq("id", user_id).execute()
        return True, needed
    return False, needed

def load_user_db(user_id):
    m_res = supabase.table("sku_mapping").select("portal_sku, master_sku").eq("user_id", user_id).execute()
    i_res = supabase.table("master_inventory").select("master_sku").eq("user_id", user_id).execute()
    df_map = pd.DataFrame(m_res.data) if m_res.data else pd.DataFrame(columns=['portal_sku', 'master_sku'])
    master_list = [i['master_sku'].upper() for i in i_res.data] if i_res.data else []
    return df_map, sorted(master_list)

# --- PDF GENERATOR (4x6 Inch) ---
def generate_4x6_pdf(df):
    buffer = io.BytesIO()
    # 4x6 Inch Page Size
    w, h = 4*Inch, 6*Inch
    c = canvas.Canvas(buffer, pagesize=(w, h))
    
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(w/2, h - 30, "SMART PICKLIST PRO")
    c.setFont("Helvetica", 10)
    c.line(20, h-40, w-20, h-40)
    
    y = h - 60
    c.setFont("Helvetica-Bold", 10)
    c.drawString(30, y, "Master SKU")
    c.drawString(w-60, y, "Qty")
    y -= 15
    c.line(20, y+10, w-20, y+10)
    
    c.setFont("Helvetica", 9)
    for _, row in df.iterrows():
        if y < 40: # New Page if space is low
            c.showPage()
            y = h - 40
            c.setFont("Helvetica", 9)
        
        sku_text = str(row['Master_SKU'])
        # Wrap text if SKU is too long
        if len(sku_text) > 25:
            sku_text = sku_text[:23] + ".."
            
        c.drawString(30, y, sku_text)
        c.drawString(w-55, y, str(row['Qty']))
        y -= 15
        
    c.save()
    buffer.seek(0)
    return buffer

# --- UTILS ---
def get_sku_size(sku):
    match = re.search(r'\b(\d*XL|L|M|S)\b', str(sku).upper())
    return match.group(1) if match else ""

def clean_sku_for_pattern(sku):
    sku = str(sku).upper()
    patterns = [r'\(.*?\)', r'\b\d*XL\b', r'\b[SML]\b', r'[-_]\s*$', r'\s+']
    for p in patterns: sku = re.sub(p, '', sku)
    return sku.strip('-_ ')

# --- APP UI ---
if st.session_state.user is None:
    st.title("🚀 Smart Picklist Pro")
    with st.sidebar:
        m = st.radio("Action", ["Login", "Signup"])
        e, p = st.text_input("Email"), st.text_input("Password", type="password")
        if m == "Login" and st.button("Login"):
            try:
                res = supabase.auth.sign_in_with_password({"email": e, "password": p})
                st.session_state.user = res.user; st.rerun()
            except: st.sidebar.error("Invalid Login")
        if m == "Signup" and st.button("Create Account"):
            try:
                supabase.auth.sign_up({"email": e, "password": p}); st.sidebar.success("Done! Login now.")
            except: st.sidebar.error("Error")
else:
    u_id = st.session_state.user.id
    creds = get_user_credits(u_id)
    st.sidebar.metric("Credits", creds)
    if st.sidebar.button("Logout"):
        supabase.auth.sign_out(); st.session_state.user = None; st.rerun()

    with st.sidebar.expander("📥 Master Settings"):
        m_f = st.file_uploader("Upload CSV", type=['csv'])
        if m_f and st.button("Sync"):
            df_m = pd.read_csv(m_f)
            new_m = [{"user_id": u_id, "master_sku": str(s).upper()} for s in df_m.iloc[:,0].dropna().unique()]
            supabase.table("master_inventory").upsert(new_m, on_conflict="user_id, master_sku").execute()
            st.success("Synced!"); st.rerun()

    st.title("📦 Order Processing")
    mapping_df, master_options = load_user_db(u_id)
    files = st.file_uploader("Upload Orders", type=["csv", "pdf"], accept_multiple_files=True)

    if files:
        orders_list = []
        for f in files:
            # (Extraction logic placeholder for brevity - same as optimized before)
            if f.name.endswith('.pdf'):
                # Call extract_meesho_pdf...
                pass
            else:
                df_c = pd.read_csv(f)
                # Call CSV processing...
                pass

        # Combined Process
        if orders_list:
            combined = pd.concat(orders_list, ignore_index=True)
            if st.button("Generate Picklist"):
                ok, cost = deduct_credits(u_id, len(combined))
                if ok:
                    m_d = dict(zip(mapping_df['portal_sku'].astype(str), mapping_df['master_sku'].astype(str)))
                    combined['Master_SKU'] = combined['Portal_SKU'].map(m_d)
                    ready = combined.dropna(subset=['Master_SKU'])
                    if not ready.empty:
                        st.success(f"Deducted {cost} credits.")
                        summary = ready.groupby('Master_SKU')['Qty'].sum().reset_index().sort_values('Qty', ascending=False)
                        st.dataframe(summary, use_container_width=True)
                        
                        # --- PDF DOWNLOAD 4x6 ---
                        pdf_file = generate_4x6_pdf(summary)
                        st.download_button("📥 Download 4x6 Picklist PDF", pdf_file, "picklist_4x6.pdf", "application/pdf")
                    else: st.warning("No mappings.")
                else: st.error(f"Low Balance! Need {cost}.")

            st.divider()
            m_d = dict(zip(mapping_df['portal_sku'].astype(str), mapping_df['master_sku'].astype(str)))
            unmapped = [s for s in combined['Portal_SKU'].unique() if str(s) not in m_d]
            if unmapped:
                st.subheader("🔍 Review & Map SKUs")
                if 'temp_res' not in st.session_state:
                    res = []
                    for s in unmapped:
                        best, high_score = "Select Manually", 0
                        for opt in master_options:
                            score = fuzz.token_set_ratio(str(s).upper(), str(opt).upper())
                            if score > high_score:
                                high_score, best = score, opt
                        res.append({"Confirm": (high_score >= 90), "Portal SKU": s, "Master SKU": best, "Match %": f"{high_score}%"})
                    st.session_state.temp_res = pd.DataFrame(res)

                edited = st.data_editor(st.session_state.temp_res, column_config={
                    "Master SKU": st.column_config.SelectboxColumn(options=master_options),
                    "Match %": st.column_config.TextColumn(disabled=True)
                }, hide_index=True)

                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Apply Pattern (Size-to-Size)"):
                        new_t, learn = edited.copy(), {}
                        for i, r in edited.iterrows():
                            if r['Master SKU'] != st.session_state.temp_res.iloc[i]['Master SKU']:
                                learn[clean_sku_for_pattern(r['Portal SKU'])] = clean_sku_for_pattern(r['Master SKU'])
                        for i, r in new_t.iterrows():
                            pb = clean_sku_for_pattern(r['Portal SKU'])
                            if pb in learn:
                                sz = get_sku_size(r['Portal SKU'])
                                nv = f"{learn[pb]}-{sz}" if sz else learn[pb]
                                if nv in master_options: new_t.at[i, 'Master SKU'], new_t.at[i, 'Confirm'] = nv, True
                        st.session_state.temp_res = new_t; st.rerun()
                with c2:
                    if st.button("Save Mapping"):
                        to_s = edited[edited['Confirm'] == True]
                        if not to_s.empty:
                            rows = [{"user_id": u_id, "portal_sku": str(r['Portal SKU']), "master_sku": str(r['Master SKU'])} for _, r in to_s.iterrows()]
                            supabase.table("sku_mapping").upsert(rows, on_conflict="user_id, portal_sku").execute()
                            st.success("Saved!"); del st.session_state.temp_res; st.rerun()
