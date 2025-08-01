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
        # Load wallet balances
        real_balance = trading_engine.load_capital(mode="real") or {}
        virtual_balance = trading_engine.load_capital(mode="virtual") or {}

        # Extract capital safely with fallbacks
        real_total = float(real_balance.get("capital") or real_balance.get("available", 0.0) + real_balance.get("used", 0.0))
        virtual_total = float(virtual_balance.get("capital") or virtual_balance.get("available", 100.0) + virtual_balance.get("used", 0.0))

        # Get Daily PnL
        real_pnl = float(trading_engine.get_daily_pnl(mode="real") or 0.0)
        virtual_pnl = float(trading_engine.get_daily_pnl(mode="virtual") or 0.0)

        # Display wallet metrics with dollar formatting
        st.sidebar.metric("💰 Real Wallet", f"${real_total:,.2f}", f"{format_percentage(real_pnl)} today")
        st.sidebar.metric("🧪 Virtual Wallet", f"${virtual_total:,.2f}", f"{format_percentage(virtual_pnl)} today")

        # Trading Status (based on PnL)
        max_loss_pct = float(trading_engine.default_settings.get("MAX_LOSS_PCT", -15.0))
        trading_status = "🟢 Active" if real_pnl > max_loss_pct else "🔴 Paused"
        status_color = get_status_color("success" if real_pnl > 0 else "failed" if real_pnl < 0 else "pending")

        st.sidebar.markdown(
            f"**Status:** <span style='color: {status_color}'>{trading_status}</span>",
            unsafe_allow_html=True
        )

        # Automation status
        automation_status = automated_trader.get_status()
        is_running = automation_status.get("running", False)
        automation_color = "#00d4aa" if is_running else "#ff4444"
        automation_label = "🤖 Running" if is_running else "⏸️ Stopped"

        st.sidebar.markdown(
            f"**Auto Mode:** <span style='color: {automation_color}'>{automation_label}</span>",
            unsafe_allow_html=True
        )

        # Database status
        db_health = db_manager.get_db_health()
        db_color = "#00d4aa" if db_health.get("status") == "ok" else "#ff4444"
        db_status = "🟢 Ok" if db_health.get("status") == "ok" else f"🔴 Error: {db_health.get('error', 'Unknown')}"
        st.sidebar.markdown(
            f"**Database:** <span style='color: {db_color}'>{db_status}</span>",
            unsafe_allow_html=True
        )

    except Exception as e:
        st.sidebar.error(f"❌ Sidebar Metrics Error: {e}")
