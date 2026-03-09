import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
from datetime import datetime
import uuid

# --- 1. SETTINGS & CONNECTION ---
st.set_page_config(page_title="Audio Transcription Tracker", layout="centered")

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

# --- 2. THE UI ---
st.title("🎙️ Audio Transcription Tracker")

with st.form("log_form", clear_on_submit=True):
    email = st.text_input("Enter your Work Email").strip().lower()
    action = st.selectbox("What are you doing?", ["Completed Task", "Login", "Start Break", "End Break", "Logout"])
    q_id = st.text_input("Question ID (Only if completing a task)")
    submit = st.form_submit_button("🚀 Submit Entry")

# --- 3. DATA PROCESSING ---
if submit:
    if not email:
        st.error("Email is required!")
    else:
        with st.spinner("Syncing..."):
            try:
                # NEW: Robust data loading that ignores phantom empty columns
                def get_clean_df(worksheet):
                    data = worksheet.get_all_values()
                    df = pd.DataFrame(data[1:], columns=data[0])
                    # Remove any columns that have no name or are purely whitespace
                    df = df.loc[:, ~df.columns.str.contains('^$|Unnamed', case=False)]
                    return df

                roster_df = get_clean_df(roster_sheet)
                questions_df = get_clean_df(questions_sheet)

                worker_match = roster_df[roster_df['Worker_Email'].str.lower() == email]

                if worker_match.empty:
                    st.error(f"Email '{email}' not found in Roster.")
                else:
                    name = worker_match.iloc[0]['Worker_Name']
                    role = worker_match.iloc[0]['Role']
                    
                    duration, proj_id = 0, ""
                    if action == "Completed Task":
                        q_match = questions_df[questions_df['Question_ID'].astype(str) == str(q_id)]
                        if not q_match.empty:
                            duration = q_match.iloc[0]['Audio_Duration']
                            proj_id = q_match.iloc[0]['Project_ID']

                    now = datetime.now()
                    new_row = [
                        str(uuid.uuid4())[:8], q_id, duration, email, name, role,
                        now.strftime("%m/%d/%Y %H:%M:%S"), now.strftime("%m/%d/%Y"), proj_id, action
                    ]
                    
                    logs_sheet.append_row(new_row)
                    st.success(f"Successfully logged {action} for {name}!")

            except Exception as e:
                st.error(f"Data Sync Error: {e}")
