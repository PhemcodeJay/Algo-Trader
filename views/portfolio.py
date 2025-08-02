import streamlit as st
from datetime import datetime, timezone
from utils import format_trades

def render(trading_engine, dashboard):
    st.image("logo.png", width=80)
    st.title("💼 Wallet Summary")

    def get_attr(t, attr, default=None):
        return t.get(attr, default) if isinstance(t, dict) else getattr(t, attr, default)

    tabs = st.tabs(["🔄 All Trades", "📂 Open Trades", "✅ Closed Trades"])

    for i, tab in enumerate(tabs):
        with tab:
            mode = st.radio("Mode", ["All", "Real", "Virtual"], key=f"mode_{i}", horizontal=True)

            # === Load trades based on tab and mode ===
            if i == 0:  # All
                trades = trading_engine.get_recent_trades(limit=100) or []
            else:
                if mode == "All":
                    trades = (
                        trading_engine.get_open_real_trades() + trading_engine.get_open_virtual_trades()
                        if i == 1 else
                        trading_engine.get_closed_real_trades() + trading_engine.get_closed_virtual_trades()
                    )
                elif mode == "Real":
                    trades = (
                        trading_engine.get_open_real_trades()
                        if i == 1 else
                        trading_engine.get_closed_real_trades()
                    )
                else:
                    trades = (
                        trading_engine.get_open_virtual_trades()
                        if i == 1 else
                        trading_engine.get_closed_virtual_trades()
                    )

            # === Load capital ===
            if mode == "All":
                balances = trading_engine.load_capital("all") or {}
                real = balances.get("real", {})
                virtual = balances.get("virtual", {})

                capital = float(real.get("capital", 0.0)) + float(virtual.get("capital", 0.0))
                available = float(real.get("available", real.get("capital", 0.0))) + float(virtual.get("available", virtual.get("capital", 0.0)))
                start_balance = float(real.get("start_balance", 0.0)) + float(virtual.get("start_balance", 0.0))
                currency = real.get("currency") or virtual.get("currency", "USD")
            else:
                balance = trading_engine.load_capital(mode.lower()) or {}

                capital = float(balance.get("capital", 0.0))
                available = float(balance.get("available", balance.get("capital", 0.0)))
                start_balance = float(balance.get("start_balance", 0.0))
                currency = balance.get("currency", "USD")

            # === Metrics Calculation ===
            total_return_pct = ((capital - start_balance) / start_balance * 100) if start_balance else 0.0
            win_rate = trading_engine.calculate_win_rate(trades)
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            daily_pnl = sum(
                float(get_attr(t, "pnl", 0.0) or 0.0)
                for t in trades
                if str(get_attr(t, "timestamp", "")).startswith(today_str)
            )

            unrealized_pnl = sum(float(get_attr(t, "unrealized_pnl", 0.0)) for t in trades) if i == 1 else 0.0
            realized_pnl = sum(float(get_attr(t, "pnl", 0.0)) for t in trades) if i == 2 else 0.0

            # === Dashboard Metrics ===
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("Capital", f"${capital:,.2f}", currency)
            col2.metric("Available", f"${available:,.2f}")
            col3.metric("Total Return", f"{total_return_pct:+.2f}%")
            col4.metric("Daily P&L", f"${daily_pnl:+.2f}")
            col5.metric("Win Rate", f"{win_rate:.2f}%")

            # === Extra P&L Display ===
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

            st.markdown("---")

            # === Trades Table or Manual UI ===
            st.subheader("🧾 Trades Table")

            # Format for display
            formatted_trades = format_trades(trades)

            if not formatted_trades:
                st.info("No trades found.")
                continue

            # === Pagination ===
            page_size = 10
            total = len(formatted_trades)
            page_num = st.number_input("Page", min_value=1, max_value=(total - 1) // page_size + 1, step=1, key=f"page_{i}")
            start = (page_num - 1) * page_size
            end = start + page_size
            paginated_trades = formatted_trades[start:end]

            # === Virtual Open Trade Closing Buttons ===
            if i == 1 and mode == "Virtual":
                for trade in paginated_trades:
                    with st.expander(f"{trade['symbol']} | {trade['Side']} | Entry: {trade['Entry']}"):
                        cols = st.columns(4)
                        cols[0].markdown(f"**Qty:** {trade['Qty']}")
                        cols[1].markdown(f"**SL:** {trade['SL']}")
                        cols[2].markdown(f"**TP:** {trade['TP']}")
                        cols[3].markdown(f"**PnL:** {trade['PnL']}")
                        st.markdown(f"**Status:** {trade['Status']}  &nbsp;&nbsp; ⏱ `{trade['Time']}`")

                        if trade["Status"].lower() == "open":
                            if st.button("❌ Close Trade", key=f"close_{trade['Symbol']}_{trade['Time']}"):
                                success = trading_engine.close_virtual_trade(trade.get("id"))
                                if success:
                                    st.success("Trade closed successfully.")
                                    st.rerun()
                                else:
                                    st.error("Failed to close trade.")
            else:
                dashboard.display_trades_table(paginated_trades)
