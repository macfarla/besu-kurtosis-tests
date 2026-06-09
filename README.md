# besu-kurtosis-tests

Kurtosis devnet configs and test scripts for validating Besu PRs.

## Structure

- `shared/` — utilities reused across tests (log seeder, LogSpammer contract)
- `ws-backpressure/` — WebSocket event-loop backpressure regression (PR #10354)
- `bonsai-layer-leak/` — LayeredKeyValueStorage unbounded growth during sync (PR #10600)
- `full-sync-isSyncing/` — `PostMergeContext.isSyncing()` always false on post-merge networks, causing `UNSUPPORTED_FORK` on blob API calls during full sync (issue #10589)

## Common setup

```bash
# Install Kurtosis
brew install kurtosis-tech/tap/kurtosis-cli

# Python deps
pip install web3 py-solc-x websockets eth-account

# Start log collection (do this once before any kurtosis run)
kurtosis loki start
```

## Pre-funded account

All ethereum-package devnets include a standard pre-funded genesis account.
Use it with `seed_logs.py --private-key`:

- Address: `0x8943545177806ED17B9F23F0a21ee5948eCaa776`
- Private key: `0xbcdf20249abf0ed6d944c0288fad489e33f66b3960d9e6229c1cd214ed3bbe31`
