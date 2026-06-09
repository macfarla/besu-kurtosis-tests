# Full sync isSyncing() fix (besu-eth/besu#10589)

Reproduces and validates the fix for `PostMergeContext.isSyncing()` always returning
`false` on post-TTD (post-merge) networks, causing `engine_getBlobsV2/V3` to return
`UNSUPPORTED_FORK (-38005)` while Besu was still syncing through a fork activation
boundary.

## How the test works

A 2-node kurtosis devnet runs with Fulu activating at epoch 3. Spamoor generates blob
transactions so blocks contain blobs from slot 24 onwards.

After finality is reached (epoch 4+), Besu's data is wiped and both services are
restarted. Besu starts from genesis while the canonical chain is already 50+ blocks
ahead. The observer Lighthouse immediately begins calling `engine_getBlobsV2/V3` for
blob-containing blocks. With the bug, Besu's `isSyncing()` returns false (incorrectly),
fork validation runs against the pre-Fulu genesis head, and every call returns
`UNSUPPORTED_FORK`. With the fix, `isSyncing()` returns true and the call succeeds.

## Prerequisites

```bash
brew install kurtosis-tech/tap/kurtosis-cli
docker
kurtosis loki start
```

## 1 — Build the image under test

```bash
cd /path/to/besu
git checkout <fix-branch>
./gradlew distDocker -x test
docker tag hyperledger/besu:develop besu-issue10589:local
```

## 2 — Run the enclaves

```bash
# Phase 1: confirm the bug (unpatched)
kurtosis run github.com/ethpandaops/ethereum-package \
  --enclave issue-10589-phase1 \
  --args-file full-sync-isSyncing/phase1-unpatched.yaml \
  --image-download always

# Phase 2: verify the fix (swap el_image in phase2-patched.yaml first)
kurtosis run github.com/ethpandaops/ethereum-package \
  --enclave issue-10589-phase2 \
  --args-file full-sync-isSyncing/phase2-patched.yaml \
  --image-download always
```

## 3 — Trigger (after epoch 4+ finality, ~3 minutes)

Run the same procedure for both enclaves (substituting the enclave name):

```bash
ENCLAVE=issue-10589-phase1   # or issue-10589-phase2

# Stop both services
kurtosis service stop $ENCLAVE el-2-besu-lighthouse
kurtosis service stop $ENCLAVE cl-2-lighthouse-besu

# Wipe Besu data (must exec while container is running)
kurtosis service start $ENCLAVE el-2-besu-lighthouse
sleep 10
kurtosis service exec $ENCLAVE el-2-besu-lighthouse "rm -rf /data/besu/execution-data"
kurtosis service stop $ENCLAVE el-2-besu-lighthouse

# Restart both — Besu is now at genesis, chain is 50+ blocks ahead with blobs
kurtosis service start $ENCLAVE el-2-besu-lighthouse
kurtosis service start $ENCLAVE cl-2-lighthouse-besu
```

## 4 — Observe

```bash
# CL logs — look for UNSUPPORTED_FORK errors (bug) or clean blob retrieval (fix)
kurtosis service logs $ENCLAVE cl-2-lighthouse-besu 2>&1 | grep -E "38005|Unsupported|blob|Synced"

# Besu logs — look for GetBlobsV3 success and block imports
kurtosis service logs $ENCLAVE el-2-besu-lighthouse 2>&1 | grep -E "GetBlobsV|Imported|VALID|SYNCING"
```

## Expected results

**Phase 1 (bug present):**
```
Execution engine call failed  error: ServerMessage { code: -38005, message: "Unsupported fork" }
Error fetching or processing blobs from EL  error: RequestFailed(...)
```
Errors repeat every 6 seconds while Besu syncs from genesis through the Fulu boundary.

**Phase 2 (fix working):**
```
EngineGetBlobsV3 | Requested 3 bundles, found 3 valid bundles
Imported #N ... 3 blobs ... status: VALID
FCU(VALID) | head: ...
```
No `UNSUPPORTED_FORK` errors. Besu syncs normally and the CL shows `Synced (verified)`.

## Cleanup

```bash
kurtosis enclave rm -f issue-10589-phase1 issue-10589-phase2
```

## Notes

- `fulu_fork_epoch: 3` is the ethereum-package user-facing field; `osaka_time` is an
  internal field derived from it and cannot be set directly.
- The trigger wipe is needed because kurtosis devnets start fresh and Besu syncs in
  real-time, so it never naturally falls behind. Wiping Besu's state mid-run simulates
  the cold-start full sync scenario seen on live testnets like Hoodi.
