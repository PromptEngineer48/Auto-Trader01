# This script is used to get the active trading signals from Delta Exchange.
# It uses the Delta Exchange API to get the list of products and then gets the signal for each product.
# Demo Output:
# Active Signals: [{'CAKEUSD': 'SHORT'}]

import hashlib
import hmac
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from dotenv import load_dotenv
import os
import logging
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import sys

load_dotenv()

class DeltaSignals:
    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = 'https://api.india.delta.exchange'
        
        # Setup logging
        self.logger = self._setup_logger()
        
        # Setup requests session with retries
        self.session = self._setup_requests_session()
        
        # Detect environment
        self.is_aws = self._is_running_on_aws()
        self.logger.info(f"Running in {'AWS' if self.is_aws else 'local'} environment")
        
        # Adjust batch settings based on environment
        self.batch_size = 3 if self.is_aws else 5  # Smaller batches in AWS
        self.batch_delay = 2 if self.is_aws else 1  # Longer delay in AWS
        self.max_workers = 3 if self.is_aws else 5  # Fewer workers in AWS
        
    def _is_running_on_aws(self) -> bool:
        """Check if running on AWS."""
        return bool(os.getenv('AWS_LAMBDA_FUNCTION_NAME') or os.getenv('AWS_EXECUTION_ENV'))
        
    def _setup_logger(self):
        """Setup logging configuration."""
        logger = logging.getLogger('DeltaSignals')
        logger.setLevel(logging.INFO)
        
        # Set log directory based on environment
        log_dir = '/tmp/logs' if self._is_running_on_aws() else 'logs'
        
        try:
            os.makedirs(log_dir, exist_ok=True)
        except Exception as e:
            print(f"Warning: Could not create log directory: {e}")
            log_dir = '/tmp' if self._is_running_on_aws() else '.'
        
        # Create formatters and handlers
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
        # File handler
        file_handler = logging.FileHandler(
            os.path.join(log_dir, f'delta_signals_{datetime.now().strftime("%Y%m%d")}.log')
        )
        file_handler.setFormatter(formatter)
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)  # Use stdout for AWS CloudWatch
        console_handler.setFormatter(formatter)
        
        # Remove any existing handlers
        if logger.hasHandlers():
            logger.handlers.clear()
        
        # Add handlers
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        return logger
        
    def _setup_requests_session(self):
        """Setup requests session with retries."""
        session = requests.Session()
        
        # Configure retry strategy
        retries = Retry(
            total=3,  # number of retries
            backoff_factor=0.5,  # wait 0.5, 1, 2 seconds between retries
            status_forcelist=[408, 429, 500, 502, 503, 504],  # retry on these status codes
        )
        
        # Add retry adapter to session
        adapter = HTTPAdapter(max_retries=retries)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        
        return session

    def _generate_signature(self, method, endpoint, payload=''):
        timestamp = str(int(time.time())+3)
        signature_data = method + timestamp + endpoint + payload
        message = bytes(signature_data, 'utf-8')
        secret = bytes(self.api_secret, 'utf-8')
        hash = hmac.new(secret, message, hashlib.sha256)
        return hash.hexdigest(), timestamp

    def _get_all_usd_products(self):
        """Get all USD-denominated products from Delta Exchange."""
        try:
            self.logger.info("Fetching product list...")
            method = 'GET'
            endpoint = '/v2/products'
            signature, timestamp = self._generate_signature(method, endpoint)
            
            headers = {
                'api-key': self.api_key,
                'signature': signature,
                'timestamp': timestamp,
                'Content-Type': 'application/json'
            }
            
            response = self.session.get(
                f'{self.base_url}/v2/products',
                headers=headers,
                timeout=10
            )
            
            if response.status_code != 200:
                self.logger.error(f"Failed to fetch products. Status code: {response.status_code}")
                return []
            
            data = response.json()
            
            if not data.get('success'):
                self.logger.error("API response indicates failure")
                return []
                
            products = [
                {'id': product.get('id'), 'symbol': product.get('symbol')} 
                for product in data['result'] 
                if isinstance(product, dict) and product.get('symbol', '').endswith('USD')
            ]
            
            self.logger.info(f"Found {len(products)} USD products")
            return products
            
        except requests.Timeout:
            self.logger.error("Timeout while fetching products")
            return []
        except requests.RequestException as e:
            self.logger.error(f"Network error while fetching products: {str(e)}")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error fetching products: {str(e)}")
            return []

    def _get_signal(self, symbol):
        """Get trading signal for a specific symbol."""
        try:
            if not isinstance(symbol, str):
                self.logger.warning(f"Invalid symbol type: {type(symbol)}")
                return None
                
            self.logger.debug(f"Getting signal for {symbol}")
            
            end_time = int(time.time())
            start_time = end_time - (2 * 3 * 60)
            
            query_string = f'resolution=3m&symbol={symbol}&start={start_time}&end={end_time}'
            endpoint = f'/v2/history/candles?{query_string}'
            
            method = 'GET'
            signature, timestamp = self._generate_signature(method, endpoint)
            
            headers = {
                'api-key': self.api_key,
                'signature': signature,
                'timestamp': timestamp,
                'Content-Type': 'application/json'
            }
            
            response = self.session.get(
                f'{self.base_url}/v2/history/candles?{query_string}',
                headers=headers,
                timeout=10
            )
            
            if response.status_code != 200:
                self.logger.warning(f"Failed to get signal for {symbol}. Status: {response.status_code}")
                return None
                
            data = response.json()
            
            if not data.get('success') or not data.get('result'):
                self.logger.warning(f"No valid data for {symbol}")
                return None
                
            latest_candle = data['result'][0]
            high = float(latest_candle['high'])
            low = float(latest_candle['low'])
            close = float(latest_candle['close'])
            open_price = float(latest_candle['open'])
            
            if any(price <= 0 for price in [high, low, close, open_price]):
                self.logger.warning(f"Invalid price data for {symbol}")
                return None
                
            hl_range_percent = ((high - low) / low) * 100
            
            if hl_range_percent >= 1:
                signal = "LONG" if close > open_price else "SHORT"
                self.logger.info(f"Signal detected for {symbol}: {signal}")
                return {symbol: signal}
            
            return None
            
        except requests.Timeout:
            self.logger.error(f"Timeout getting signal for {symbol}")
            return None
        except requests.RequestException as e:
            self.logger.error(f"Network error getting signal for {symbol}: {str(e)}")
            return None
        except Exception as e:
            self.logger.error(f"Error getting signal for {symbol}: {str(e)}")
            return None

    def _process_batch(self, symbols):
        """Process a batch of symbols to get signals."""
        if not symbols:
            return []
            
        signals = []
        try:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = list(executor.map(lambda x: self._get_signal(x['symbol']), symbols))
                for future in futures:
                    if future is not None:
                        signals.append(future)
        except Exception as e:
            self.logger.error(f"Error processing batch: {str(e)}")
            
        return signals

    def get_active_signals(self):
        """Get all active trading signals."""
        self.logger.info("Starting signal detection process...")
        
        try:
            # Get product list
            product_list = self._get_all_usd_products()
            if not product_list:
                self.logger.warning("No products found")
                return []

            all_signals = []
            total_symbols = len(product_list)
            processed_symbols = 0
            
            self.logger.info(f"Processing {total_symbols} symbols in batches of {self.batch_size}...")
            
            # Process in batches
            for i in range(0, total_symbols, self.batch_size):
                try:
                    batch = product_list[i:i+self.batch_size]
                    batch_num = i//self.batch_size + 1
                    total_batches = (total_symbols + self.batch_size - 1)//self.batch_size
                    
                    self.logger.info(
                        f"Processing batch {batch_num}/{total_batches} - "
                        f"Symbols: {', '.join(s['symbol'] for s in batch)}"
                    )
                    
                    signals = self._process_batch(batch)
                    all_signals.extend(signals)
                    
                    processed_symbols += len(batch)
                    self.logger.info(f"Progress: {processed_symbols}/{total_symbols} symbols processed")
                    
                    # Add delay between batches if not the last batch
                    if i + self.batch_size < total_symbols:
                        time.sleep(self.batch_delay)
                        
                except Exception as e:
                    self.logger.error(f"Error processing batch: {str(e)}")
                    continue
            
            self.logger.info(f"Signal detection complete! Found {len(all_signals)} signals")
            return all_signals
            
        except Exception as e:
            self.logger.error(f"Error in signal detection process: {str(e)}")
            return []

def get_delta_signals(api_key, api_secret):
    """
    Get active trading signals from Delta Exchange.
    
    Args:
        api_key (str): Delta Exchange API key
        api_secret (str): Delta Exchange API secret
        
    Returns:
        list: List of dictionaries containing active signals in format [{'SYMBOL': 'SIGNAL'}]
    """
    delta = DeltaSignals(api_key, api_secret)
    return delta.get_active_signals()

# Example usage:
if __name__ == "__main__":
    API_KEY = api_key
    API_SECRET = api_secret
    
    print("\n=== Delta Exchange Signal Detection ===")
    print(f"Started at: {datetime.now().strftime('%H:%M:%S')}")
    
    signals = get_delta_signals(API_KEY, API_SECRET)
    
    print("\n=== Results ===")
    print(f"Time: {datetime.now().strftime('%H:%M:%S')}")
    print("Active Signals:", signals)
    print("=" * 40) 
    
    ## demo output
    # signals = [{'ARCUSD': 'LONG'}, {'MELANIAUSD': 'SHORT'}]
