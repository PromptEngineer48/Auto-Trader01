### FINDING TRADES AND PLACING ORDERS

import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from typing import Dict, List, Optional, Tuple
import requests

from src.utils.wallet_balance_checker import DeltaWallet
from src.trading.delta_signals import get_delta_signals, DeltaSignals
from src.trading.check_min_order import DeltaMarginChecker
from src.trading.place_order import DeltaExchange
from src.trading.open_positions_fetcher import OpenPositionsFetcher

# Setup logging
def setup_logger():
    logger = logging.getLogger('DeltaTrading')
    logger.setLevel(logging.INFO)
    
    # Create logs directory if it doesn't exist
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Create formatters and handlers
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # File handler with path to logs directory
    file_handler = logging.FileHandler(
        os.path.join(log_dir, f'delta_trading_{datetime.now().strftime("%Y%m%d")}.log')
    )
    console_handler = logging.StreamHandler()
    
    # Set formatters
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

class DeltaTradingSystem:
    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv('API_KEY')
        self.api_secret = os.getenv('API_SECRET')
        self.logger = setup_logger()
        
        # Initialize components
        self.wallet = DeltaWallet()
        self.margin_checker = DeltaMarginChecker(self.api_key, self.api_secret)
        self.exchange = DeltaExchange()
        self.signals = DeltaSignals(self.api_key, self.api_secret)
        self.positions_fetcher = OpenPositionsFetcher(self.api_key, self.api_secret)
        
        # Initialize product mapping
        self.product_mapping = {}
        
    def get_product_mapping(self) -> Dict[str, int]:
        """Get mapping of symbol to product ID from Delta Exchange."""
        try:
            self.logger.info("Fetching product mapping from Delta Exchange...")
            
            # Use the existing method from DeltaSignals
            products = self.signals._get_all_usd_products()
            
            if not products:
                self.logger.error("Failed to fetch product mapping")
                return {}
                
            # Create mapping from the products list
            mapping = {product['symbol']: product['id'] for product in products}
            self.logger.info(f"Successfully fetched product mapping for {len(mapping)} symbols")
            return mapping
            
        except Exception as e:
            self.logger.error(f"Error getting product mapping: {str(e)}")
            return {}
        
    def get_available_balance(self) -> float:
        """Get available balance and calculate remaining trading capacity."""
        try:
            total_balance = self.wallet.get_usd_balance()
            available_balance = self.wallet.get_usd_available_balance()
            max_trading_balance = total_balance * 0.5  # 50% of total balance
            used_balance = total_balance - available_balance
            remaining_trading_balance = max_trading_balance - used_balance
            
            self.logger.info(f"Total Balance: ${total_balance:,.2f}")
            self.logger.info(f"Max Trading Balance (50%): ${max_trading_balance:,.2f}")
            self.logger.info(f"Used Balance: ${used_balance:,.2f}")
            self.logger.info(f"Remaining Trading Balance: ${remaining_trading_balance:,.2f}")
            
            return max(0.0, remaining_trading_balance)  # Don't return negative balance
        except Exception as e:
            self.logger.error(f"Error getting balance: {str(e)}")
            return 0.0

    def get_trading_opportunities(self, trading_balance: float) -> List[Dict]:
        """Get trading opportunities based on signals and margin requirements."""
        try:
            # Get active signals
            self.logger.info("Fetching trading signals...")
            signals = get_delta_signals(self.api_key, self.api_secret)
            if not signals:
                self.logger.info("No active signals found")
                return []

            # Get margin requirements
            self.logger.info("Fetching margin requirements...")
            margin_requirements = self.margin_checker.get_margin_requirements()
            if not margin_requirements:
                self.logger.error("Failed to get margin requirements")
                return []

            # Create margin lookup dictionary
            margin_lookup = {list(item.keys())[0]: float(list(item.values())[0].replace('$', '')) 
                           for item in margin_requirements}

            # Filter opportunities based on available balance
            opportunities = []
            for signal in signals:
                symbol = list(signal.keys())[0]
                direction = signal[symbol]
                margin_required = margin_lookup.get(symbol, float('inf'))
                
                if margin_required <= trading_balance:
                    opportunities.append({
                        'symbol': symbol,
                        'direction': direction,
                        'margin_required': margin_required
                    })

            return opportunities

        except Exception as e:
            self.logger.error(f"Error getting trading opportunities: {str(e)}")
            return []

    def get_existing_positions(self) -> Dict[str, str]:
        """Get currently open positions and their directions."""
        try:
            self.logger.info("Fetching existing positions...")
            positions = self.positions_fetcher.get_open_positions()
            
            position_map = {}
            for position in positions:
                symbol = position['product_symbol']
                size = float(position['position'].get('size', 0))
                if size != 0:  # Only consider non-zero positions
                    direction = 'LONG' if size > 0 else 'SHORT'
                    position_key = f"{symbol}_{direction}"  # Include direction in key
                    position_map[position_key] = direction
                    self.logger.info(f"Found existing position: {symbol} {direction}")
                    
            self.logger.info(f"Found {len(position_map)} existing positions")
            return position_map
            
        except Exception as e:
            self.logger.error(f"Error fetching existing positions: {str(e)}")
            return {}

    def execute_trades(self, opportunities: List[Dict]):
        """Execute trades for the identified opportunities, avoiding duplicate positions."""
        # Get product mapping if not already available
        if not self.product_mapping:
            self.product_mapping = self.get_product_mapping()
            if not self.product_mapping:
                self.logger.error("Failed to get product mapping. Cannot execute trades.")
                return

        # Get existing positions
        existing_positions = self.get_existing_positions()
        
        # Filter out opportunities where we already have same direction positions
        filtered_opportunities = []
        for opp in opportunities:
            symbol = opp['symbol']
            direction = opp['direction']
            position_key = f"{symbol}_{direction}"
            
            if position_key in existing_positions:
                self.logger.info(f"Skipping {symbol} {direction} - Already have this direction position")
                continue
            filtered_opportunities.append(opp)
            
        if not filtered_opportunities:
            self.logger.info("No new opportunities to trade after filtering existing positions")
            return
            
        self.logger.info(f"Found {len(filtered_opportunities)} new opportunities after filtering existing positions")
            
        for opp in filtered_opportunities:
            try:
                symbol = opp['symbol']
                self.logger.info(f"Placing {opp['direction']} order for {symbol}")
                
                # Get product ID from mapping
                product_id = self.product_mapping.get(symbol)
                if not product_id:
                    self.logger.error(f"Could not find product ID for symbol {symbol}")
                    continue
                
                # Determine size based on symbol
                if symbol == 'AAVEUSD':
                    size = 2
                elif symbol == 'SOLUSD':
                    size = 4
                else:
                    size = 6
                
                self.logger.info(f"Setting order size to {size} for {symbol}")
                
                # Place the order
                response = self.exchange.place_order(
                    product_id=product_id,
                    size=size,  # Dynamic size based on symbol
                    order_type='market_order',
                    side='buy' if opp['direction'] == 'LONG' else 'sell'
                )
                
                if response.get('success'):
                    self.logger.info(f"Successfully placed order for {symbol} with size {size}")
                else:
                    self.logger.error(f"Failed to place order for {symbol}: {response}")
                    
            except Exception as e:
                self.logger.error(f"Error executing trade for {opp['symbol']}: {str(e)}")

    def run(self):
        """Main trading system execution."""
        try:
            self.logger.info("Starting Delta Trading System")
            
            # Get available balance
            trading_balance = self.get_available_balance()
            if trading_balance <= 0:
                self.logger.error("Insufficient balance for trading")
                return

            # Get trading opportunities
            opportunities = self.get_trading_opportunities(trading_balance)
            if not opportunities:
                self.logger.info("No suitable trading opportunities found")
                return

            # Execute trades
            self.execute_trades(opportunities)
            
            self.logger.info("Trading system execution completed")

        except Exception as e:
            self.logger.error(f"Error in main execution: {str(e)}")

if __name__ == "__main__":
    trading_system = DeltaTradingSystem()
    trading_system.run()
