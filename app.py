import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime
import uuid

# --- 1. CONNECTION ---
st.set_page_config(page_title="Production Tracker v3", layout="wide")

@st.cache_resource
def get_gspread_client():
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

SHEET_URL = "https://docs.google.com/spreadsheets/d/1zLXD14kx_lA61qkCpTkKsHDEIMvgLRiN58RY-j8OPsk/edit?usp=sharing"

client = get_gspread_client()
sh = client.open_by_url(SHEET_URL)
roster_sheet = sh.worksheet("Team_Roster")
questions_sheet = sh.worksheet("Master_Questions")
logs_sheet = sh.worksheet("Task_Logs")
# New tab for state tracking
try:
    activity_sheet = sh.worksheet("User_Activity")
except:
    st.error("Please create a 'User_Activity' tab in your Google Sheet first!")
    st.stop()

def get_clean_df(ws):
    data = ws.get_all_values()
    return pd.DataFrame(data[1:], columns=data[0])

# --- 2. LOAD DATA ---
roster_df = get_clean_df(roster_sheet)
questions_df = get_clean_df(questions_sheet)

# --- 3. SIDEBAR: SHIFT CONTROL ---
st.sidebar.title("🕒 Shift Control")
email_list = sorted(roster_df['Worker_Email'].unique().tolist())
user_email = st.sidebar.selectbox("Verify Email", email_list) # No blank option

# Fetch current user state from Google Sheets
activity_df = get_clean_df(activity_sheet)
user_state_row = activity_df[activity_df['Worker_Email'] == user_email]
current_status = user_state_row.iloc[0]['Current_Status'] if not user_state_row.empty else "Logged Out"

col1, col2 = st.sidebar.columns(2)

def log_activity(email, action):
    now = datetime.now().strftime("%m/%d/%Y %H:%M:%S")
    # Update state tab
    if user_state_row.empty:
        activity_sheet.append_row([email, action, now])
    else:
        cell = activity_sheet.find(email)
        activity_sheet.update_cell(cell.row, 2, action)
        activity_sheet.update_cell(cell.row, 3, now)
    
    # Log to main Task_Logs for reporting
    logs_sheet.append_row([str(uuid.uuid4())[:8], "", 0, email, "", "", now, now[:10], "", action])
    st.sidebar.success(f"{action} Recorded!")
    st.rerun()

# Button Logic: Independent and state-aware
if current_status == "Logged Out":
    if st.sidebar.button("🟢 Login", use_container_width=True):
        log_activity(user_email, "Login")
else:
    if st.sidebar.button("🔴 Logout", use_container_width=True):
        log_activity(user_email, "Logout")

if current_status == "Login" or current_status == "End Break":
    if st.sidebar.button("☕ Start Break", use_container_width=True):
        log_activity(user_email, "Start Break")
elif current_status == "Start Break":
    if st.sidebar.button("✅ End Break", color="green", use_container_width=True):
        log_activity(user_email, "End Break")

# --- 4. MAIN CONTENT: TASK LOGGING ---
st.title("🎙️ Production Log")
st.info(f"Current Status: **{current_status}**")

if current_status in ["Login", "End Break"]:
    with st.container(border=True):
        # 1. Question ID Dropdown
        q_list = questions_df['Question_ID'].astype(str).unique().tolist()
        selected_q = st.selectbox("Select Question ID", q_list) # No blank option
        
        # Look up actual duration
        q_match = questions_df[questions_df['Question_ID'].astype(str) == selected_q]
        max_duration = float(q_match.iloc[0]['Audio_Duration'])
        proj_id = q_match.iloc[0]['Project_ID']

        # 2. Task Status Logic
        task_status = st.radio("Task Status", ["Completed", "In Progress"], index=0, horizontal=True)
        
        if task_status == "In Progress":
            duration = st.number_input("Enter Audio Duration (secs)", min_value=0.0, max_value=max_duration, step=1.0)
            st.caption(f"⚠️ Limit: {max_duration}s")
        else:
            duration = max_duration
            st.success(f"Fixed Duration: {duration}s")

        if st.button("Submit Task"):
            now = datetime.now()
            worker_info = roster_df[roster_df['Worker_Email'] == user_email].iloc[0]
            
            new_row = [
                str(uuid.uuid4())[:8], selected_q, duration, user_email,
                worker_info['Worker_Name'], worker_info['Role'],
                now.strftime("%m/%d/%Y %H:%M:%S"), now.strftime("%m/%d/%Y"),
                proj_id, task_status
            ]
            logs_sheet.append_row(new_row)
            st.toast("Task Logged!", icon="🚀")
else:
    st.warning("Please Login or End your Break to log tasks.")
