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
auto_refresh_enabled = st.sidebar.checkbox("Auto Refresh (15 min)", value=True)
if auto_refresh_enabled:
    st_autorefresh(interval=900_000, limit=None, key="auto_refresh_15min")

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

# --- Manual Refresh Button ---
if st.sidebar.button("🔄 Refresh Now"):
    st.cache_data.clear()
    st.rerun()

# --- Sidebar Wallet & Status ---
def render_sidebar(trading_engine, automated_trader, db_manager):
    try:
        real_balance = trading_engine.load_capital(mode="real") or {}
        virtual_balance = trading_engine.load_capital(mode="virtual") or {}

        real_total = float(real_balance.get("capital") or real_balance.get("available", 0.0) + real_balance.get("used", 0.0))
        virtual_total = float(virtual_balance.get("capital") or virtual_balance.get("available", 100.0) + virtual_balance.get("used", 0.0))

        real_pnl = float(trading_engine.get_daily_pnl(mode="real") or 0.0)
        virtual_pnl = float(trading_engine.get_daily_pnl(mode="virtual") or 0.0)

        st.sidebar.metric("💰 Real Wallet", f"${real_total:,.2f}", f"{format_percentage(real_pnl)} today")
        st.sidebar.metric("🧪 Virtual Wallet", f"${virtual_total:,.2f}", f"{format_percentage(virtual_pnl)} today")

        max_loss_pct = float(trading_engine.default_settings.get("MAX_LOSS_PCT", -15.0))
        trading_status = "🟢 Active" if real_pnl > max_loss_pct else "🔴 Paused"
        status_color = get_status_color("success" if real_pnl > 0 else "failed" if real_pnl < 0 else "pending")

        st.sidebar.markdown(
            f"**Status:** <span style='color: {status_color}'>{trading_status}</span>",
            unsafe_allow_html=True
        )

        automation_status = automated_trader.get_status()
        is_running = automation_status.get("running", False)
        automation_color = "#00d4aa" if is_running else "#ff4444"
        automation_label = "🤖 Running" if is_running else "⏸️ Stopped"

        st.sidebar.markdown(
            f"**Auto Mode:** <span style='color: {automation_color}'>{automation_label}</span>",
            unsafe_allow_html=True
        )

        db_health = db_manager.get_db_health()
        db_color = "#00d4aa" if db_health.get("status") == "ok" else "#ff4444"
        db_status = "🟢 Ok" if db_health.get("status") == "ok" else f"🔴 Error: {db_health.get('error', 'Unknown')}"
        st.sidebar.markdown(
            f"**Database:** <span style='color: {db_color}'>{db_status}</span>",
            unsafe_allow_html=True
        )

    except Exception as e:
        st.sidebar.error(f"❌ Sidebar Metrics Error: {e}")

# ✅ --- RENDER Sidebar Info ---
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

    signals_count = db_manager.get_signals_count()
    trades_count = db_manager.get_trades_count()
    portfolio_count = db_manager.get_portfolio_count()

    st.write(f"Signals count: {signals_count}")
    st.write(f"Trades count: {trades_count}")
    st.write(f"Portfolio count: {portfolio_count}")

elif page == "⚙️ Settings":
    import views.settings as view
    view.render(trading_engine, dashboard)
