import streamlit as st
from datetime import datetime, timezone
from db import Signal  # ✅ Signal model

def render(trading_engine, dashboard, db_manager):
    st.image("logo.png", width=80) 
    st.title("🚀 AlgoTrader Dashboard")

    # === Load real and virtual capital ===
    real_balance = trading_engine.load_capital(mode="real") or {"available": 100.0, "capital": 100.0}
    virtual_balance = trading_engine.load_capital(mode="virtual") or {"available": 100.0, "capital": 100.0}


    real_daily_pnl = trading_engine.get_daily_pnl() or 0.0
    virtual_daily_pnl = 0.0  # Placeholder if virtual PnL tracking not implemented

    # === Load trades ===
    all_trades = trading_engine.get_recent_trades(limit=100) or []
    real_trades = [t for t in all_trades if not t.get("virtual")]
    virtual_trades = [t for t in all_trades if t.get("virtual")]


    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # === Load latest signals ===
    with db_manager.get_session() as session:
        signal_objs = session.query(Signal).order_by(Signal.created_at.desc()).limit(5).all()
        recent_signals = [s.to_dict() for s in signal_objs]

    # === KPI Metrics ===
    st.markdown("### 📈 Key Metrics")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💰 Real Wallet", f"${real_balance.get('available', 100):.2f}", f"{real_daily_pnl:.2f}%")
    col2.metric("🧪 Virtual Wallet", f"${virtual_balance.get('available', 100):.2f}", f"{virtual_daily_pnl:.2f}%")
    col3.metric("📊 Active Signals", len(recent_signals), "Recent")
    col4.metric("📅 Today's Real Trades", len([
        t for t in real_trades if t.get("timestamp", "").startswith(today_str)
    ]))

    st.markdown("---")

    # === Latest Signals and Portfolio Chart ===
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("📡 Latest Signals")
        if recent_signals:
            for i, signal in enumerate(recent_signals):
                symbol = signal.get('symbol', 'N/A')
                signal_type = signal.get('signal_type', 'N/A')
                score = round(float(signal.get('score') or 0), 1)

                with st.expander(f"{symbol} - {signal_type} ({score}%)", expanded=(i == 0)):
                    dashboard.display_signal_card(signal)
        else:
            st.info("No recent signals available.")

    with col_right:
        st.subheader("📊 Real Wallet Performance")
        if real_trades:
            start_balance = float(real_balance.get("capital", 100.0))
            fig = dashboard.create_portfolio_performance_chart(real_trades, start_balance)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No real trade history available.")

    st.markdown("---")

    # === Real vs Virtual Trade Summary ===
    st.subheader("🔍 Trade Summary")
    tab1, tab2 = st.tabs(["📈 Real Trades", "🧪 Virtual Trades"])

    with tab1:
        if real_trades:
            dashboard.display_trade_table(real_trades)
        else:
            st.info("No real trades available.")

    with tab2:
        if virtual_trades:
            dashboard.display_trade_table(virtual_trades)
        else:
            st.info("No virtual trades available.")
