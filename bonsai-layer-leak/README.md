# Bonsai layer-leak regression test (besu-eth/besu#10498 / PR #10599)

Reproduces and validates the fix for the `LayeredKeyValueStorage` chain accumulation
bug: when `engine_newPayload` is called repeatedly without an intervening FCU (e.g.
during initial sync or a CL backfill retry loop), each call deepens the in-memory
layer chain by 1, leaking ~10 GB/day and causing O(depth) CPU in `isClosed()`.

## How the test works

An FCU-dropping proxy (`engine-api-fcu-proxy.py`) sits between Lighthouse and Besu.
It forwards all `engine_newPayload*` calls but silently drops all
`engine_forkchoiceUpdated*` calls (returning SYNCING to the CL). This causes Besu
to accumulate world-state layers without the head advancing.

The proxy matches the `ethpandaops/rpc-snooper` CLI interface so it works as a
drop-in via `snooper_params.image` — no manual port-forwarding needed.

## Prerequisites

```bash
brew install kurtosis-tech/tap/kurtosis-cli
docker
```

## 1 — Build the proxy image

```bash
cd bonsai-layer-leak
docker build -f fcu-proxy.Dockerfile -t fcu-proxy:local .
```

## 2 — Build Besu images

```bash
cd /path/to/besu

# Unfixed baseline
git checkout main        # or the unfixed commit
./gradlew distDocker
docker tag hyperledger/besu:develop local/besu-unfixed:layer-leak

# Fixed build (PR #10599)
git checkout bonsai-spiral
./gradlew :ethereum:core:clean distDocker
docker tag hyperledger/besu:develop local/besu-fixed:layer-leak
```

## 3 — Run the enclaves

Edit `network_params.yaml` to set `el_image`, then:

```bash
# Unfixed
kurtosis run github.com/ethpandaops/ethereum-package \
  --enclave layer-leak-unfixed \
  --args-file bonsai-layer-leak/network_params.yaml \
  --image-download missing

# Fixed (swap el_image in network_params.yaml first)
kurtosis run github.com/ethpandaops/ethereum-package \
  --enclave layer-leak-fixed \
  --args-file bonsai-layer-leak/network_params.yaml \
  --image-download missing
```

## 4 — Observe

```bash
# Layer depth — look for [LAYER_DEPTH] log lines
kurtosis service logs <enclave> el-1-besu-lighthouse 2>&1 | grep LAYER_DEPTH

# Proxy stats — confirms FCU is being dropped
kurtosis service logs <enclave> snooper-el-1-besu-lighthouse 2>&1 | grep -E "STATS|FCU|SYNCING"
```

## Expected results

**Unfixed:** `[LAYER_DEPTH]` shows depth climbing 1 → 2 → 3 → … → N (one layer
leaked per `engine_newPayload` call). Heap grows continuously.

**Fixed:** depth reaches 2 on the first backlog block and stays at ≤ 2 for all
subsequent blocks. Heap stays flat. Exec times settle to 3–8 ms.

## Cleanup

```bash
kurtosis enclave rm -f layer-leak-unfixed layer-leak-fixed
```
