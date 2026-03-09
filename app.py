import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime
import uuid
import time

# --- 1. SETTINGS & CONNECTION ---
st.set_page_config(page_title="Audio Transcription Tracker", layout="centered")

# Using st.cache_resource so we don't reconnect on every click
@st.cache_resource
def get_gspread_client():
    try:
        creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        st.error("❌ Failed to authenticate with Google. Check your Streamlit Secrets.")
        st.stop()

# YOUR GOOGLE SHEET CONFIG
SHEET_URL = "https://docs.google.com/spreadsheets/d/1zLXD14kx_lA61qkCpTkKsHDEIMvgLRiN58RY-j8OPsk/edit?usp=sharing"

try:
    client = get_gspread_client()
    sh = client.open_by_url(SHEET_URL)
    
    # Connect to your specific tabs
    roster_sheet = sh.worksheet("Team_Roster")
    questions_sheet = sh.worksheet("Master_Questions")
    logs_sheet = sh.worksheet("Task_Logs")
except Exception as e:
    st.error(f"❌ Could not connect to worksheets. Error: {e}")
    st.info("Ensure tab names are exactly 'Team_Roster', 'Master_Questions', and 'Task_Logs'.")
    st.stop()

# --- 2. THE USER INTERFACE ---
st.title("🎙️ Audio Transcription Tracker")
st.markdown("Enter your details below to log your work or shift status.")

with st.form("log_form", clear_on_submit=True):
    email = st.text_input("Enter your Work Email (e.g., desicrew.sajith@gmail.com)").strip().lower()
    action = st.selectbox("What are you doing?", ["Completed Task", "Login", "Start Break", "End Break", "Logout"])
    q_id = st.text_input("Question ID (Leave blank for Login/Logout/Break)")
    
    submit = st.form_submit_button("🚀 Submit Entry")

# --- 3. THE LOGIC ---
if submit:
    if not email:
        st.error("Email is required to log data.")
    elif action == "Completed Task" and not q_id:
        st.error("Please provide a Question ID for completed tasks.")
    else:
        with st.spinner("Syncing with Master Records..."):
            try:
                # Load data into DataFrames for fast lookup
                roster_df = pd.DataFrame(roster_sheet.get_all_records())
                questions_df = pd.DataFrame(questions_sheet.get_all_records())
                
                # Check if worker exists in Team_Roster
                worker_match = roster_df[roster_df['Worker_Email'].str.lower() == email]
                
                if worker_match.empty:
                    st.error(f"Worker with email '{email}' not found in Team_Roster tab.")
                else:
                    worker_name = worker_match.iloc[0]['Worker_Name']
                    worker_role = worker_match.iloc[0]['Role']
                    
                    # Default values for non-task logs
                    audio_duration = 0
                    project_id = ""
                    
                    # If it's a task, find the duration and project
                    if action == "Completed Task":
                        q_match = questions_df[questions_df['Question_ID'].astype(str) == str(q_id)]
                        if not q_match.empty:
                            audio_duration = q_match.iloc[0]['Audio_Duration']
                            project_id = q_match.iloc[0]['Project_ID']
                        else:
                            st.warning(f"Question ID '{q_id}' not found in Master_Questions. Logging with 0 duration.")

                    # Build the row to append to Task_Logs
                    now = datetime.now()
                    new_log_entry = [
                        str(uuid.uuid4())[:8],       # Log_ID
                        q_id,                        # Question_ID
                        audio_duration,              # Audio_Duration
                        email,                       # Worker_Email
                        worker_name,                 # Worker_Name
                        worker_role,                 # Role
                        now.strftime("%m/%d/%Y %H:%M:%S"), # Timestamp
                        now.strftime("%m/%d/%Y"),    # Shift_Date
                        project_id,                  # Project_ID
                        action                       # Task_Status
                    ]
                    
                    # Append to Google Sheets
                    logs_sheet.append_row(new_log_entry)
                    st.success(f"Successfully logged {action} for {worker_name}!")
                    
                    # QC Target Feedback (180-min goal)
                    if worker_role == "QC" and action == "Completed Task":
                        # Convert duration (seconds) to minutes
                        mins = round(float(audio_duration) / 60, 2)
                        st.balloons()
                        st.info(f"Progress: Added {mins} minutes to your daily QC goal!")

            except Exception as e:
                st.error(f"Data Sync Error: {e}")
                st.info("Try submitting again in a few seconds.")
