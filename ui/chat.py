"""AI Financial Assistant: chat + insights. The AI only explains numbers Python calculated."""
import streamlit as st

from accounting import anomaly_detection as anomaly
from ai import explainer, groq_client, insights
from config import MISSING_KEY_MESSAGE
from database import crud, review_db
from ui import common, context_helper


def _show_unverified(numbers) -> None:
    if numbers:
        st.warning("⚠️ These figures could not be matched to the calculated data: "
                   + ", ".join(numbers) + ". Please verify before relying on them.")


def _insights_tab(ctx: dict, currency: str) -> None:
    pl = ctx["profit_and_loss"]
    st.markdown("#### 🧮 Calculated by Python")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Revenue", common.money(pl["total_revenue"], currency))
    k2.metric("Expenses", common.money(pl["total_expenses"], currency))
    k3.metric("Net Profit", common.money(pl["net_profit"], currency))
    margin = pl["net_profit_margin_percent"]
    k4.metric("Profit Margin", "n/a" if margin is None else f"{margin:.1f}%")

    st.markdown("#### 🤖 AI explanation")
    if st.button("Generate AI insights and recommendations"):
        try:
            with st.spinner("Asking Groq to explain your numbers..."):
                result = insights.generate_insights(ctx)
            st.session_state.ai_insights = {"result": result, "period": ctx["period"]}
        except groq_client.GroqConfigError:
            st.error(MISSING_KEY_MESSAGE)
        except groq_client.AIError as exc:
            st.error(str(exc))

    saved = st.session_state.get("ai_insights")
    if saved:
        if saved["period"] != ctx["period"]:
            st.info(f"This was generated for: {saved['period']}. Click the button to refresh.")
        result = saved["result"]
        if result.get("raw"):
            st.warning("The AI reply was not in the expected format, so it is shown as plain text.")
        st.write(result["summary"])
        if result["concerns"]:
            st.markdown("**Main concerns**")
            for item in result["concerns"]:
                st.write("•", item)
        if result["recommendations"]:
            st.markdown("**Recommendations**")
            for item in result["recommendations"]:
                st.write("•", item)
        _show_unverified(result.get("unverified_numbers"))
        st.caption("AI-generated explanation of the calculated figures above. Not professional advice.")
    with st.expander("Data sent to the AI"):
        st.json(ctx)


def _chat_tab(ctx: dict) -> None:
    st.caption("Try: What is my biggest expense? · Which expense increased the most? · "
               "Which transactions require review? · How much do customers owe me? · What is my cash position?")
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    history = st.session_state.chat_history

    for message in history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            _show_unverified(message.get("warning"))

    question = st.chat_input("Ask about your business numbers...")
    if question:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            try:
                with st.spinner("Thinking..."):
                    answer = insights.answer_question(question, ctx, history)
                warning = insights.verify_numbers(answer, ctx)
                st.markdown(answer)
                _show_unverified(warning)
                history.append({"role": "user", "content": question})
                history.append({"role": "assistant", "content": answer, "warning": warning})
            except groq_client.GroqConfigError:
                st.error(MISSING_KEY_MESSAGE)
            except groq_client.AIError as exc:
                st.error(str(exc))

    if history and st.button("Clear chat"):
        st.session_state.chat_history = []
        st.rerun()


def render() -> None:
    st.title("🤖 AI Financial Assistant")
    st.info("Numbers are calculated by Python from your confirmed data. The AI only explains them. "
            "It is not a substitute for a qualified accountant.")
    data = common.report_controls()
    if data is None:
        return
    if data.period_data.empty:
        st.info("No transactions in the selected period.")
        return

    currency = st.session_state.profile["currency"]
    ctx = context_helper.build_full_context(data, currency)

    tab_chat, tab_insights = st.tabs(["💬 Ask a question", "🧠 Insights & recommendations"])
    with tab_chat:
        _chat_tab(ctx)
    with tab_insights:
        _insights_tab(ctx, currency)
