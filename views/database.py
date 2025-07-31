import streamlit as st
import pandas as pd

def render(db_manager):
    st.image("logo.png", width=80) 
    st.title("🗄️ Trade Journal")

    col1, col2, col3 = st.columns(3)

    # Database status
    try:
        db_health = db_manager.get_db_health()
        status = db_health.get("status", "error")
        col1.metric("Database Status", "🟢 Ok" if status == "ok" else "🔴 Error")
    except Exception as e:
        col1.metric("Database Status", "🔴 Error")
        st.error(str(e))

    # Total trades
    try:
        trades = db_manager.get_trades(limit=1000)
        col2.metric("Total Trades", len(trades))
    except Exception:
        col2.metric("Total Trades", "Error")

    # Total signals
    try:
        signals = db_manager.get_signals(limit=1000)
        col3.metric("Total Signals", len(signals))
    except Exception:
        col3.metric("Total Signals", "Error")

    st.markdown("---")

    # Left: Recent trades
    left, right = st.columns(2)
    with left:
        st.subheader("📊 Recent Trades")
        try:
            recent = db_manager.get_trades(limit=5)
            if recent:
                for t in recent:
                    t_dict = t.to_dict() if hasattr(t, "to_dict") else t
                    pnl = t_dict.get("pnl", 0.0)
                    pnl_color = "🟢" if pnl > 0 else "🔴"
                    st.write(f"{pnl_color} {t_dict['symbol']} - ${pnl:.2f}")
            else:
                st.info("No trades in database.")
        except Exception as e:
            st.error(str(e))

    # Right: System Info
    with right:
        st.subheader("🛠️ System Info")
        try:
            portfolio = db_manager.get_portfolio()
            balance = sum(p.capital for p in portfolio) if portfolio else 0.0
            daily_pnl = db_manager.get_daily_pnl_pct()
            stats = db_manager.get_automation_stats()

            color = "🟢" if daily_pnl >= 0 else "🔴"
            st.write(f"**Wallet:** ${balance:.2f}")
            st.write(f"**Daily P&L:** {color} {daily_pnl:.2f}%")
            st.write(f"**Total Signals:** {stats.get('total_signals', '—')}")
            st.write(f"**Open Trades:** {stats.get('open_trades', '—')}")
            st.write(f"**Last Update:** {stats.get('timestamp', '—')}")
        except Exception as e:
            st.error(str(e))

    st.markdown("---")

    # DB Operations
    st.subheader("🔧 DB Operations")
    col1, col2, col3 = st.columns(3)

    if col1.button("🔄 Test Connection"):
        try:
            db_manager.get_session().execute("SELECT 1")
            st.success("Connection successful.")
        except Exception as e:
            st.error(f"Connection failed: {e}")

    if col2.button("📊 Refresh Stats"):
        st.rerun()

    if col3.button("🔄 Migrate JSON Data"):
        try:
            if hasattr(db_manager, "migrate_json_data"):
                db_manager.migrate_json_data()
                st.success("Migration complete.")
            else:
                st.warning("Migration method not implemented.")
        except Exception as e:
            st.error(f"Migration error: {e}")

    # Database Tables
    st.subheader("📋 Database Tables")
    table_map = {
        "portfolio": "Wallet balance & open holdings",
        "trades": "Executed trades & PnL",
        "signals": "Generated trading signals",
        "settings": "Config key‑value pairs",
    }

    for tbl, desc in table_map.items():
        with st.expander(f"📁 {tbl.upper()}"):
            st.caption(desc)
            try:
                fetch_method = getattr(db_manager, f"get_{tbl}")
                data = fetch_method()  # assumes default limit inside method
                df = pd.DataFrame([r.to_dict() if hasattr(r, "to_dict") else r for r in data])
                st.dataframe(df, use_container_width=True)
            except Exception as e:
                st.error(f"Error loading {tbl}: {e}")
