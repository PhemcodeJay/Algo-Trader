import streamlit as st
import os
import pandas as pd
from datetime import datetime, timedelta, timezone

def render(trading_engine, dashboard):
    st.image("logo.png", width=80)
    st.title("📈 Market Analysis")

    # --- Fetch symbols safely ---
    try:
        symbol_response = trading_engine.client.get_symbols()
        if isinstance(symbol_response, dict) and "result" in symbol_response:
            symbols = [item["name"] for item in symbol_response["result"]]
        elif isinstance(symbol_response, list):
            symbols = [item.get("symbol") or item.get("name") for item in symbol_response]
        else:
            st.warning("Unexpected symbol format from API.")
            symbols = []
    except Exception as e:
        st.error(f"Error fetching symbols: {e}")
        return

    selected_symbol = st.selectbox("Select Symbol", symbols) if symbols else None

    if not selected_symbol:
        st.info("No symbols available to select.")
        return

    # --- User input for chart params ---
    col1, col2, col3 = st.columns(3)
    with col1:
        timeframe = st.selectbox("Timeframe", ["15m", "1h", "4h", "1d"], index=1)
    with col2:
        limit = st.slider("Candles", min_value=50, max_value=500, value=100)
    with col3:
        indicators = st.multiselect(
            "Indicators",
            options=[
                "EMA 9", "EMA 21", "MA 50", "MA 200", "Bollinger Bands",
                "RSI", "MACD", "Stoch RSI", "Volume"
            ],
            default=["Bollinger Bands", "MA 200", "RSI", "Volume"]
        )

    # --- Fetch chart data ---
    with st.spinner("Loading chart data…"):
        try:
            if hasattr(trading_engine.client, "get_chart_data"):
                chart_data = trading_engine.client.get_chart_data(selected_symbol, timeframe, limit)
            else:
                chart_data = trading_engine.client.get_kline(selected_symbol, interval=timeframe, limit=limit)
        except Exception as e:
            st.error(f"Error fetching chart data: {e}")
            return

        # --- Validate chart data ---
        if not isinstance(chart_data, list) or len(chart_data) < 5:
            st.error(f"No chart data returned or invalid format for {selected_symbol}")
            return

        # --- Check required keys ---
        sample_keys = chart_data[0].keys()
        required_cols = {"timestamp", "open", "high", "low", "close"}
        if not required_cols.issubset(sample_keys):
            st.error("Chart data is missing OHLC fields.")
            st.write("Sample keys:", sample_keys)
            return

        # --- Convert timestamp ---
        df = pd.DataFrame(chart_data)
        try:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', errors='coerce') \
                if df['timestamp'].max() > 1e12 else pd.to_datetime(df['timestamp'], errors='coerce')
        except Exception as e:
            st.error(f"Timestamp conversion error: {e}")
            return

        df = df.dropna(subset=['timestamp', 'open', 'high', 'low', 'close'])

        if df.empty:
            st.error("Chart data after cleaning is empty.")
            return

        # --- Render chart ---
        try:
            fig = dashboard.create_technical_chart(df.to_dict("records"), selected_symbol, indicators)
            st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.error(f"Chart rendering error: {e}")
            st.write("Chart DF Sample:", df.head())
            return

        # --- Render current signals if available ---
        current_signals = [
            s for s in trading_engine.get_recent_signals()
            if s.get("symbol") == selected_symbol
        ]
        if current_signals:
            st.subheader(f"🎯 Current Signals for {selected_symbol}")
            for signal in current_signals:
                dashboard.display_signal_card(signal)
