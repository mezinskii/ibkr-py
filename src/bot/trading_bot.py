import asyncio
import json
import uuid
import requests
from datetime import datetime, timedelta
from src.api.ibkr_client import IBKRClient
from src.config.strategies import STRATEGIES
from src.utils.logging import logger

class IBKRBot:
    def __init__(self, gui_callback):
        self.client = IBKRClient(gui_callback)
        self.running = False
        self.gui_callback = gui_callback
        self.position_open = False
        self.order_id = None
        self.tp_order_id = None
        self.current_strategy = None
        self.manual_trigger = None

    def log(self, message):
        logger.info(message)
        self.gui_callback(message)

    async def place_calendar_spread(self, near, far, qty, name):
        try:
            if not self.client.account_id:
                self.log(f"[{name}] No account ID")
                return False
            price = abs(near.get("last", 0) - far.get("last", 0)) or 0.1
            order = {
                "conid": int(near["conid"]),
                "secType": "BAG",
                "cOID": str(uuid.uuid4()),
                "orderType": "LMT",
                "side": "SELL",
                "quantity": int(qty),
                "legs": [
                    {"conid": int(near["conid"]), "side": "SELL", "ratio": 1},
                    {"conid": int(far["conid"]), "side": "BUY", "ratio": 1}
                ],
                "price": float(price),
                "tif": "GTC"
            }
            self.current_strategy = {**self.current_strategy, "near_conid": near["conid"], "far_conid": far["conid"]} if self.current_strategy else {"near_conid": near["conid"], "far_conid": far["conid"]}
            self.log(f"[{name}] Placing spread: {json.dumps(order, indent=2)}")
            if not await self.client.validate_order(order, name):
                return False
            r = requests.post(f"{self.client.BASE_URL}/iserver/account/{self.client.account_id}/order", json=order, verify=False)
            if r.status_code == 200:
                response_data = r.json()
                if isinstance(response_data, list) and len(response_data) > 0:
                    self.order_id = response_data[0].get("order_id")
                    self.log(f"[{name}] Spread placed {self.order_id}")
                    return True
                else:
                    self.log(f"[{name}] Order failed: Unexpected response format {response_data}")
                    return False
            self.log(f"[{name}] Order failed: {r.status_code}, {r.text}")
            return False
        except Exception as e:
            self.log(f"[{name}] Spread error: {e}")
            return False

    async def place_take_profit(self, spread_price, qty, name):
        try:
            if not self.client.account_id:
                return False
            tp = spread_price * (1 + self.current_strategy["TP"]/100)
            order = {
                "conid": int(self.current_strategy["near_conid"]),
                "secType": "BAG",
                "cOID": str(uuid.uuid4()),
                "orderType": "LMT",
                "side": "BUY",
                "quantity": int(qty),
                "legs": [
                    {"conid": int(self.current_strategy["near_conid"]), "side": "BUY", "ratio": 1},
                    {"conid": int(self.current_strategy["far_conid"]), "side": "SELL", "ratio": 1}
                ],
                "price": float(tp),
                "tif": "GTC"
            }
            self.log(f"[{name}] Placing TP: {json.dumps(order, indent=2)}")
            if not await self.client.validate_order(order, name):
                return False
            r = requests.post(f"{self.client.BASE_URL}/iserver/account/{self.client.account_id}/order", json=order, verify=False)
            if r.status_code == 200:
                response_data = r.json()
                if isinstance(response_data, list) and len(response_data) > 0:
                    self.tp_order_id = response_data[0].get("order_id")
                    self.log(f"[{name}] TP placed {self.tp_order_id}")
                    return True
                else:
                    self.log(f"[{name}] TP failed: Unexpected response format {response_data}")
                    return False
            self.log(f"[{name}] TP failed: {r.status_code}, {r.text}")
            return False
        except Exception as e:
            self.log(f"[{name}] TP error: {e}")
            return False

    async def cancel_order(self, order_id, name):
        try:
            r = requests.delete(f"{self.client.BASE_URL}/iserver/account/{self.client.account_id}/order/{order_id}", verify=False)
            if r.status_code == 200:
                self.log(f"[{name}] Order {order_id} canceled")
                return True
            else:
                self.log(f"[{name}] Cancel failed: {r.status_code}, {r.text}")
                return False
        except Exception as e:
            self.log(f"[{name}] Cancel error: {e}")
            return False

    async def close_position(self, name):
        if not self.position_open:
            return
        try:
            ord_close = {
                "conid": int(self.current_strategy["near_conid"]),
                "secType": "BAG",
                "cOID": str(uuid.uuid4()),
                "orderType": "MKT",
                "side": "BUY",
                "quantity": 1,
                "legs": [
                    {"conid": int(self.current_strategy["near_conid"]), "side": "BUY", "ratio": 1},
                    {"conid": int(self.current_strategy["far_conid"]), "side": "SELL", "ratio": 1}
                ],
                "tif": "DAY"
            }
            r = requests.post(f"{self.client.BASE_URL}/iserver/account/{self.client.account_id}/order", json=ord_close, verify=False)
            if r.status_code == 200:
                self.log(f"[{name}] Position closed")
                self.position_open = False
                self.order_id = None
                self.tp_order_id = None
            else:
                self.log(f"[{name}] Close failed: {r.text}")
        except Exception as e:
            self.log(f"[{name}] Close error: {e}")

    async def execute_strategy(self, strat):
        if self.position_open:
            self.log(f"[{strat['name']}] Position already open")
            return
        self.current_strategy = strat
        self.log(f"[{strat['name']}] Executing strategy")
        now = datetime.now()
        near = now + timedelta(days=strat["D1"])
        far = now + timedelta(days=strat["D2"])
        chain1 = await self.client.get_option_chain("SPX", near)
        chain2 = await self.client.get_option_chain("SPX", far)
        if not chain1 or not chain2:
            return self.log(f"[{strat['name']}] Chain fetch failed")
        opt_near = await self.client.find_option(chain1, strat["Delta"])
        opt_far = await self.client.find_option(chain2, strat["Delta"])
        if opt_near is None or opt_far is None:
            return self.log(f"[{strat['name']}] No suitable options")
        if opt_near['strike'] != opt_far['strike']:
            return self.log(f"[{strat['name']}] Strike mismatch")
        if opt_near['conid'] == opt_far['conid']:
            return self.log(f"[{strat['name']}] Same conid")
        if await self.place_calendar_spread(opt_near, opt_far, 1, strat['name']):
            self.position_open = True
            await self.place_take_profit(abs(opt_near['last'] - opt_far['last']), 1, strat['name'])

    async def run(self):
        if not self.client.authenticated:
            if not await self.client.authenticate():
                self.log("Auth failed, stopping")
                return
        self.running = True
        self.log("Bot started")
        while self.running:
            now = datetime.now()
            day = now.strftime("%A")
            tm = now.strftime("%H:%M")
            if self.manual_trigger:
                await self.execute_strategy(self.manual_trigger)
                self.manual_trigger = None
                await asyncio.sleep(60)
                continue
            for strat in STRATEGIES:
                if day == strat['DayOfWeek'] and tm == strat['T1']:
                    await self.execute_strategy(strat)
                    await asyncio.sleep(60)
                    break
            if self.position_open and self.current_strategy and tm == self.current_strategy['T2']:
                await self.close_position(self.current_strategy['name'])
            await asyncio.sleep(1)

    def stop(self):
        self.running = False
        self.log("Bot stopped")

    def trigger_strategy(self, sid):
        strat = next((s for s in STRATEGIES if s['id'] == sid), None)
        if strat:
            self.manual_trigger = strat
            self.log(f"Manually triggered {strat['name']}")
        else:
            self.log(f"Strategy {sid} not found")