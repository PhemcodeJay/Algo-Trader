import os
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple, Union, List, cast
import requests
from requests.structures import CaseInsensitiveDict
from db import db_manager


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
                logger.info("[BybitClient] ✅ Loaded virtual wallet from JSON")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error("❌ Error loading capital.json: %s", e)
            self.virtual_wallet = {}

    def _send_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], timedelta, CaseInsensitiveDict]:
        if self.client is None:
            logger.error("[BybitClient] ❌ Client not initialized.")
            return {}, timedelta(), CaseInsensitiveDict()

        # NEW: Special-case nested methods
        if method == "get_orders":
            method_func = getattr(self.client.order, "get_orders", None)
        elif method == "get_order":
            method_func = getattr(self.client.order, "get_order", None)
        else:
            method_func = getattr(self.client, method, None)

        if not callable(method_func):
            logger.error(f"[BybitClient] ❌ Method '{method}' not found on client.")
            return {}, timedelta(), CaseInsensitiveDict()

        try:
            start_time = datetime.now()
            raw_result = method_func(**(params or {}))
            elapsed = datetime.now() - start_time

            if not isinstance(raw_result, dict):
                logger.warning(f"[BybitClient] ⚠️ Invalid response format: {raw_result}")
                return {}, elapsed, CaseInsensitiveDict()

            if raw_result.get("retCode") != 0:
                logger.warning(f"[BybitClient] ⚠️ API Error: {raw_result.get('retMsg')} (ErrCode: {raw_result.get('retCode')})")
                return {}, elapsed, CaseInsensitiveDict()

            result = raw_result.get("result") or {}
            return result, elapsed, CaseInsensitiveDict(raw_result.get("retExtInfo", {}))

        except Exception as e:
            logger.exception(f"[BybitClient] ❌ Exception during '{method}' call: {e}")
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

    def wallet_balance(self, coin: str = "USDT") -> dict:
        if self.use_real:
            # === Real trading: Call Bybit API with accountType ===
            response, _, _ = self._send_request("get_wallet_balance", {
                "accountType": "UNIFIED",   # or "CONTRACT" / "SPOT" depending on your setup
                "coin": coin
            })

            if not response:
                logger.warning("[BybitClient] ⚠️ No wallet balance response received.")
                return {"capital": 0.0, "currency": coin}

            balance_info = response.get("result", {}).get("list", [])
            if balance_info:
                coin_balances = balance_info[0].get("coin", [])
                for c in coin_balances:
                    if c.get("coin") == coin:
                        available = c.get("availableToWithdraw", 0.0)
                        return {"capital": float(available), "currency": coin}

            logger.warning("[BybitClient] ⚠️ Wallet balance for coin not found.")
            return {"capital": 0.0, "currency": coin}

        else:
            # === Virtual mode: Load from capital.json ===
            try:
                with open("capital.json", "r") as f:
                    capital_data = json.load(f)

                virtual = capital_data.get("virtual", {})
                capital = float(virtual.get("available", 0.0) + virtual.get("used", 0.0))
                currency = virtual.get("currency", coin)

                return {
                    "capital": capital,
                    "currency": currency
                }

            except Exception as e:
                logger.exception("[BybitClient] ❌ Failed to load virtual capital.")
                return {"capital": 0.0, "currency": coin}

    
    def get_wallet_balance(self) -> dict:
        if self.use_real:
            # Use wallet_balance for real
            return self.wallet_balance("USDT")
        else:
            # Virtual mode: get detailed virtual wallet info
            try:
                with open("capital.json", "r") as f:
                    capital_data = json.load(f)
                virtual = capital_data.get("virtual", {})
                available = float(virtual.get("available", 0.0))
                used = float(virtual.get("used", 0.0))
                return {
                    "available": available,
                    "used": used,
                    "equity": available + used,
                    "currency": virtual.get("currency", "USDT")
                }
            except Exception as e:
                return {
                    "available": 0.0,
                    "used": 0.0,
                    "equity": 0.0,
                    "currency": "USDT"
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
            

    def get_qty_step(self, symbol: str) -> float:
        if not self.client:
            return 1.0

        try:
            result = self.client.get_instruments_info(category="linear", symbol=symbol)
            if isinstance(result, tuple):
                result = result[0]  # Get just the response dict

            instruments = result.get("result", {}).get("list", [])
            if instruments:
                qty_step = instruments[0].get("lotSizeFilter", {}).get("qtyStep")
                return float(qty_step)
        except Exception as e:
            logger.error(f"Failed to fetch qtyStep for {symbol}: {e}")
        return 1.0

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        qty: float,
        price: Optional[float] = None,
        time_in_force: Optional[str] = "GoodTillCancel",
        reduce_only: bool = False,
        close_on_trigger: bool = False,
        order_link_id: Optional[str] = None
    ) -> Dict[str, Any]:

        if self.use_real and self.client:
            if order_link_id:
                try:
                    open_orders = self._send_request("get_open_orders", {"symbol": symbol})
                    open_orders_data = extract_response(open_orders)
                    matched_order = next(
                        (o for o in open_orders_data.get("list", []) if o.get("order_link_id") == order_link_id),
                        None
                    )
                    if matched_order:
                        amend_params = {
                            "symbol": symbol,
                            "order_link_id": order_link_id,
                            "qty": qty
                        }
                        if price is not None:
                            amend_params["price"] = price
                        response = self._send_request("amend_active_order", amend_params)
                        return extract_response(response)
                except Exception as e:
                    logger.warning(f"[Real] ⚠️ Failed to amend order with link_id={order_link_id}: {e}")

            qty_step = self.get_qty_step(symbol)
            qty = round(float(qty) / qty_step) * qty_step
            precision = str(qty_step)[::-1].find('.')
            formatted_qty = f"{qty:.{precision}f}"

            params: Dict[str, Any] = {
                "category": "linear",
                "symbol": symbol,
                "side": side,
                "order_type": order_type,
                "qty": formatted_qty,
                "time_in_force": time_in_force,
                "reduce_only": reduce_only,
                "close_on_trigger": close_on_trigger,
            }
            if price is not None:
                params["price"] = price
            if order_link_id:
                params["order_link_id"] = order_link_id

            response = self._send_request("place_order", params)

            try:
                data = extract_response(response)
            except Exception as e:
                logger.error(f"[Real] ❌ Failed to extract response: {e}")
                return {
                    "success": False,
                    "message": "Invalid response format",
                    "error": str(e),
                    "response": response
                }

            result = data.get("result", data)
            order_id = result.get("orderId") or result.get("order_id")
            if not order_id:
                logger.warning(f"[Real] ⚠️ No order_id returned: {response}")
                return {
                    "success": False,
                    "message": "No order ID returned",
                    "response": response
                }

            try:
                time.sleep(0.5)
                status_resp = self._send_request("get_orders", {"category": "linear", "orderId": order_id})
                order_info = extract_response(status_resp)

                if not isinstance(order_info, dict):
                    logger.warning(f"[Real] ❌ Unexpected order_info type: {type(order_info)} - {order_info}")
                    return {
                        "success": False,
                        "message": "Invalid order info returned",
                        "order_id": order_id,
                        "response": order_info
                    }

                order_status = order_info.get("order_status", "UNKNOWN")

                if order_status in ["New", "PartiallyFilled", "Filled"]:
                    logger.info(f"[Real] ✅ Order confirmed. Placing TP/SL limit orders...")

                    try:
                        entry_price = float(result.get("price") or price)
                        self.place_tp_sl_limit_orders(
                            symbol=symbol,
                            side=side,
                            entry_price=entry_price,
                            qty=qty,
                            order_link_id=order_link_id
                        )
                    except Exception as e:
                        logger.error(f"[TP/SL] ❌ Failed to place TP/SL: {e}")

                    return {
                        "success": True,
                        "message": "Order placed successfully",
                        "order_id": order_id,
                        "status": order_status,
                        "response": result
                    }
                else:
                    logger.warning(f"[Real] ❌ Order not active: {order_info}")
                    return {
                        "success": False,
                        "message": f"Order status is '{order_status}'",
                        "order_id": order_id,
                        "response": order_info
                    }

            except Exception as e:
                logger.error(f"[Real] 🚨 Failed to validate order status: {e}")
                return {
                    "success": False,
                    "message": "Exception while checking order status",
                    "error": str(e),
                    "response": response
                }

       # ============================
        # ✅ Virtual Trading Mode
        # ============================
        price_used = price or 1.0
        leverage = 20
        margin = self.calculate_margin(qty, price_used, leverage)
        wallet = self.virtual_wallet.get("virtual", {})
        available_capital = wallet.get("available", 0)

        # Check for existing virtual order (amend logic)
        existing_order = next(
            (o for o in self._virtual_orders if o["symbol"] == symbol and o["side"] == side and o["status"] == "open"),
            None
        )

        if existing_order:
            old_margin = existing_order["margin"]
            margin_diff = margin - old_margin

            if margin_diff > available_capital:
                logger.warning(f"[Virtual] ❌ Not enough capital to modify order. Needed: {margin_diff}, Available: {available_capital}")
                return {"error": "Insufficient virtual capital for modification"}

            wallet["available"] -= margin_diff
            wallet["used"] += margin_diff
            self.virtual_wallet["virtual"] = wallet
            self._save_virtual_wallet()

            existing_order.update({
                "qty": qty,
                "price": price,
                "margin": margin,
                "update_time": datetime.utcnow()
            })

            for pos in self._virtual_positions:
                if pos["order_id"] == existing_order["order_id"]:
                    pos.update({
                        "qty": qty,
                        "price": price or 0.0,
                        "margin": margin,
                        "update_time": datetime.utcnow()
                    })
                    break

            return {"message": "Virtual order modified", "order": existing_order}

        # No existing order — open new position
        if margin > available_capital:
            logger.warning(f"[Virtual] ❌ Not enough capital. Needed: {margin}, Available: {available_capital}")
            return {"error": "Insufficient virtual capital"}

        # Close old and adjust wallet
        closed_pos = self.close_virtual_position(symbol)
        pnl = closed_pos.get("realized_pnl", 0) if closed_pos else 0
        wallet["available"] = wallet.get("available", 0) - margin + pnl
        wallet["used"] = wallet.get("used", 0) + margin
        self.virtual_wallet["virtual"] = wallet
        self._save_virtual_wallet()

        order_id = f"virtual_{int(time.time() * 1000)}"
        create_time = datetime.utcnow()
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
            "create_time": create_time
        }
        self._virtual_orders.append(virtual_order)

        self._virtual_positions.append({
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price or 0.0,
            "margin": margin,
            "status": "open",
            "create_time": create_time,
            "order_id": order_id
        })

        # ✅ Place TP/SL virtual limit orders
        entry_price = price or 1.0
        tp_multiplier = 1.02
        sl_multiplier = 0.98

        tp_price = round(entry_price * tp_multiplier, 4)
        sl_price = round(entry_price * sl_multiplier, 4)
        opposite_side = "Sell" if side == "Buy" else "Buy"

        tp_order = {
            "order_id": f"{order_id}_TP",
            "symbol": symbol,
            "side": opposite_side,
            "order_type": "Limit",
            "qty": qty,
            "price": tp_price,
            "status": "open",
            "reduce_only": True,
            "create_time": create_time
        }
        sl_order = {
            "order_id": f"{order_id}_SL",
            "symbol": symbol,
            "side": opposite_side,
            "order_type": "Limit",
            "qty": qty,
            "price": sl_price,
            "status": "open",
            "reduce_only": True,
            "create_time": create_time
        }

        self._virtual_orders.extend([tp_order, sl_order])

        logger.info(f"[Virtual] ✅ TP @ {tp_price}, SL @ {sl_price} placed.")

        # Save trade in DB
        trade_data = {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "entry_price": entry_price,
            "leverage": leverage,
            "margin_usdt": margin,
            "order_id": order_id,
            "status": "open",
            "timestamp": create_time,
            "virtual": True
        }
        db_manager.add_trade(trade_data)

        return virtual_order


    def place_tp_sl_limit_orders(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        qty: float,
        order_link_id: Optional[str] = None,
        order_id: Optional[str] = None
        ):
        tp_multiplier = 1.30  # +30%
        sl_multiplier = 0.85  # -15%

        tp_price = round(entry_price * tp_multiplier, 4)
        sl_price = round(entry_price * sl_multiplier, 4)

        opposite_side = "Sell" if side == "Buy" else "Buy"
        formatted_qty = f"{qty:.3f}"

        if self.use_real:
            # ✅ REAL MODE: Send to Bybit API
            tp_order = {
                "category": "linear",
                "symbol": symbol,
                "side": opposite_side,
                "order_type": "Limit",
                "qty": formatted_qty,
                "price": tp_price,
                "time_in_force": "GoodTillCancel",
                "reduce_only": True,
                "close_on_trigger": False,
                "order_link_id": f"{order_link_id}_TP" if order_link_id else None
            }

            sl_order = {
                "category": "linear",
                "symbol": symbol,
                "side": opposite_side,
                "order_type": "Limit",
                "qty": formatted_qty,
                "price": sl_price,
                "time_in_force": "GoodTillCancel",
                "reduce_only": True,
                "close_on_trigger": True,
                "order_link_id": f"{order_link_id}_SL" if order_link_id else None
            }

            self._send_request("place_order", tp_order)
            self._send_request("place_order", sl_order)
            logger.info(f"[Real] ✅ TP @ {tp_price}, SL @ {sl_price} placed for {symbol}")

        else:
            # ✅ VIRTUAL MODE: Add to virtual order book
            if not order_id:
                order_id = f"virtual_{int(time.time() * 1000)}"

            tp_order = {
                "order_id": f"{order_id}_VTP",
                "symbol": symbol,
                "side": opposite_side,
                "order_type": "Limit",
                "qty": qty,
                "price": tp_price,
                "status": "open",
                "reduce_only": True,
                "close_on_trigger": False,
                "create_time": datetime.utcnow()
            }

            sl_order = {
                "order_id": f"{order_id}_VSL",
                "symbol": symbol,
                "side": opposite_side,
                "order_type": "Limit",
                "qty": qty,
                "price": sl_price,
                "status": "open",
                "reduce_only": True,
                "close_on_trigger": True,
                "create_time": datetime.utcnow()
            }

            self._virtual_orders.extend([tp_order, sl_order])
            logger.info(f"[Virtual] ✅ TP @ {tp_price}, SL @ {sl_price} placed for {symbol}")

                
    def get_open_positions(self) -> List[Dict[str, Any]]:
        return [pos for pos in self._virtual_positions if pos["status"] == "open"]
    
    def get_orders(self, order_id: str, symbol: str, category: str = "linear") -> dict:
        return self._send_request(
            "get_orders",  # ✅ Match the key in your _endpoint_map
            {
                "orderId": order_id,   # ✅ Use camelCase to match Bybit V5 API
                "symbol": symbol,
                "category": category
            }
        )


    def get_closed_positions(self) -> List[Dict[str, Any]]:
        return [pos for pos in self._virtual_positions if pos["status"] == "closed"]

    def close_virtual_position(self, symbol: str):
        for pos in self._virtual_positions:
            if pos["symbol"] == symbol and pos["status"] == "open":
                pos["status"] = "closed"
                pos["close_time"] = datetime.utcnow()

                # ✅ Calculate PnL
                pnl = self.calculate_virtual_pnl(pos)
                pos["unrealized_pnl"] = pnl
                pos["realized_pnl"] = pnl  # Virtual PnL treated as realized
                margin = pos.get("margin", 0)

                # ✅ Update wallet
                wallet = self.virtual_wallet.get("virtual", {})
                wallet["used"] = max(wallet.get("used", 0) - margin, 0)
                wallet["available"] = wallet.get("available", 0) + margin + pnl
                self.virtual_wallet["virtual"] = wallet
                self._save_virtual_wallet()

                # ✅ Log to DB
                candles = self.get_chart_data(symbol=symbol, interval="1", limit=1)
                if candles:
                    exit_price = candles[-1]["close"]
                    db_manager.close_trade(
                        order_id=pos["order_id"],
                        exit_price=exit_price,
                        pnl=pnl
                    )
                else:
                    logger.warning(f"[Virtual] ⚠️ Could not fetch exit price for {symbol}, trade not logged.")

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
        
    def get_price_step(self, symbol: str) -> float:
        if not self.client:
            return 0.01  # fallback default

        try:
            result = self.client.get_instruments_info(category="linear", symbol=symbol)
            if isinstance(result, tuple):
                result = result[0]  # Extract the dict if it's a tuple

            instruments = result.get("result", {}).get("list", [])
            if instruments:
                tick_size = instruments[0].get("priceFilter", {}).get("tickSize")
                return float(tick_size)
        except Exception as e:
            logger.error(f"Failed to fetch price step for {symbol}: {e}")
        return 0.01  # fallback default



# Export instance
bybit_client = BybitClient()
