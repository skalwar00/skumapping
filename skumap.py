import streamlit as st
import pandas as pd
import re
import io

# --- CRITICAL IMPORTS WITH FIXED COMPATIBILITY ---
try:
    from supabase import create_client, Client
    from thefuzz import fuzz
    import pdfplumber
    # Unit import fix for Python 3.11+
    from reportlab.lib.units import Inch 
    from reportlab.pdfgen import canvas
except ImportError as e:
    st.error(f"❌ Library Error: {e}")
    st.info("Please wait for Streamlit to finish installation or check requirements.txt")
    st.stop()

# --- PAGE SETUP ---
st.set_page_config(page_title="Smart Picklist Pro", layout="wide")

# --- SUPABASE CONNECTION ---
try:
    url: str = st.secrets["SUPABASE_URL"]
    key: str = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(url, key)
except Exception:
    st.error("❌ Supabase Secrets (URL/KEY) missing in Streamlit Settings!")
    st.stop()

# --- SESSION STATE ---
if 'user' not in st.session_state:
    st.session_state.user = None

# --- AUTH FUNCTIONS ---
def login_user(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state.user = res.user
        st.rerun()
    except:
        st.sidebar.error("Invalid Email/Password")

def signup_user(email, password):
    try:
        supabase.auth.sign_up({"email": email, "password": password})
        st.sidebar.success("Account Created! Now Login.")
    except:
        st.sidebar.error("Signup Failed")

# --- DATA & CREDIT FUNCTIONS ---
def get_user_credits(user_id):
    try:
        res = supabase.table("profiles").select("credits").eq("id", user_id).single().execute()
        return res.data['credits'] if res.data else 0
    except:
        return 0

def deduct_credits(user_id, order_count):
    # Logic: 4 orders = 1 credit
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
    w, h = 4*Inch, 6*Inch
    c = canvas.Canvas(buffer, pagesize=(w, h))
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(w/2, h - 30, "SMART PICKLIST PRO")
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

# --- UTILS ---
def get_sku_size(sku):
    match = re.search(r'\b(\d*XL|L|M|S)\b', str(sku).upper())
    return match.group(1) if match else ""

def clean_sku_for_pattern(sku):
    sku = str(sku).upper()
    patterns = [r'\(.*?\)', r'\b\d*XL\b', r'\b[SML]\b', r'[-_]\s*$', r'\s+']
    for p in patterns: sku = re.sub(p, '', sku)
    return sku.strip('-_ ')

def extract_meesho_pdf(pdf_file):
    data = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2: continue
                sku_idx = size_idx = qty_idx = None
                h_idx = -1
                for i, row in enumerate(table):
                    r_str = " ".join([str(c).lower() for c in row if c])
                    if 'sku' in r_str and ('qty' in r_str or 'quantity' in r_str):
                        for idx, cell in enumerate(row):
                            c_t = str(cell).lower()
                            if 'sku' in c_t: sku_idx = idx
                            if 'size' in c_t: size_idx = idx
                            if 'qty' in c_t or 'quantity' in c_t: qty_idx = idx
                        h_idx = i
                        break
                if sku_idx is not None:
                    for row in table[h_idx+1:]:
                        if not row[sku_idx]: continue
                        s, sz = str(row[sku_idx]).strip(), str(row[size_idx]).strip() if size_idx is not None else ""
                        q = 1
                        if qty_idx is not None:
                            n = re.findall(r'\d+', str(row[qty_idx]))
                            q = int(n[0]) if n else 1
                        data.append({'Portal_SKU': f"{s} {sz}".strip(), 'Qty': q})
    return pd.DataFrame(data)

# --- MAIN UI ---
if st.session_state.user is None:
    st.title("🚀 Smart Picklist Pro")
    with st.sidebar:
        mode = st.radio("Action", ["Login", "Signup"])
        e = st.text_input("Email")
        p = st.text_input("Password", type="password")
        if mode == "Login" and st.button("Login"): login_user(e, p)
        if mode == "Signup" and st.button("Create Account"): signup_user(e, p)
else:
    u_id = st.session_state.user.id
    creds = get_user_credits(u_id)
    st.sidebar.metric("Available Credits", creds)
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
            if f.name.endswith('.pdf'):
                df_p = extract_meesho_pdf(f)
                if not df_p.empty: orders_list.append(df_p)
            else:
                df_c = pd.read_csv(f)
                c_map = {str(c).lower().strip().replace(" ", "_"): c for c in df_c.columns}
                s_c = next((c_map[k] for k in ['sku', 'seller_sku', 'seller_sku_code'] if k in c_map), None)
                q_c = next((c_map[k] for k in ['quantity', 'qty', 'total_quantity'] if k in c_map), None)
                if s_c:
                    q_d = pd.to_numeric(df_c[q_c], errors='coerce').fillna(1) if q_c else 1
                    orders_list.append(pd.DataFrame({'Portal_SKU': df_c[s_c].astype(str).str.strip(), 'Qty': q_d}))

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
                        pdf_file = generate_4x6_pdf(summary)
                        st.download_button("📥 Download 4x6 Picklist", pdf_file, "picklist.pdf", "application/pdf")
                    else: st.warning("No mappings found.")
                else: st.error(f"Need {cost} credits.")

            st.divider()
            m_d = dict(zip(mapping_df['portal_sku'].astype(str), mapping_df['master_sku'].astype(str)))
            unmapped = [s for s in combined['Portal_SKU'].unique() if str(s) not in m_d]
            if unmapped:
                st.subheader("🔍 Review & Map")
                if 'temp_res' not in st.session_state:
                    res = []
                    for s in unmapped:
                        best, hs = "Select Manually", 0
                        for opt in master_options:
                            score = fuzz.token_set_ratio(str(s).upper(), str(opt).upper())
                            if score > hs: hs, best = score, opt
                        res.append({"Confirm": (hs >= 90), "Portal SKU": s, "Master SKU": best, "Match %": f"{hs}%"})
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
                    if st.button("Save Mappings"):
                        to_s = edited[edited['Confirm'] == True]
                        if not to_s.empty:
                            rows = [{"user_id": u_id, "portal_sku": str(r['Portal SKU']), "master_sku": str(r['Master SKU'])} for _, r in to_s.iterrows()]
                            supabase.table("sku_mapping").upsert(rows, on_conflict="user_id, portal_sku").execute()
                            st.success("Saved!"); del st.session_state.temp_res; st.rerun()
