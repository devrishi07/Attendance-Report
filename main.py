import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timedelta
from prettytable import PrettyTable
import re

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------
BASE_URL = "https://sraap.in"
LOGIN_URL = f"{BASE_URL}/student_login.php"
CAPTCHA_URL = f"{BASE_URL}/captcha/image.php"
DASHBOARD_URL = f"{BASE_URL}/student/dash_board.php"
SEM_END_DATE = datetime(2025, 11, 21).date()  # adjust as needed

# list of holidays (add real ones here)
HOLIDAYS = {
    datetime(2025, 11, 5).date(),
    datetime(2025, 11, 14).date(),
    datetime(2025, 12, 13).date()
}

course_name = { '24CS002PC215' : 'AI ASSISTED CODE', 
               '24CS101PC214': 'CLOUD COMPUTING' , 
               '24CS401PC212': 'COMPUTER NETWORKS' , 
               '24CS201PC210': 'DATA ANALYTICS AND VISUALIZATION' , 
               '24CS301PC211': 'INFORMATION MANAGEMENT SYSTEM' , 
               '24CS202PC213':'WEB TECHNOLOGIES AND MOBILE PROGRAMMING' 
}

session = requests.Session()


# ---------------------------------------------------------
# STEP 1: LOGIN
# ---------------------------------------------------------
def login():
    print("Fetching login page...")
    session.get(LOGIN_URL)

    captcha_resp = session.get(CAPTCHA_URL, stream=True)
    with open("captcha.jpg", "wb") as f:
        for chunk in captcha_resp.iter_content(8192):
            f.write(chunk)

    print("Captcha saved as captcha.jpg — open it and enter the text.")
    user_id = input("Enrollment Number: ").strip()
    password = input("Password: ").strip()
    captcha_text = input("Captcha text: ").strip()

    payload = {
        "user_id": user_id,
        "user_password": password,
        "token": captcha_text,
        "submit": "Sign in",
    }

    resp = session.post(LOGIN_URL, data=payload, headers={"Referer": LOGIN_URL})
    dash = session.get(DASHBOARD_URL)

    if "Attendance" in dash.text or "attendance" in dash.text:
        print("✅ Login successful!")
    else:
        print("❌ Login failed. Saving debug_failed.html")
        with open("debug_failed.html", "w", encoding="utf-8") as f:
            f.write(dash.text)
        exit()

    with open("dashboard.html", "w", encoding="utf-8") as f:
        f.write(dash.text)
    return dash.text


# ---------------------------------------------------------
# STEP 2: EXTRACT BATCH
# ---------------------------------------------------------
def extract_batch_number(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    h3 = soup.find("h3", align="center")
    if not h3:
        raise ValueError("Couldn't find batch info.")
    text = h3.get_text(strip=True)
    match = re.search(r"Batch Number\s*-\s*([A-Z0-9]+)", text)
    if not match:
        raise ValueError("Batch number not found.")
    return match.group(1)


# ---------------------------------------------------------
# STEP 3: PARSE ATTENDANCE TABLE
# ---------------------------------------------------------
def parse_attendance_table(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    attendance_table = None
    for table in soup.find_all("table"):
        if "Course" in table.get_text():
            attendance_table = table
            break

    attendance_data = {}
    if attendance_table:
        rows = attendance_table.find_all("tr")[1:]
        for row in rows:
            cols = row.find_all("th")
            if len(cols) >= 3:
                subject = cols[1].get_text(strip=True)
                pct_text = cols[2].get_text(strip=True).replace("%", "")
                try:
                    pct = float(pct_text)
                except ValueError:
                    pct = 0.0
                attendance_data[subject] = {"percentage": pct}
    return attendance_data


# ---------------------------------------------------------
# STEP 4: HELD / ATTENDED COUNTS
# ---------------------------------------------------------
def get_subject_attendance(subject_code):
    url = f"{BASE_URL}/student/attendance_subwise.php?course_code={subject_code}&submit=Submit"
    resp = session.get(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", {"id": "example"})
    if not table:
        return 0, 0
    rows = table.find_all("tr")
    last = rows[-1].find_all("td")
    held = int(last[1].get_text(strip=True))
    attended = int(last[2].get_text(strip=True))
    return held, attended


# ---------------------------------------------------------
# STEP 5: LOAD TIMETABLE SUMMARY
# ---------------------------------------------------------
def load_timetable_summary(path="timetable_summary.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------
# STEP 6: CALCULATE SKIPPABLE CLASSES (with holidays)
# ---------------------------------------------------------
def calculate_skippable_classes(batch, timetable_summary, attendance_data):
    today = datetime.now().date()

    weekly_schedule = timetable_summary.get(batch)
    if not weekly_schedule:
        raise ValueError(f"No timetable found for batch {batch}")

    # Build a weekday map (0 = Monday ... 6 = Sunday)
    day_map = {i: day for i, day in enumerate(weekly_schedule)}

    # Walk through calendar day by day
    subject_future_counts = {}
    current = today
    while current <= SEM_END_DATE:
        if current.weekday() < len(day_map):
            if current.weekday() < 5 and current not in HOLIDAYS:
                for subj, count in day_map[current.weekday()].items():
                    subject_future_counts[subj] = subject_future_counts.get(subj, 0) + count
        current += timedelta(days=1)

    results = []
    for subject, future_classes in subject_future_counts.items():
        held, attended = get_subject_attendance(subject)
        total_projected = held + future_classes
        required = 0.75 * total_projected
        skippable = max(0, int(attended + future_classes - required))
        results.append({
            "subject": course_name[subject],
            "held": held,
            "attended": attended,
            "future": future_classes,
            "skippable": skippable
        })

    return results


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
if __name__ == "__main__":
    html_text = login()
    batch = extract_batch_number(html_text)
    print(f"Detected Batch: {batch}")

    timetable_summary = load_timetable_summary()
    attendance_data = parse_attendance_table(html_text)

    print("\nCalculating skippable classes...")
    results = calculate_skippable_classes(batch, timetable_summary, attendance_data)


    # PrettyTable output
    table = PrettyTable()
    table.field_names = ["Subject", "Held", "Attended", "Percentage", "Future", "Can Skip"]

    for r in results:
        table.add_row([r["subject"], r["held"], r["attended"], round((r["attended"] / r["held"]) * 100, 2), r["future"], r["skippable"]])

    print("\n--- Attendance Projection ---")
    print(f"Batch: {batch}")
    print(table)
