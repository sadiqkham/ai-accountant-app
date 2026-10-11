"""Receivables and Payables pages."""
from datetime import date, timedelta

import plotly.express as px
import streamlit as st

from accounting import ledger_calc
from database import db
from database import ledger as ledger_db

LABELS = {
    "receivable": {"title": "💰 Accounts Receivable", "party": "Customer", "total": "Total Receivables",
                   "intro": "Money your customers owe you.", "action": "received from"},
    "payable": {"title": "🧾 Accounts Payable", "party": "Supplier", "total": "Total Payables",
                "intro": "Money you owe your suppliers.", "action": "paid to"},
}


def _summary_text(open_rows, label: dict, currency: str) -> str:
    """Text summary like the example in the master prompt."""
    lines = []
    for party, amount in open_rows.groupby("party")["amount_due"].sum().sort_values(ascending=False).items():
        lines.append(f"{str(party)[:26]:<28}{currency} {amount:>12,.0f}")
    lines.append("-" * 44)
    lines.append(f"{label['total']:<28}{currency} {open_rows['amount_due'].sum():>12,.0f}")
    return "\n".join(lines)


def render(kind: str) -> None:
    label = LABELS[kind]
    currency = st.session_state.profile["currency"]
    today = date.today()
    st.title(label["title"])
    st.caption(label["intro"] + " These entries are typed in here and kept separate from your transaction list.")

    try:
        raw = ledger_db.list_entries(kind)
    except db.DatabaseError as exc:
        st.error(str(exc))
        return
    prepared = ledger_calc.prepare_ledger(raw, today)
    summary = ledger_calc.summarize(prepared)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric(label["total"], f"{currency} {summary['total_due']:,.0f}")
    m2.metric("Overdue", f"{currency} {summary['overdue_amount']:,.0f}")
    m3.metric("Open entries", summary["open_count"])
    m4.metric("Oldest overdue (days)", summary["oldest_overdue_days"])

    tab_list, tab_add, tab_pay = st.tabs(["📋 List", "➕ Add", "💵 Record payment"])

    with tab_list:
        if prepared.empty:
            st.info("Nothing recorded yet. Use the **Add** tab.")
        else:
            show_open_only = st.checkbox("Show only entries with money still due", value=True)
            shown = prepared[prepared["amount_due"] > 0] if show_open_only else prepared
            open_rows = prepared[prepared["amount_due"] > 0]
            if not open_rows.empty:
                st.code(_summary_text(open_rows, label, currency), language=None)
            table = shown[["id", "party", "amount", "amount_paid", "amount_due", "invoice_date",
                           "due_date", "days_outstanding", "days_overdue", "display_status"]].rename(columns={
                "party": label["party"], "amount": "Amount", "amount_paid": "Paid", "amount_due": "Amount due",
                "invoice_date": "Invoice date", "due_date": "Due date",
                "days_outstanding": "Days outstanding", "days_overdue": "Days overdue",
                "display_status": "Status"})
            st.dataframe(table, hide_index=True, column_config={
                "Amount": st.column_config.NumberColumn(format="%.0f"),
                "Paid": st.column_config.NumberColumn(format="%.0f"),
                "Amount due": st.column_config.NumberColumn(format="%.0f")})
            st.download_button("⬇️ Download as CSV", table.to_csv(index=False), f"{kind}s.csv", "text/csv")

            if summary["total_due"] > 0:
                aging = px.bar(x=list(summary["aging"].keys()), y=list(summary["aging"].values()),
                               title="Aging of amounts due", labels={"x": "", "y": f"Amount ({currency})"})
                st.plotly_chart(aging)

            with st.expander("⚠️ Delete an entry"):
                options = {f"#{r.id} {r.party} ({r.amount:,.0f})": int(r.id) for r in prepared.itertuples()}
                chosen = st.selectbox("Entry", list(options), key=f"del_{kind}")
                confirm = st.checkbox("I understand this cannot be undone", key=f"delc_{kind}")
                if st.button("Delete entry", key=f"delb_{kind}", disabled=not confirm):
                    ledger_db.delete_entry(kind, options[chosen])
                    st.rerun()

    with tab_add:
        with st.form(f"add_{kind}", clear_on_submit=True):
            party = st.text_input(label["party"])
            amount = st.number_input("Amount", min_value=0.0, step=1000.0, format="%.2f")
            c1, c2 = st.columns(2)
            invoice_date = c1.date_input("Invoice date", value=today, format="DD/MM/YYYY")
            due_date = c2.date_input("Due date", value=today + timedelta(days=30), format="DD/MM/YYYY")
            submitted = st.form_submit_button("Add entry")
        if submitted:
            try:
                ledger_db.add_entry(kind, party, amount, invoice_date, due_date)
                st.success("Entry saved.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
            except db.DatabaseError as exc:
                st.error(str(exc))

    with tab_pay:
        open_rows = prepared[prepared["amount_due"] > 0]
        if open_rows.empty:
            st.info("There is nothing outstanding.")
        else:
            options = {f"#{r.id} {r.party}, still due {r.amount_due:,.0f}": (int(r.id), float(r.amount_due))
                       for r in open_rows.itertuples()}
            chosen = st.selectbox("Entry", list(options), key=f"pay_{kind}")
            entry_id, still_due = options[chosen]
            payment = st.number_input(f"Amount {label['action']} this party", min_value=0.0,
                                      max_value=still_due, value=still_due, step=1000.0, key=f"payamt_{kind}")
            st.caption("This updates the ledger only. To show it in your P&L and cash flow, also add it "
                       "as a transaction.")
            if st.button("Record payment", key=f"payb_{kind}"):
                try:
                    paid, status = ledger_db.record_payment(kind, entry_id, payment)
                    st.success(f"Saved. Total paid so far: {currency} {paid:,.0f} (status: {status}).")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
                except db.DatabaseError as exc:
                    st.error(str(exc))
