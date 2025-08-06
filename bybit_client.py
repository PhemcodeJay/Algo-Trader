import os
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple, Union, List, cast
import requests
from requests.structures import CaseInsensitiveDict
from db import db_manager

# Create the logger instance
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # Set minimum log level

# Prevent duplicate handlers if this is called multiple times
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


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
         
        self.logger = logging.getLogger(__name__) 
        self.logger.setLevel(logging.INFO)
        self._virtual_orders: List[Dict[str, Any]] = []
        self._virtual_positions: List[Dict[str, Any]] = []
        self.session = requests.Session()
        self.client = None  # initialize to None
        self.base_url = "https://api.bybit.com"
        self.virtual_wallet = {}
        self._load_virtual_wallet()

        try:
            from pybit.unified_trading import HTTP
            self._HTTP = HTTP
        except ImportError as e:
            logger.error("❌ Pybit is not installed or failed to import: %s", e)
            return

        if self.use_real:
            self.api_key = os.getenv("BYBIT_API_KEY", "")
            self.api_secret = os.getenv("BYBIT_API_SECRET", "")

            if not self.api_key or not self.api_secret:
                logger.error("❌ BYBIT_API_KEY and/or BYBIT_API_SECRET not set.")
                return

            try:
                self.client = self._HTTP(
                    api_key=self.api_key,
                    api_secret=self.api_secret,
                    testnet=False  # ✅ no 'endpoint' parameter needed
                )
                logger.info("[BybitClient] ✅ Live trading enabled (mainnet)")
            except Exception as e:
                logger.exception("❌ Failed to initialize Bybit client: %s", e)
                self.client = None

        elif self.use_testnet:
            self.api_key = os.getenv("BYBIT_TESTNET_API_KEY", "")
            self.api_secret = os.getenv("BYBIT_TESTNET_API_SECRET", "")
            try:
                self.client = self._HTTP(
                    api_key=self.api_key,
                    api_secret=self.api_secret,
                    testnet=True
                )
                logger.info("[BybitClient] 🧪 Testnet trading enabled")
            except Exception as e:
                logger.exception("❌ Failed to initialize Bybit testnet client: %s", e)
                self.client = None

        else:
            logger.warning("⚠️ No trading mode specified. Defaulting to virtual mode.")
            self._load_virtual_wallet()

        # ✅ Optional sanity check
        if self.client:
            try:
                test_result = self.client.get_server_time()
                logger.debug(f"[BybitClient] Server time: {test_result}")
            except Exception as e:
                logger.warning(f"[BybitClient] ⚠️ Test connection failed: {e}")

    def _save_virtual_wallet(self):
        try:
            with open("capital.json", "w") as f:
                json.dump(self.virtual_wallet, f, indent=4)
                self.logger.info("[BybitClient] 💾 Saved virtual wallet to capital.json")
        except Exception as e:
            self.logger.exception("[BybitClient] ❌ Error saving virtual wallet: %s", e)

    def _load_virtual_wallet(self):
        try:
            with open("capital.json", "r") as f:
                self.virtual_wallet = json.load(f)
                self.logger.info("[BybitClient] ✅ Loaded virtual wallet from capital.json")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.logger.warning("[BybitClient] ⚠️ Could not load capital.json: %s", e)
            self.virtual_wallet = {
                "USDT": {
                    "equity": 100.0,
                    "available_balance": 100.0
                }
            }
            self.logger.info("[BybitClient] 💰 Initialized default virtual wallet")
            self._save_virtual_wallet()
        except Exception as e:
            self.logger.exception("[BybitClient] ❌ Unexpected error loading virtual wallet: %s", e)
            self.virtual_wallet = {
                "USDT": {
                    "equity": 0.0,
                    "available_balance": 0.0
                }
            }

    def _send_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], timedelta, CaseInsensitiveDict]:
        if self.client is None:
            logger.error("[BybitClient] ❌ Client not initialized.")
            return {}, timedelta(), CaseInsensitiveDict()

        # Handle known method routing properly
        method_func = None

        try:
            if method in {"get_orders", "get_positions", "get_wallet_balance"}:
                method_func = getattr(self.client, method, None)
            elif method == "get_order":  # Only if you know client.order exists
                # Caution: `self.client.order` is invalid for pybit.HTTP
                logger.error("[BybitClient] ❌ 'order' attribute does not exist on client.")
                return {}, timedelta(), CaseInsensitiveDict()
            else:
                method_func = getattr(self.client, method, None)

            if not callable(method_func):
                logger.error(f"[BybitClient] ❌ Method '{method}' not found or not callable on client.")
                return {}, timedelta(), CaseInsensitiveDict()

            start_time = datetime.now()
            raw_result = method_func(**(params or {}))
            elapsed = datetime.now() - start_time

            if not isinstance(raw_result, dict):
                logger.warning(f"[BybitClient] ⚠️ Invalid response format: {raw_result}")
                return {}, elapsed, CaseInsensitiveDict()

            if raw_result.get("retCode") != 0:
                logger.warning(
                    f"[BybitClient] ⚠️ API Error: {raw_result.get('retMsg')} "
                    f"(ErrCode: {raw_result.get('retCode')})"
                )
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


def update_usdt_capital(self) -> None:
    try:
        response: Dict[str, Any] = self.client.get_wallet_balance(accountType="UNIFIED")
        result = response.get("result", {})
        wallet_list = result.get("list", [])

        if not wallet_list:
            self.logger.warning("[BybitClient] ⚠️ Wallet list is empty in response.")
            return

        usdt_wallet = wallet_list[0]
        coins = usdt_wallet.get("coin", [])

        coin_data = next((coin for coin in coins if coin.get("coin") == "USDT"), None)
        if not coin_data:
            self.logger.warning("[BybitClient] ⚠️ Wallet balance for USDT not found.")
            return

        wallet_balance = float(coin_data.get("walletBalance", 0.0))
        available_to_withdraw = float(coin_data.get("availableToWithdraw", 0.0))

        capital_data = {
            "capital": wallet_balance,
            "available": available_to_withdraw,
            "used": wallet_balance - available_to_withdraw,
            "start_balance": self.capital.get("real", {}).get("start_balance", wallet_balance),
            "currency": "USDT"
        }

        if "real" not in self.capital:
            self.capital["real"] = {}

        self.capital["real"].update(capital_data)
        self.save_capital()
        self.db.set_setting("real_balance", capital_data["capital"])

        self.logger.info(f"[BybitClient] ✅ Synced real USDT balance: {capital_data}")

    except Exception as e:
        self.logger.error(f"[BybitClient] ❌ Failed to update USDT capital: {e}")

    
    
    def calculate_margin(self, qty: float, price: float, leverage: float) -> float:
        return round((qty * price) / leverage, 2)
    
    def _save_virtual_wallet(self):
        try:
            with open("capital.json", "w") as f:
                json.dump(self.virtual_wallet, f, indent=4)
            logger.info("[BybitClient] 💾 Virtual wallet saved to capital.json")
        except Exception as e:
            logger.exception("[BybitClient] ❌ Failed to save virtual wallet: %s", e)


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
        # ================================
        # ✅ REAL TRADING MODE
        # ================================
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
                status_data, _, _ = status_resp
                orders_list = status_data.get("list", [])
                if not orders_list:
                    logger.warning("[Real] ❌ No orders found in order status response.")
                    return {
                        "success": False,
                        "message": "No orders returned",
                        "order_id": order_id,
                        "response": status_data
                    }

                order_info = orders_list[0]
                order_status = order_info.get("orderStatus", "UNKNOWN")

                if order_status in ["New", "PartiallyFilled", "Filled"]:
                    logger.info(f"[Real] ✅ Order confirmed. Placing TP/SL limit orders...")
                    try:
                        raw_price = result.get("price")
                        entry_price = float(raw_price) if raw_price is not None else float(price or 0.0)
                        self.place_tp_sl(symbol, qty, side, entry_price)
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
            # ✅ REAL MODE
            tp_order = {
                "category": "linear",
                "symbol": symbol,
                "side": opposite_side,
                "order_type": "Limit",
                "qty": formatted_qty,
                "price": tp_price,
                "time_in_force": "GoodTillCancel",
                "reduce_only": True,
                "close_on_trigger": False
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
                "close_on_trigger": True
            }

            if order_link_id:
                tp_order["order_link_id"] = f"{order_link_id}_TP"
                sl_order["order_link_id"] = f"{order_link_id}_SL"

            try:
                self._send_request("place_order", tp_order)
                logger.info(f"[Real] ✅ TP order placed at {tp_price} for {symbol}")
            except Exception as e:
                logger.error(f"[Real] ❌ Failed to place TP order: {e}")

            try:
                self._send_request("place_order", sl_order)
                logger.info(f"[Real] ✅ SL order placed at {sl_price} for {symbol}")
            except Exception as e:
                logger.error(f"[Real] ❌ Failed to place SL order: {e}")

        else:
            # ✅ VIRTUAL MODE
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
                "create_time": datetime.utcnow().isoformat()
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
                "create_time": datetime.utcnow().isoformat()
            }

            self._virtual_orders.extend([tp_order, sl_order])
            logger.info(f"[Virtual] ✅ TP @ {tp_price}, SL @ {sl_price} added for {symbol}")

                
    def get_open_positions(self) -> List[Dict[str, Any]]:
        return [pos for pos in self._virtual_positions if pos["status"] == "open"]
    
    def get_orders(self, order_id: str, symbol: str, category: str = "linear") -> dict:
        return self._send_request(
                "get_open_orders",  # ✅ Correct method name for Bybit V5 API
                {
                    "orderId": order_id,       # ✅ Matches V5 API spec
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

    def sync_trade_to_db(self, trade_data):
        try:
            # Save trade
            self.db.add_trade(trade_data)
            self.logger.info(f"[BybitClient] ✅ Trade saved to DB: {trade_data['symbol']}")

            # Update capital
            pnl = trade_data.get("realized_pnl", 0)
            mode = trade_data.get("mode", "real")
            self.capital[mode]["capital"] += pnl
            self.capital[mode]["available"] += pnl
            self.save_capital()

            # Update DB and portfolio
            self.db.set_setting(f"{mode}_balance", self.capital[mode]["capital"])
            self.db.update_portfolio(trade_data["symbol"], mode=mode)

        except Exception as e:
            self.logger.error(f"[BybitClient] ❌ Failed to sync trade: {e}")
  
    def save_capital(self):
        with open("capital.json", "w") as f:
            json.dump(self.capital, f, indent=4)


# Export instance
bybit_client = BybitClient()
