# WebSocket backpressure regression test (PR #10354)

Verifies that the WebSocket event-loop deadlock fix holds: a slow consumer that
fills the TCP receive window should not block the Vert.x event loop.

## Prerequisites

```bash
# Kurtosis
brew install kurtosis-tech/tap/kurtosis-cli

# Python deps (only needed once)
pip install web3 py-solc-x websockets eth-account
```

## 1 — Build images

```bash
cd /path/to/besu

# Unpatched (main)
git checkout main
./gradlew distDocker
docker tag hyperledger/besu:develop local/besu-unpatched:ws-bp

# Patched (PR branch)
git checkout <pr-branch>
./gradlew :ethereum:api:clean distDocker
docker tag hyperledger/besu:develop local/besu-patched:ws-bp
```

> Use `:ethereum:api:clean distDocker` for the second build to force
> recompilation and avoid Gradle serving cached bytecode.

## 2 — Start enclaves

```bash
# Edit network_params.yaml to set el_image, then:

kurtosis loki start

kurtosis run github.com/ethpandaops/ethereum-package \
  --enclave ws-bp-unpatched \
  --args-file network_params.yaml \
  --image-download missing
# swap el_image to local/besu-patched:ws-bp and repeat for ws-bp-patched
```

## 3 — Seed logs

Get the HTTP RPC port from `kurtosis enclave inspect <enclave>`, then:

```bash
cd ../shared

python3 seed_logs.py \
  --rpc http://localhost:<HTTP_PORT> \
  --blocks 200 --per-block 50 \
  --private-key 0xbcdf20249abf0ed6d944c0288fad489e33f66b3960d9e6229c1cd214ed3bbe31

# Note the --contract, --from-block, --to-block printed at the end
```

The pre-funded account (`0x8943545177806ED17B9F23F0a21ee5948eCaa776`) is the
standard ethpandaops genesis allocation present in all ethereum-package devnets.

## 4 — Run the test

Get the WS port from `kurtosis enclave inspect <enclave>`, then:

```bash
cd ../ws-backpressure

python3 ws_backpressure_test.py \
  --ws ws://localhost:<WS_PORT> \
  --contract <address> \
  --from-block <N> --to-block <M>
```

## Expected results

- Unpatched: `FAIL — event loop blocked (probe timed out)`
- Patched:   `PASS — event loop stayed responsive throughout backpressure window`

To confirm via Besu logs while the test runs:

```bash
kurtosis service logs <enclave> el-1-besu-lighthouse | grep -i "blocked\|BlockedThreadChecker"
```

## Cleanup

```bash
kurtosis enclave rm -f ws-bp-unpatched ws-bp-patched
```
