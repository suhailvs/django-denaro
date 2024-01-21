import argparse
import asyncio
import os
import sys

import pickledb
import requests
from fastecdsa import keys, curve

dir_path = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, dir_path + "/../..")

from utils import create_transaction, string_to_bytes
from denaro import Database, node

from denaro.constants import CURVE
from denaro.helpers import point_to_string, sha256

Database.credentials = {
    'user': os.environ.get('DENARO_DATABASE_USER', 'postgres'),
    'password': os.environ.get('DENARO_DATABASE_PASSWORD', 'root'),
    'database': os.environ.get('DENARO_DATABASE_NAME', 'denaro')
}


async def main():
    parser = argparse.ArgumentParser(description='Denaro wallet')
    parser.add_argument('command', metavar='command', type=str, help='action to do with the wallet', choices=['createwallet', 'send', 'balance'])
    parser.add_argument('-to', metavar='recipient', type=str, required=False)
    parser.add_argument('-d', metavar='amount', type=str, required=False)
    parser.add_argument('-m', metavar='message', type=str, dest='message', required=False)

    args = parser.parse_args()
    db = pickledb.load(f'{dir_path}/wallet.json', True)
    denaro_database: Database = await Database.get()
    node.main.db = denaro_database

    command = args.command

    if command == 'createwallet':
        private_keys = db.get('private_keys') or []
        private_key = keys.gen_private_key(CURVE)
        private_keys.append(private_key)
        db.set('private_keys', private_keys)

        public_key = keys.get_public_key(private_key, curve.P256)
        address = point_to_string(public_key)

        print(f'Private key: {hex(private_key)}\nAddress: {address}')
    elif command == 'balance':
        private_keys = db.get('private_keys') or []
        total_balance = 0
        total_pending_balance = 0
        for private_key in private_keys:
            public_key = keys.get_public_key(private_key, curve.P256)
            address = point_to_string(public_key)
            balance = await denaro_database.get_address_balance(address)
            total_balance += balance
            pending_balance = await denaro_database.get_address_balance(address, True)
            total_pending_balance += pending_balance
            print(f'\nAddress: {address}\nPrivate key: {hex(private_key)}\nBalance: {balance}{f" ({pending_balance - balance} pending)" if pending_balance - balance != 0 else ""}')
        print(f'\nTotal Balance: {total_balance}{f" ({total_pending_balance - total_balance} pending)" if total_pending_balance - total_balance != 0 else ""}')
    elif command == 'send':
        parser = argparse.ArgumentParser()
        parser.add_argument('command', metavar='command', type=str, help='action to do with the wallet')
        parser.add_argument('-to', metavar='recipient', type=str, dest='recipient', required=True)
        parser.add_argument('-d', metavar='amount', type=str, dest='amount', required=True)
        parser.add_argument('-m', metavar='message', type=str, dest='message', required=False)

        args = parser.parse_args()
        receiver = args.recipient
        amount = args.amount
        message = args.message

        tx = await create_transaction(db.get('private_keys'), receiver, amount, string_to_bytes(message))
        try:
            requests.get('http://localhost:3006/push_tx', {'tx_hex': tx.hex()}, timeout=10)
        except Exception as e:
            print(f'Could not push transaction to local node: {e}')
            await denaro_database.add_pending_transaction(tx)
            requests.get('https://denaro-node.gaetano.eu.org/push_tx', {'tx_hex': tx.hex()}, timeout=10)
        print(f'Transaction pushed. Transaction hash: {sha256(tx.hex())}')


if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    loop.run_until_complete(main())
