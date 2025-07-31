import streamlit as st
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from db import db  # using the global `db` instance
from db import Signal


def render(trading_engine, dashboard):
    st.image("logo.png", width=80)
    st.title("📊 AI Trading Signals")

    # Load signals from DB using db_manager
    signal_objs = db.get_signals(limit=100)

    # Convert to dicts
    signal_dicts = [s.to_dict() for s in signal_objs]

    if not signal_dicts:
        st.info("No signals found in the database.")
        return

    st.subheader("🧠 Recent AI Signals")
    st.dataframe(signal_dicts)

    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        strategies = sorted({s["strategy"] for s in signal_dicts})
        strategy_filter = st.multiselect("Filter by Strategy", options=strategies, default=strategies)

    with col2:
        side_filter = st.multiselect("Filter by Side", ["LONG", "SHORT"], default=["LONG", "SHORT"])

    with col3:
        min_score = st.slider("Minimum Score", 70, 100, 80)

    # Apply filters
    filtered_signals = [
        s for s in signal_dicts
        if s["strategy"] in strategy_filter
        and s["side"] in side_filter
        and s["score"] >= min_score
    ]

    st.subheader(f"📡 {len(filtered_signals)} Filtered Signals")

    if filtered_signals:
        dashboard.display_signals_table(filtered_signals)

        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("📤 Export to Discord"):
                for s in filtered_signals[:5]:
                    trading_engine.post_signal_to_discord(s)
                st.success("Posted top 5 to Discord!")

        with col2:
            if st.button("📤 Export to Telegram"):
                for s in filtered_signals[:5]:
                    trading_engine.post_signal_to_telegram(s)
                st.success("Posted top 5 to Telegram!")

        with col3:
            if st.button("📄 Export PDF"):
                trading_engine.save_signal_pdf(filtered_signals)
                st.success("PDF exported!")
    else:
        st.info("No signals match the current filters.")
