import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime, timedelta
import uuid

# --- 1. SETTINGS & IST TIMEZONE ---
st.set_page_config(page_title="Production Tracker Pro", layout="wide")

def get_ist_time():
    # IST is UTC + 5:30
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

@st.cache_resource
def get_gspread_client():
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

# YOUR GOOGLE SHEET ID
SHEET_URL = "https://docs.google.com/spreadsheets/d/1zLXD14kx_lA61qkCpTkKsHDEIMvgLRiN58RY-j8OPsk/edit?usp=sharing"

client = get_gspread_client()
sh = client.open_by_url(SHEET_URL)
roster_sheet = sh.worksheet("Team_Roster")
questions_sheet = sh.worksheet("Master_Questions")
logs_sheet = sh.worksheet("Task_Logs")
activity_sheet = sh.worksheet("User_Activity")

# --- 2. SESSION STATE ---
if 'user_status' not in st.session_state:
    st.session_state.user_status = "Logged Out"

# --- 3. HELPER FUNCTIONS ---
def get_clean_df(ws):
    data = ws.get_all_values()
    if not data: return pd.DataFrame()
    return pd.DataFrame(data[1:], columns=data[0])

def update_google_status(email, action):
    now_ist = get_ist_time()
    now_str = now_ist.strftime("%m/%d/%Y %H:%M:%S")
    st.session_state.user_status = action
    
    try:
        # 1. Update the 'State' tab
        cell = activity_sheet.find(email)
        if cell:
            activity_sheet.update_cell(cell.row, 2, action)
            activity_sheet.update_cell(cell.row, 3, now_str)
        else:
            activity_sheet.append_row([email, action, now_str])
        
        # 2. Log event to Task_Logs
        logs_sheet.append_row([str(uuid.uuid4())[:8], "", 0, email, "", "", now_str, now_str[:10], "", action])
    except Exception as e:
        st.error(f"Sync error: {e}")

# --- 4. SIDEBAR ---
st.sidebar.title("🕒 Shift Control (IST)")
roster_df = get_clean_df(roster_sheet)
email_list = sorted(roster_df['Worker_Email'].unique().tolist())
user_email = st.sidebar.selectbox("Verify Email", email_list)

# Initial Sync
if st.sidebar.button("🔄 Sync Status"):
    activity_df = get_clean_df(activity_sheet)
    user_row = activity_df[activity_df['Worker_Email'] == user_email]
    if not user_row.empty:
        st.session_state.user_status = user_row.iloc[0]['Current_Status']
        st.session_state.last_time = user_row.iloc[0]['Last_Action_Time']

# Status Buttons
if st.session_state.user_status == "Logged Out":
    if st.sidebar.button("🟢 Login", use_container_width=True):
        update_google_status(user_email, "Login")
        st.rerun()
else:
    if st.sidebar.button("🔴 Logout", use_container_width=True):
        update_google_status(user_email, "Logged Out")
        st.rerun()

st.sidebar.divider()

if st.session_state.user_status in ["Login", "End Break"]:
    if st.sidebar.button("☕ Start Break", use_container_width=True):
        update_google_status(user_email, "Start Break")
        st.rerun()
elif st.session_state.user_status == "Start Break":
    # Calculating current break duration in real-time
    activity_df = get_clean_df(activity_sheet)
    start_time_str = activity_df[activity_df['Worker_Email'] == user_email].iloc[0]['Last_Action_Time']
    start_time = datetime.strptime(start_time_str, "%m/%d/%Y %H:%M:%S")
    elapsed = get_ist_time() - start_time
    mins_passed = int(elapsed.total_seconds() / 60)
    
    st.sidebar.warning(f"On Break: {mins_passed} / 60 mins used")
    
    if st.sidebar.button("✅ End Break", type="primary", use_container_width=True):
        update_google_status(user_email, "End Break")
        st.rerun()

# --- 5. MAIN CONTENT ---
st.title("🎙️ Production Log")
st.subheader(f"Current Status: **{st.session_state.user_status}**")

if st.session_state.user_status in ["Login", "End Break"]:
    with st.container(border=True):
        questions_df = get_clean_df(questions_sheet)
        q_list = sorted(questions_df['Question_ID'].astype(str).unique().tolist())
        selected_q = st.selectbox("Select Question ID", q_list)
        
        q_match = questions_df[questions_df['Question_ID'].astype(str) == selected_q]
        max_dur = float(q_match.iloc[0]['Audio_Duration'])
        proj_id = q_match.iloc[0]['Project_ID']

        task_mode = st.radio("Task Status", ["Completed", "In Progress"], horizontal=True)
        duration = st.number_input("Duration (s)", min_value=0.0, max_value=max_dur, value=max_dur) if task_mode == "In Progress" else max_dur

        if st.button("🚀 Submit Task"):
            worker = roster_df[roster_df['Worker_Email'] == user_email].iloc[0]
            now_ist = get_ist_time().strftime("%m/%d/%Y %H:%M:%S")
            logs_sheet.append_row([str(uuid.uuid4())[:8], selected_q, duration, user_email, worker['Worker_Name'], worker['Role'], now_ist, now_ist[:10], proj_id, task_mode])
            st.success("Task Recorded!")
else:
    st.warning("⚠️ Access Locked. Complete your shift actions in the sidebar.")
