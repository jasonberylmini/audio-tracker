import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime, timedelta
import uuid
import time

# ----------------------------
# CONFIG
# ----------------------------

st.set_page_config(page_title="Production Tracker Pro", layout="wide")

MAX_RETRY = 3
BATCH_FLUSH_THRESHOLD = 5

# ----------------------------
# TIME (IST)
# ----------------------------

def get_ist_time():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

# ----------------------------
# GOOGLE CONNECTION
# ----------------------------

@st.cache_resource
def get_gspread_client():
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]

    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)

    return gspread.authorize(creds)

client = get_gspread_client()

SHEET_URL = "https://docs.google.com/spreadsheets/d/1zLXD14kx_lA61qkCpTkKsHDEIMvgLRiN58RY-j8OPsk/edit"

sh = client.open_by_url(SHEET_URL)

# ----------------------------
# SHEETS
# ----------------------------

roster_sheet = sh.worksheet("Team_Roster")
questions_sheet = sh.worksheet("Master_Questions")
logs_sheet = sh.worksheet("Task_Logs")
activity_sheet = sh.worksheet("User_Activity")

# ----------------------------
# SAFE GOOGLE WRITE
# ----------------------------

def append_row_retry(sheet, row):

    for attempt in range(MAX_RETRY):
        try:
            sheet.append_row(row)
            return True
        except:
            time.sleep(1)

    st.error("Failed writing to Google Sheets")
    return False


def append_rows_retry(sheet, rows):

    for attempt in range(MAX_RETRY):
        try:
            sheet.append_rows(rows)
            return True
        except:
            time.sleep(1)

    st.error("Batch write failed")
    return False

# ----------------------------
# CACHE SHEET DATA
# ----------------------------

@st.cache_data(ttl=10)
def get_sheet_data(sheet_name):

    ws = sh.worksheet(sheet_name)

    data = ws.get_all_values()

    if not data:
        return pd.DataFrame()

    return pd.DataFrame(data[1:], columns=data[0])


# ----------------------------
# SESSION STATE
# ----------------------------

if "user_status" not in st.session_state:
    st.session_state.user_status = "Logged Out"

if "log_buffer" not in st.session_state:
    st.session_state.log_buffer = []

# ----------------------------
# LOGIN PANEL
# ----------------------------

st.sidebar.title("Login Panel (IST)")

roster_df = get_sheet_data("Team_Roster")

email_list = sorted(roster_df["Worker_Email"].unique().tolist())

user_email = st.sidebar.selectbox("Verify Email", email_list)

if st.session_state.user_status != "Login":

    if st.sidebar.button("🟢 Login"):

        st.session_state.user_status = "Login"

        now = get_ist_time().strftime("%m/%d/%Y %H:%M:%S")

        append_row_retry(activity_sheet, [user_email, "Login", now])

        st.rerun()

else:

    st.sidebar.success("Logged in")

# ----------------------------
# MAIN PAGE
# ----------------------------

st.title("🎙️ Production Tracker Pro")

st.subheader(f"Status: **{st.session_state.user_status}**")

# ----------------------------
# TASK LOGGING
# ----------------------------

if st.session_state.user_status == "Login":

    questions_df = get_sheet_data("Master_Questions")

    q_list = sorted(questions_df["Question_ID"].astype(str).unique().tolist())

    selected_q = st.selectbox("Select Question ID", q_list)

    q_match = questions_df[questions_df["Question_ID"].astype(str) == selected_q]

    max_dur = float(q_match.iloc[0]["Audio_Duration"])

    proj_id = q_match.iloc[0]["Project_ID"]

    task_mode = st.radio("Task Status", ["Completed", "In Progress"], horizontal=True)

    if task_mode == "In Progress":

        duration = st.number_input("Duration (s)", min_value=0.0, max_value=max_dur)

    else:

        duration = max_dur

    if st.button("🚀 Submit Task"):

        worker = roster_df[roster_df["Worker_Email"] == user_email].iloc[0]

        now = get_ist_time().strftime("%m/%d/%Y %H:%M:%S")

        row = [

            str(uuid.uuid4())[:8],
            selected_q,
            duration,
            user_email,
            worker["Worker_Name"],
            worker["Role"],
            now,
            now[:10],
            proj_id,
            task_mode,
        ]

        st.session_state.log_buffer.append(row)

        st.success("Task recorded!")

# ----------------------------
# BUFFER FLUSH
# ----------------------------

if len(st.session_state.log_buffer) >= BATCH_FLUSH_THRESHOLD:

    append_rows_retry(logs_sheet, st.session_state.log_buffer)

    st.session_state.log_buffer = []

# ----------------------------
# MANAGER DASHBOARD
# ----------------------------

st.divider()

if st.checkbox("Manager Dashboard"):

    logs_df = get_sheet_data("Task_Logs")

    if not logs_df.empty:

        total_tasks = len(logs_df)

        today = get_ist_time().strftime("%m/%d/%Y")

        tasks_today = len(logs_df[logs_df["Date"] == today])

        avg_duration = logs_df["Duration"].astype(float).mean()

        workers = len(logs_df["Worker_Email"].unique())

        col1, col2, col3, col4 = st.columns(4)

        col1.metric("Total Tasks", total_tasks)
        col2.metric("Tasks Today", tasks_today)
        col3.metric("Avg Duration", round(avg_duration,2))
        col4.metric("Workers", workers)

        st.subheader("Top Workers")

        leaderboard = (

            logs_df.groupby("Worker_Email")
            .size()
            .reset_index(name="Tasks")
            .sort_values("Tasks", ascending=False)

        )

        st.dataframe(leaderboard.head(20))

        st.subheader("Recent Logs")

        st.dataframe(logs_df.tail(200))

else:

    st.warning("⚠️ Please login to start working.")
