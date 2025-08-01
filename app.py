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
        # === Load full capital.json once ===
        capital_data = trading_engine.load_capital() or {}
        real = capital_data.get("real", {})
        virtual = capital_data.get("virtual", {})

        # === Real Wallet Info ===
        real_capital = float(real.get("capital", 0.0))
        real_start = float(real.get("start_balance", real_capital))
        real_pnl = real_capital - real_start

        # === Virtual Wallet Info ===
        virtual_capital = float(virtual.get("capital", 0.0))
        virtual_start = float(virtual.get("start_balance", virtual_capital))
        virtual_pnl = virtual_capital - virtual_start

        # === Display Wallets ===
        st.sidebar.subheader("💰 Real Wallet")
        st.sidebar.metric("Total", f"${real_capital:,.2f}")
        st.sidebar.metric("Available", f"${real.get('available', 0):,.2f}")
        st.sidebar.metric("Used", f"${real.get('used', 0):,.2f}")
        st.sidebar.metric("PnL", format_currency(real_pnl), f"{format_percentage(real_pnl)} today")

        st.sidebar.subheader("🧪 Virtual Wallet")
        st.sidebar.metric("Total", f"${virtual_capital:,.2f}")
        st.sidebar.metric("Available", f"${virtual.get('available', 0):,.2f}")
        st.sidebar.metric("Used", f"${virtual.get('used', 0):,.2f}")
        st.sidebar.metric("PnL", format_currency(virtual_pnl), f"{format_percentage(virtual_pnl)} today")


        # === Trading Status based on MAX_LOSS_PCT threshold ===
        max_loss_pct = float(trading_engine.default_settings.get("MAX_LOSS_PCT", -15.0))
        trading_status = "🟢 Active" if real_pnl > max_loss_pct else "🔴 Paused"
        status_color = get_status_color("success" if real_pnl > 0 else "failed" if real_pnl < 0 else "pending")

        st.sidebar.markdown(
            f"**Status:** <span style='color: {status_color}'>{trading_status}</span>",
            unsafe_allow_html=True
        )

        # === Automation Status ===
        automation_status = automated_trader.get_status()
        is_running = automation_status.get("running", False)
        automation_color = "#00d4aa" if is_running else "#ff4444"
        automation_label = "🤖 Running" if is_running else "⏸️ Stopped"

        st.sidebar.markdown(
            f"**Auto Mode:** <span style='color: {automation_color}'>{automation_label}</span>",
            unsafe_allow_html=True
        )

        # === Database Health ===
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
