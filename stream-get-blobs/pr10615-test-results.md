# Test Results: Streaming engine_getBlobsV2 / engine_getBlobsV3 (Issue #10615)

## Image under test

`hyperledger/besu:26.6-develop-d8ccdf6` (tagged `besu-stream-blobs:local`)
Branch: `feat/stream-engine-get-blobs`

## Network config

```yaml
participants:
  - el_type: geth
    cl_type: lighthouse
    count: 1
  - el_type: besu
    el_image: "besu-stream-blobs:local"
    el_log_level: "debug"
    cl_type: lighthouse
    validator_count: 0
    count: 1

network_params:
  preset: minimal
  fulu_fork_epoch: 0
```

Enclave: `stream-blobs-test`

## Test procedure

- Blob transaction submitted directly to Besu's RPC (port 62219) so the blob is immediately present in Besu's pending pool
- `engine_getBlobsV2` and `engine_getBlobsV3` called on Besu's engine port (62220) with JWT auth before the tx is mined

## Results

| Check | Expected | Result |
|---|---|---|
| V2 — single known hash | array with `blob` + `proofs` fields | PASS (blob len 262146) |
| V3 — single known hash | array with `blob` + `proofs` fields | PASS (blob len 262146) |
| V2 — known + unknown hash | `null` (all-or-nothing) | PASS |
| V3 — known + unknown hash | `[{blob object}, null]` (partial) | PASS |
| No UNSUPPORTED_FORK (-38005) | No errors | Confirmed |

## Streaming path confirmed

Besu debug logs show the methods routing through the `EngineGetBlobsV2` / `EngineGetBlobsV3` classes:

```
EngineGetBlobsV2 | Requested 1 bundles, found 1 valid bundles, 0 missing, 0 unsupported
EngineGetBlobsV3 | Requested 1 bundles, found 1 valid bundles (false partial response)
EngineGetBlobsV2 | Requested 2 bundles, found 1 valid bundles, 1 missing, 0 unsupported
EngineGetBlobsV3 | Requested 2 bundles, found 1 valid bundles (true partial response)
```

`true partial response` (V3 with mixed known/unknown hashes) vs `false partial response` (V3 with all found) confirms V3 partial-response semantics are working correctly.

## Notes

- Blob tx must be submitted to Besu's RPC directly (not via Geth). When submitted to Geth, the tx is mined within ~3s — faster than P2P propagation to Besu's pending pool, so the engine API call races a block inclusion event. Submitting to Besu gives immediate access to the blob in its local pool.
- `fulu_fork_epoch: 0` activates Osaka at genesis — `osaka_time` is an internal field and cannot be set by the user.
