import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime
import uuid

# --- 1. CONNECT TO GOOGLE SHEETS ---
def get_gspread_client():
    # Grabs the secret key you pasted into Streamlit Secrets
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

# PASTE YOUR FULL GOOGLE SHEET URL BETWEEN THE QUOTES BELOW
SHEET_URL = "https://docs.google.com/spreadsheets/d/1zLXD14kx_lA61qkCpTkKsHDEIMvgLRiN58RY-j8OPsk/edit?usp=sharing"

client = get_gspread_client()
sh = client.open_by_url(SHEET_URL)

# Define our worksheets based on your tabs
roster_sheet = sh.worksheet("Team_Roster")
questions_sheet = sh.worksheet("Master_Questions")
logs_sheet = sh.worksheet("Task_Logs")

# --- 2. THE UI ---
st.title("🎙️ Audio Transcription Tracker")

with st.form("log_form", clear_on_submit=True):
    email = st.text_input("Enter your Work Email").strip().lower()
    action = st.selectbox("What are you doing?", ["Completed Task", "Login", "Start Break", "End Break", "Logout"])
    q_id = st.text_input("Question ID (Only if completing a task)")
    
    submit = st.form_submit_button("Submit Entry")

if submit:
    if not email:
        st.error("Email is required!")
    else:
        with st.spinner("Syncing with Google Sheets..."):
            # Fetch data from your tabs to automate the log
            roster_data = pd.DataFrame(roster_sheet.get_all_records())
            questions_data = pd.DataFrame(questions_sheet.get_all_records())
            
            # Match worker info
            worker_row = roster_data[roster_data['Worker_Email'].str.lower() == email]
            
            if worker_row.empty:
                st.error("Email not found in Team_Roster! Check with your lead.")
            else:
                name = worker_row.iloc[0]['Worker_Name']
                role = worker_row.iloc[0]['Role']
                
                # Default values
                duration = 0
                proj_id = ""
                
                # If they finished a file, look up the specs
                if action == "Completed Task" and q_id:
                    # Convert q_id to int if your sheet stores them as numbers
                    match = questions_data[questions_data['Question_ID'].astype(str) == str(q_id)]
                    if not match.empty:
                        duration = match.iloc[0]['Audio_Duration']
                        proj_id = match.iloc[0]['Project_ID']
                    else:
                        st.warning("Question ID not found in Master list. Logging with 0 duration.")

                # Prepare the row for Task_Logs
                # Columns: Log_ID, Question_ID, Audio_Duration, Worker_Email, Worker_Name, Role, Timestamp, Shift_Date, Project_ID, Task_Status
                now = datetime.now()
                new_row = [
                    str(uuid.uuid4())[:8],
                    q_id,
                    duration,
                    email,
                    name,
                    role,
                    now.strftime("%m/%d/%Y %H:%M:%S"),
                    now.strftime("%m/%d/%Y"),
                    proj_id,
                    action
                ]
                
                logs_sheet.append_row(new_row)
                st.success(f"Done! Logged '{action}' for {name}.")
                
                # Quick motivation for QC 180-min target
                if role == "QC" and action == "Completed Task":
                    mins = round(float(duration)/60, 2)
                    st.info(f"That's {mins} mins added to your daily progress!")
