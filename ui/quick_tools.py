"""Temporary tools until Phase 4 adds AI categorization and the review screen."""
import streamlit as st

from accounting import rules
from database import crud, db


def render() -> None:
    st.divider()
    st.subheader("🏷️ Quick categorize and confirm (temporary MVP tools)")
    if "flash" in st.session_state:
        st.success(st.session_state.pop("flash"))

    try:
        data = db.get_transactions()
    except db.DatabaseError as exc:
        st.error(str(exc))
        return
    if data.empty:
        st.caption("Add or load transactions first.")
        return

    blank = (data["category"].isna()) | (data["category"] == "")
    m1, m2, m3 = st.columns(3)
    m1.metric("Without category", int(blank.sum()))
    m2.metric("Pending", int((data["status"] == "Pending").sum()))
    m3.metric("Confirmed", int((data["status"] == "Confirmed").sum()))

    st.markdown("**Step 1: suggest categories with keyword rules**")
    st.caption("Fills only rows that have no category. Categories you chose yourself are never changed.")
    if st.button("Apply keyword rules"):
        suggestions, no_match = [], 0
        for row in data[blank].itertuples():
            found = rules.suggest_category(row.description, row.transaction_type)
            if found:
                suggestions.append((int(row.id),) + found)
            else:
                no_match += 1
        changed = crud.apply_rule_categories(suggestions)
        st.session_state.flash = (f"Categorized {changed} transaction(s). "
                                  f"{no_match} had no matching rule and need a manual category (Phase 4).")
        st.rerun()

    st.markdown("**Step 2: confirm (testing shortcut)**")
    st.caption("Phase 4 adds the real review screen (accept / edit / reject). Until then this marks every "
               "categorized Pending row as Confirmed so you can test the reports.")
    if st.button("✅ Confirm all categorized transactions"):
        n = crud.confirm_categorized()
        st.session_state.flash = f"Confirmed {n} transaction(s)."
        st.rerun()
