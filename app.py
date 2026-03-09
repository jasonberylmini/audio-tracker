import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime
import uuid

# --- 1. CONNECTION ---
st.set_page_config(page_title="Production Tracker Pro", layout="wide")

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
activity_sheet = sh.worksheet("User_Activity")

def get_clean_df(ws):
    data = ws.get_all_values()
    if not data: return pd.DataFrame()
    df = pd.DataFrame(data[1:], columns=data[0])
    return df.loc[:, ~df.columns.str.contains('^$|Unnamed', case=False)]

# --- 2. LOAD DATA ---
roster_df = get_clean_df(roster_sheet)
questions_df = get_clean_df(questions_sheet)

# --- 3. SIDEBAR: SHIFT CONTROL ---
st.sidebar.title("🕒 Shift Control")

# email dropdown without blank
email_list = sorted(roster_df['Worker_Email'].unique().tolist())
user_email = st.sidebar.selectbox("Verify Email", email_list)

# Fetch current state
activity_df = get_clean_df(activity_sheet)
user_state = activity_df[activity_df['Worker_Email'] == user_email]

# Robust check for the column
if not user_state.empty and 'Current_Status' in user_state.columns:
    current_status = user_state.iloc[0]['Current_Status']
else:
    current_status = "Logged Out"

def update_state(email, action):
    now = datetime.now().strftime("%m/%d/%Y %H:%M:%S")
    activity_data = activity_sheet.get_all_values()
    emails_in_sheet = [row[0] for row in activity_data]
    
    if email in emails_in_sheet:
        row_idx = emails_in_sheet.index(email) + 1
        activity_sheet.update_cell(row_idx, 2, action)
        activity_sheet.update_cell(row_idx, 3, now)
    else:
        activity_sheet.append_row([email, action, now])
    
    # Log the event
    logs_sheet.append_row([str(uuid.uuid4())[:8], "", 0, email, "", "", now, now[:10], "", action])
    st.rerun()

# Independent Buttons with State Logic
if current_status == "Logged Out":
    if st.sidebar.button("🟢 Login", use_container_width=True):
        update_state(user_email, "Login")
else:
    if st.sidebar.button("🔴 Logout", use_container_width=True):
        update_state(user_email, "Logged Out")

st.sidebar.divider()

# Break Logic: Cannot start break without ending it
if current_status in ["Login", "End Break"]:
    if st.sidebar.button("☕ Start Break", use_container_width=True):
        update_state(user_email, "Start Break")
elif current_status == "Start Break":
    # Button "Lits up" visually via type
    if st.sidebar.button("✅ End Break", type="primary", use_container_width=True):
        update_state(user_email, "End Break")

# --- 4. MAIN CONTENT: TASK LOGGING ---
st.title("🎙️ Production Log")
st.subheader(f"Status: {current_status}")

if current_status in ["Login", "End Break"]:
    with st.container(border=True):
        # Question dropdown without blank
        q_list = sorted(questions_df['Question_ID'].astype(str).unique().tolist())
        selected_q = st.selectbox("Select Question ID", q_list)
        
        q_match = questions_df[questions_df['Question_ID'].astype(str) == selected_q]
        max_dur = float(q_match.iloc[0]['Audio_Duration'])
        proj_id = q_match.iloc[0]['Project_ID']

        task_mode = st.radio("Task Status", ["Completed", "In Progress"], horizontal=True)
        
        if task_mode == "In Progress":
            # Manual entry with CAP
            duration = st.number_input(f"Enter Duration (Max {max_dur}s)", min_value=0.0, max_value=max_dur, step=1.0)
        else:
            duration = max_dur
            st.info(f"Fixed Duration: {duration}s")

        if st.button("🚀 Submit Task"):
            worker = roster_df[roster_df['Worker_Email'] == user_email].iloc[0]
            now = datetime.now()
            
            logs_sheet.append_row([
                str(uuid.uuid4())[:8], selected_q, duration, user_email,
                worker['Worker_Name'], worker['Role'],
                now.strftime("%m/%d/%Y %H:%M:%S"), now.strftime("%m/%d/%Y"),
                proj_id, task_mode
            ])
            st.success("Task Recorded!")
            st.balloons()
else:
    st.warning("⚠️ Access Locked. Please **Login** or **End Break** in the sidebar to resume work.")
