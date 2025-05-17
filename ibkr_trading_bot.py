import requests
import tkinter as tk
from tkinter import ttk, scrolledtext
import pandas as pd
import asyncio
import threading
import json
from datetime import datetime, timedelta
import uuid
import logging
import urllib3

# Suppress InsecureRequestWarning for localhost
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# IBKR Client Portal API base URL
BASE_URL = "https://localhost:5000/v1/api"

# List of strategies
STRATEGIES = [
    {
        "id": "1",
        "name": "Monday SPX Calendar",
        "DayOfWeek": "Monday",
        "Delta": 70,
        "D1": 4,
        "D2": 6,
        "T1": "09:32",
        "T2": "15:30",
        "TP": 20,
        "MaxCost": 10000,
        "Vix": [10, 30],
        "VixOvernightRange": [-5, 5],
        "VixIntradayRange": [-3, 3],
        "AveragingDropPct": 10,
        "AveragingTimes": ["10:00", "11:00"],
        "AveragingAmount": 2000
    },
    {
        "id": "2",
        "name": "Wednesday SPX Calendar",
        "DayOfWeek": "Wednesday",
        "Delta": 65,
        "D1": 2,
        "D2": 7,
        "T1": "10:00",
        "T2": "15:00",
        "TP": 15,
        "MaxCost": 8000,
        "Vix": [12, 28],
        "VixOvernightRange": [-4, 4],
        "VixIntradayRange": [-2, 2],
        "AveragingDropPct": 8,
        "AveragingTimes": ["11:00", "12:00"],
        "AveragingAmount": 1500
    },
    {
        "id": "3",
        "name": "Saturday Test",
        "DayOfWeek": "Saturday",
        "Delta": 70,
        "D1": 4,
        "D2": 6,
        "T1": "13:00",
        "T2": "15:30",
        "TP": 20,
        "MaxCost": 10000,
        "Vix": [10, 30],
        "VixOvernightRange": [-5, 5],
        "VixIntradayRange": [-3, 3],
        "AveragingDropPct": 10,
        "AveragingTimes": ["13:30"],
        "AveragingAmount": 2000
    }
]

class IBKRBot:
    def __init__(self, gui_callback):
        self.session_id = None
        self.authenticated = False
        self.running = False
        self.gui_callback = gui_callback
        self.position_open = False
        self.order_id = None
        self.tp_order_id = None
        self.current_strategy = None
        self.manual_trigger = None
        self.account_id = None

    def log(self, message):
        logger.info(message)
        self.gui_callback(message)

    async def authenticate(self):
        try:
            validate = requests.get(f"{BASE_URL}/sso/validate", verify=False, timeout=5)
            if validate.status_code != 200:
                self.log(f"Session validation failed: {validate.status_code}, {validate.text}")
                return False

            tickle = requests.get(f"{BASE_URL}/tickle", verify=False, timeout=5)
            if tickle.status_code == 200 and tickle.json().get("session"):
                self.session_id = tickle.json()["session"]
                self.authenticated = True
                self.log("Authenticated with IBKR API")

                acct = requests.get(f"{BASE_URL}/iserver/accounts", verify=False, timeout=5)
                if acct.status_code == 200:
                    accts = acct.json().get("accounts", [])
                    self.account_id = accts[0] if accts else None
                    if self.account_id:
                        self.log(f"Fetched account ID: {self.account_id}")
                        return True
                self.log(f"Failed to fetch account ID: {acct.status_code}, {acct.text}")
            else:
                self.log(f"Authentication failed: {tickle.status_code}, {tickle.text}")
            return False
        except requests.RequestException as e:
            self.log(f"Authentication error: {e}")
            return False

    async def get_option_chain(self, symbol, expiration_date):
        try:
            if not self.authenticated:
                if not await self.authenticate():
                    return None

            resp = requests.get(
                f"{BASE_URL}/iserver/secdef/search?symbol={symbol}&exchange=CBOE", verify=False, timeout=5
            )
            if resp.status_code != 200:
                self.log(f"Failed to get SPX conid: {resp.status_code}, {resp.text}")
                return None

            data = resp.json()
            if not isinstance(data, list) or not data:
                self.log(f"Invalid conid response: {resp.text}")
                return None

            conid = data[0]["conid"]
            self.log(f"Fetched SPX conid: {conid}")

            month = expiration_date.strftime('%b%y').upper()
            exp = expiration_date.strftime('%Y%m%d')

            strikes = requests.get(
                f"{BASE_URL}/iserver/secdef/strikes?conid={conid}&secType=OPT&month={month}",
                verify=False, timeout=5
            )
            if strikes.status_code != 200:
                self.log(f"Failed to get strikes: {strikes.status_code}, {strikes.text}")
                return None

            puts = strikes.json().get("put", [])
            if not puts:
                self.log(f"No put strikes for {month}")
                return None

            target = 5950.0
            if target not in puts:
                target = min(puts, key=lambda x: abs(x - target))
                self.log(f"Adjusted strike: {target}")

            info = requests.get(
                f"{BASE_URL}/iserver/secdef/info?conid={conid}&secType=OPT&month={month}&right=P&strike={target}",
                verify=False, timeout=5
            )
            if info.status_code != 200:
                self.log(f"Failed to get chain: {info.status_code}, {info.text}")
                fallback = requests.post(
                    f"{BASE_URL}/trsrv/secdef", json={"conids": [conid]}, verify=False, timeout=5
                )
                if fallback.status_code != 200:
                    self.log(f"Fallback failed: {fallback.status_code}, {fallback.text}")
                    return None
                chain = fallback.json().get("secdef", [])
            else:
                chain = info.json()

            days = (expiration_date - datetime.now()).days
            price = 50.0 if days <= 4 else 55.0

            options = [
                {"conid": o["conid"], "strike": float(o["strike"]), "right": o.get("right","P"),
                 "last": price, "delta": 0.7, "expiry": o.get("maturityDate","")}
                for o in chain
                if o.get("right","P")=="P" and float(o["strike"])==target and o.get("maturityDate","")==exp
            ]
            if not options:
                self.log(f"No options for {month} on {exp} at {target}")
                return None

            self.log(f"Fetched chain for {exp} strike {target}, conid {options[0]['conid']}")
            return {"options": options}
        except Exception as e:
            self.log(f"Error fetching chain: {e}")
            return None

    async def find_option(self, chain, target_delta):
        if not chain or not chain.get("options"): return None
        df = pd.DataFrame(chain["options"])
        if df.empty: return None
        puts = df[df["right"]=="P"].copy()
        if puts.empty: return None
        puts["diff"] = abs(puts["delta"] - target_delta/100)
        opt = puts.loc[puts["diff"].idxmin()]
        self.log(f"Selected option: conid={opt['conid']} expiry={opt['expiry']}")
        return opt

    async def validate_order(self, order, strategy_name):
        try:
            if not self.account_id:
                self.log(f"[{strategy_name}] No account ID")
                return False
            resp = requests.post(
                f"{BASE_URL}/iserver/account/{self.account_id}/order/whatif",
                json=order,
                verify=False
            )
            if resp.status_code==200:
                self.log(f"[{strategy_name}] Order validated: {resp.text}")
                return True
            else:
                self.log(f"[{strategy_name}] Validation failed: {resp.status_code}, {resp.text}")
                return False
        except Exception as e:
            self.log(f"[{strategy_name}] Validation error: {e}")
            return False

    async def place_calendar_spread(self, near, far, qty, name):
        try:
            if not self.account_id:
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
            self.current_strategy = {**self.current_strategy, "near_conid": near["conid"], "far_conid": far["conid"]}
            self.log(f"[{name}] Placing spread: {json.dumps(order, indent=2)}")
            if not await self.validate_order(order, name):
                return False
            r = requests.post(f"{BASE_URL}/iserver/account/{self.account_id}/order", json=order, verify=False)
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
            return False;

    async def place_take_profit(self, spread_price, qty, name):
        try:
            if not self.account_id:
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
            if not await self.validate_order(order, name):
                return False
            r = requests.post(f"{BASE_URL}/iserver/account/{self.account_id}/order", json=order, verify=False)
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

    async def close_position(self, name):
        if not self.position_open: return
        try:
            ord_close = {
                "conid": int(self.current_strategy["near_conid"]),
                "secType": "BAG",
                "cOID": str(uuid.uuid4()),
                "orderType": "MKT",
                "side": "BUY",
                "quantity": 1,
                "legs": [
                    {"conid": int(self.current_strategy["near_conid"]), "side":"BUY","ratio":1},
                    {"conid": int(self.current_strategy["far_conid"]), "side":"SELL","ratio":1}
                ],
                "tif": "DAY"
            }
            r = requests.post(f"{BASE_URL}/iserver/account/{self.account_id}/order", json=ord_close, verify=False)
            if r.status_code==200:
                self.log(f"[{name}] Position closed")
                self.position_open=False;self.order_id=None;self.tp_order_id=None
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
        far  = now + timedelta(days=strat["D2"])
        chain1 = await self.get_option_chain("SPX", near)
        chain2 = await self.get_option_chain("SPX", far)
        if not chain1 or not chain2: return self.log(f"[{strat['name']}] Chain fetch failed")
        opt_near = await self.find_option(chain1,strat["Delta"])
        opt_far  = await self.find_option(chain2,strat["Delta"])
        if opt_near is None or opt_far is None: return self.log(f"[{strat['name']}] No suitable options")
        if opt_near['strike']!=opt_far['strike']: return self.log(f"[{strat['name']}] Strike mismatch")
        if opt_near['conid']==opt_far['conid']: return self.log(f"[{strat['name']}] Same conid")
        if await self.place_calendar_spread(opt_near, opt_far, 1, strat['name']):
            self.position_open=True
            await self.place_take_profit(abs(opt_near['last']-opt_far['last']), 1, strat['name'])

    async def run(self):
        if not self.authenticated:
            if not await self.authenticate():
                self.log("Auth failed, stopping")
                return
        self.running=True
        self.log("Bot started")
        while self.running:
            now = datetime.now(); day = now.strftime("%A"); tm = now.strftime("%H:%M")
            if self.manual_trigger:
                await self.execute_strategy(self.manual_trigger)
                self.manual_trigger=None
                await asyncio.sleep(60)
                continue
            for strat in STRATEGIES:
                if day==strat['DayOfWeek'] and tm==strat['T1']:
                    await self.execute_strategy(strat)
                    await asyncio.sleep(60)
                    break
            if self.position_open and self.current_strategy and tm==self.current_strategy['T2']:
                await self.close_position(self.current_strategy['name'])
            await asyncio.sleep(1)

    def stop(self):
        self.running=False
        self.log("Bot stopped")

    def trigger_strategy(self, sid):
        strat = next((s for s in STRATEGIES if s['id']==sid), None)
        if strat:
            self.manual_trigger=strat
            self.log(f"Manually triggered {strat['name']}")
        else:
            self.log(f"Strategy {sid} not found")

class TradingGUI:
    def __init__(self, root):
        self.root=root; self.root.title("IBKR Trading Bot")
        self.bot=None
        frame=ttk.Frame(self.root,padding="10"); frame.grid(row=0,column=0,sticky=(tk.W,tk.E,tk.N,tk.S))
        self.status_var=tk.StringVar(value="Bot Status: Stopped")
        ttk.Label(frame,textvariable=self.status_var).grid(row=0,column=0,columnspan=3,pady=5)
        ttk.Label(frame,text="Select Strategy:").grid(row=1,column=0,pady=5)
        self.strategy_var=tk.StringVar()
        combo=ttk.Combobox(frame,textvariable=self.strategy_var,state="readonly")
        combo['values']=[s['name'] for s in STRATEGIES]; combo.grid(row=1,column=1,pady=5)
        if STRATEGIES: combo.current(0)
        self.details_text=scrolledtext.ScrolledText(frame,height=5,width=50); self.details_text.grid(row=2,column=0,columnspan=3,pady=5)
        self.update_strategy_details()
        self.log_text=scrolledtext.ScrolledText(frame,height=10,width=50)
        self.log_text.grid(row=3,column=0,columnspan=3,pady=5)
        self.log_text.bind("<Control-c>",self.copy_log)
        self.add_context_menu()
        ttk.Button(frame,text="Start Bot",command=self.start_bot).grid(row=4,column=0,pady=5)
        ttk.Button(frame,text="Stop Bot",command=self.stop_bot).grid(row=4,column=1,pady=5)
        ttk.Button(frame,text="Start Selected Strategy",command=self.start_selected_strategy).grid(row=4,column=2,pady=5)
        ttk.Button(frame,text="Close Position",command=self.close_position).grid(row=5,column=0,columnspan=3,pady=5)

    def log(self,msg):
        self.log_text.configure(state="normal"); self.log_text.insert(tk.END,f"{msg}\n"); self.log_text.see(tk.END)
    def copy_log(self,event=None):
        try:
            txt=self.log_text.selection_get(); self.root.clipboard_clear(); self.root.clipboard_append(txt); self.log("Copied")
        except tk.TclError:
            self.log("Nothing selected to copy")
        return "break"
    def add_context_menu(self):
        menu=tk.Menu(self.log_text,tearoff=0); menu.add_command(label="Copy",command=self.copy_log)
        self.log_text.bind("<Button-3>",lambda e: menu.post(e.x_root,e.y_root))
    def update_strategy_details(self):
        self.details_text.delete(1.0,tk.END)
        name=self.strategy_var.get()
        strat=next((s for s in STRATEGIES if s['name']==name),STRATEGIES[0])
        txt=f"Strategy: {strat['name']}\nDay: {strat['DayOfWeek']}, Entry: {strat['T1']}, Exit: {strat['T2']}\n"
        txt+=f"Delta: {strat['Delta']}, D1: {strat['D1']}, D2: {strat['D2']}\nTP: {strat['TP']}%, MaxCost: ${strat['MaxCost']}"
        self.details_text.insert(tk.END,txt)
    def start_bot(self):
        if not self.bot or not self.bot.running:
            self.bot=IBKRBot(self.log); self.status_var.set("Bot Status: Running")
            threading.Thread(target=lambda: asyncio.run(self.bot.run()),daemon=True).start()
    def stop_bot(self):
        if self.bot and self.bot.running:
            self.bot.stop(); self.status_var.set("Bot Status: Stopped")
    def start_selected_strategy(self):
        if not self.bot or not self.bot.running:
            self.log("Start bot first")
            return
        name=self.strategy_var.get()
        strat=next((s for s in STRATEGIES if s['name']==name),None)
        if strat: self.bot.trigger_strategy(strat['id'])
        else: self.log("No strategy selected")
    def close_position(self):
        if self.bot and self.bot.position_open:
            asyncio.run_coroutine_threadsafe(self.bot.close_position(self.bot.current_strategy['name']),
                                             asyncio.get_event_loop())

if __name__ == "__main__":
    root=tk.Tk()
    app=TradingGUI(root)
    root.mainloop()
