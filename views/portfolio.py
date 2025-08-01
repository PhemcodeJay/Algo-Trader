import streamlit as st
from datetime import datetime, timezone

def render(trading_engine, dashboard):
    st.image("logo.png", width=80)
    st.title("💼 Wallet Summary")

    tabs = st.tabs(["🔄 All Trades", "📂 Open Trades", "✅ Closed Trades"])

    for i, tab in enumerate(tabs):
        with tab:
            mode = st.radio("Mode", ["All", "Real", "Virtual"], key=f"mode_{i}", horizontal=True)

            # === Load trades ===
            if i == 0:
                trades = trading_engine.get_recent_trades(limit=100) or []
            elif i == 1:
                trades = (
                    trading_engine.get_open_real_trades() + trading_engine.get_open_virtual_trades()
                    if mode == "All" else
                    trading_engine.get_open_real_trades()
                    if mode == "Real" else
                    trading_engine.get_open_virtual_trades()
                )
            else:
                trades = (
                    trading_engine.get_closed_real_trades() + trading_engine.get_closed_virtual_trades()
                    if mode == "All" else
                    trading_engine.get_closed_real_trades()
                    if mode == "Real" else
                    trading_engine.get_closed_virtual_trades()
                )

            # === Load capital based on mode ===
            if mode == "All":
                balances = trading_engine.load_capital("all") or {}
                real = balances.get("real", {})
                virtual = balances.get("virtual", {})
                capital = float(real.get("capital", 0.0)) + float(virtual.get("capital", 0.0))
                start_balance = float(real.get("start_balance", 0.0)) + float(virtual.get("start_balance", 0.0))
                currency = real.get("currency", virtual.get("currency", "USD"))
            else:
                balance = trading_engine.load_capital(mode.lower()) or {}
                capital = float(balance.get("capital", 0.0))
                start_balance = float(balance.get("start_balance", 0.0))
                currency = balance.get("currency", "USD")

            total_return_pct = ((capital - start_balance) / start_balance * 100) if start_balance else 0.0
            win_rate = trading_engine.calculate_win_rate(trades)
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Daily PnL from today’s trades
            def get_attr(t, attr, default=None):
                return t.get(attr, default) if isinstance(t, dict) else getattr(t, attr, default)

            daily_pnl = sum(
                float(get_attr(t, "pnl", 0.0))
                for t in trades
                if isinstance(get_attr(t, "timestamp", ""), str)
                and get_attr(t, "timestamp", "").startswith(today_str)
            )

            # PnL metrics depending on tab
            unrealized_pnl = 0.0
            realized_pnl = 0.0

            if i == 1:  # Open trades
                unrealized_pnl = sum(float(get_attr(t, "unrealized_pnl", 0.0)) for t in trades)
            elif i == 2:  # Closed trades
                realized_pnl = sum(float(get_attr(t, "pnl", 0.0)) for t in trades)

            # === Display metrics ===
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Balance", f"${capital:.2f}", currency)
            col2.metric("Total Return", f"{total_return_pct:+.2f}%")
            col3.metric("Daily P&L", f"${daily_pnl:+.2f}")
            col4.metric("Win Rate", f"{win_rate:.2f}%")

            if i == 1:
                st.markdown("### 📊 Unrealized P&L")
                st.metric("Unrealized PnL (Open Trades)", f"${unrealized_pnl:+.2f}")

            if i == 2:
                st.markdown("### 💰 Realized P&L")
                st.metric("Realized PnL (Closed Trades)", f"${realized_pnl:+.2f}")

            st.markdown("---")

            # === Charts and Stats ===
            left, right = st.columns([2, 1])
            with left:
                st.subheader("📈 Assets Analysis")
                if trades:
                    fig = dashboard.create_detailed_performance_chart(trades, capital)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No trade data available.")

            with right:
                st.subheader("📊 Trade Stats")
                if trades:
                    stats = trading_engine.calculate_trade_statistics(trades)
                    dashboard.display_trade_statistics(stats)
                else:
                    st.info("No statistics available.")

            # === Trades Table ===
            st.subheader("🧾 Trades Table")
            if trades:
                dashboard.display_trades_table(trades)
            else:
                st.info("No trades found.")
