# Rewriting the file after kernel reset
streamlit_code = '''
import streamlit as st
import pandas as pd
from io import BytesIO
from openpyxl.styles import Font

# === AUTHENTICATION ===
def login():
    st.title("🔒 ITEFM Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if username == "ademco" and password == "yimingiscool":
            st.session_state.logged_in = True
        else:
            st.error("Invalid username or password.")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    login()
    st.stop()

# === CONFIG ===
SOT_KEYWORDS = [
    "CCTV", "DVMR/NVR", "Electronic Access Control System",
    "Intrusion Detection Systems", "VEHICULAR ARM BARRIER SYSTEM",
    "Host", "Network Switch"
]

CAMP_GROUPS = {
    "AC1": {
        "CLC": ["CLC-"],
        "MJC": ["MJC-"],
        "BPC": ["BPC-"]
    },
    "AC2": {
        "MBC": ["MBC-"],
        "KC": ["KC-", "KC2-", "KC3-"],
        "SMC": ["SMC-"]
    },
    "AC3": {
        "MWC": ["MWC-"],
        "RRRC1": ["RRRC1-"]
    }
}

REPORT_COLUMNS = [
    "Equipment QR Code", "Type of Service", "Location", "Job Status",
    "Job Cannot Be Done", "Job Cannot be Done Reason",
    "Job Closed Date Time Month", "Status",
    "Frequency", "Scheduled Start", "Scheduled End"
]

# === HELPERS ===
def load_excel(file, skiprows=None):
    df = pd.read_excel(file, skiprows=skiprows)
    df.columns = df.columns.astype(str).str.strip()
    return df

def ensure_columns(df: pd.DataFrame, columns: list):
    for col in columns:
        if col not in df.columns:
            df[col] = None
    return df

def starts_with_any(series, prefixes):
    return series.astype(str).apply(lambda x: any(x.startswith(p) for p in prefixes))

def process_camp(job_df, asset_df, camp, prefixes):
    job_camp = job_df[starts_with_any(job_df["Equipment QR Code"], prefixes)].copy()
    asset_camp = asset_df[starts_with_any(asset_df["Equipment Tag Number"], prefixes)].copy()

    if "Status" in job_camp.columns:
        job_camp = job_camp.rename(columns={"Status": "Job Status"})

    merged = pd.merge(
        job_camp,
        asset_camp,
        left_on="Equipment QR Code",
        right_on="Equipment Tag Number",
        how="inner"
    )

    merged = merged[merged["SOT Type"].astype(str).apply(lambda x: any(k in x for k in SOT_KEYWORDS))]

    matched_df = pd.DataFrame({
        "Equipment QR Code": merged["Equipment QR Code"],
        "Type of Service": merged.get("Type of Service"),
        "Location": merged.get("Location"),
        "Job Status": merged.get("Job Status"),
        "Job Cannot Be Done": merged.get("Job Cannot Be Done"),
        "Job Cannot be Done Reason": merged.get("Job Cannot be Done Reason"),
        "Job Closed Date Time Month": merged.get("Job Closed Date Time Month"),
        "Status": merged.get("Status"),
        "Frequency": merged.get("Frequency"),
        "Scheduled Start": merged.get("Scheduled Start"),
        "Scheduled End": merged.get("Scheduled End"),
    })
    matched_df = ensure_columns(matched_df, REPORT_COLUMNS)

    matched_qrs = matched_df["Equipment QR Code"].unique()
    unmatched = asset_camp[~asset_camp["Equipment Tag Number"].isin(matched_qrs)]
    unmatched = unmatched[unmatched["SOT Type"].astype(str).apply(lambda x: any(k in x for k in SOT_KEYWORDS))]

    unmatched_df = pd.DataFrame({
        "Equipment QR Code": unmatched["Equipment Tag Number"],
        "Type of Service": unmatched["SOT Type"],
        "Location": unmatched.get("Physical Location"),
        "Job Status": None,
        "Job Cannot Be Done": None,
        "Job Cannot be Done Reason": None,
        "Job Closed Date Time Month": None,
        "Status": unmatched.get("Status"),
        "Frequency": None,
        "Scheduled Start": None,
        "Scheduled End": None,
    })
    unmatched_df = ensure_columns(unmatched_df, REPORT_COLUMNS)

    all_status = pd.concat([matched_df, unmatched_df], ignore_index=True)
    all_status["Job Status"] = all_status["Job Status"].fillna("Pending Job Creation")
    all_status = all_status.sort_values(by="Equipment QR Code")

    return all_status[REPORT_COLUMNS], unmatched_df, matched_df[REPORT_COLUMNS]

def to_excel_with_format(all_df, unmatched_df, matched_df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        all_df.to_excel(writer, sheet_name="All Equipment Status", index=False)
        matched_df.to_excel(writer, sheet_name="Matched Data", index=False)
        unmatched_df.to_excel(writer, sheet_name="Unmatched Tag Numbers", index=False)

        ws = writer.sheets["All Equipment Status"]
        status_idx = all_df.columns.get_loc("Job Status") + 1
        for r, row in enumerate(all_df.itertuples(index=False), start=2):
            if row[status_idx - 1] == "Pending Job Creation":
                for c in range(1, len(all_df.columns) + 1):
                    ws.cell(row=r, column=c).font = Font(color="FF0000")

    output.seek(0)
    return output

# === STREAMLIT APP ===
st.set_page_config(page_title="ITEFM Maintenance Report Generator", layout="wide")
st.title("📋 ITEFM Maintenance Report Generator")

ac_group = st.sidebar.radio("Select Camp Group", list(CAMP_GROUPS.keys()))
job_file = st.sidebar.file_uploader("Upload Job Listing File (.xlsx)", type="xlsx", key=f"{ac_group}_job")
asset_file = st.sidebar.file_uploader("Upload Grouped Asset List (.xlsx)", type="xlsx", key=f"{ac_group}_asset")

if st.button("Generate Reports"):
    if not job_file or not asset_file:
        st.warning("Please upload both job and asset files.")
        st.stop()

    job_df = load_excel(job_file, skiprows=8)
    asset_df = load_excel(asset_file, skiprows=5)

    st.subheader("Download Reports:")
    for camp, prefixes in CAMP_GROUPS[ac_group].items():
        try:
            all_df, unmatched_df, matched_df = process_camp(job_df, asset_df, camp, prefixes)
            xls = to_excel_with_format(all_df, unmatched_df, matched_df)

            st.download_button(
                label=f"⬇️ Download {camp} Report",
                data=xls,
                file_name=f"{camp}_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"{camp}_dl"
            )
        except Exception as e:
            st.error(f"{camp} Error: {e}")
'''

file_path = "/mnt/data/ITEFM_updated_streamlit_app.py"
with open(file_path, "w", encoding="utf-8") as f:
    f.write(streamlit_code)

file_path

