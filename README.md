# Delta Trading System

An automated trading system for Delta Exchange that uses technical analysis to generate trading signals and execute trades with proper risk management.

## Features

- Automated trading signal generation
- Real-time balance monitoring
- Dynamic margin requirement checking
- Risk management (50% balance limit)
- Comprehensive logging system
- Error handling and recovery

## Project Structure

```
delta-trading/
├── src/
│   ├── utils/
│   │   └── wallet_balance_checker.py
│   └── trading/
│       ├── delta_signals.py
│       ├── check_min_order.py
│       └── place_order.py
├── main.py
├── requirements.txt
└── .env
```

## Components

### 1. Wallet Management (`src/utils/wallet_balance_checker.py`)
- Tracks total and available USD balance
- Handles API authentication
- Provides balance information for trading decisions

### 2. Trading Signals (`src/trading/delta_signals.py`)
- Fetches all USD products from Delta Exchange
- Generates trading signals based on price action
- Returns active signals (LONG/SHORT)

### 3. Margin Management (`src/trading/check_min_order.py`)
- Calculates margin requirements for USD perpetual futures
- Determines margin needed per lot
- Provides simplified margin requirements list

### 4. Order Execution (`src/trading/place_order.py`)
- Handles order placement on Delta Exchange
- Uses market orders for execution
- Manages order responses and confirmations

### 5. Main Trading System (`main.py`)
- Orchestrates all components
- Implements trading logic
- Manages risk and balance allocation
- Handles logging and error reporting

## Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd delta-trading
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with your Delta Exchange API credentials:
```
API_KEY=your_api_key_here
API_SECRET=your_api_secret_here
```

## Configuration

The system is configured with the following default settings:
- Uses 50% of total balance for trading
- Fixed lot size of 1
- Market orders only
- USD perpetual futures only

## Usage

Run the trading system:
```bash
python main.py
```

The system will:
1. Check available balance
2. Generate trading signals
3. Verify margin requirements
4. Execute trades based on signals
5. Log all activities

## Logging

Logs are stored in daily files with the format:
- `delta_trading_YYYYMMDD.log`
- Includes both console and file logging
- Records all balance changes and trade executions

## Risk Management

The system implements several risk management features:
- Maximum 50% of total balance for trading
- Tracks used balance separately
- Prevents negative balance situations
- Validates margin requirements before trading
- Fixed lot size to control position size

## Error Handling

Comprehensive error handling includes:
- API connection issues
- Invalid responses
- Insufficient balance
- Failed orders
- Network problems

## Dependencies

- Python 3.x
- requests
- python-dotenv
- logging

## Security

- API credentials stored in `.env` file
- Secure API signature generation
- No hardcoded credentials
- Environment variable support

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

[Your License Here]

## Disclaimer

This trading system is for educational purposes only. Trading cryptocurrencies involves significant risk of loss. Use at your own risk. 