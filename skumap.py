import streamlit as st
import pandas as pd
import re
import io
from datetime import datetime, timedelta, timezone
import extra_streamlit_components as stx 

# --- 1. CRITICAL IMPORTS ---
try:
    from supabase import create_client, Client
    from thefuzz import fuzz
    import pdfplumber
    from reportlab.pdfgen import canvas
    INCH = 72 
except ImportError:
    st.error("❌ Libraries are installing... Please wait.")
    st.stop()

# --- 2. CONFIG & DATABASE ---
st.set_page_config(page_title="Aavoni Ecom Suite", layout="wide", page_icon="📊")

cookie_manager = stx.CookieManager()

if "SUPABASE_URL" not in st.secrets or "SUPABASE_KEY" not in st.secrets:
    st.error("❌ Supabase Secrets Missing!")
    st.stop()

url = st.secrets["SUPABASE_URL"].strip()
key = st.secrets["SUPABASE_KEY"].strip()
supabase: Client = create_client(url, key)

if 'user' not in st.session_state: 
    st.session_state.user = None

# --- 3. PERSISTENT LOGIN (Stay Logged In) ---
if st.session_state.user is None:
    token = cookie_manager.get(cookie="sb-access-token")
    if token:
        try:
            res = supabase.auth.get_user(token)
            if res.user:
                st.session_state.user = res.user
        except:
            cookie_manager.delete("sb-access-token")

# --- 4. SHARED UTILS ---
def get_design_pattern(master_sku):
    sku = str(master_sku).upper().strip()
    sku = re.sub(r'[-_](S|M|L|XL|XXL|\d*XL|FREE|SMALL|LARGE)$', '', sku)
    return sku.strip('-_ ')

def get_smart_suffix(portal_sku):
    s_up = portal_sku.upper()
    for size_tag in ['XXXL', 'XXL', '3XL', '2XL', 'XL', 'L', 'M', 'S']:
        if re.search(rf'[-_\s]{size_tag}$', s_up) or s_up.endswith(size_tag):
            return size_tag
    return ""

@st.cache_data(ttl=300)
def load_all_data(u_id):
    try:
        m_res = supabase.table("sku_mapping").select("portal_sku, master_sku").eq("user_id", u_id).execute()
        i_res = supabase.table("master_inventory").select("master_sku").eq("user_id", u_id).execute()
        m_dict = {item['portal_sku'].upper(): item['master_sku'] for item in m_res.data} if m_res.data else {}
        m_list = sorted([str(i['master_sku']).upper() for i in i_res.data]) if i_res.data else []
        return m_dict, m_list
    except:
        return {}, []

def generate_4x6_pdf(df):
    buffer = io.BytesIO()
    w, h = 4 * INCH, 6 * INCH
    c = canvas.Canvas(buffer, pagesize=(w, h))
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(w/2, h - 30, "ORDERS PICKLIST")
    c.setFont("Helvetica", 9)
    y = h - 60
    for _, row in df.iterrows():
        if y < 40: c.showPage(); y = h - 40
        c.drawString(30, y, f"{row['Master_SKU']} x {row['Qty']}")
        y -= 15
    c.save()
    buffer.seek(0)
    return buffer

# --- 5. LOGIN/SIGNUP UI ---
def login_signup_ui():
    st.title("🚀 Aavoni Seller Suite")
    mode = st.radio("Action", ["Login", "Signup"])
    with st.form("auth_form"):
        e = st.text_input("Email")
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Submit"):
            try:
                if mode == "Signup":
                    supabase.auth.sign_up({"email": e, "password": p})
                    st.success("Signup Successful! Please Login.")
                else:
                    res = supabase.auth.sign_in_with_password({"email": e, "password": p})
                    if res.user:
                        st.session_state.user = res.user
                        cookie_manager.set("sb-access-token", res.session.access_token, expires_at=datetime.now() + timedelta(days=30))
                        st.rerun()
            except Exception as ex: st.error(f"Error: {ex}")

# --- 6. MAIN EXECUTION ---
if st.session_state.user is None:
    login_signup_ui()
else:
    u_id = st.session_state.user.id
    mapping_dict, master_options = load_all_data(u_id)
    master_set = set(master_options)

    with st.sidebar:
        st.write(f"👤 {st.session_state.user.email}")
        if st.button("Logout"):
            supabase.auth.sign_out()
            cookie_manager.delete("sb-access-token")
            st.session_state.user = None
            st.rerun()

    t1, t2 = st.tabs(["📦 Picklist & Mapping", "⚙️ Master Inventory"])

    with t1:
        files = st.file_uploader("Upload Orders", accept_multiple_files=True)
        if files:
            orders_data = []
            # ... (Order parsing logic same as before) ...
            # Dummy order data for structure:
            combined = pd.DataFrame([{'Portal_SKU': 'TEST-SKU-M', 'Qty': 1}]) 
            
            unmapped = [s for s in combined['Portal_SKU'].unique() if s not in mapping_dict]
            
            if unmapped:
                st.subheader("🔍 Smart Mapping")
                # BULK FETCH PATTERNS
                p_res = supabase.table("pattern_mapping").select("portal_base, master_base").eq("user_id", u_id).execute()
                pattern_memory = {i['portal_base']: i['master_base'] for i in p_res.data} if p_res.data else {}
                
                map_rows = []
                for s in unmapped:
                    best, hs, m_type = "Select", 0, "Fuzzy"
                    p_base = get_design_pattern(s)
                    
                    if p_base in pattern_memory:
                        m_base = pattern_memory[p_base]
                        size = get_smart_suffix(s)
                        suggested = f"{m_base}-{size}" if size else m_base
                        if suggested in master_set:
                            best, hs, m_type = suggested, 100, "Learned"
                        elif m_base in master_set:
                            best, hs, m_type = m_base, 95, "Pattern Only"
                    
                    if hs < 95:
                        for opt in master_options:
                            score = fuzz.token_set_ratio(s.upper(), opt.upper())
                            if score > hs: hs, best = score, opt
                    
                    map_rows.append({"Confirm": (hs >= 95), "Portal SKU": s, "Master SKU": best, "Match %": hs, "Mode": m_type})
                
                edited_map = st.data_editor(pd.DataFrame(map_rows), column_config={
                    "Match %": st.column_config.ProgressColumn(format="%d%%", min_value=0, max_value=100),
                    "Master SKU": st.column_config.SelectboxColumn(options=master_options)
                }, hide_index=True)

                if st.button("💾 Save & Learn"):
                    to_save = edited_map[edited_map['Confirm'] == True]
                    if not to_save.empty:
                        # 1. Save SKU Mapping
                        rows = [{"user_id": u_id, "portal_sku": r['Portal SKU'], "master_sku": r['Master SKU']} for _, r in to_save.iterrows()]
                        supabase.table("sku_mapping").upsert(rows).execute()
                        # 2. Save Pattern Memory
                        p_rows = []
                        seen = set()
                        for _, r in to_save.iterrows():
                            pb, mb = get_design_pattern(r['Portal SKU']), get_design_pattern(r['Master SKU'])
                            if pb not in seen:
                                p_rows.append({"user_id": u_id, "portal_base": pb, "master_base": mb})
                                seen.add(pb)
                        if p_rows:
                            supabase.table("pattern_mapping").upsert(p_rows, on_conflict="user_id, portal_base").execute()
                        st.cache_data.clear(); st.success("Saved!"); st.rerun()


    # --- TAB 2: COSTING MANAGER ---
    with t2:
        st.header("💰 Costing Manager")
        # Yahan hum current mapping list se unique designs nikalte hain
        all_master = list(set(mapping_dict.values()))
        all_designs = sorted(list(set([get_design_pattern(s) for s in all_master])))
        
        if not all_designs:
            st.warning("⚠️ Pehle SKUs map karein taaki designs list ban sake.")
        else:
            with st.form("cost_up"):
                col1, col2 = st.columns(2)
                sel = col1.selectbox("Select Design", options=all_designs)
                new_v = col2.number_input("Landed Cost (₹)", min_value=0.0, value=float(costing_dict.get(sel, 0.0)))
                if st.form_submit_button("Save Costing"):
                    supabase.table("design_costing").upsert({"user_id": u_id, "design_pattern": sel, "landed_cost": new_v}).execute()
                    st.cache_data.clear()
                    st.success(f"Saved: {sel} at ₹{new_v}")
                    st.rerun()
            
            if costing_dict:
                st.dataframe(pd.DataFrame(list(costing_dict.items()), columns=['Pattern', 'Cost']), use_container_width=True)

    # --- TAB 3 & 4: YOUR REMAINING LOGIC ---
    # (Note: In tabs ke andar bhi costing_dict aur mapping_dict ka hi use karein jo upar se aa rahe hain)

    # --- TAB 3: FLIPKART ANALYZER ---
    with t3:
        st.title("📊 Flipkart P/L")
        uploaded_file = st.file_uploader("Upload Flipkart Orders Excel (.xlsx)", type=["xlsx"])
        if uploaded_file:
            try:
                excel_data = pd.ExcelFile(uploaded_file)
                target_sheet = next((s for s in excel_data.sheet_names if "Orders P&L" in s), excel_data.sheet_names[0])
                df = pd.read_excel(uploaded_file, sheet_name=target_sheet)
                df.columns = [str(c).strip() for c in df.columns]
                sku_col, sett_col = "SKU Name", "Bank Settlement [Projected] (INR)"
                unit_col, id_col, status_col = "Net Units", "Order ID", "Order Status"

                if sku_col in df.columns and sett_col in df.columns:
                    df[unit_col] = pd.to_numeric(df[unit_col], errors='coerce').fillna(0).astype(int)
                    df[sett_col] = pd.to_numeric(df[sett_col], errors='coerce').fillna(0)
                    
                    def get_cat_data(sku_name):
                        p_sku = str(sku_name).strip().upper()
                        m_sku = mapping_dict.get(p_sku, p_sku)
                        pat = get_design_pattern(m_sku)
                        if pat in costing_dict: return "DB Match", costing_dict[pat]
                        is_hf = p_sku.startswith("HF")
                        base = hf_base if is_hf else std_base
                        if "3CBO" in p_sku: return "Combo 3", (base * 3)
                        if "CBO" in p_sku: return "Combo 2", (base * 2)
                        return ("HF Single" if is_hf else "Std Single"), base

                    res = df[sku_col].apply(get_cat_data)
                    df['Category'], df['Unit_Cost'] = [x[0] for x in res], [x[1] for x in res]
                    df['Net_Profit'] = df.apply(lambda x: x[sett_col] - (x[unit_col] * x['Unit_Cost']) if x[unit_col] > 0 else x[sett_col], axis=1)

                    m1, m2, m3 = st.columns(3)
                    t_pay, t_prof = df[sett_col].sum(), df['Net_Profit'].sum()
                    m1.metric("Total Settlement", f"₹{int(t_pay):,}")
                    m2.metric("Net Profit", f"₹{int(t_prof):,}", delta=f"{(t_prof/t_pay*100 if t_pay>0 else 0):.1f}% Margin")
                    m3.metric("Net Units Sold", f"{int(df[unit_col].sum()):,}")

                    st.divider()
                    st.subheader("💰 Category Performance")
                    summary = df.groupby('Category').agg({unit_col: 'sum', sett_col: 'sum', 'Net_Profit': 'sum'})
                    st.table(summary.fillna(0).astype(int))

                    st.subheader("🔎 All Orders Breakdown")
                    final_disp = df[[id_col, sku_col, 'Category', 'Unit_Cost', status_col, unit_col, sett_col, 'Net_Profit']].copy()
                    final_disp[sett_col] = final_disp[sett_col].round(0).astype(int)
                    final_disp['Net_Profit'] = final_disp['Net_Profit'].round(0).astype(int)
                    final_disp['Unit_Cost'] = final_disp['Unit_Cost'].round(0).astype(int)
                    st.dataframe(final_disp.sort_index(ascending=False), use_container_width=True, hide_index=True)

            except Exception as e: st.error(f"Error: {e}")

    with t4:
        st.title("👗 Myntra Smart P&L & Return Analyzer")

        uploaded_files = st.file_uploader(
            "Upload Flow + SKU + Settlement Files",
            type=['csv'],
            accept_multiple_files=True
        )

        def get_final_cost(sku_name):
            sku = str(sku_name).strip()
            mapped = mapping_dict.get(sku.upper(), sku)
            pattern = get_design_pattern(mapped)
            if pattern in costing_dict:
                return costing_dict[pattern]
            sku_up = sku.upper()
            if sku_up.startswith('HF'):
                return 230 if ('CBO' in sku_up or 'COMBO' in sku_up) else 115
            elif sku_up.startswith('PT'):
                return 330 if ('CBO' in sku_up or 'COMBO' in sku_up) else 165
            return 0

        # --- FIX: Sabhi logic button ke andar honi chahiye ---
        if st.button("Generate Smart Analysis"):
            if uploaded_files and len(uploaded_files) >= 3: # 3-4 files check

                flow_df = None
                sku_df = None
                fwd_list = []
                rev_list = []

                # --- FILE DETECTION ---
                for file in uploaded_files:
                    df = pd.read_csv(file)
                    # Column names ko clean karna zaroori hai KeyError se bachne ke liye
                    df.columns = [c.strip().lower() for c in df.columns]
                    cols = df.columns

                    if 'sale_order_code' in cols:
                        flow_df = df
                    elif 'seller sku code' in cols and 'total_actual_settlement' not in cols:
                        sku_df = df
                    elif 'total_actual_settlement' in cols:
                        temp_val = pd.to_numeric(df['total_actual_settlement'], errors='coerce').mean()
                        fname = file.name.lower()
                        if 'reverse' in fname or 'return' in fname or (temp_val is not None and temp_val < 0):
                            rev_list.append(df)
                        else:
                            fwd_list.append(df)

                # --- PROCESS ---
                if flow_df is not None and sku_df is not None:
                    # Merge logic (Lower case handles spaces/casing issues)
                    final = pd.merge(
                        flow_df,
                        sku_df[['order release id', 'seller sku code']].drop_duplicates(),
                        left_on='sale_order_code',
                        right_on='order release id',
                        how='left'
                    )

                    fwd_combined = pd.concat(fwd_list, ignore_index=True) if fwd_list else pd.DataFrame()
                    rev_combined = pd.concat(rev_list, ignore_index=True) if rev_list else pd.DataFrame()

                    fwd_sum = fwd_combined.groupby('order_release_id')['total_actual_settlement'].sum().reset_index() if not fwd_combined.empty else pd.DataFrame()
                    rev_sum = rev_combined.groupby('order_release_id')['total_actual_settlement'].sum().reset_index() if not rev_combined.empty else pd.DataFrame()

                    final = pd.merge(final, fwd_sum, left_on='sale_order_code', right_on='order_release_id', how='left')
                    final.rename(columns={'total_actual_settlement': 'Forward_Amt'}, inplace=True)

                    final = pd.merge(final, rev_sum, left_on='sale_order_code', right_on='order_release_id', how='left')
                    final.rename(columns={'total_actual_settlement': 'Reverse_Amt'}, inplace=True)

                    final['Forward_Amt'] = pd.to_numeric(final['Forward_Amt'], errors='coerce').fillna(0)
                    final['Reverse_Amt'] = pd.to_numeric(final['Reverse_Amt'], errors='coerce').fillna(0)
                    final['Net_Settlement'] = final['Forward_Amt'] + final['Reverse_Amt']
                    
                    final['seller sku code'] = final['seller sku code'].fillna("Unknown SKU")
                    final['order_item_status'] = final['order_item_status'].fillna("Not Found")

                    # COSTING
                    final['Unit_Cost'] = final['seller sku code'].apply(get_final_cost)
                    final['Total_Cost'] = final.apply(
                        lambda x: x['Unit_Cost'] if str(x['order_item_status']).lower() == 'delivered' else 0,
                        axis=1
                    )
                    final['Net_Profit'] = final['Net_Settlement'] - final['Total_Cost']

                    def label_order(net):
                        if net == 0: return "RTO"
                        if net < 0: return "Customer Return"
                        return "Delivered & Paid"

                    final['Order_Type'] = final['Net_Settlement'].apply(label_order)

                    # --- DASHBOARD ---
                    st.subheader("📊 Summary")
                    c1, c2, c3, c4 = st.columns(4)
                    total_settlement = final['Net_Settlement'].sum()
                    total_profit = final['Net_Profit'].sum()

                    c1.metric("Net Payout", f"₹{int(total_settlement):,}")
                    c2.metric("Total Cost", f"₹{int(final['Total_Cost'].sum()):,}")
                    c3.metric("Net Profit", f"₹{int(total_profit):,}")
                    c4.metric("Margin", f"{(total_profit/total_settlement*100 if total_settlement else 0):.1f}%")

                    st.divider()
                    st.subheader("📦 Orders")
                    st.dataframe(final[['sale_order_code', 'seller sku code', 'Order_Type', 'Net_Settlement', 'Net_Profit']], use_container_width=True)

                    # DOWNLOAD
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                        final.to_excel(writer, index=False)
                    st.download_button("📥 Download Excel", data=buffer.getvalue(), file_name="myntra_analysis.xlsx")
                    st.success("Done ✅")
                else:
                    st.error("Flow / SKU file missing. Check column names.")
            else:
                st.warning("Kam se kam 3-4 files upload karein (Flow, SKU, Settlements)")
