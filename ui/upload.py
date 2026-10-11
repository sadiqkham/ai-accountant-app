"""Upload Data page."""
import streamlit as st

from database import db
from utils import file_processing as fp
from utils.sample_data import generate_sample_dataframe


def render() -> None:
    st.title("📤 Upload Data")
    st.write("Upload a CSV or Excel file of your transactions. "
             "Nothing is saved until you check the preview and click **Save**.")

    with st.expander("Expected columns and sample file"):
        st.write("**Required:** Date, Description, Amount  \n"
                 "**Optional:** Type, Payment_Method, Party  \n"
                 "Similar names such as *Narration*, *Details*, *Customer* or *Vendor* are matched "
                 "automatically. Dates are read as **day-month-year** (05-10-2026 = 5 October 2026).")
        st.download_button("⬇️ Download sample CSV",
                           generate_sample_dataframe().to_csv(index=False),
                           "sample_transactions.csv", "text/csv")

    uploaded = st.file_uploader("Choose a .csv or .xlsx file", type=["csv", "xlsx"])
    if uploaded is None:
        return

    # 1. Read the file
    try:
        raw = fp.read_uploaded_file(uploaded)
    except fp.FileProcessingError as exc:
        st.error(str(exc))
        return

    st.subheader("1. File preview")
    st.caption(f"{len(raw)} rows found")
    st.dataframe(raw.head(10))

    # 2. Match columns
    mapped, mapping, missing = fp.map_columns(raw)
    st.subheader("2. Column matching")
    for original, standard in mapping.items():
        st.write(f"`{original}` → **{standard}**")
    ignored = [c for c in raw.columns if c not in mapping]
    if ignored:
        st.caption("Ignored columns: " + ", ".join(ignored))
    if missing:
        st.error("Required column(s) not found: " + ", ".join(missing) +
                 ". Please rename your columns or use the sample file as a template.")
        return
    if "Type" not in mapped.columns:
        st.warning("No Type column found. Transactions will be saved as 'Unknown' type.")

    # 3. Validate
    st.subheader("3. Validation result")
    result = fp.clean_transactions(mapped)
    checked = fp.mark_duplicates(result.valid, db.get_existing_keys())
    dup_count = int((checked["Duplicate_Reason"] != "").sum())

    c1, c2, c3 = st.columns(3)
    c1.metric("Rows in file", result.total_rows)
    c2.metric("Valid rows", len(result.valid))
    c3.metric("Rows with problems", len(result.issues))

    for message in result.warnings:
        st.warning(message)
    if not result.issues.empty:
        st.error("These rows cannot be saved. Fix them in your file and upload again:")
        st.dataframe(result.issues)
    if checked.empty:
        st.error("No valid rows to save.")
        return

    # 4. Duplicates and save
    skip = True
    if dup_count:
        st.warning(f"{dup_count} possible duplicate row(s) found.")
        st.dataframe(checked[checked["Duplicate_Reason"] != ""])
        skip = st.checkbox("Skip duplicates when saving (recommended)", value=True)
    to_save = checked[checked["Duplicate_Reason"] == ""] if skip else checked

    st.subheader("4. Save")
    st.dataframe(to_save.drop(columns=["Duplicate_Reason"]).head(50))
    if st.button(f"💾 Save {len(to_save)} transactions"):
        try:
            saved = db.insert_transactions(to_save.drop(columns=["Duplicate_Reason"]))
            st.success(f"Saved {saved} transactions with status 'Pending'. "
                       "Category review comes in a later phase.")
        except db.DatabaseError as exc:
            st.error(str(exc))
