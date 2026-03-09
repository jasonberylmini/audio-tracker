import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime
import uuid

# --- 1. SETTINGS & CONNECTION ---
st.set_page_config(page_title="Audio Tracker Pro", layout="centered")

@st.cache_resource
def get_gspread_client():
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

SHEET_URL = "https://docs.google.com/spreadsheets/d/1zLXD14kx_lA61qkCpTkKsHDEIMvgLRiN58RY-j8OPsk/edit?usp=sharing"

# Load Sheets
client = get_gspread_client()
sh = client.open_by_url(SHEET_URL)
roster_sheet = sh.worksheet("Team_Roster")
questions_sheet = sh.worksheet("Master_Questions")
logs_sheet = sh.worksheet("Task_Logs")

# Utility to clean phantom columns
def get_clean_df(ws):
    data = ws.get_all_values()
    df = pd.DataFrame(data[1:], columns=data[0])
    return df.loc[:, ~df.columns.str.contains('^$|Unnamed', case=False)]

# --- 2. DATA PRE-LOADING ---
# We load these once so the dropdowns are snappy
roster_df = get_clean_df(roster_sheet)
questions_df = get_clean_df(questions_sheet)

# --- 3. THE UI ---
st.title("🎙️ Audio Transcription Tracker")

# 1. Email Dropdown
email_list = sorted(roster_df['Worker_Email'].unique().tolist())
selected_email = st.selectbox("Select Your Work Email", [""] + email_list)

# 2. Action Selection
action = st.selectbox("What are you doing?", ["Completed Task", "Login", "Start Break", "End Break", "Logout"])

# 3. Dynamic Question ID & Duration Pop-up
q_id = ""
duration = 0
proj_id = ""

if action == "Completed Task":
    q_list = questions_df['Question_ID'].astype(str).unique().tolist()
    q_id = st.selectbox("Select Question ID", [""] + q_list)
    
    if q_id:
        # Auto-lookup the duration in real-time
        match = questions_df[questions_df['Question_ID'].astype(str) == q_id]
        if not match.empty:
            duration = float(match.iloc[0]['Audio_Duration'])
            proj_id = match.iloc[0]['Project_ID']
            # The "Auto Pop-up"
            st.metric(label="Audio Duration (Seconds)", value=f"{duration}s")
            st.caption(f"Project: {proj_id}")

# --- 4. THE SUBMISSION ---
if st.button("🚀 Submit Entry"):
    if not selected_email:
        st.error("Please select your email!")
    elif action == "Completed Task" and not q_id:
        st.error("Please select a Question ID!")
    else:
        with st.spinner("Logging data..."):
            # Get Worker Details
            worker_row = roster_df[roster_df['Worker_Email'] == selected_email]
            name = worker_row.iloc[0]['Worker_Name']
            role = worker_row.iloc[0]['Role']
            
            now = datetime.now()
            # Prepare the final row for Task_Logs
            new_row = [
                str(uuid.uuid4())[:8], q_id, duration, selected_email, 
                name, role, now.strftime("%m/%d/%Y %H:%M:%S"), 
                now.strftime("%m/%d/%Y"), proj_id, action
            ]
            
            logs_sheet.append_row(new_row)
            st.success(f"Successfully logged {action} for {name}!")
            
            if role == "QC" and action == "Completed Task":
                st.balloons()
