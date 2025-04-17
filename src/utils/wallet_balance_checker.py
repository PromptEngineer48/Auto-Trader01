# This script is used to check the wallet balance of the user.
# It uses the Delta Exchange API to get the wallet balance.
# Demo Output:
# Wallet Balance (USD): $126.00


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

class DeltaWallet:
    def __init__(self):
        self.api_key = os.getenv('API_KEY')
        self.api_secret = os.getenv('API_SECRET')
        self.base_url = 'https://api.india.delta.exchange'

    def _generate_signature(self, method: str, endpoint: str, payload: str = '') -> Tuple[str, str]:
        timestamp = str(int(time.time()) + 3)
        signature_data = method + timestamp + endpoint + str(payload)
        message = bytes(signature_data, 'utf-8')
        secret = bytes(self.api_secret, 'utf-8')
        hash_obj = hmac.new(secret, message, hashlib.sha256)
        return hash_obj.hexdigest(), timestamp

    def get_wallet_balance(self) -> Dict:
        method = 'GET'
        endpoint = '/v2/wallet/balances'
        signature, timestamp = self._generate_signature(method, endpoint)

        headers = {
            'api-key': self.api_key,
            'signature': signature,
            'timestamp': timestamp,
            'Content-Type': 'application/json'
        }

        response = requests.get(f'{self.base_url}{endpoint}', headers=headers)
        return response.json()

    def get_usd_available_balance(self) -> float:
        wallet_data = self.get_wallet_balance()
        if wallet_data.get('result') and len(wallet_data['result']) > 0:
            return float(wallet_data['result'][0]['available_balance'])
        return 0.0

    def get_usd_balance(self) -> float:
        wallet_data = self.get_wallet_balance()
        if wallet_data.get('result') and len(wallet_data['result']) > 0:
            return float(wallet_data['result'][0]['balance'])
        return 0.0

# Example usage
if __name__ == "__main__":
    wallet = DeltaWallet()
    usd_balance = wallet.get_usd_available_balance()
    print(f'Wallet Balance (USD): ${usd_balance:,.2f}')
