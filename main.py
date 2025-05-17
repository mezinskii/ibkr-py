import tkinter as tk
from src.gui.trading_gui import TradingGUI

if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("600x500")  # Установить размер окна
    app = TradingGUI(root)
    root.mainloop()