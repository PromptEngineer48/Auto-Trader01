#### MANAGING STOP LOSSES AND CLOSING POSITIONS

# This script is used to manage trailing stop losses for open positions.
# It uses the Delta Exchange API to get the open positions and the current price.
# It then calculates the stop loss price based on the current price and the stop loss percentage.
# If the price moves in the opposite direction of the position, the stop loss is updated.
# If the price moves in the same direction as the position, the stop loss is not updated.
# It also checks if stop losses have been hit and closes positions accordingly.

import json
import time
import os
from datetime import datetime
from typing import Dict, List, Optional
from src.trading.open_positions_fetcher import OpenPositionsFetcher
import logging
from dotenv import load_dotenv
import requests
import hmac
import hashlib
from src.trading.place_order import DeltaExchange
import websocket
import threading

load_dotenv()

class TrailingStopManager:
    def __init__(self, api_key: str, api_secret: str, stop_loss_percentage: float = 2.0):
        # Get script directory for file paths
        self.script_dir = os.path.dirname(os.path.realpath(__file__))
        
        # Setup logging first
        self.logger = self._setup_logger()
        
        self.api_key = api_key
        self.api_secret = api_secret
        self.stop_loss_percentage = stop_loss_percentage
        
        # Set positions file path relative to script directory
        self.positions_file = os.path.join(self.script_dir, 'positions_data.json')
        self.logger.info(f"Using positions file at: {self.positions_file}")
        
        self.positions_fetcher = OpenPositionsFetcher(api_key, api_secret)
        self.exchange = DeltaExchange()
        self.base_url = 'https://api.india.delta.exchange'
        self.product_mapping = {}

    def _generate_signature(self, method: str, endpoint: str, payload: str = '') -> tuple[str, str]:
        """Generate signature for API authentication."""
        try:
            timestamp = str(int(time.time())+3)
            signature_data = method + timestamp + endpoint + payload
            message = bytes(signature_data, 'utf-8')
            secret = bytes(self.api_secret, 'utf-8')
            hash = hmac.new(secret, message, hashlib.sha256)
            return hash.hexdigest(), timestamp
        except Exception as e:
            self.logger.error(f"Error generating signature: {str(e)}")
            raise

    def _get_current_price(self, symbol: str) -> float:
        """Get current price for a symbol from Delta Exchange."""
        try:
            self.logger.info(f"Attempting to get price for {symbol}...")
            
            # Try REST API first
            try:
                self.logger.info("Attempting to get price via REST API...")
                # Get current timestamp
                end_time = int(time.time())
                start_time = end_time - 60  # Last minute
                
                # Build query for candles endpoint
                query_string = f'resolution=1m&symbol={symbol}&start={start_time}&end={end_time}'
                endpoint = f'/v2/history/candles?{query_string}'
                
                signature, timestamp = self._generate_signature('GET', endpoint)
                
                headers = {
                    'api-key': self.api_key,
                    'signature': signature,
                    'timestamp': timestamp,
                    'Content-Type': 'application/json'
                }
                
                response = requests.get(
                    f'{self.base_url}/v2/history/candles?{query_string}',
                    headers=headers,
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('success') and data.get('result'):
                        price = float(data['result'][0]['close'])
                        self.logger.info(f"Successfully got price via REST API: {price}")
                        return price
                
                self.logger.warning("Failed to get price via REST API, falling back to WebSocket...")
                
            except Exception as e:
                self.logger.error(f"REST API error: {str(e)}, falling back to WebSocket...")
            
            # Fallback to WebSocket
            self.logger.info("Attempting to get price via WebSocket...")
            self.current_price = 0
            
            def on_message(ws, message):
                try:
                    data = json.loads(message)
                    if data.get('type') == 'candlestick_1m' and data.get('symbol') == symbol:
                        self.current_price = float(data.get('close', 0))
                        self.logger.info(f"Received price via WebSocket: {self.current_price}")
                        ws.close()
                except Exception as e:
                    self.logger.error(f"WebSocket message error: {str(e)}")

            def on_error(ws, error):
                self.logger.error(f"WebSocket error: {error}")

            def on_close(ws, close_status_code, close_msg):
                self.logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")

            def on_open(ws):
                self.logger.info("WebSocket opened")
                subscribe_payload = {
                    "type": "subscribe",
                    "payload": {
                        "channels": [
                            {
                                "name": "candlestick_1m",
                                "symbols": [symbol]
                            }
                        ]
                    }
                }
                ws.send(json.dumps(subscribe_payload))

            ws = websocket.WebSocketApp(
                "wss://socket.india.delta.exchange",
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
                on_open=on_open
            )

            ws_thread = threading.Thread(target=ws.run_forever)
            ws_thread.daemon = True
            ws_thread.start()
            
            timeout = 5
            start_time = time.time()
            while time.time() - start_time < timeout and self.current_price == 0:
                time.sleep(0.1)
            
            ws.close()
            
            if self.current_price > 0:
                return self.current_price
            
            self.logger.error(f"Failed to get price for {symbol}")
            return 0

        except Exception as e:
            self.logger.error(f"Error in price fetching: {str(e)}")
            return 0

    def _load_positions_data(self) -> Dict:
        """Load positions data from JSON file."""
        try:
            if os.path.exists(self.positions_file):
                with open(self.positions_file, 'r') as f:
                    try:
                        data = json.load(f)
                        self.logger.info(f"Successfully loaded positions data from {self.positions_file}")
                        return data
                    except json.JSONDecodeError as je:
                        self.logger.error(f"JSON decode error: {str(je)}. Creating new positions data.")
                        return {"positions": {}}
            else:
                self.logger.warning(f"Positions file not found at {self.positions_file}. Creating new file.")
                return {"positions": {}}
        except Exception as e:
            self.logger.error(f"Error loading positions data from {self.positions_file}: {str(e)}")
            return {"positions": {}}

    def _save_positions_data(self, data: Dict):
        """Save positions data to JSON file with verification."""
        MAX_RETRIES = 3
        retry_count = 0
        
        while retry_count < MAX_RETRIES:
            try:
                # Log attempt details
                self.logger.info(f"Save attempt {retry_count + 1} of {MAX_RETRIES}")
                self.logger.info(f"Using positions file: {self.positions_file}")
                
                # Create backup directory if it doesn't exist
                backup_dir = os.path.join(self.script_dir, '.backup')
                os.makedirs(backup_dir, exist_ok=True)
                
                # Create timestamped backup if file exists
                if os.path.exists(self.positions_file):
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    backup_file = os.path.join(backup_dir, f'positions_data_{timestamp}.json')
                    self.logger.info(f"Creating backup at: {backup_file}")
                    with open(self.positions_file, 'r') as src, open(backup_file, 'w') as dst:
                        json.dump(json.load(src), dst, indent=4)
                
                # Create temp directory if it doesn't exist
                temp_dir = os.path.join(self.script_dir, '.temp')
                os.makedirs(temp_dir, exist_ok=True)
                
                # Save with temporary file in temp directory
                temp_file = os.path.join(temp_dir, f'positions_data_{int(time.time())}.json')
                self.logger.info(f"Writing to temp file: {temp_file}")
                
                with open(temp_file, 'w') as f:
                    json.dump(data, f, indent=4)
                
                # Verify temp file
                if not os.path.exists(temp_file):
                    raise Exception("Failed to create temporary file")
                
                with open(temp_file, 'r') as f:
                    written_data = json.load(f)
                    if written_data != data:
                        raise Exception("Data verification failed for temp file")
                
                # Atomic replace
                os.replace(temp_file, self.positions_file)
                
                # Final verification
                with open(self.positions_file, 'r') as f:
                    final_data = json.load(f)
                    if final_data != data:
                        raise Exception("Final data verification failed")
                
                self.logger.info("File saved and verified successfully")
                
                # Clean up temp directory
                try:
                    for f in os.listdir(temp_dir):
                        os.remove(os.path.join(temp_dir, f))
                    os.rmdir(temp_dir)
                except Exception as e:
                    self.logger.warning(f"Could not clean up temp directory: {e}")
                
                # Keep only last 5 backups
                try:
                    backups = sorted([f for f in os.listdir(backup_dir) if f.startswith('positions_data_')])
                    if len(backups) > 5:
                        for old_backup in backups[:-5]:
                            os.remove(os.path.join(backup_dir, old_backup))
                except Exception as e:
                    self.logger.warning(f"Could not clean up old backups: {e}")
                
                return  # Success, exit the retry loop
                
            except Exception as e:
                retry_count += 1
                self.logger.error(f"Save attempt {retry_count} failed: {str(e)}")
                
                # On last retry, try to restore from backup
                if retry_count == MAX_RETRIES and os.path.exists(f"{self.positions_file}.bak"):
                    try:
                        self.logger.info("Attempting to restore from backup")
                        os.replace(f"{self.positions_file}.bak", self.positions_file)
                        self.logger.info("Restored from backup successfully")
                    except Exception as restore_error:
                        self.logger.error(f"Failed to restore from backup: {str(restore_error)}")
                
                if retry_count < MAX_RETRIES:
                    self.logger.info(f"Retrying in 1 second...")
                    time.sleep(1)
                else:
                    self.logger.error("All save attempts failed")
                    raise Exception("Failed to save positions data after all retries")

    def _calculate_stop_loss(self, current_price: float, entry_price: float, size: float) -> float:
        """Calculate stop loss price based on fixed difference from entry price."""
        # Calculate fixed difference based on entry price
        stop_diff = entry_price * (self.stop_loss_percentage / 100)
        
        if size > 0:  # Long position
            # For long positions, maintain fixed difference below current price
            return round(current_price - stop_diff, 5)
        else:  # Short position
            # For short positions, maintain fixed difference above current price
            return round(current_price + stop_diff, 5)

    def _should_update_stop_loss(self, current_price: float, current_stop_loss: float, entry_price: float, size: float) -> bool:
        """Check if stop loss should be updated based on fixed difference from entry price."""
        # Calculate fixed difference based on entry price
        stop_diff = entry_price * (self.stop_loss_percentage / 100)
        
        if size > 0:  # Long position
            # For long positions, update if new stop loss would be higher
            new_stop_loss = current_price - stop_diff
            return new_stop_loss > current_stop_loss
        else:  # Short position
            # For short positions, update if new stop loss would be lower
            new_stop_loss = current_price + stop_diff
            return new_stop_loss < current_stop_loss

    def get_product_mapping(self) -> Dict[str, int]:
        """Get mapping of symbol to product ID from Delta Exchange."""
        try:
            self.logger.info("Fetching product mapping from Delta Exchange...")
            
            # Use the existing method from OpenPositionsFetcher
            products = self.positions_fetcher._get_all_usd_products()
            
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

    def manage_stop_losses(self):
        """Main function to manage trailing stop losses and close positions if stop loss is hit."""
        try:
            print(f"\n=== Trailing Stop Manager Run at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
            
            # Get product mapping if not already available
            if not self.product_mapping:
                self.product_mapping = self.get_product_mapping()
                if not self.product_mapping:
                    self.logger.error("Failed to get product mapping. Cannot manage stop losses.")
                    return
            
            # Load existing positions data
            positions_data = self._load_positions_data()
            stored_positions = positions_data.get("positions", {})
            
            # Get current open positions
            current_positions = self.positions_fetcher.get_open_positions()
            current_symbols = {pos['product_symbol'] for pos in current_positions}
            
            # Process each current position
            for position in current_positions:
                symbol = position['product_symbol']
                pos_data = position['position']
                entry_price = float(pos_data.get('entry_price', 0))
                size = float(pos_data.get('size', 0))
                
                # Get product ID from mapping
                product_id = self.product_mapping.get(symbol)
                if not product_id:
                    self.logger.error(f"Could not find product ID for symbol {symbol}")
                    continue
                
                # Get current price from WebSocket
                current_price = self._get_current_price(symbol)
                
                # Skip if current price is 0
                if current_price == 0:
                    self.logger.warning(f"Skipping position management for {symbol} due to invalid current price (0)")
                    continue
                
                if symbol not in stored_positions:
                    # New position - set initial stop loss based on entry price
                    initial_stop_loss = self._calculate_stop_loss(entry_price, entry_price, size)
                    position_data = {
                        'entry_price': entry_price,
                        'current_price': current_price,
                        'stop_loss': initial_stop_loss,
                        'size': size,
                        'stop_loss_updates': 0,
                        'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                    stored_positions[symbol] = position_data
                    
                    # Log new position details
                    self.logger.info(
                        f"New position added: {symbol}\n"
                        f"  Type: {'Long' if size > 0 else 'Short'}\n"
                        f"  Entry Price: {entry_price}\n"
                        f"  Current Price: {current_price}\n"
                        f"  Initial Stop Loss: {initial_stop_loss}\n"
                        f"  Size: {size}"
                    )
                    
                    print(f"\nNew position detected: {symbol}")
                    print(f"Position Type: {'Long' if size > 0 else 'Short'}")
                    print(f"Entry Price: {entry_price}")
                    print(f"Current Price: {current_price}")
                    print(f"Initial stop loss set at: {initial_stop_loss}")
                else:
                    # Update current price in stored position
                    stored_pos = stored_positions[symbol]
                    stored_pos['current_price'] = current_price
                    
                    # Check if stop loss is hit
                    if size > 0:  # Long position
                        if current_price <= stored_pos['stop_loss']:
                            print(f"\nStop loss hit for {symbol} (Long position)")
                            print(f"Current Price: {current_price}")
                            print(f"Stop Loss: {stored_pos['stop_loss']}")
                            
                            # Close position by placing a sell order
                            response = self.exchange.place_order(
                                product_id=product_id,
                                size=abs(size),
                                order_type='market_order',
                                side='sell'
                            )
                            
                            if response.get('success'):
                                print(f"Successfully closed long position for {symbol}")
                                del stored_positions[symbol]
                            else:
                                print(f"Failed to close position for {symbol}: {response}")
                        elif self._should_update_stop_loss(current_price, stored_pos['stop_loss'], stored_pos['entry_price'], size):
                            # Update trailing stop loss for long position
                            old_stop_loss = stored_pos['stop_loss']
                            new_stop_loss = self._calculate_stop_loss(current_price, stored_pos['entry_price'], size)
                            stored_pos['stop_loss'] = new_stop_loss
                            stored_pos['stop_loss_updates'] += 1
                            stored_pos['last_update'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            
                            # Log stop loss update
                            self.logger.info(
                                f"Updated long stop loss for {symbol}\n"
                                f"  Old Stop Loss: {old_stop_loss}\n"
                                f"  New Stop Loss: {new_stop_loss}\n"
                                f"  Current Price: {current_price}\n"
                                f"  Update Count: {stored_pos['stop_loss_updates']}"
                            )
                            
                            print(f"\nUpdated stop loss for {symbol}")
                            print(f"Position Type: Long")
                            print(f"Current Price: {current_price}")
                            print(f"New stop loss: {new_stop_loss}")
                    else:  # Short position
                        if current_price >= stored_pos['stop_loss']:
                            print(f"\nStop loss hit for {symbol} (Short position)")
                            print(f"Current Price: {current_price}")
                            print(f"Stop Loss: {stored_pos['stop_loss']}")
                            
                            # Close position by placing a buy order
                            response = self.exchange.place_order(
                                product_id=product_id,
                                size=abs(size),
                                order_type='market_order',
                                side='buy'
                            )
                            
                            if response.get('success'):
                                print(f"Successfully closed short position for {symbol}")
                                del stored_positions[symbol]
                            else:
                                print(f"Failed to close position for {symbol}: {response}")
                        elif self._should_update_stop_loss(current_price, stored_pos['stop_loss'], stored_pos['entry_price'], size):
                            # Update trailing stop loss for short position
                            old_stop_loss = stored_pos['stop_loss']
                            new_stop_loss = self._calculate_stop_loss(current_price, stored_pos['entry_price'], size)
                            stored_pos['stop_loss'] = new_stop_loss
                            stored_pos['stop_loss_updates'] += 1
                            stored_pos['last_update'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            
                            # Log stop loss update
                            self.logger.info(
                                f"Updated short stop loss for {symbol}\n"
                                f"  Old Stop Loss: {old_stop_loss}\n"
                                f"  New Stop Loss: {new_stop_loss}\n"
                                f"  Current Price: {current_price}\n"
                                f"  Update Count: {stored_pos['stop_loss_updates']}"
                            )
                            
                            print(f"\nUpdated stop loss for {symbol}")
                            print(f"Position Type: Short")
                            print(f"Current Price: {current_price}")
                            print(f"New stop loss: {new_stop_loss}")
            
            # Remove closed positions
            closed_positions = set(stored_positions.keys()) - current_symbols
            for symbol in closed_positions:
                position = stored_positions[symbol]
                self.logger.info(
                    f"Position closed: {symbol}\n"
                    f"  Type: {'Long' if position['size'] > 0 else 'Short'}\n"
                    f"  Entry Price: {position['entry_price']}\n"
                    f"  Final Price: {position['current_price']}\n"
                    f"  Stop Loss: {position['stop_loss']}\n"
                    f"  Stop Loss Updates: {position['stop_loss_updates']}\n"
                    f"  Last Update: {position['last_update']}"
                )
                print(f"\nPosition closed: {symbol}")
                del stored_positions[symbol]
            
            # Save updated positions data
            positions_data["positions"] = stored_positions
            self._save_positions_data(positions_data)
            
            # Print summary
            print("\n=== Current Positions Summary ===")
            for symbol, pos_data in stored_positions.items():
                print(f"\nSymbol: {symbol}")
                print(f"Position Type: {'Long' if pos_data['size'] > 0 else 'Short'}")
                print(f"Entry Price: {pos_data['entry_price']}")
                print(f"Current Price: {pos_data['current_price']}")
                print(f"Stop Loss: {pos_data['stop_loss']}")
                print(f"Size: {pos_data['size']}")
                print(f"Stop Loss Updates: {pos_data['stop_loss_updates']}")
                print(f"Last Update: {pos_data['last_update']}")
                print("-------------------")

            print("\n=== Stop Loss Check Complete ===")
            print(f"Checked {len(current_positions)} positions for stop loss hits")
            print(f"Successfully managed {len(stored_positions)} active positions")

        except Exception as e:
            self.logger.error(f"Error in manage_stop_losses: {str(e)}")
            print(f"Error occurred: {str(e)}")

    def _setup_logger(self):
        """Setup logging configuration."""
        logger = logging.getLogger('TrailingStopManager')
        logger.setLevel(logging.INFO)
        
        # Create logs directory relative to script directory
        log_dir = os.path.join(self.script_dir, 'logs')
        try:
            os.makedirs(log_dir, exist_ok=True)
            print(f"Using log directory: {log_dir}")
        except Exception as e:
            print(f"Warning: Could not create log directory: {e}")
            log_dir = self.script_dir  # Fallback to script directory
        
        # Create formatters and handlers
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
        # File handler
        file_handler = logging.FileHandler(
            os.path.join(log_dir, f'trailing_stop_{datetime.now().strftime("%Y%m%d")}.log')
        )
        file_handler.setFormatter(formatter)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        
        # Remove any existing handlers to avoid duplicates
        if logger.hasHandlers():
            logger.handlers.clear()
        
        # Add handlers
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        return logger

def main():
    # Setup basic logging for main function
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger('main')
    
    try:
        # Load environment variables
        load_dotenv()
        
        api_key = os.getenv('API_KEY')
        api_secret = os.getenv('API_SECRET')
        
        if not api_key or not api_secret:
            logger.error("API credentials not found in environment variables")
            return
        
        logger.info("Starting TrailingStopManager")
        manager = TrailingStopManager(api_key, api_secret)
        
        # Run the manager
        manager.manage_stop_losses()
        
    except KeyboardInterrupt:
        logger.info("Program interrupted by user")
    except Exception as e:
        logger.error(f"Program terminated due to error: {str(e)}")

if __name__ == "__main__":
    main()
