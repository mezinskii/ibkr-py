```markdown
# IBKR Trading Bot

A Python-based trading bot for Interactive Brokers (IBKR) Client Portal API, designed to automate calendar spread trading strategies on SPX options.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Ensure the IBKR Client Portal Gateway is running locally at `https://localhost:5000`.

3. Run the application:
   ```bash
   python main.py
   ```

## Structure

- `src/config/`: Trading strategy configurations.
- `src/api/`: IBKR API client logic.
- `src/bot/`: Trading bot logic.
- `src/gui/`: Tkinter-based GUI.
- `src/utils/`: Logging and utilities.

## Features

- Automated calendar spread trading for SPX options.
- GUI for selecting and triggering strategies.
- Support for manual and scheduled strategy execution.
- Logging of all API interactions and bot actions.
```