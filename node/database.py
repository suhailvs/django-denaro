from typing import List, Union, Tuple, Dict
from denaro.transactions import Transaction, CoinbaseTransaction, TransactionInput
from denaro.helpers import sha256, point_to_string
from .models import PendingTransactions, PendingSpentOutputs

class Database:
    connection = None
    credentials = {}
    instance = None
    pool = None
    is_indexed = False

    def add_pending_transaction(self, transaction: Transaction, verify: bool = True):
        if isinstance(transaction, CoinbaseTransaction):
            return False
        tx_hex = transaction.hex()
        if verify and not transaction.verify_pending():
            return False
        PendingTransactions.objects.create(tx_hash = sha256(tx_hex), 
                                           tx_hex = tx_hex, 
                                           inputs_addresses = [point_to_string(tx_input.get_public_key()) for tx_input in transaction.inputs], 
                                           fees =  transaction.fees)
        
        self.add_transactions_pending_spent_outputs([transaction])
        return True

    def add_transactions_pending_spent_outputs(self, transactions: List[Transaction]) -> None:
        outputs = sum([[(tx_input.tx_hash, tx_input.index) for tx_input in transaction.inputs] for transaction in transactions], [])
        # [(2, 4), (3, 4), (1, 3), (3, 6)]
        for output in outputs:
            PendingSpentOutputs.objects.create(tx_hash=output[0], index=output[1])