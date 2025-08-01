import streamlit as st
from datetime import datetime, timezone
from db import Signal  # ✅ Signal model
from utils import format_currency
        

def render(trading_engine, dashboard, db_manager):
    st.image("logo.png", width=80)
    st.title("🚀 AlgoTrader Dashboard")

    # === Load wallet data ===
    capital_data = trading_engine.load_capital("all") or {}
    real = capital_data.get("real", {})
    virtual = capital_data.get("virtual", {})

    real_total = float(real.get("capital", 0.0))
    real_available = float(real.get("available", 0.0))

    virtual_total = float(virtual.get("capital", 0.0))
    virtual_available = float(virtual.get("available", 0.0))

    # === Load recent trades ===
    all_trades = trading_engine.get_recent_trades(limit=100) or []
    real_trades = [t for t in all_trades if not t.get("virtual")]
    virtual_trades = [t for t in all_trades if t.get("virtual")]

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # === Load recent signals ===
    with db_manager.get_session() as session:
        signal_objs = session.query(Signal).order_by(Signal.created_at.desc()).limit(5).all()
        recent_signals = [s.to_dict() for s in signal_objs]

    # === KPI Metrics ===
    st.markdown("### 📈 Overview")
    col1, col2, col3, col4 = st.columns(4)

    col1.metric("💰 Real Wallet", format_currency(real_total), f"Available: {format_currency(real_available)}")
    col2.metric("🧪 Virtual Wallet", format_currency(virtual_total), f"Available: {format_currency(virtual_available)}")
    col3.metric("📡 Active Signals", len(recent_signals), "Recent")
    col4.metric("📅 Real Trades Today", len([
        t for t in real_trades if str(t.get("timestamp", "")).startswith(today_str)
    ]))

    st.markdown("---")

    # === Left: Recent Signals / Right: Wallet chart ===
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("📡 Latest Signals")
        if recent_signals:
            for i, signal in enumerate(recent_signals):
                symbol = signal.get("symbol", "N/A")
                signal_type = signal.get("signal_type", "N/A")
                score = round(float(signal.get("score") or 0.0), 1)
                with st.expander(f"{symbol} - {signal_type} ({score}%)", expanded=(i == 0)):
                    dashboard.display_signal_card(signal)
        else:
            st.info("No recent signals available.")

    with col_right:
        st.subheader("📊 Real Wallet Performance")
        if real_trades:
            fig = dashboard.create_portfolio_performance_chart(real_trades, real_total)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No real trade history available.")

    st.markdown("---")

    # === Trade Summary ===
    st.subheader("🔍 Trade Summary")
    tab1, tab2 = st.tabs(["📈 Real Trades", "🧪 Virtual Trades"])

    with tab1:
        if real_trades:
            dashboard.display_trades_table(real_trades)
        else:
            st.info("No real trades available.")

    with tab2:
        if virtual_trades:
            dashboard.display_trades_table(virtual_trades)
        else:
            st.info("No virtual trades available.")
