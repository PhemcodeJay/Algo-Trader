import streamlit as st
from PIL import Image
from utils import get_status_color, format_currency, format_percentage, get_ticker_snapshot
from engine import engine
from dashboard_components import DashboardComponents
from automated_trader import automated_trader
from db import db_manager
from streamlit_autorefresh import st_autorefresh

# --- Setup Page ---
st.set_page_config(
    page_title="AlgoTrader",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)
st.set_option("client.showErrorDetails", True)

# --- Sidebar Header ---
logo = Image.open("logo.png")
st.sidebar.image(logo, width=100)
st.sidebar.title("🚀 AlgoTrader")
st.sidebar.markdown("---")

# --- Auto Refresh ---
auto_refresh_enabled = st.sidebar.checkbox("Auto Refresh (5 min)", value=True)
if auto_refresh_enabled:
    st_autorefresh(interval=300_000, limit=None, key="auto_refresh_5min")

# --- Init Components (cached) ---
@st.cache_resource
def init_components():
    return engine, DashboardComponents(engine)

trading_engine, dashboard = init_components()

# --- Market Ticker Bar ---
try:
    ticker_data = get_ticker_snapshot()
    dashboard.render_ticker(ticker_data, position="top")
except Exception as e:
    st.warning(f"⚠️ Could not load market ticker: {e}")

# --- Navigation Menu ---
page = st.sidebar.selectbox(
    "Navigate",
    [
        "🏠 Dashboard",
        "📊 Signals",
        "💼 Portfolio",
        "📈 Charts",
        "🤖 Automation",
        "🗄️ Database",
        "⚙️ Settings"
    ]
)

# --- Manual Refresh ---
if st.sidebar.button("🔄 Refresh Now"):
    st.cache_data.clear()
    st.rerun()

# --- Sidebar Wallet & Status ---
def render_sidebar(trading_engine, automated_trader, db_manager):
    try:
        # Load real and virtual balances
        real_balance = trading_engine.load_capital(mode="real") or {}
        virtual_balance = trading_engine.load_capital(mode="virtual") or {}

        # Daily PnL (real and virtual)
        real_pnl = trading_engine.get_daily_pnl(mode="real") or 0.0
        virtual_pnl = trading_engine.get_daily_pnl(mode="virtual") or 0.0

        # Extract capital and optionally available/used if present
        real_total = float(real_balance.get("capital", real_balance.get("available", 0.0) + real_balance.get("used", 0.0)))
        virtual_total = float(virtual_balance.get("capital", virtual_balance.get("available", 100.0) + virtual_balance.get("used", 0.0)))

        # Optional: keep available/used if your UI still needs it
        real_available = float(real_balance.get("available", 0.0))
        real_used = float(real_balance.get("used", 0.0))
        virtual_available = float(virtual_balance.get("available", 100.0))
        virtual_used = float(virtual_balance.get("used", 0.0))


        # Wallet Metrics
        st.sidebar.metric("💰 Real Wallet", format_currency(real_total), f"{format_percentage(real_pnl)} today")
        st.sidebar.metric("🧪 Virtual Wallet", format_currency(virtual_total), f"{format_percentage(virtual_pnl)} today")

        # Trading system status based on real PnL
        status = (
            "success" if real_pnl > 0
            else "failed" if real_pnl < 0
            else "pending"
        )
        status_color = get_status_color(status)
        max_loss_pct = trading_engine.default_settings.get("MAX_LOSS_PCT", -15.0)
        trading_status = "🟢 Active" if real_pnl > max_loss_pct else "🔴 Paused"
        st.sidebar.markdown(
            f"**Status:** <span style='color: {status_color}'>{trading_status}</span>",
            unsafe_allow_html=True
        )

        # Automation status
        automation_status = automated_trader.get_status()
        automation_color = "#00d4aa" if automation_status.get("running", False) else "#ff4444"
        automation_label = "🤖 Running" if automation_status.get("running", False) else "⏸️ Stopped"
        st.sidebar.markdown(
            f"**Auto Mode:** <span style='color: {automation_color}'>{automation_label}</span>",
            unsafe_allow_html=True
        )

        # Database health
        db_health = db_manager.get_db_health()
        db_color = "#00d4aa" if db_health.get("status") == "ok" else "#ff4444"
        db_status = "🟢 Ok" if db_health.get("status") == "ok" else f"🔴 Error: {db_health.get('error', '')}"
        st.sidebar.markdown(
            f"**Database:** <span style='color: {db_color}'>{db_status}</span>",
            unsafe_allow_html=True
        )

    except Exception as e:
        st.sidebar.error(f"❌ Sidebar Metrics Error: {e}")

# Call the sidebar rendering function
render_sidebar(trading_engine, automated_trader, db_manager)

# --- Page Routing ---
if page == "🏠 Dashboard":
    import views.dashboard as view
    view.render(trading_engine, dashboard, db_manager)

elif page == "📊 Signals":
    import views.signals as view
    view.render(trading_engine, dashboard)

elif page == "💼 Portfolio":
    import views.portfolio as view
    view.render(trading_engine, dashboard)

elif page == "📈 Charts":
    import views.charts as view
    view.render(trading_engine, dashboard)

elif page == "🤖 Automation":
    import views.automation as view
    view.render(trading_engine, dashboard, automated_trader)

elif page == "🗄️ Database":
    st.title("🗄️ Database Overview")

    db_health = db_manager.get_db_health()
    st.write(f"Database Health: {db_health.get('status')}")
    if db_health.get("status") != "ok":
        st.error(f"Database Error: {db_health.get('error', 'Unknown error')}")

    st.write(f"Signals count: {db_manager.get_signals_count()}")
    st.write(f"Trades count: {db_manager.get_trades_count()}")
    st.write(f"Portfolio count: {db_manager.get_portfolio_count()}")

elif page == "⚙️ Settings":
    import views.settings as view
    view.render(trading_engine, dashboard)
