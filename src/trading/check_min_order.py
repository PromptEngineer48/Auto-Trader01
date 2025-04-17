# This script is used to check the margin requirements for USD perpetual futures.
# It uses the Delta Exchange API to get the list of products and then gets the margin requirements for each product.
# Demo Output:
# Margin Requirements for USD Perpetual Futures:
# Symbol      Price     Contract Unit    Leverage    Init Margin%    Margin/Lot($)
# BTCUSD      50000.00   BTC             10x          1.00%          $5000.00

# Simplified Symbol-Margin List:
# [
#     {'BTCUSD': '$5000.00'},
#     {'ETHUSD': '$1000.00'},
#     {'SOLUSD': '$500.00'}
# ]


import hashlib
import hmac
import json
import time
import requests
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv('API_KEY')
api_secret = os.getenv('API_SECRET')

class DeltaMarginChecker:
    def __init__(self, api_key: str, api_secret: str, base_url: str = 'https://api.india.delta.exchange/v2'):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        """Setup logging configuration."""
        logger = logging.getLogger(__name__)
        if not logger.handlers:
            logger.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            
            # Create logs directory if it doesn't exist
            log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs')
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
            
            # File handler with path to logs directory
            file_handler = logging.FileHandler(
                os.path.join(log_dir, f'delta_margin_check_{datetime.now().strftime("%Y%m%d")}.log')
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            
            # Console handler
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)
        return logger

    def _generate_signature(self, method: str, endpoint: str, payload: str = '') -> Tuple[str, str]:
        """Generate signature for API authentication."""
        try:
            timestamp = str(int(time.time()) + 3)
            signature_data = method + timestamp + endpoint + payload
            message = bytes(signature_data, 'utf-8')
            secret = bytes(self.api_secret, 'utf-8')
            hash_obj = hmac.new(secret, message, hashlib.sha256)
            return hash_obj.hexdigest(), timestamp
        except Exception as e:
            self.logger.error(f"Error generating signature: {str(e)}")
            raise

    def get_margin_requirements(self) -> Optional[List[Dict]]:
        """Fetch and display margin requirements for USD perpetual futures."""
        try:
            self.logger.info("Fetching current prices...")
            # First get current prices from public API
            try:
                public_response = requests.get(f'{self.base_url}/tickers', timeout=10)
                public_response.raise_for_status()
                public_data = public_response.json()
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Failed to fetch prices: {str(e)}")
                return None
            
            if not public_data.get('success'):
                self.logger.error(f"Error in price API response: {public_data.get('error', 'Unknown error')}")
                return None
                
            # Create a price dictionary for quick lookup
            prices = {}
            for ticker in public_data['result']:
                try:
                    symbol = ticker.get('symbol')
                    mark_price = ticker.get('mark_price')
                    if symbol and mark_price:
                        prices[symbol] = float(mark_price)
                except (ValueError, TypeError) as e:
                    self.logger.warning(f"Invalid price data for {symbol}: {str(e)}")
                    continue
                
            self.logger.info("Fetching product details...")
            # Then get product details
            try:
                method = 'GET'
                endpoint = '/v2/products'
                signature, timestamp = self._generate_signature(method, endpoint)
                
                headers = {
                    'api-key': self.api_key,
                    'signature': signature,
                    'timestamp': timestamp,
                    'Content-Type': 'application/json'
                }
                
                response = requests.get(f'{self.base_url}/products', headers=headers, timeout=10)
                response.raise_for_status()
                data = response.json()
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Failed to fetch product details: {str(e)}")
                return None
            
            if not data.get('success'):
                self.logger.error(f"Error in product API response: {data.get('error', 'Unknown error')}")
                return None
                
            # Store results for sorting
            results = []
            
            # Process all products
            for product in data['result']:
                try:
                    symbol = product.get('symbol')
                    contract_type = product.get('contract_type')
                    
                    if not all([symbol, contract_type]):
                        continue
                    
                    # Only process USD-denominated perpetual futures
                    if (symbol and symbol in prices and 
                        contract_type == 'perpetual_futures' and 
                        symbol.endswith('USD')):
                        
                        current_price = prices[symbol]
                        contract_value = float(product.get('contract_value', 0))
                        leverage = float(product.get('default_leverage', 0))
                        initial_margin = float(product.get('initial_margin', 0)) / 100
                        contract_unit = product.get('contract_unit_currency', '')
                        
                        if contract_value <= 0 or leverage <= 0 or initial_margin <= 0:
                            self.logger.warning(f"Invalid values for {symbol}: contract_value={contract_value}, leverage={leverage}, initial_margin={initial_margin}")
                            continue
                        
                        # Value of 1 lot = (current_price * contract_value) * initial_margin
                        one_lot_value = (current_price * contract_value) * initial_margin
                        
                        # Store the result
                        results.append({
                            'symbol': symbol,
                            'margin': one_lot_value,
                            'price': current_price,
                            'contract_value': contract_value,
                            'contract_unit': contract_unit,
                            'leverage': leverage,
                            'initial_margin': initial_margin * 100
                        })
                except (ValueError, TypeError) as e:
                    self.logger.warning(f"Error processing product {symbol}: {str(e)}")
                    continue
            
            if not results:
                self.logger.warning("No valid USD perpetual futures found")
                return None
                
            # Sort results by margin required
            results.sort(key=lambda x: x['margin'])
            
            # Print results in a table format
            print("\nMargin Requirements for USD Perpetual Futures:")
            print("Symbol".ljust(12) + "Price".rjust(15) + "Contract".rjust(12) + "Unit".rjust(8) + 
                  "Leverage".rjust(10) + "Init Margin%".rjust(12) + "Margin/Lot($)".rjust(15))
            print("-" * 84)
            
            for result in results:
                print(
                    f"{result['symbol']:<12}"
                    f"${result['price']:>14.2f}"
                    f"{result['contract_value']:>12.3f}"
                    f"{result['contract_unit']:>8}"
                    f"{result['leverage']:>10.0f}x"
                    f"{result['initial_margin']:>12.1f}%"
                    f"${result['margin']:>14.2f}"
                )
            
            # Print simplified symbol-margin list in the requested format
            print("\nSimplified Symbol-Margin List:")
            print("-" * 40)
            simplified_list = [{result['symbol']: f"${result['margin']:.2f}"} for result in results]
            # print(json.dumps(simplified_list, indent=2))
            
            return simplified_list
            
        except Exception as e:
            self.logger.error(f"Unexpected error in get_margin_requirements: {str(e)}")
            return None

def main():
    
    checker = DeltaMarginChecker(api_key, api_secret)
    try:
        simplified_list = checker.get_margin_requirements()
        print(simplified_list)
    except KeyboardInterrupt:
        checker.logger.info("Program interrupted by user")
    except Exception as e:
        checker.logger.error(f"Program terminated due to error: {str(e)}")

if __name__ == "__main__":
    main() 