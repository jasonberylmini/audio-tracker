import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime, timedelta
import uuid
import time
from typing import List

# --- CONFIG ---
st.set_page_config(page_title="Production Tracker Pro — v2", layout="wide")
MAX_RETRY = 4
RETRY_BACKOFF = 1.0  # seconds
LOCK_TIMEOUT_MINUTES = 10  # questions locked longer than this are considered stale
BATCH_FLUSH_THRESHOLD = 5  # number of buffered logs before flushing
BATCH_FLUSH_INTERVAL = 30  # seconds between automatic flush attempts

# --- HELPERS ---
def get_ist_time():
    return datetime.utcnow() + timedelta(hours=5, minutes=30)

@st.cache_resource
def get_gspread_client():
    """Create gspread client with basic retry on transient failures."""
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    for attempt in range(1, MAX_RETRY + 1):
        try:
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            return gspread.authorize(creds)
        except Exception as e:
            if attempt == MAX_RETRY:
                raise
            time.sleep(RETRY_BACKOFF * attempt)

# --- Sheet URL: keep using the same sheet ---
SHEET_URL = st.secrets.get("SHEET_URL", "")
if not SHEET_URL:
    # fallback to older inline string if not in secrets
    SHEET_URL = "https://docs.google.com/spreadsheets/d/1zLXD14kx_lA61qkCpTkKsHDEIMvgLRiN58RY-j8OPsk/edit?usp=sharing"

client = get_gspread_client()
sh = client.open_by_url(SHEET_URL)
roster_sheet = sh.worksheet("Team_Roster")
questions_sheet = sh.worksheet("Master_Questions")
logs_sheet = sh.worksheet("Task_Logs")
activity_sheet = sh.worksheet("User_Activity")

# --- Robust write helpers ---
def append_row_retry(sheet, row: List, sleep_base=RETRY_BACKOFF):
    for attempt in range(1, MAX_RETRY + 1):
        try:
            # prefer append_rows for batch-friendly operations
            sheet.append_row(row)
            return True
        except Exception as e:
            if attempt == MAX_RETRY:
                st.error(f"Failed to append row after {MAX_RETRY} attempts: {e}")
                return False
            time.sleep(sleep_base * attempt)

def append_rows_retry(sheet, rows: List[List], sleep_base=RETRY_BACKOFF):
    # gspread has append_rows which is more efficient for multiple rows
    for attempt in range(1, MAX_RETRY + 1):
        try:
            sheet.append_rows(rows)
            return True
        except Exception as e:
            if attempt == MAX_RETRY:
                st.error(f"Failed to append rows after {MAX_RETRY} attempts: {e}")
                return False
            time.sleep(sleep_base * attempt)

def update_cell_retry(sheet, row: int, col: int, value, sleep_base=RETRY_BACKOFF):
    for attempt in range(1, MAX_RETRY + 1):
        try:
            sheet.update_cell(row, col, value)
            return True
        except Exception as e:
            if attempt == MAX_RETRY:
                st.error(f"Failed to update cell after {MAX_RETRY} attempts: {e}")
                return False
            time.sleep(sleep_base * attempt)

# --- Caching reads to reduce API calls ---
@st.cache_data(ttl=15)
def get_clean_df(ws):
    data = ws.get_all_values()
    if not data:
        return pd.DataFrame()
    return pd.DataFrame(data[1:], columns=data[0])

# --- Session state init ---
if 'user_status' not in st.session_state:
    st.session_state.user_status = "Logged Out"
if 'last_action_time' not in st.session_state:
    st.session_state.last_action_time = None
if 'log_buffer' not in st.session_state:
    st.session_state.log_buffer = []
if 'last_flush' not in st.session_state:
    st.session_state.last_flush = time.time()

# --- Utilities for locking questions ---
def clear_stale_locks():
    try:
        q_df = get_clean_df(questions_sheet)
        if q_df.empty:
            return
        now = get_ist_time()
        # ensure expected columns exist
        if 'Locked_By' not in q_df.columns:
            return
        # iterate rows and clear locks older than timeout
        for i, row in q_df.iterrows():
            lock_time_str = row.get('Locked_At', '')
            locked_by = row.get('Locked_By', '')
            if not lock_time_str or not locked_by:
                continue
            try:
                lock_time = datetime.strptime(lock_time_str, "%m/%d/%Y %H:%M:%S")
            except Exception:
                continue
            if now - lock_time > timedelta(minutes=LOCK_TIMEOUT_MINUTES):
                # row index + 2 because header row
                r = i + 2
                # Clear Locked_By and Locked_At
                update_cell_retry(questions_sheet, r, q_df.columns.get_loc('Locked_By') + 1, '')
                update_cell_retry(questions_sheet, r, q_df.columns.get_loc('Locked_At') + 1, '')
    except Exception as e:
        # don't crash the app if clearing locks fails
        st.session_state.get('last_lock_clear_error', None)

# --- Activity update helper ---
def update_google_status(email, action):
    now_ist = get_ist_time()
    now_str = now_ist.strftime("%m/%d/%Y %H:%M:%S")
    st.session_state.user_status = action
    st.session_state.last_action_time = now_ist
    try:
        cell = activity_sheet.find(email)
        if cell:
            # Current_Status is assumed to be column 2, Last_Action_Time column 3
            update_cell_retry(activity_sheet, cell.row, 2, action)
            update_cell_retry(activity_sheet, cell.row, 3, now_str)
        else:
            append_row_retry(activity_sheet, [email, action, now_str])
        # Log to Task_Logs lightly for audit
        append_row_retry(logs_sheet, [str(uuid.uuid4())[:8], "", 0, email, "", "", now_str, now_str[:10], "", action])
    except Exception as e:
        st.error(f"Sync error: {e}")

# --- Buffer & flush logic ---
def buffer_log(row: List):
    st.session_state.log_buffer.append(row)
    # Flush if threshold reached
    if len(st.session_state.log_buffer) >= BATCH_FLUSH_THRESHOLD:
        flush_buffered_logs()

def flush_buffered_logs(force=False):
    now = time.time()
    if not st.session_state.log_buffer:
        st.session_state.last_flush = now
        return
    if not force and now - st.session_state.last_flush < BATCH_FLUSH_INTERVAL and len(st.session_state.log_buffer) < BATCH_FLUSH_THRESHOLD:
        return
    rows = st.session_state.log_buffer.copy()
    success = append_rows_retry(logs_sheet, rows)
    if success:
        st.session_state.log_buffer = []
        st.session_state.last_flush = now

# Flush on app exit or manual flush button

# --- UI ---
st.sidebar.title("🕒 Login Panel (IST)")
roster_df = get_clean_df(roster_sheet)
email_list = sorted(roster_df['Worker_Email'].unique().tolist()) if not roster_df.empty else [""]
user_email = st.sidebar.selectbox("Verify Email", email_list)

# Simple Login Only
if st.session_state.user_status != "Login":
    if st.sidebar.button("🟢 Login", use_container_width=True):
        update_google_status(user_email, "Login")
        st.experimental_rerun()
else:
    st.sidebar.success("You are logged in")

st.sidebar.divider()

# Status Buttons
if st.session_state.user_status == "Logged Out":
    if st.sidebar.button("🟢 Login", use_container_width=True):
        update_google_status(user_email, "Login")
        st.experimental_rerun()
else:
    if st.sidebar.button("🔴 Logout", use_container_width=True):
        update_google_status(user_email, "Logged Out")
        st.experimental_rerun()

st.sidebar.divider()

if st.session_state.user_status == "Login":
    if st.sidebar.button("☕ Start Break", use_container_width=True):
        update_google_status(user_email, "Start Break")
        st.experimental_rerun()
elif st.session_state.user_status == "Start Break":
    # Show real-time break duration and enforce 60 min auto-logout
    if st.session_state.last_action_time:
        elapsed = get_ist_time() - st.session_state.last_action_time
        mins_used = int(elapsed.total_seconds() / 60)
        st.sidebar.warning(f"On Break: {mins_used} / 60 mins used")
        if mins_used > 60:
            # Force logout
            update_google_status(user_email, "Logged Out")
            st.sidebar.error("Break exceeded 60 minutes — auto logged out.")
            st.experimental_rerun()
    if st.sidebar.button("✅ End Break", type="primary", use_container_width=True):
        update_google_status(user_email, "End Break")
        st.experimental_rerun()

st.sidebar.divider()

# --- Main UI ---
st.title("🎙️ Production Tracker Pro — v2")
st.subheader(f"Current Status: **{st.session_state.user_status}**")

# Manager view toggle
is_manager = st.checkbox("Manager View / Dashboard")

# clear stale locks periodically (best-effort)
try:
    clear_stale_locks()
except Exception:
    pass

if st.session_state.user_status in ["Login", "End Break"]:
    with st.container():
        questions_df = get_clean_df(questions_sheet)
        q_list = []
        if not questions_df.empty and 'Question_ID' in questions_df.columns:
            q_list = sorted(questions_df['Question_ID'].astype(str).unique().tolist())

        col1, col2, col3 = st.columns([1, 2, 1])
        with col1:
            selected_q = st.selectbox("Select Question ID", q_list)
            # Manual lock/unlock controls
            if st.button("🔐 Lock Selected") and selected_q:
                # find the row in master questions and set Locked_By and Locked_At
                try:
                    q_cell = questions_sheet.find(str(selected_q))
                    r = q_cell.row
                    now_str = get_ist_time().strftime("%m/%d/%Y %H:%M:%S")
                    # ensure columns exist; be defensive
                    header = questions_sheet.row_values(1)
                    if 'Locked_By' not in header:
                        # append Locked_By and Locked_At columns to header (best-effort)
                        questions_sheet.update_cell(1, len(header) + 1, 'Locked_By')
                        questions_sheet.update_cell(1, len(header) + 2, 'Locked_At')
                        header = questions_sheet.row_values(1)
                    locked_by_col = header.index('Locked_By') + 1
                    locked_at_col = header.index('Locked_At') + 1
                    update_cell_retry(questions_sheet, r, locked_by_col, user_email)
                    update_cell_retry(questions_sheet, r, locked_at_col, now_str)
                    st.success("Question locked for you.")
                except Exception as e:
                    st.error(f"Could not lock question: {e}")
        with col2:
            task_mode = st.radio("Task Status", ["Completed", "In Progress"], horizontal=True)
            duration = None
            if selected_q and not questions_df.empty:
                q_match = questions_df[questions_df['Question_ID'].astype(str) == str(selected_q)]
                if not q_match.empty and 'Audio_Duration' in q_match.columns:
                    max_dur = float(q_match.iloc[0]['Audio_Duration'])
                else:
                    max_dur = 9999.0
                duration = st.number_input("Duration (s)", min_value=0.0, max_value=max_dur, value=max_dur if task_mode == 'Completed' else max_dur)
            else:
                duration = st.number_input("Duration (s)", min_value=0.0, value=0.0)
            if st.button("🚀 Submit Task"):
                # Pull worker info from roster
                if roster_df.empty:
                    st.error("Roster empty. Cannot submit.")
                else:
                    try:
                        worker = roster_df[roster_df['Worker_Email'] == user_email].iloc[0]
                    except Exception:
                        worker = { 'Worker_Name': '', 'Role': '' }
                    now_ist = get_ist_time().strftime("%m/%d/%Y %H:%M:%S")
                    proj_id = q_match.iloc[0]['Project_ID'] if (not questions_df.empty and not q_match.empty and 'Project_ID' in q_match.columns) else ''
                    row = [str(uuid.uuid4())[:8], str(selected_q), duration, user_email, worker.get('Worker_Name',''), worker.get('Role',''), now_ist, now_ist[:10], proj_id, task_mode]
                    # Buffer the log instead of direct write
                    buffer_log(row)
                    st.success("Task recorded (buffered) — will flush to sheet shortly.")
        with col3:
            if st.button("Next Available Question"):
                # find first unlocked question
                try:
                    q_df = questions_df if not questions_df.empty else pd.DataFrame()
                    found = False
                    if not q_df.empty:
                        header = list(q_df.columns)
                        for i, r in q_df.iterrows():
                            locked_by = r.get('Locked_By', '') if 'Locked_By' in header else ''
                            status = r.get('Status', '') if 'Status' in header else ''
                            if (not locked_by) and (not status or str(status).strip().lower() != 'completed'):
                                # lock it
                                rownum = i + 2
                                now_str = get_ist_time().strftime("%m/%d/%Y %H:%M:%S")
                                # ensure Locked_By / Locked_At exist
                                if 'Locked_By' not in header:
                                    questions_sheet.update_cell(1, len(header) + 1, 'Locked_By')
                                    questions_sheet.update_cell(1, len(header) + 2, 'Locked_At')
                                    header = questions_sheet.row_values(1)
                                locked_by_col = header.index('Locked_By') + 1
                                locked_at_col = header.index('Locked_At') + 1
                                update_cell_retry(questions_sheet, rownum, locked_by_col, user_email)
                                update_cell_retry(questions_sheet, rownum, locked_at_col, now_str)
                                st.success(f"Assigned question {r['Question_ID']} to you.")
                                found = True
                                break
                    if not found:
                        st.info("No unlocked questions found right now.")
                except Exception as e:
                    st.error(f"Could not assign question: {e}")

        # provide a manual flush button for the worker if needed
        if st.button("Flush buffered logs now"):
            flush_buffered_logs(force=True)
            st.success("Flush attempted")

else:
    st.warning("⚠️ Access Locked. Please Login to start working.")

# --- Manager Dashboard ---
if is_manager:
    st.markdown("---")
    st.header("Manager Dashboard")
    logs_df = get_clean_df(logs_sheet)
    if logs_df.empty:
        st.info("No logs yet.")
    else:
        # Basic metrics
        total_tasks = len(logs_df)
        today = get_ist_time().strftime("%m/%d/%Y")
        tasks_today = len(logs_df[logs_df['Date'] == today]) if 'Date' in logs_df.columns else 0
        avg_duration = logs_df['Duration'].astype(float).mean() if 'Duration' in logs_df.columns else 0
        active_workers = len(set(logs_df['Worker_Email'])) if 'Worker_Email' in logs_df.columns else 0
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Tasks", total_tasks)
        col2.metric("Tasks Today", tasks_today)
        col3.metric("Avg Duration (s)", f"{avg_duration:.2f}")
        col4.metric("Unique Workers", active_workers)

        # Top workers leaderboard
        if 'Worker_Email' in logs_df.columns:
            leaderboard = logs_df.groupby('Worker_Email').size().reset_index(name='count').sort_values('count', ascending=False)
            st.subheader("Top Workers")
            st.table(leaderboard.head(20))

        # Show recent activity
        st.subheader("Recent Logs")
        st.dataframe(logs_df.tail(200))

# --- housekeeping: periodic buffer flush ---
try:
    flush_buffered_logs()
except Exception:
    pass

# --- Footer ---
st.markdown("---")
st.caption("Production Tracker Pro — v2. Features: buffered writes, question locking, stale lock clearing, manager dashboard, auto-logout on long breaks.")
