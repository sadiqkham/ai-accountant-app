"""Review & Categorize page: AI suggestions, then YOU decide."""
import pandas as pd
import streamlit as st

from accounting import rules
from ai import categorizer
from database import crud, db, review_db
from utils.helpers import ALL_CATEGORIES, CATEGORIES, TRANSACTION_TYPES

MAX_ROWS_SHOWN = 200


def _flash(kind: str, message: str) -> None:
    st.session_state.review_flash = (kind, message)


def _categorize_section(data: pd.DataFrame) -> None:
    st.subheader("1. Categorize")
    blank = (data["category"].isna()) | (data["category"] == "")
    waiting = data[blank & (data["status"] == "Pending")]
    c1, c2 = st.columns(2)

    with c1:
        st.markdown("**🤖 Categorize with AI**")
        st.caption("Sends description, amount, type and party name to Groq. "
                   "Only empty categories are filled.")
        max_rows = st.number_input("Max transactions this run", 5, 500, 150, step=5)
        if st.button("Categorize with AI", disabled=waiting.empty):
            rows = waiting.head(int(max_rows))
            bar = st.progress(0.0, text="Asking Groq...")

            def show_progress(done: int, total: int) -> None:
                bar.progress(done / total, text=f"{done} of {total} transactions processed")

            result = categorizer.categorize_dataframe(rows, progress=show_progress)
            bar.empty()
            items = [(tx_id, r["transaction_type"], r["category"], r["subcategory"], r["confidence"])
                     for tx_id, r in result["suggested"].items()]
            changed = review_db.apply_ai_categories(items)
            st.session_state.review_problems = result["problems"][:15]
            if result["stopped"]:
                _flash("warning", f"AI stopped early: {result['stopped']} ({changed} suggestions were saved.)")
            else:
                _flash("success", f"AI suggested categories for {changed} of {len(rows)} transactions. "
                                  f"{len(rows) - changed} were left blank for you to decide.")
            st.rerun()

    with c2:
        st.markdown("**🔤 Keyword rules (works offline)**")
        st.caption("Simple fallback from Phase 3. Fills only empty categories.")
        if st.button("Apply keyword rules", disabled=waiting.empty):
            suggestions = []
            for row in waiting.itertuples():
                found = rules.suggest_category(row.description, row.transaction_type)
                if found:
                    suggestions.append((int(row.id),) + found)
            changed = crud.apply_rule_categories(suggestions)
            _flash("success", f"Keyword rules categorized {changed} transaction(s).")
            st.rerun()

    problems = st.session_state.get("review_problems")
    if problems:
        with st.expander(f"Why some transactions were left blank ({len(problems)})"):
            for p in problems:
                st.write("•", p)


def _bulk_section(data: pd.DataFrame) -> None:
    st.subheader("2. Quick accept")
    threshold = st.slider("Accept all Pending suggestions with AI confidence at or above (%)", 80, 100, 95)
    eligible = int(((data["status"] == "Pending") & (data["category"].fillna("") != "")
                    & (data["ai_confidence"].fillna(-1) >= threshold / 100)).sum())
    st.caption(f"{eligible} transaction(s) qualify. Still glance at the table below from time to time.")
    if st.button(f"Accept {eligible} high-confidence transaction(s)", disabled=eligible == 0):
        n = review_db.accept_high_confidence(threshold / 100)
        _flash("success", f"Confirmed {n} transaction(s).")
        st.rerun()


def _review_table(data: pd.DataFrame) -> None:
    st.subheader("3. Review table")
    view = st.radio("Show", ["Needs review (Pending)", "Rejected"], horizontal=True)
    status = "Pending" if view.startswith("Needs") else "Rejected"
    rows = data[data["status"] == status].sort_values("ai_confidence", na_position="last")
    if rows.empty:
        st.info("Nothing to show here.")
        return
    total = len(rows)
    rows = rows.head(MAX_ROWS_SHOWN)
    st.caption(f"Showing {len(rows)} of {total}. Lowest AI confidence first. "
               "Edit Type, Category or Subcategory in the table, tick rows, then use the buttons.")
    select_all = st.checkbox("Select all rows shown")

    custom = sorted({c for c in rows["category"].fillna("") if c and c not in ALL_CATEGORIES})
    table = pd.DataFrame({
        "Select": [bool(select_all)] * len(rows),
        "Date": rows["date"].tolist(),
        "Description": rows["description"].tolist(),
        "Party": rows["party"].fillna("").tolist(),
        "Amount": rows["amount"].tolist(),
        "Type": [t if t in TRANSACTION_TYPES else "Unknown" for t in rows["transaction_type"]],
        "Category": [c if c else None for c in rows["category"].fillna("")],
        "Subcategory": rows["subcategory"].fillna("").tolist(),
        "Confidence (%)": [None if pd.isna(x) else round(float(x) * 100) for x in rows["ai_confidence"]],
    }, index=rows["id"].tolist())

    edited = st.data_editor(
        table, hide_index=True, key=f"review_editor_{status}_{select_all}",
        disabled=["Date", "Description", "Party", "Amount", "Confidence (%)"],
        column_config={
            "Select": st.column_config.CheckboxColumn("✓"),
            "Amount": st.column_config.NumberColumn(format="%.0f"),
            "Confidence (%)": st.column_config.NumberColumn(format="%.0f"),
            "Type": st.column_config.SelectboxColumn(options=TRANSACTION_TYPES + ["Unknown"], required=True),
            "Category": st.column_config.SelectboxColumn(options=ALL_CATEGORIES + custom),
        })

    selected = edited[edited["Select"] == True]  # noqa: E712
    n = len(selected)
    b1, b2, b3 = st.columns(3)

    if b1.button(f"✅ Accept {n} selected (with my edits)", disabled=n == 0):
        errors, payload = [], []
        for tx_id, row in selected.iterrows():
            tx_type, category = row["Type"], row["Category"]
            name = str(row["Description"])[:35]
            if category is None or pd.isna(category) or category == "":
                errors.append(f"'{name}': choose a category first.")
            elif tx_type not in CATEGORIES or category not in CATEGORIES[tx_type]:
                errors.append(f"'{name}': category '{category}' does not belong to type '{tx_type}'.")
            else:
                sub = "" if pd.isna(row["Subcategory"]) else str(row["Subcategory"]).strip()
                payload.append((int(tx_id), tx_type, category, sub))
        if errors:
            st.error("Nothing was saved. Please fix:\n\n" + "\n".join(f"- {e}" for e in errors[:8]))
        else:
            _flash("success", f"Confirmed {review_db.save_and_confirm(payload)} transaction(s).")
            st.rerun()

    if b2.button(f"❌ Reject {n} selected", disabled=n == 0):
        _flash("success", f"Rejected {review_db.set_status(selected.index.tolist(), 'Rejected')} "
                          "transaction(s). They are excluded from reports.")
        st.rerun()

    if b3.button(f"🔄 Reclassify {n} selected", disabled=n == 0):
        _flash("success", f"Cleared {review_db.reclassify(selected.index.tolist())} transaction(s). "
                          "They are back in Pending with no category.")
        st.rerun()


def render() -> None:
    st.title("✅ Review & Categorize")
    st.caption("The AI only suggests. Only transactions you CONFIRM feed the official reports.")
    if "review_flash" in st.session_state:
        kind, message = st.session_state.pop("review_flash")
        getattr(st, kind)(message)

    try:
        data = db.get_transactions()
        counts = review_db.counts()
    except db.DatabaseError as exc:
        st.error(str(exc))
        return
    if data.empty:
        st.info("No transactions yet. Add, upload or load sample data first.")
        return

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Pending, no category", counts["pending_uncategorized"])
    m2.metric("Pending, needs review", counts["pending_categorized"])
    m3.metric("Confirmed", counts["confirmed"])
    m4.metric("Rejected", counts["rejected"])

    _categorize_section(data)
    _bulk_section(data)
    _review_table(data)
