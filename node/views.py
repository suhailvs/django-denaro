import random
from asyncio import gather
from collections import deque
from os import environ
import re

from asyncpg import UniqueViolationError
from fastapi import FastAPI, Body, Query
from fastapi.responses import RedirectResponse

from httpx import TimeoutException
from icecream import ic
from starlette.background import BackgroundTasks, BackgroundTask
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from denaro.helpers import timestamp, sha256, transaction_to_json
from denaro.manager import create_block, get_difficulty, Manager, get_transactions_merkle_tree, \
    split_block_content, calculate_difficulty, clear_pending_transactions, block_to_bytes, get_transactions_merkle_tree_ordered
from denaro.node.nodes_manager import NodesManager, NodeInterface
from denaro.node.utils import ip_is_local
from denaro.transactions import Transaction, CoinbaseTransaction
from denaro import Database
from denaro.constants import VERSION, ENDIAN

# Create your views here.

# db: Database = None
transactions_cache = deque(maxlen=100)

from django.http import JsonResponse
from .models import UnspentOutput
from .database import Database

db = Database()

def root(request):
    output = UnspentOutput.objects.order_by('tx_hash','index')
    unspent_outputs_hash = sha256(''.join(row.tx_hash + bytes([row.index]).hex() for row in output))
    return JsonResponse({"version": VERSION, "unspent_outputs_hash": unspent_outputs_hash})


def propagate(path: str, args: dict, ignore_url=None, nodes: list = None):
    global self_url
    self_node = NodeInterface(self_url or '')
    ignore_node = NodeInterface(ignore_url or '')
    aws = []
    for node_url in nodes or NodesManager.get_propagate_nodes():
        node_interface = NodeInterface(node_url)
        if node_interface.base_url == self_node.base_url or node_interface.base_url == ignore_node.base_url:
            continue
        aws.append(node_interface.request(path, args, self_node.url))
    for response in gather(*aws, return_exceptions=True):
        print('node response: ', response)

async def push_tx(request):
    tx_hex = request.GET['tx_hex']
    
    tx = await Transaction.from_hex(tx_hex)
    if tx.hash() in transactions_cache:
        return JsonResponse({'ok': False, 'error': 'Transaction just added'})
    try:
        if db.add_pending_transaction(tx):
            if 'Sender-Node' in request.headers:
                NodesManager.update_last_message(request.headers['Sender-Node'])
            propagate('push_tx', {'tx_hex': tx_hex})
            transactions_cache.append(tx.hash())
            return JsonResponse({'ok': True, 'result': 'Transaction has been accepted'})
        else:
            return JsonResponse({'ok': False, 'error': 'Transaction has not been added'})
    except UniqueViolationError:
        return JsonResponse({'ok': False, 'error': 'Transaction already present'})
"""

@app.get("/push_tx")
@app.post("/push_tx")
async def push_tx(request: Request, background_tasks: BackgroundTasks, tx_hex: str = None, body=Body(False)):
    if body and tx_hex is None:
        tx_hex = body['tx_hex']
    tx = await Transaction.from_hex(tx_hex)
    if tx.hash() in transactions_cache:
        return {'ok': False, 'error': 'Transaction just added'}
    try:
        if await db.add_pending_transaction(tx):
            if 'Sender-Node' in request.headers:
                NodesManager.update_last_message(request.headers['Sender-Node'])
            background_tasks.add_task(propagate, 'push_tx', {'tx_hex': tx_hex})
            transactions_cache.append(tx.hash())
            return {'ok': True, 'result': 'Transaction has been accepted'}
        else:
            return {'ok': False, 'error': 'Transaction has not been added'}
    except UniqueViolationError:
        return {'ok': False, 'error': 'Transaction already present'}


@app.post("/push_block")
@app.get("/push_block")
async def push_block(request: Request, background_tasks: BackgroundTasks, block_content: str = '', txs='', block_no: int = None, body=Body(False)):
    if is_syncing:
        return {'ok': False, 'error': 'Node is already syncing'}
    if body:
        txs = body['txs']
        if 'block_content' in body:
            block_content = body['block_content']
        if 'id' in body:
            block_no = body['id']
        if 'block_no' in body:
            block_no = body['block_no']
    if isinstance(txs, str):
        txs = txs.split(',')
        if txs == ['']:
            txs = []
    previous_hash = split_block_content(block_content)[0]
    next_block_id = await db.get_next_block_id()
    if block_no is None:
        previous_block = await db.get_block(previous_hash)
        if previous_block is None:
            if 'Sender-Node' in request.headers:
                background_tasks.add_task(sync_blockchain, request.headers['Sender-Node'])
                return {'ok': False,
                        'error': 'Previous hash not found, had to sync according to sender node, block may have been accepted'}
            else:
                return {'ok': False, 'error': 'Previous hash not found'}
        block_no = previous_block['id'] + 1
    if next_block_id < block_no:
        background_tasks.add_task(sync_blockchain, request.headers['Sender-Node'] if 'Sender-Node' in request.headers else None)
        return {'ok': False, 'error': 'Blocks missing, had to sync according to sender node, block may have been accepted'}
    if next_block_id > block_no:
        return {'ok': False, 'error': 'Too old block'}
    final_transactions = []
    hashes = []
    for tx_hex in txs:
        if len(tx_hex) == 64:  # it's an hash
            hashes.append(tx_hex)
        else:
            final_transactions.append(await Transaction.from_hex(tx_hex))
    if hashes:
        pending_transactions = await db.get_pending_transactions_by_hash(hashes)
        if len(pending_transactions) < len(hashes):  # one or more tx not found
            if 'Sender-Node' in request.headers:
                background_tasks.add_task(sync_blockchain, request.headers['Sender-Node'])
                return {'ok': False,
                        'error': 'Transaction hash not found, had to sync according to sender node, block may have been accepted'}
            else:
                return {'ok': False, 'error': 'Transaction hash not found'}
        final_transactions.extend(pending_transactions)
    if not await create_block(block_content, final_transactions):
        return {'ok': False}

    if 'Sender-Node' in request.headers:
        NodesManager.update_last_message(request.headers['Sender-Node'])

    background_tasks.add_task(propagate, 'push_block', {
        'block_content': block_content,
        'txs': [tx.hex() for tx in final_transactions] if len(final_transactions) < 10 else txs,
        'block_no': block_no
    })
    return {'ok': True}


@app.get("/sync_blockchain")
@limiter.limit("10/minute")
async def sync(request: Request, node_url: str = None):
    global is_syncing
    if is_syncing:
        return {'ok': False, 'error': 'Node is already syncing'}
    is_syncing = True
    await sync_blockchain(node_url)
    is_syncing = False


LAST_PENDING_TRANSACTIONS_CLEAN = [0]


@app.get("/get_mining_info")
async def get_mining_info(background_tasks: BackgroundTasks):
    Manager.difficulty = None
    difficulty, last_block = await get_difficulty()
    pending_transactions = await db.get_pending_transactions_limit(hex_only=True)
    pending_transactions = sorted(pending_transactions)
    if LAST_PENDING_TRANSACTIONS_CLEAN[0] < timestamp() - 600:
        print(LAST_PENDING_TRANSACTIONS_CLEAN[0])
        LAST_PENDING_TRANSACTIONS_CLEAN[0] = timestamp()
        background_tasks.add_task(clear_pending_transactions, pending_transactions)
    return {'ok': True, 'result': {
        'difficulty': difficulty,
        'last_block': last_block,
        'pending_transactions': pending_transactions[:10],
        'pending_transactions_hashes': [sha256(tx) for tx in pending_transactions],
        'merkle_root': get_transactions_merkle_tree(pending_transactions[:10])
    }}


@app.get("/get_address_info")
@limiter.limit("2/second")
async def get_address_info(request: Request, address: str, transactions_count_limit: int = Query(default=5, le=50), show_pending: bool = False, verify: bool = False):
    outputs = await db.get_spendable_outputs(address)
    balance = sum(output.amount for output in outputs)
    return {'ok': True, 'result': {
        'balance': "{:f}".format(balance),
        'spendable_outputs': [{'amount': "{:f}".format(output.amount), 'tx_hash': output.tx_hash, 'index': output.index} for output in outputs],
        'transactions': [await db.get_nice_transaction(tx.hash(), address if verify else None) for tx in await db.get_address_transactions(address, limit=transactions_count_limit, check_signatures=True)] if transactions_count_limit > 0 else [],
        'pending_transactions': [await db.get_nice_transaction(tx.hash(), address if verify else None) for tx in await db.get_address_pending_transactions(address, True)] if show_pending else None,
        'pending_spent_outputs': await db.get_address_pending_spent_outputs(address) if show_pending else None
    }}


@app.get("/add_node")
@limiter.limit("10/minute")
async def add_node(request: Request, url: str, background_tasks: BackgroundTasks):
    nodes = NodesManager.get_nodes()
    url = url.strip('/')
    if url == self_url:
        return {'ok': False, 'error': 'Recursively adding node'}
    if url in nodes:
        return {'ok': False, 'error': 'Node already present'}
    else:
        try:
            assert await NodesManager.is_node_working(url)
            background_tasks.add_task(propagate, 'add_node', {'url': url}, url)
            NodesManager.add_node(url)
            return {'ok': True, 'result': 'Node added'}
        except Exception as e:
            print(e)
            return {'ok': False, 'error': 'Could not add node'}


@app.get("/get_nodes")
async def get_nodes():
    return {'ok': True, 'result': NodesManager.get_recent_nodes()[:100]}


@app.get("/get_pending_transactions")
async def get_pending_transactions():
    return {'ok': True, 'result': [tx.hex() for tx in await db.get_pending_transactions_limit(1000)]}


@app.get("/get_transaction")
@limiter.limit("2/second")
async def get_transaction(request: Request, tx_hash: str, verify: bool = False):
    tx = await db.get_nice_transaction(tx_hash)
    if tx is None:
        return {'ok': False, 'error': 'Transaction not found'}
    return {'ok': True, 'result': tx}


@app.get("/get_block")
@limiter.limit("30/minute")
async def get_block(request: Request, block: str, full_transactions: bool = False):
    if block.isdecimal():
        block_info = await db.get_block_by_id(int(block))
        if block_info is not None:
            block_hash = block_info['hash']
        else:
            return {'ok': False, 'error': 'Block not found'}
    else:
        block_hash = block
        block_info = await db.get_block(block_hash)
    if block_info:
        return {'ok': True, 'result': {
            'block': block_info,
            'transactions': await db.get_block_transactions(block_hash, hex_only=True) if not full_transactions else None,
            'full_transactions': await db.get_block_nice_transactions(block_hash) if full_transactions else None
        }}
    else:
        return {'ok': False, 'error': 'Block not found'}


@app.get("/get_blocks")
@limiter.limit("10/minute")
async def get_blocks(request: Request, offset: int, limit: int = Query(default=..., le=1000)):
    blocks = await db.get_blocks(offset, limit)
    return {'ok': True, 'result': blocks}
"""