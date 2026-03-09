import streamlit as st
import pandas as pd
from datetime import datetime
import uuid
import time

st.set_page_config(page_title="Task Logger", layout="centered")

st.title("🎧 Audio Task Logger")

# We would load your Google Sheets into Pandas DataFrames here behind the scenes.
# For example: 
# roster_df = load_google_sheet("Team_Roster")
# questions_df = load_google_sheet("Master_Questions")

with st.form("task_form"):
    # Worker identifies themselves
    email = st.text_input("Worker Email (e.g., desicrew.sajith@gmail.com)")
    
    # What are they doing right now?
    status = st.selectbox("Action", ["Completed Task", "Login", "Start Break", "End Break", "Logout"])
    
    # Only need the ID if they are actually logging a completed audio file
    question_id = st.text_input("Question ID (Leave blank if just logging a break/shift)")
    
    submitted = st.form_submit_button("Submit Log")

if submitted:
    if not email:
        st.error("Whoops, need your email to log this!")
    else:
        with st.spinner("Processing..."):
            # 1. Auto-generate the data
            log_id = uuid.uuid4().hex[:8] # Creates a random ID like '49660a20'
            current_time = datetime.now()
            timestamp = current_time.strftime("%m/%d/%Y %H:%M:%S")
            shift_date = current_time.strftime("%m/%d/%Y")
            
            # 2. Vibe Check: In the real app, we look up these values from your DataFrames
            # worker_name = roster_df.loc[roster_df['Worker_Email'] == email, 'Worker_Name'].values[0]
            # role = roster_df.loc[roster_df['Worker_Email'] == email, 'Role'].values[0]
            # audio_duration = questions_df.loc[questions_df['Question_ID'] == question_id, 'Audio_Duration'].values[0]
            # project_id = questions_df.loc[questions_df['Question_ID'] == question_id, 'Project_ID'].values[0]
            
            # Placeholder values for demonstration
            worker_name = "Auto-Fetched Name"
            role = "QC" 
            audio_duration_seconds = 64.09
            project_id = "ID-107"
            
            if status != "Completed Task":
                # If it's a break or login, wipe the task-specific data for a clean log
                question_id = ""
                audio_duration_seconds = 0
                project_id = ""

            # 3. Create the exact row for your Task_Logs sheet
            new_row = [
                log_id, question_id, audio_duration_seconds, email, 
                worker_name, role, timestamp, shift_date, project_id, status
            ]
            
            # 4. Save to Google Sheets
            time.sleep(1) # API throttle protection
            # sheet.append_row(new_row)
            
            st.success("Log saved successfully!")
            
            # Let's keep your team on track. 
            # We convert the seconds from your tool into minutes to check against targets.
            if role == "QC" and status == "Completed Task":
                duration_mins = round(audio_duration_seconds / 60, 2)
                st.info(f"Nice! That's {duration_mins} minutes closer to your 180-minute daily target.")
