import os
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple, Union, List, cast
import requests
from requests.structures import CaseInsensitiveDict

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

def extract_response(response: Union[Dict[str, Any], Tuple[Any, ...]]) -> Dict[str, Any]:
    if isinstance(response, tuple):
        if len(response) >= 1 and isinstance(response[0], dict):
            return response[0]
        logger.warning("Unexpected tuple response format")
        return {}
    elif isinstance(response, dict):
        return response
    else:
        logger.warning(f"Unexpected response type: {type(response)}")
        return {}

class BybitClient:
    def __init__(self):
        self.use_real = os.getenv("USE_REAL_TRADING", "").strip().lower() in ("1", "true", "yes")
        self.use_testnet = os.getenv("BYBIT_TESTNET", "").strip().lower() in ("1", "true", "yes")

        if self.use_real and self.use_testnet:
            logger.error("❌ Conflict: Both USE_REAL_TRADING and BYBIT_TESTNET are set. Enable only one.")
            self.client = None
            return

        self._virtual_orders: List[Dict[str, Any]] = []
        self._virtual_positions: List[Dict[str, Any]] = []

        self.session = requests.Session()
        self.base_url = "https://api.bybit.com"  # default for mainnet

        try:
            from pybit.unified_trading import HTTP
            self._HTTP = HTTP
        except ImportError as e:
            logger.error("❌ Pybit is not installed or failed to import: %s", e)
            self.client = None
            return

        if self.use_real:
            self.api_key = os.getenv("BYBIT_API_KEY", "")
            self.api_secret = os.getenv("BYBIT_API_SECRET", "")
            if not self.api_key or not self.api_secret:
                logger.error("❌ BYBIT_API_KEY and/or BYBIT_API_SECRET not set.")
                self.client = None
                return
            try:
                self.client = self._HTTP(api_key=self.api_key, api_secret=self.api_secret, testnet=False)
                logger.info("[BybitClient] ✅ Live trading enabled (mainnet)")
            except Exception as e:
                logger.exception("❌ Failed to initialize Bybit client: %s", e)
                self.client = None

        elif self.use_testnet:
            self.api_key = ""
            self.api_secret = ""
            self.client = None
            self.base_url = "https://api-testnet.bybit.com"
            self._load_virtual_wallet()
            logger.info("[BybitClient] 🧪 Virtual trading mode enabled")

        else:
            logger.error("❌ Neither USE_REAL_TRADING nor BYBIT_TESTNET is set.")
            self.client = None

    def _load_virtual_wallet(self):
        try:
            with open("capital.json", "r") as f:
                self.virtual_wallet = json.load(f)
                logger.info("[BybitClient] ✅ Loaded virtual wallet from capital.json")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error("❌ Error loading capital.json: %s", e)
            self.virtual_wallet = {}

    def _send_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], timedelta, CaseInsensitiveDict]:
        if self.client is None:
            return {}, timedelta(), CaseInsensitiveDict()

        method_func = getattr(self.client, method, None)
        if not callable(method_func):
            logger.error(f"Method '{method}' not found.")
            return {}, timedelta(), CaseInsensitiveDict()

        try:
            start_time = datetime.now()
            raw_result = method_func(**(params or {}))
            elapsed = datetime.now() - start_time
            return cast(Dict[str, Any], raw_result), elapsed, CaseInsensitiveDict()
        except Exception as e:
            logger.exception(f"Error calling Bybit API method '{method}': {e}")
            return {}, timedelta(), CaseInsensitiveDict()

    def get_kline(self, symbol: str, interval: str, limit: int = 200) -> Dict[str, Any]:
        response = self._send_request("kline", {"symbol": symbol, "interval": interval, "limit": limit})
        return extract_response(response)

    def get_chart_data(self, symbol: str, interval: str = "1", limit: int = 100) -> List[Dict[str, Any]]:
        raw = self.get_kline(symbol, interval, limit)
        if not raw.get("result", {}).get("list"):
            return []
        return [
            {
                "timestamp": datetime.fromtimestamp(int(item[0]) / 1000),
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": float(item[5])
            } for item in raw["result"]["list"]
        ]

    def get_balance(self, coin: str = "USDT") -> dict:
        if self.client is None:
            return {
                "capital": float(self.virtual_wallet.get("capital", 100.0)),
                "currency": self.virtual_wallet.get("currency", coin)
            }

        response = self._send_request("wallet_balance", {"coin": coin})
        data = extract_response(response)
        balance = data.get(coin, {}).get("available_balance", 100.0)
        return {"capital": float(balance), "currency": coin}
    
    def get_wallet_balance(self) -> dict:
        if self.use_real:
            return self.get_balance("USDT")

        wallet = self.virtual_wallet.get("virtual", {})
        return {
            "available": wallet.get("available", 0.0),
            "used": wallet.get("used", 0.0),
            "equity": wallet.get("available", 0.0) + wallet.get("used", 0.0),
            "currency": self.virtual_wallet.get("currency", "USDT")
        }

    
    def calculate_margin(self, qty: float, price: float, leverage: float) -> float:
        return round((qty * price) / leverage, 2)
    
    def _save_virtual_wallet(self):
        try:
            with open("capital.json", "w") as f:
                json.dump(self.virtual_wallet, f, indent=4)
            logger.info("[BybitClient] 💾 Virtual wallet updated in capital.json")
        except Exception as e:
            logger.error(f"❌ Failed to save capital.json: {e}")
            

    def place_order(self, symbol: str, side: str, order_type: str, qty: float, price: Optional[float] = None,
                time_in_force: Optional[str] = "GoodTillCancel", reduce_only: bool = False,
                close_on_trigger: bool = False, order_link_id: Optional[str] = None) -> Dict[str, Any]:
        if self.use_real and self.client:
            params: Dict[str, Any] = {
                "symbol": symbol,
                "side": side,
                "order_type": order_type,
                "qty": qty,
                "time_in_force": time_in_force,
                "reduce_only": reduce_only,
                "close_on_trigger": close_on_trigger,
            }
            if price is not None:
                params["price"] = price
            if order_link_id:
                params["order_link_id"] = order_link_id
            response = self._send_request("place_active_order", params)
            return extract_response(response)

        # Virtual mode
        order_id = f"virtual_{int(time.time() * 1000)}"
        price_used = price or 1.0  # prevent division by zero
        leverage = 20  # You can make this dynamic
        margin = self.calculate_margin(qty, price_used, leverage)

        # Check if enough capital
        wallet = self.virtual_wallet.get("virtual", {})
        available_capital = wallet.get("available", 0)
        if margin > available_capital:
            logger.warning(f"[Virtual] ❌ Not enough capital. Needed: {margin}, Available: {available_capital}")
            return {"error": "Insufficient virtual capital"}

        # ✅ Close any open position on same symbol (if exists) and get PnL
        closed_pos = self.close_virtual_position(symbol)
        pnl = closed_pos.get("realized_pnl", 0) if closed_pos else 0

        # ✅ Update wallet
        wallet["available"] = wallet.get("available", 0) - margin + pnl
        wallet["used"] = wallet.get("used", 0) + margin
        self.virtual_wallet["virtual"] = wallet
        self._save_virtual_wallet()

        # ✅ Record virtual order
        virtual_order = {
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "qty": qty,
            "price": price,
            "status": "open",
            "margin": margin,
            "leverage": leverage,
            "create_time": datetime.utcnow()
        }
        self._virtual_orders.append(virtual_order)

        self._virtual_positions.append({
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price or 0.0,
            "margin": margin,
            "status": "open",
            "create_time": datetime.utcnow(),
            "order_id": order_id
        })

        return virtual_order

        
    def get_open_positions(self) -> List[Dict[str, Any]]:
        return [pos for pos in self._virtual_positions if pos["status"] == "open"]

    def get_closed_positions(self) -> List[Dict[str, Any]]:
        return [pos for pos in self._virtual_positions if pos["status"] == "closed"]

    def close_virtual_position(self, symbol: str):
        for pos in self._virtual_positions:
            if pos["symbol"] == symbol and pos["status"] == "open":
                pos["status"] = "closed"
                pos["close_time"] = datetime.utcnow()

                # ✅ Calculate PnL first
                pnl = self.calculate_virtual_pnl(pos)
                pos["unrealized_pnl"] = pnl
                pos["realized_pnl"] = pnl  # For virtual trading, unrealized is treated as realized
                margin = pos.get("margin", 0)

                # ✅ Update wallet
                wallet = self.virtual_wallet.get("virtual", {})
                wallet["used"] = max(wallet.get("used", 0) - margin, 0)
                wallet["available"] = wallet.get("available", 0) + margin + pnl
                self.virtual_wallet["virtual"] = wallet

                self._save_virtual_wallet()

                logger.info(f"[Virtual] Closed {symbol}: Margin refunded: {margin}, PnL: {pnl:.2f}, New balance: {wallet['available']:.2f}")
                return pos

        logger.warning(f"[Virtual] No open position found for {symbol} to close.")
        return None


    def calculate_virtual_pnl(self, position: Dict[str, Any]) -> float:
        symbol = position["symbol"]
        entry_price = float(position.get("price", 0))
        qty = float(position.get("qty", 0))
        side = position["side"].lower()

        candles = self.get_chart_data(symbol=symbol, interval="1", limit=1)
        if not candles:
            logger.warning(f"Price not available for {symbol}")
            return 0.0

        last_price = candles[-1]["close"]
        if side == "buy":
            return (last_price - entry_price) * qty
        else:
            return (entry_price - last_price) * qty

    def get_virtual_unrealized_pnls(self) -> List[Dict[str, Any]]:
        return [
            {**pos, "unrealized_pnl": self.calculate_virtual_pnl(pos)}
            for pos in self.get_open_positions()
        ]
    
    def monitor_virtual_orders(self):
        """Simulate monitoring and filling of virtual orders."""
        for order in self._virtual_orders:
            if order["status"] == "open":
                order["status"] = "filled"
                order["fill_time"] = datetime.utcnow()
                logger.info(f"[Virtual] Order {order['order_id']} filled at {order['price']}")

        for pos in self._virtual_positions:
            if pos["status"] == "open" and "fill_time" not in pos:
                pos["fill_time"] = datetime.utcnow()
                logger.info(f"[Virtual] Position for {pos['symbol']} marked as active.")

    def get_symbols(self):
        try:
            url = self.base_url + "/v5/market/instruments-info"
            params = {"category": "linear"}
            response = self.session.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("result", {}).get("list", [])
        except Exception as e:
            print(f"[BybitClient] ❌ Failed to fetch symbols: {e}")
            return []


# Export instance
bybit_client = BybitClient()
