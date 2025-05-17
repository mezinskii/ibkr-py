import requests
import pandas as pd
import json
from datetime import datetime
from src.utils.logging import logger

BASE_URL = "https://localhost:5000/v1/api"

class IBKRClient:
    def __init__(self, log_callback):
        self.session_id = None
        self.authenticated = False
        self.account_id = None
        self.log = log_callback

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
                {"conid": o["conid"], "strike": float(o["strike"]), "right": o.get("right", "P"),
                 "last": price, "delta": 0.7, "expiry": o.get("maturityDate", "")}
                for o in chain
                if o.get("right", "P") == "P" and float(o["strike"]) == target and o.get("maturityDate", "") == exp
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
        if not chain or not chain.get("options"):
            return None
        df = pd.DataFrame(chain["options"])
        if df.empty:
            return None
        puts = df[df["right"] == "P"].copy()
        if puts.empty:
            return None
        puts["diff"] = abs(puts["delta"] - target_delta / 100)
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
            if resp.status_code == 200:
                self.log(f"[{strategy_name}] Order validated: {resp.text}")
                return True
            else:
                self.log(f"[{strategy_name}] Validation failed: {resp.status_code}, {resp.text}")
                return False
        except Exception as e:
            self.log(f"[{strategy_name}] Validation error: {e}")
            return False