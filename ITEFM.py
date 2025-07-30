import streamlit as st
import pandas as pd
from io import BytesIO
from openpyxl.styles import Font
from openpyxl import load_workbook

# === Constants ===
SOT_KEYWORDS = [
    "DVMR/NVR", "Electronic Access Control System", "Indoor CCTV",
    "Intrusion Detection Systems", "VEHICULAR ARM BARRIER SYSTEM"
]

MATCH_COLUMNS = [
    "Equipment QR Code", "Type of Service", "Location", "Status",
    "Job Cannot Be Done", "Job Cannot be Done Reason",
    "Job Closed Date Time Month", "Current Status",
    "Frequency", "Scheduled Start", "Scheduled End"
]

CAMP_GROUPS = {
    "AC1": ["CLC", "MJC", "BPC"],
    "AC2": ["MBC", "KC", "SMC"],
    "AC3": ["MWC", "RRRC1"]
}

# === Helper Functions ===
def load_excel(file, skiprows=None):
    return pd.read_excel(file, header=0, skiprows=skiprows)

def process_camp(ac_df, master_df, camp_prefix):
    ac_filtered = ac_df[ac_df["Equipment QR Code"].astype(str).str.startswith(camp_prefix)]

    # Filter by SOT type
    master_filtered = master_df[
        master_df["SOT Type"].astype(str).apply(lambda x: any(k in x for k in SOT_KEYWORDS))
        | (master_df["SOT Type"] == "VEHICULAR ARM BARRIER SYSTEM")
    ][["Equipment Tag Number", "Current Status", "SOT Type", "Physical Location"]]

    # Merge matched
    merged = pd.merge(ac_filtered, master_filtered,
                      left_on="Equipment QR Code", right_on="Equipment Tag Number", how="inner")

    # Ensure all match columns exist
    for col in MATCH_COLUMNS:
        if col not in merged.columns:
            merged[col] = None

    matched_final = merged[MATCH_COLUMNS]

    # Unmatched from master list
    unmatched = master_filtered[~master_filtered["Equipment Tag Number"].isin(merged["Equipment QR Code"])]
    unmatched_final = unmatched.rename(columns={
        "Equipment Tag Number": "Equipment QR Code",
        "SOT Type": "Type of Service",
        "Physical Location": "Location"
    })[["Equipment QR Code", "Type of Service", "Location", "Current Status"]]

    for col in MATCH_COLUMNS:
        if col not in unmatched_final.columns:
            unmatched_final[col] = None

    unmatched_final = unmatched_final[MATCH_COLUMNS]

    all_status = pd.concat([matched_final, unmatched_final], ignore_index=True)
    all_status["Status"] = all_status["Status"].fillna("Pending Job Creation")
    all_status = all_status.sort_values(by="Equipment QR Code")

    return all_status, unmatched_final, matched_final

def apply_red_font_and_download(all_df, unmatched_df, matched_df, camp_name):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        all_df.to_excel(writer, sheet_name="All Equipment Status", index=False)
        matched_df.to_excel(writer, sheet_name="Matched Data", index=False)
        unmatched_df.to_excel(writer, sheet_name="Unmatched Tag Numbers", index=False)

        # Apply red font to rows where Status is "Pending Job Creation"
        ws = writer.sheets["All Equipment Status"]
        status_col_idx = all_df.columns.get_loc("Status") + 1
        for row_idx, row in enumerate(all_df.itertuples(index=False), start=2):
            if row[status_col_idx - 1] == "Pending Job Creation":
                for col_idx in range(1, len(all_df.columns) + 1):
                    ws.cell(row=row_idx, column=col_idx).font = Font(color="FF0000")

    output.seek(0)
    return output

# === Streamlit App ===
st.set_page_config(page_title="ITEFM Camp Report Generator", layout="wide")
st.title("🏕️ ITEFM Camp Report Generator")

# Sidebar: Camp group selection
camp_group = st.sidebar.radio("Select Camp Group", list(CAMP_GROUPS.keys()))

# Upload relevant AC file
st.sidebar.markdown(f"### Upload {camp_group} Source File")
ac_file = st.sidebar.file_uploader(f"Upload {camp_group} File", type=["xlsx"], key=f"{camp_group}_ac")

# Upload master list files
st.sidebar.markdown("### Upload Master Lists")
camp_files = {}
for camp in CAMP_GROUPS[camp_group]:
    camp_files[camp] = st.sidebar.file_uploader(f"{camp} Master List", type=["xlsx"], key=camp)

# Keep session state for generate flag
if "generate_reports" not in st.session_state:
    st.session_state["generate_reports"] = False

if st.button("Generate Reports"):
    st.session_state["generate_reports"] = True

if st.session_state["generate_reports"]:
    if not ac_file:
        st.error(f"Please upload the {camp_group} source file.")
        st.stop()

    try:
        ac_df = load_excel(ac_file, skiprows=8)
        ac_df.columns = ac_df.columns.str.strip()
    except Exception as e:
        st.error(f"Failed to read AC file: {e}")
        st.stop()

    for camp in CAMP_GROUPS[camp_group]:
        file = camp_files[camp]
        if not file:
            st.warning(f"{camp} Master List not uploaded.")
            continue

        try:
            master_df = load_excel(file, skiprows=5)
            master_df.columns = master_df.columns.str.strip()
        except Exception as e:
            st.error(f"Error reading {camp} master list: {e}")
            continue

        try:
            combined_df, unmatched_df, matched_df = process_camp(ac_df, master_df, camp_prefix=f"{camp}-")
            excel_data = apply_red_font_and_download(combined_df, unmatched_df, matched_df, camp)

            st.download_button(
                label=f"⬇️ Download Report for {camp}",
                data=excel_data,
                file_name=f"{camp}_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        except Exception as e:
            st.error(f"Failed processing for {camp}: {e}")
