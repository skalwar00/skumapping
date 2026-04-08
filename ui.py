import streamlit as st

def apply_ui():
    st.markdown("""
    <style>
    .stApp {background-color: #f9fafb;}

    .top-header {
        display:flex;
        justify-content:space-between;
        align-items:center;
        background:white;
        padding:15px 25px;
        border-radius:10px;
        border:1px solid #e5e7eb;
        margin-bottom:20px;
    }

    .top-header h1 {
        color:#2563eb;
        margin:0;
    }

    .top-header p {
        color:#6b7280;
        margin:0;
    }

    section[data-testid="stSidebar"] {
        background-color:#f3f4f6;
    }

    .stButton>button {
        background:#2563eb;
        color:white;
        border-radius:8px;
        height:42px;
        font-weight:600;
        border:none;
    }

    .stButton>button:hover {
        background:#1e40af;
    }

    [data-testid="stFileUploader"] {
        border:2px dashed #d1d5db;
        padding:18px;
        border-radius:10px;
        background:white;
    }

    [data-testid="stMetric"] {
        background:white;
        padding:15px;
        border-radius:10px;
        border:1px solid #e5e7eb;
    }
    </style>
    """, unsafe_allow_html=True)

def show_header():
    st.markdown("""
    <div class="top-header">
        <h1>🚀 SmartSeller Suite</h1>
        <p>Seller Automation Dashboard</p>
    </div>
    """, unsafe_allow_html=True)
