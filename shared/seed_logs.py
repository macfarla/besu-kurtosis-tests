#!/usr/bin/env python3
"""
Deploy LogSpammer and drive it across many blocks so eth_getLogs over the
seeded range returns several MB of data — enough to trigger WS backpressure.

Usage:
    pip install web3 py-solc-x
    python seed_logs.py --rpc http://localhost:8545 --blocks 200 --per-block 50

Outputs:
    contract address, fromBlock, toBlock  (pass these to ws_backpressure_test.py)
"""

import argparse
import json
import time

from eth_account import Account
from solcx import compile_source, install_solc
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware, SignAndSendRawMiddlewareBuilder

SOLIDITY_SOURCE = open("LogSpammer.sol").read()


def deploy(w3: Web3, deployer: str) -> str:
    install_solc("0.8.20", show_progress=False)
    compiled = compile_source(
        SOLIDITY_SOURCE,
        output_values=["abi", "bin"],
        solc_version="0.8.20",
    )
    contract_id = "<stdin>:LogSpammer"
    abi = compiled[contract_id]["abi"]
    bytecode = compiled[contract_id]["bin"]

    Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx_hash = Contract.constructor().transact({"from": deployer, "gas": 500_000})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    print(f"Deployed LogSpammer at {receipt.contractAddress}  (block {receipt.blockNumber})")
    return receipt.contractAddress, abi


def seed(w3: Web3, deployer: str, address: str, abi, blocks: int, per_block: int):
    contract = w3.eth.contract(address=address, abi=abi)
    from_block = w3.eth.block_number

    for i in range(blocks):
        tx_hash = contract.functions.spam(per_block).transact(
            {"from": deployer, "gas": 30_000 + per_block * 5_000}
        )
        w3.eth.wait_for_transaction_receipt(tx_hash)
        if (i + 1) % 10 == 0:
            print(f"  block {i + 1}/{blocks}  ({(i+1)*per_block} events so far)")

    to_block = w3.eth.block_number
    total = blocks * per_block
    print(f"\nDone. {total} events across blocks {from_block}–{to_block}")
    print(f"\nPass to ws_backpressure_test.py:")
    print(f"  --contract {address} --from-block {from_block} --to-block {to_block}")
    return from_block, to_block


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", default="http://localhost:8545")
    ap.add_argument("--blocks", type=int, default=200,
                    help="Number of spam() calls (one per block)")
    ap.add_argument("--per-block", type=int, default=50,
                    help="Events emitted per spam() call")
    ap.add_argument("--account", default=None,
                    help="Sender address; defaults to accounts[0]")
    ap.add_argument("--private-key", default=None,
                    help="Private key for local signing (required when node has no unlocked accounts)")
    args = ap.parse_args()

    w3 = Web3(Web3.HTTPProvider(args.rpc))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    assert w3.is_connected(), f"Cannot connect to {args.rpc}"

    if args.private_key:
        acct = Account.from_key(args.private_key)
        w3.middleware_onion.add(SignAndSendRawMiddlewareBuilder.build(acct))
        w3.eth.default_account = acct.address
        deployer = args.account or acct.address
    else:
        deployer = args.account or w3.eth.accounts[0]
    print(f"Using account {deployer}")

    address, abi = deploy(w3, deployer)
    seed(w3, deployer, address, abi, args.blocks, args.per_block)


if __name__ == "__main__":
    main()
