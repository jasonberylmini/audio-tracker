import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime, timedelta
import uuid
import time

st.set_page_config(page_title="Production Tracker Pro", layout="wide")

# -----------------------------
# TIME FUNCTION
# -----------------------------

def get_ist_time():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

# -----------------------------
# GOOGLE CONNECTION
# -----------------------------

@st.cache_resource
def get_gspread_client():

    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]

    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)

    return gspread.authorize(creds)

client = get_gspread_client()

SHEET_URL = "https://docs.google.com/spreadsheets/d/1zLXD14kx_lA61qkCpTkKsHDEIMvgLRiN58RY-j8OPsk/edit"

sh = client.open_by_url(SHEET_URL)

roster_sheet = sh.worksheet("Team_Roster")
questions_sheet = sh.worksheet("Master_Questions")
logs_sheet = sh.worksheet("Task_Logs")
activity_sheet = sh.worksheet("User_Activity")

# -----------------------------
# SAFE WRITE
# -----------------------------

def append_row_retry(sheet, row):

    for i in range(3):
        try:
            sheet.append_row(row)
            return True
        except:
            time.sleep(1)

    st.error("Google Sheets write failed")
    return False


# -----------------------------
# CACHE DATA
# -----------------------------

@st.cache_data(ttl=10)
def get_sheet_data(sheet_name):

    ws = sh.worksheet(sheet_name)

    data = ws.get_all_values()

    if not data:
        return pd.DataFrame()

    return pd.DataFrame(data[1:], columns=data[0])


# -----------------------------
# SESSION STATE
# -----------------------------

if "user_status" not in st.session_state:
    st.session_state.user_status = "Logged Out"

# -----------------------------
# LOGIN PANEL
# -----------------------------

st.sidebar.title("Login Panel")

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

# -----------------------------
# MAIN APP
# -----------------------------

st.title("🎙️ Production Tracker Pro")

st.subheader(f"Status: **{st.session_state.user_status}**")

if st.session_state.user_status == "Login":

    questions_df = get_sheet_data("Master_Questions")
    logs_df = get_sheet_data("Task_Logs")

    q_list = sorted(questions_df["Question_ID"].astype(str).unique().tolist())

    selected_q = st.selectbox("Select Question ID", q_list)

    q_match = questions_df[questions_df["Question_ID"].astype(str) == selected_q]

    max_dur = float(q_match.iloc[0]["Audio_Duration"])
    proj_id = q_match.iloc[0]["Project_ID"]

    st.write(f"Max allowed duration: **{max_dur} seconds**")

    task_mode = st.radio("Task Status", ["In Progress", "Completed"], horizontal=True)

    duration = st.number_input(
        "Duration (s)",
        min_value=0.0,
        value=max_dur if task_mode == "Completed" else 0.0,
    )

    if st.button("🚀 Submit Task"):

        # -------------------------
        # VALIDATE DURATION
        # -------------------------

        if duration > max_dur:

            st.error(f"Duration cannot exceed {max_dur} seconds")
            st.stop()

        # -------------------------
        # CHECK EXISTING RECORDS
        # -------------------------

        existing = logs_df[logs_df["Question_ID"].astype(str) == selected_q]

        # CASE 1: already completed
        if not existing.empty and "Completed" in existing["Task_Status"].values:

            st.error("❌ This audio has already been completed.")
            st.stop()

        # CASE 2: already in progress
        if not existing.empty and "In Progress" in existing["Task_Status"].values:

            row = existing[existing["Task_Status"] == "In Progress"].iloc[0]

            # another worker trying
            if row["Worker_Email"] != user_email:

                st.error("❌ This audio is already being processed by another worker.")
                st.stop()

            # same worker completing
            if task_mode == "Completed":

                row_index = row.name
                sheet_row = row_index + 2

                logs_sheet.update_cell(sheet_row, 3, duration)
                logs_sheet.update_cell(sheet_row, 10, "Completed")

                st.success("Task marked as completed!")

                st.cache_data.clear()

                st.stop()

        # -------------------------
        # NEW TASK ENTRY
        # -------------------------

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

        success = append_row_retry(logs_sheet, row)

        if success:
            st.success("Task recorded!")

        st.cache_data.clear()

else:

    st.warning("⚠️ Please login to start working.")
