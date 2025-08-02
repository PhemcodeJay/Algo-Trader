import streamlit as st
from PIL import Image
from utils import get_ticker_snapshot
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

# --- Sidebar Wallet Display ---
def render_wallet_summary(trading_engine):
    try:
        capital_data = trading_engine.load_capital("all") or {}
        real = capital_data.get("real", {})
        virtual = capital_data.get("virtual", {})

        # --- Virtual Wallet ---
        st.sidebar.subheader("🧪 Virtual Wallet")
        st.sidebar.metric("Available", f"${float(virtual.get('available', 0.0)):,.2f}")
        st.sidebar.metric("Total", f"${float(virtual.get('capital', 0.0)):,.2f}")

        # --- Real Wallet ---
        st.sidebar.subheader("💰 Real Wallet")
        st.sidebar.metric("Available", f"${float(real.get('available', 0.0)):,.2f}")
        st.sidebar.metric("Total", f"${float(real.get('capital', 0.0)):,.2f}")
       
    except Exception as e:
        st.sidebar.error(f"❌ Wallet Load Error: {e}")

# ✅ Render Sidebar Wallet Info
render_wallet_summary(trading_engine)

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
