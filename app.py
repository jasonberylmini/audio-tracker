import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime, timedelta
import uuid
import time

# --- 1. CONNECTION & IST TIMEZONE ---
st.set_page_config(page_title="Production Tracker Pro", layout="wide")

def get_ist_time():
    # Offset UTC to IST (+5:30)
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

@st.cache_resource
def get_gspread_client():
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

SHEET_URL = "https://docs.google.com/spreadsheets/d/1zLXD14kx_lA61qkCpTkKsHDEIMvgLRiN58RY-j8OPsk/edit?usp=sharing"

# Fail-safe loading
try:
    client = get_gspread_client()
    sh = client.open_by_url(SHEET_URL)
    roster_sheet = sh.worksheet("Team_Roster")
    questions_sheet = sh.worksheet("Master_Questions")
    logs_sheet = sh.worksheet("Task_Logs")
    activity_sheet = sh.worksheet("User_Activity")
except Exception as e:
    st.error(f"⚠️ Connection Error: {e}")
    st.info("Check your Tab names and permissions!")
    st.stop()

def get_clean_df(ws):
    # Added a tiny sleep to prevent API spam
    time.sleep(0.5)
    data = ws.get_all_values()
    if not data: return pd.DataFrame()
    df = pd.DataFrame(data[1:], columns=data[0])
    return df.loc[:, ~df.columns.str.contains('^$|Unnamed', case=False)]

# --- 2. LOAD DATA ---
roster_df = get_clean_df(roster_sheet)
questions_df = get_clean_df(questions_sheet)

# --- 3. SIDEBAR: SHIFT CONTROL ---
st.sidebar.title("🕒 Shift Control (IST)")

email_list = sorted(roster_df['Worker_Email'].unique().tolist())
user_email = st.sidebar.selectbox("Verify Email", email_list)

activity_df = get_clean_df(activity_sheet)
user_state_row = activity_df[activity_df['Worker_Email'] == user_email]

# Fixed the 'Current_Status' KeyError
if not user_state_row.empty and 'Current_Status' in user_state_row.columns:
    current_status = user_state_row.iloc[0]['Current_Status']
else:
    current_status = "Logged Out"

def update_state(email, action):
    now_ist = get_ist_time().strftime("%m/%d/%Y %H:%M:%S")
    # Finding the row manually to avoid full sheet refreshes
    cell = activity_sheet.find(email)
    if cell:
        activity_sheet.update_cell(cell.row, 2, action)
        activity_sheet.update_cell(cell.row, 3, now_ist)
    else:
        activity_sheet.append_row([email, action, now_ist])
    
    # Log the shift change
    logs_sheet.append_row([str(uuid.uuid4())[:8], "", 0, email, "", "", now_ist, now_ist[:10], "", action])
    st.rerun()

# Independent Status Buttons
if current_status == "Logged Out":
    if st.sidebar.button("🟢 Login", use_container_width=True):
        update_state(user_email, "Login")
else:
    if st.sidebar.button("🔴 Logout", use_container_width=True):
        update_state(user_email, "Logged Out")

st.sidebar.divider()

if current_status in ["Login", "End Break"]:
    if st.sidebar.button("☕ Start Break", use_container_width=True):
        update_state(user_email, "Start Break")
elif current_status == "Start Break":
    if st.sidebar.button("✅ End Break", type="primary", use_container_width=True):
        update_state(user_email, "End Break")

# --- 4. MAIN CONTENT ---
st.title("🎙️ Production Log")
st.subheader(f"Current Status: {current_status}")

if current_status in ["Login", "End Break"]:
    with st.container(border=True):
        q_list = sorted(questions_df['Question_ID'].astype(str).unique().tolist())
        selected_q = st.selectbox("Select Question ID", q_list)
        
        q_match = questions_df[questions_df['Question_ID'].astype(str) == selected_q]
        max_dur = float(q_match.iloc[0]['Audio_Duration'])
        proj_id = q_match.iloc[0]['Project_ID']

        task_mode = st.radio("Task Status", ["Completed", "In Progress"], horizontal=True)
        
        if task_mode == "In Progress":
            duration = st.number_input(f"Enter Duration (Max {max_dur}s)", min_value=0.0, max_value=max_dur, step=1.0)
        else:
            duration = max_dur
            st.info(f"Fixed Duration: {duration}s")

        if st.button("🚀 Submit Task"):
            worker = roster_df[roster_df['Worker_Email'] == user_email].iloc[0]
            now_ist = get_ist_time()
            
            logs_sheet.append_row([
                str(uuid.uuid4())[:8], selected_q, duration, user_email,
                worker['Worker_Name'], worker['Role'],
                now_ist.strftime("%m/%d/%Y %H:%M:%S"), now_ist.strftime("%m/%d/%Y"),
                proj_id, task_mode
            ])
            st.success(f"Task Logged at {now_ist.strftime('%H:%M:%S')} IST!")
else:
    st.warning("⚠️ Access Locked. Please Login or End Break to resume work.")
