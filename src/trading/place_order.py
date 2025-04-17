import hashlib
import hmac
import json
import time
import requests
import logging
from typing import Dict, List, Optional, Tuple, Union
from datetime import datetime
import os
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import sys

class OrderValidationError(Exception):
    """Raised when order parameters are invalid."""
    pass

class DeltaExchange:
    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv('API_KEY')
        self.api_secret = os.getenv('API_SECRET')
        self.base_url = 'https://api.india.delta.exchange'
        
        # Setup logging
        self.logger = self._setup_logger()
        
        # Setup requests session with retries
        self.session = self._setup_requests_session()
        
        # Detect environment
        self.is_aws = self._is_running_on_aws()
        self.logger.info(f"Running in {'AWS' if self.is_aws else 'local'} environment")
        
    def _is_running_on_aws(self) -> bool:
        """Check if running on AWS."""
        return bool(os.getenv('AWS_LAMBDA_FUNCTION_NAME') or os.getenv('AWS_EXECUTION_ENV'))
        
    def _setup_logger(self):
        """Setup logging configuration."""
        logger = logging.getLogger('DeltaExchange')
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
            os.path.join(log_dir, f'delta_exchange_{datetime.now().strftime("%Y%m%d")}.log')
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
        
        # Configure retry strategy - more conservative for order placement
        retries = Retry(
            total=2,  # Fewer retries for orders to avoid duplicates
            backoff_factor=0.3,  # Shorter delays
            status_forcelist=[408, 429, 500, 502, 503, 504],
            allowed_methods=['GET', 'POST']  # Allow retries on POST for orders
        )
        
        # Add retry adapter to session
        adapter = HTTPAdapter(max_retries=retries)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        
        return session

    def _generate_signature(self, method: str, endpoint: str, payload: str) -> Tuple[str, str]:
        """Generate signature for API authentication."""
        try:
            timestamp = str(int(time.time())+3)
            signature_data = method + timestamp + endpoint + str(payload)
            message = bytes(signature_data, 'utf-8')
            secret = bytes(self.api_secret, 'utf-8')
            hash = hmac.new(secret, message, hashlib.sha256)
            return hash.hexdigest(), timestamp
        except Exception as e:
            self.logger.error(f"Error generating signature: {str(e)}")
            raise

    def _validate_order_params(self, product_id: int, size: float, order_type: str, side: str):
        """Validate order parameters before submission."""
        try:
            # Check product_id
            if not isinstance(product_id, int) or product_id <= 0:
                raise OrderValidationError("Invalid product_id")
            
            # Check size
            if not isinstance(size, (int, float)) or size <= 0:
                raise OrderValidationError("Size must be a positive number")
            
            # Check order_type
            valid_order_types = ['market_order', 'limit_order']
            if order_type not in valid_order_types:
                raise OrderValidationError(f"Invalid order_type. Must be one of: {valid_order_types}")
            
            # Check side
            if side not in ['buy', 'sell']:
                raise OrderValidationError("Side must be 'buy' or 'sell'")
                
        except OrderValidationError as e:
            self.logger.error(f"Order validation failed: {str(e)}")
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in order validation: {str(e)}")
            raise OrderValidationError(f"Order validation error: {str(e)}")

    def place_order(
        self, 
        product_id: int, 
        size: float, 
        order_type: str, 
        side: str,
        max_retries: int = 2
    ) -> Dict:
        """
        Place an order on Delta Exchange with retries and validation
        
        Args:
            product_id (int): Product ID (e.g., 27 for BTCUSD)
            size (float): Order size
            order_type (str): Type of order (e.g., 'market_order', 'limit_order')
            side (str): Order side ('buy' or 'sell')
            max_retries (int): Maximum number of retries for failed orders
            
        Returns:
            Dict: Response from the exchange
            
        Raises:
            OrderValidationError: If order parameters are invalid
            requests.exceptions.RequestException: If API request fails
        """
        try:
            # Validate order parameters
            self._validate_order_params(product_id, size, order_type, side)
            
            # Log order attempt
            self.logger.info(
                f"Placing order - Product: {product_id}, "
                f"Size: {size}, Type: {order_type}, Side: {side}"
            )
            
            # Prepare order data
            order_data = {
                'product_id': product_id,
                'size': size,
                'order_type': order_type,
                'side': side
            }

            body = json.dumps(order_data, separators=(',', ':'))
            method = 'POST'
            endpoint = '/v2/orders'
            
            # Generate signature
            signature, timestamp = self._generate_signature(method, endpoint, body)

            headers = {
                'api-key': self.api_key,
                'signature': signature,
                'timestamp': timestamp,
                'Content-Type': 'application/json'
            }

            # Place order with timeout
            response = self.session.post(
                f'{self.base_url}/v2/orders',
                headers=headers,
                data=body,
                timeout=10
            )
            
            # Check response
            if response.status_code != 200:
                self.logger.error(
                    f"Order placement failed - Status: {response.status_code}, "
                    f"Response: {response.text}"
                )
                return {'success': False, 'error': f"HTTP {response.status_code}: {response.text}"}
            
            result = response.json()
            
            # Log result
            if result.get('success'):
                self.logger.info(f"Order placed successfully: {result}")
            else:
                self.logger.error(f"Order placement failed: {result}")
            
            return result
            
        except OrderValidationError as e:
            self.logger.error(f"Order validation error: {str(e)}")
            return {'success': False, 'error': str(e)}
        except requests.Timeout:
            self.logger.error("Order placement timeout")
            return {'success': False, 'error': 'Request timeout'}
        except requests.RequestException as e:
            self.logger.error(f"Request error placing order: {str(e)}")
            return {'success': False, 'error': str(e)}
        except Exception as e:
            self.logger.error(f"Unexpected error placing order: {str(e)}")
            return {'success': False, 'error': f"Unexpected error: {str(e)}"}

# Example usage
if __name__ == "__main__":
    # Initialize the exchange
    delta = DeltaExchange()
    
    # Example order parameters
    order_params = {
        'product_id': 27,  # Product ID for BTCUSD
        'size': 1,
        'order_type': 'market_order',
        'side': 'sell'
    }
    
    # Place the order
    response = delta.place_order(**order_params)
    print("Order Response:", response)

### Demo REsponse
# {'meta': {}, 'result': {'bracket_stop_loss_limit_price': None, 'user_id': 79261608, 'trail_amount': None, 'stop_trigger_method': None, 'reduce_only': False, 'paid_commission': '0.04892457', 'stop_order_type': None, 'meta_data': {'cashflow': '0', 'ip': '106.222.226.108', 'otc': False, 'pnl': '0', 'source': 'api'}, 'state': 'closed', 'time_in_force': 'ioc', 'id': 339704234, 'average_fill_price': '82923', 'cancellation_reason': None, 'limit_price': '87072', 'mmp': 'disabled', 'bracket_take_profit_price': None, 'bracket_order': None, 'order_type': 'market_order', 'bracket_trail_amount': None, 'side': 'buy', 'updated_at': '2025-03-18T05:28:18.939887Z', 'bracket_stop_loss_price': None, 'quote_size': None, 'size': 1, 'client_order_id': None, 'stop_price': None, 'product_id': 27, 'unfilled_size': 0, 'bracket_take_profit_limit_price': None, 'commission': '0', 'created_at': '2025-03-18T05:28:18.806653Z', 'close_on_trigger': 'false', 'product_symbol': 'BTCUSD'}, 'success': True}
