import sys
import os

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import tkinter as tk
from tkinter import ttk, scrolledtext
import asyncio
import threading
from src.bot.trading_bot import IBKRBot
from src.config.strategies import STRATEGIES

class TradingGUI:
    def __init__(self, root):
        try:
            print("Initializing TradingGUI")
            self.root = root
            self.root.title("IBKR Trading Bot")
            self.bot = None
            print("Creating frame")
            frame = ttk.Frame(self.root, padding="10")
            frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
            print("Frame created")
            self.status_var = tk.StringVar(value="Bot Status: Stopped")
            print("Creating status label")
            ttk.Label(frame, textvariable=self.status_var).grid(row=0, column=0, columnspan=3, pady=5)
            print("Creating strategy label")
            ttk.Label(frame, text="Select Strategy:").grid(row=1, column=0, pady=5)
            self.strategy_var = tk.StringVar()
            print(f"STRATEGIES: {STRATEGIES}")
            combo = ttk.Combobox(frame, textvariable=self.strategy_var, state="readonly")
            combo['values'] = [s['name'] for s in STRATEGIES]
            print(f"Combobox values: {combo['values']}")
            combo.grid(row=1, column=1, pady=5)
            if STRATEGIES:
                combo.current(0)
                print("Set default strategy")
            else:
                print("No strategies available")
            print("Creating details text")
            self.details_text = scrolledtext.ScrolledText(frame, height=5, width=50)
            self.details_text.grid(row=2, column=0, columnspan=3, pady=5)
            print("Updating strategy details")
            self.update_strategy_details()
            print("Creating log text")
            self.log_text = scrolledtext.ScrolledText(frame, height=10, width=50)
            self.log_text.grid(row=3, column=0, columnspan=3, pady=5)
            self.log_text.bind("<Control-c>", self.copy_log)
            self.add_context_menu()
            print("Creating buttons")
            ttk.Button(frame, text="Start Bot", command=self.start_bot).grid(row=4, column=0, pady=5)
            ttk.Button(frame, text="Stop Bot", command=self.stop_bot).grid(row=4, column=1, pady=5)
            ttk.Button(frame, text="Start Selected Strategy", command=self.start_selected_strategy).grid(row=4, column=2, pady=5)
            ttk.Button(frame, text="Close Position", command=self.close_position).grid(row=5, column=0, columnspan=3, pady=5)
            print("TradingGUI initialization complete")
        except Exception as e:
            print(f"Error in TradingGUI.__init__: {e}")
            self.log(f"Error initializing GUI: {e}")

    def log(self, msg):
        try:
            self.log_text.configure(state="normal")
            self.log_text.insert(tk.END, f"{msg}\n")
            self.log_text.see(tk.END)
        except Exception as e:
            print(f"Error in log: {e}")

    def copy_log(self, event=None):
        try:
            txt = self.log_text.selection_get()
            self.root.clipboard_clear()
            self.root.clipboard_append(txt)
            self.log("Copied")
        except tk.TclError:
            self.log("Nothing selected to copy")
        return "break"

    def add_context_menu(self):
        try:
            menu = tk.Menu(self.log_text, tearoff=0)
            menu.add_command(label="Copy", command=self.copy_log)
            self.log_text.bind("<Button-3>", lambda e: menu.post(e.x_root, e.y_root))
        except Exception as e:
            print(f"Error in add_context_menu: {e}")

    def update_strategy_details(self):
        try:
            self.details_text.delete(1.0, tk.END)
            name = self.strategy_var.get()
            strat = next((s for s in STRATEGIES if s['name'] == name), STRATEGIES[0] if STRATEGIES else None)
            if strat:
                txt = f"Strategy: {strat['name']}\nDay: {strat['DayOfWeek']}, Entry: {strat['T1']}, Exit: {strat['T2']}\n"
                txt += f"Delta: {strat['Delta']}, D1: {strat['D1']}, D2: {strat['D2']}\nTP: {strat['TP']}%, MaxCost: ${strat['MaxCost']}"
                self.details_text.insert(tk.END, txt)
            else:
                self.details_text.insert(tk.END, "No strategies available")
        except Exception as e:
            print(f"Error in update_strategy_details: {e}")

    def start_bot(self):
        try:
            if not self.bot or not self.bot.running:
                self.bot = IBKRBot(self.log)
                self.status_var.set("Bot Status: Running")
                threading.Thread(target=lambda: asyncio.run(self.bot.run()), daemon=True).start()
        except Exception as e:
            self.log(f"Error in start_bot: {e}")

    def stop_bot(self):
        try:
            if self.bot and self.bot.running:
                self.bot.stop()
                self.status_var.set("Bot Status: Stopped")
        except Exception as e:
            self.log(f"Error in stop_bot: {e}")

    def start_selected_strategy(self):
        try:
            if not self.bot or not self.bot.running:
                self.log("Start bot first")
                return
            name = self.strategy_var.get()
            strat = next((s for s in STRATEGIES if s['name'] == name), None)
            if strat:
                self.bot.trigger_strategy(strat['id'])
            else:
                self.log("No strategy selected")
        except Exception as e:
            self.log(f"Error in start_selected_strategy: {e}")

    def close_position(self):
        try:
            if self.bot and self.bot.position_open:
                asyncio.run_coroutine_threadsafe(self.bot.close_position(self.bot.current_strategy['name']),
                                                asyncio.get_event_loop())
        except Exception as e:
            self.log(f"Error in close_position: {e}")