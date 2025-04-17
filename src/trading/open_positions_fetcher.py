# This script is used to fetch all open positions for USD products from Delta Exchange.
# It uses the Delta Exchange API to get the open positions.
# It then prints the open positions to the console.


import hashlib
import hmac
import time
import requests
import logging
from typing import Dict, List, Optional
from datetime import datetime
import os
from dotenv import load_dotenv
import sys

load_dotenv()

api_key = os.getenv('API_KEY')
api_secret = os.getenv('API_SECRET')

class OpenPositionsFetcher:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = 'https://api.india.delta.exchange'
        self.logger = logging.getLogger('OpenPositionsFetcher')

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

    def _get_all_usd_products(self) -> List[Dict]:
        """Get all USD products from Delta Exchange."""
        try:
            print("Fetching products", end='', flush=True)
            method = 'GET'
            endpoint = '/v2/products'
            signature, timestamp = self._generate_signature(method, endpoint)
            
            headers = {
                'api-key': self.api_key,
                'signature': signature,
                'timestamp': timestamp,
                'Content-Type': 'application/json'
            }
            
            response = requests.get(f'{self.base_url}/v2/products', headers=headers)
            data = response.json()
            
            if not data.get('success'):
                print(" [X]")
                self.logger.error("Failed to fetch products")
                return []
                
            products = [{'id': product.get('id'), 'symbol': product.get('symbol')} 
                       for product in data['result'] 
                       if isinstance(product, dict) and product.get('symbol', '').endswith('USD')]
            print(" [OK]")
            return products
        except Exception as e:
            print(" [X]")
            self.logger.error(f"Error fetching products: {str(e)}")
            return []

    def get_open_positions(self) -> List[Dict]:
        """Get all open positions for USD products."""
        try:
            products_list = self._get_all_usd_products()
            if not products_list:
                self.logger.error("No products found to check positions")
                return []

            all_positions = []
            method = 'GET'
            total_products = len(products_list)
            
            print(f"Checking positions for {total_products} products", end='', flush=True)
            
            for i, product in enumerate(products_list, 1):
                try:
                    # Generate new signature for each position request
                    product_id = product['id']
                    endpoint = f'/v2/positions?product_id={product_id}'
                    signature, timestamp = self._generate_signature(method, endpoint)
                    headers = {
                        'api-key': self.api_key,
                        'signature': signature,
                        'timestamp': timestamp,
                        'Content-Type': 'application/json'
                    }
                    
                    response = requests.get(f'{self.base_url}/v2/positions?product_id={product_id}', headers=headers)
                    position_data = response.json()
                    # print("Position Data for", product_id, 'is', position_data)
                    
                    if position_data.get('success') and position_data.get('result'):
                        position = position_data['result']
                        # print("Full Position Data", position)
                        # Only add positions with non-zero size
                        if position.get('size', 0) != 0:
                            all_positions.append({
                                'product_symbol': product['symbol'],
                                'position': position
                            })
                    
                    # Print progress dots
                    if i % 5 == 0 or i == total_products:
                        print(".", end='', flush=True)
                        
                    # Add a small delay to avoid rate limiting
                    time.sleep(0.1)
                    
                except Exception as e:
                    self.logger.error(f"Error fetching position for {product['symbol']}: {str(e)}")
                    continue

            print(" [OK]")

            # Print only the non-zero positions that exist
            if all_positions:
                print("\nActive Open Positions:")
                for position in all_positions:
                    print(f"Symbol: {position['product_symbol']}")
                    print(f"Size: {position['position'].get('size', 0)}")
                    print(f"Entry Price: {position['position'].get('entry_price', 'N/A')}")
                    print("-------------------")
            else:
                print("\nNo active open positions found")

            return all_positions

        except Exception as e:
            print(" [X]")
            self.logger.error(f"Error in get_open_positions: {str(e)}")
            return []

def main():
    fetcher = OpenPositionsFetcher(api_key, api_secret)
    try:
        positions = fetcher.get_open_positions()
        if not positions:
            print("No open positions found")
    except KeyboardInterrupt:
        print("\nProgram interrupted by user")
        fetcher.logger.info("Program interrupted by user")
    except Exception as e:
        print("\nProgram terminated due to error")
        fetcher.logger.error(f"Program terminated due to error: {str(e)}")

if __name__ == "__main__":
    main() 