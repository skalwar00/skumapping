import streamlit as st
import pandas as pd
from supabase import create_client, Client
from thefuzz import fuzz
import re
import pdfplumber
import io

# --- PAGE SETUP ---
st.set_page_config(page_title="Smart Picklist Pro", layout="wide")

# --- SUPABASE CONNECTION ---
try:
    url: str = st.secrets["SUPABASE_URL"]
    key: str = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(url, key)
except Exception:
    st.error("❌ Supabase Secrets (URL/KEY) missing in Streamlit Cloud Settings!")
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
        st.sidebar.error("Signup Failed. Try a different email.")

# --- CREDIT & DATA FUNCTIONS ---
def get_user_credits(user_id):
    try:
        res = supabase.table("profiles").select("credits").eq("id", user_id).single().execute()
        return res.data['credits'] if res.data else 0
    except:
        return 0

def deduct_credits(user_id, order_count):
    needed = (order_count // 4) + (1 if order_count % 4 > 0 else 0)
    current = get_user_credits(user_id)
    if current >= needed:
        new_bal = current - needed
        supabase.table("profiles").update({"credits": new_bal}).eq("id", user_id).execute()
        return True, needed
    return False, font_needed

def load_user_db(user_id):
    m_res = supabase.table("sku_mapping").select("portal_sku, master_sku").eq("user_id", user_id).execute()
    i_res = supabase.table("master_inventory").select("master_sku").eq("user_id", user_id).execute()
    df_map = pd.DataFrame(m_res.data) if m_res.data else pd.DataFrame(columns=['portal_sku', 'master_sku'])
    master_list = [i['master_sku'].upper() for i in i_res.data] if i_res.data else []
    return df_map, sorted(master_list)

# --- UTILS (Size & Extraction) ---
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
                header_idx = -1
                for i, row in enumerate(table):
                    row_str = " ".join([str(c).lower() for c in row if c])
                    if 'sku' in row_str and ('qty' in row_str or 'quantity' in row_str):
                        for idx, cell in enumerate(row):
                            c_text = str(cell).lower()
                            if 'sku' in c_text: sku_idx = idx
                            if 'size' in c_text: size_idx = idx
                            if 'qty' in c_text or 'quantity' in c_text: qty_idx = idx
                        header_idx = i
                        break
                if sku_idx is not None:
                    for row in table[header_idx + 1:]:
                        if not row[sku_idx]: continue
                        raw_sku = str(row[sku_idx]).strip()
                        size = str(row[size_idx]).strip() if size_idx is not None else ""
                        qty_val = 1
                        if qty_idx is not None:
                            nums = re.findall(r'\d+', str(row[qty_idx]))
                            qty_val = int(nums[0]) if nums else 1
                        data.append({'Portal_SKU': f"{raw_sku} {size}".strip(), 'Qty': qty_val})
    return pd.DataFrame(data)

# --- APP UI ---
if st.session_state.user is None:
    st.title("🚀 Smart Picklist Pro")
    st.subheader("The Ultimate E-commerce Mapping Tool")
    with st.sidebar:
        mode = st.radio("Choose Action", ["Login", "Signup"])
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if mode == "Login" and st.button("Login"): login_user(email, password)
        if mode == "Signup" and st.button("Create Account"): signup_user(email, password)
else:
    user_id = st.session_state.user.id
    credits = get_user_credits(user_id)
    
    # Sidebar
    st.sidebar.title("📊 Dashboard")
    st.sidebar.write(f"User: {st.session_state.user.email}")
    st.sidebar.metric("Available Credits", credits)
    if st.sidebar.button("Logout"):
        supabase.auth.sign_out(); st.session_state.user = None; st.rerun()

    with st.sidebar.expander("📥 Master Inventory Settings"):
        m_file = st.file_uploader("Upload Master SKU File", type=['csv'])
        if m_file and st.button("Sync Master List"):
            df_m = pd.read_csv(m_file)
            new_data = [{"user_id": user_id, "master_sku": str(s).upper()} for s in df_m.iloc[:,0].dropna().unique()]
            supabase.table("master_inventory").upsert(new_data, on_conflict="user_id, master_sku").execute()
            st.success("Master List Updated!"); st.rerun()

    # Main Order Processing
    st.title("📦 Order Processing")
    mapping_df, master_options = load_user_db(user_id)
    files = st.file_uploader("Upload Orders (Flipkart CSV / Meesho PDF)", type=["csv", "pdf"], accept_multiple_files=True)

    if files:
        orders_list = []
        for f in files:
            if f.name.endswith('.pdf'):
                pdf_df = extract_meesho_pdf(f)
                if not pdf_df.empty: orders_list.append(pdf_df)
            else:
                df = pd.read_csv(f)
                cols = {str(c).lower().strip().replace(" ", "_"): c for c in df.columns}
                s_col = next((cols[k] for k in ['sku', 'seller_sku', 'seller_sku_code'] if k in cols), None)
                q_col = next((cols[k] for k in ['quantity', 'qty', 'total_quantity'] if k in cols), None)
                if s_col:
                    qty_data = pd.to_numeric(df[q_col], errors='coerce').fillna(1) if q_col else 1
                    orders_list.append(pd.DataFrame({'Portal_SKU': df[s_col].astype(str).str.strip(), 'Qty': qty_data}))

        if orders_list:
            combined = pd.concat(orders_list, ignore_index=True)
            st.success("Upload complete. Ready to process.")
            
            if st.button("Generate Picklist"):
                order_count = len(combined)
                success, cost = deduct_credits(user_id, order_count)
                if success:
                    m_dict = dict(zip(mapping_df['portal_sku'].astype(str), mapping_df['master_sku'].astype(str)))
                    combined['Master_SKU'] = combined['Portal_SKU'].map(m_dict)
                    ready = combined.dropna(subset=['Master_SKU'])
                    
                    if not ready.empty:
                        st.success(f"Success! {cost} credits deducted for {order_count} orders.")
                        summary = ready.groupby('Master_SKU')['Qty'].sum().reset_index().sort_values('Qty', ascending=False)
                        st.dataframe(summary, use_container_width=True)
                    else:
                        st.warning("No mappings found. Please map new SKUs below.")
                else:
                    st.error(f"Low Balance! Need {cost} credits, have {credits}.")

            # --- REVIEW & MAPPING SECTION ---
            st.divider()
            m_dict = dict(zip(mapping_df['portal_sku'].astype(str), mapping_df['master_sku'].astype(str)))
            unmapped = [s for s in combined['Portal_SKU'].unique() if str(s) not in m_dict]
            if unmapped:
                st.subheader("🔍 Review New Mappings")
                if 'temp_res' not in st.session_state:
                    res = []
                    for s in unmapped:
                        best_m, _ = "Select Manually", 0
                        for opt in master_options:
                            score = fuzz.token_set_ratio(str(s).upper(), str(opt).upper())
                            if score > 90: best_m = opt; break
                        res.append({"Confirm": (best_m != "Select Manually"), "Portal SKU": s, "Master SKU": best_m})
                    st.session_state.temp_res = pd.DataFrame(res)

                edited_df = st.data_editor(st.session_state.temp_res, column_config={"Master SKU": st.column_config.SelectboxColumn(options=master_options)}, hide_index=True)
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Apply Pattern
