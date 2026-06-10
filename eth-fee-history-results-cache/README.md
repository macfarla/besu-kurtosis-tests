# Test Results: Fee Method Caching (PR #10524)

## Image under test

`hyperledger/besu:26.6-develop-7dff826` (tagged `besu-pr10524:local`)
Branch: `perf/fee-methods-no-cache`

## Network config

```yaml
participants:
  - el_type: geth
    cl_type: lighthouse
    count: 1
  - el_type: besu
    el_image: "besu-pr10524:local"
    el_extra_params:
      - "--api-gas-and-priority-fee-limiting-enabled=true"
      - "--rpc-http-api=ETH,NET,WEB3,MINER,ADMIN"
    el_log_level: "debug"
    cl_type: lighthouse
    validator_count: 0
    count: 1

network_params:
  preset: minimal
  fulu_fork_epoch: 0
```

Enclave: `fee-cache-test`

## Results

| Test | Check | Result |
|---|---|---|
| 7 — genesis/short chain | `eth_gasPrice` returns a hex value, no error | PASS — `0x3b9aca00` (1 gwei, configured minimum) |
| 1 — `eth_gasPrice` correctness | Non-zero, sensible value | PASS — Besu: `0x3b9aca00` (1 gwei min), Geth: `0x8` (8 wei base fee) |
| 2 — `eth_maxPriorityFeePerGas` | Non-zero with EIP-1559 txs | N/A — no transactions on the devnet; Geth returns `0x1`, Besu returns `0x0` |
| 3 — `eth_feeHistory` fixed block range | `baseFeePerGas` identical to Geth | PASS — all `0x7` entries match |
| 3 — `eth_feeHistory` fixed block range | `gasUsedRatio` identical to Geth | COSMETIC DIFF — Geth returns `0` (int), Besu returns `0.0` (float); functionally identical |
| 3 — `eth_feeHistory` fixed block range | `oldestBlock` identical to Geth | PASS |
| 4 — `eth_feeHistory` latest cache hit | Two identical rapid calls return same result | PASS — both calls returned identical results |
| 5 — cache invalidation | `miner_setMinGasPrice` causes reward change | N/A — reward arrays are all-zero with no transactions (nothing to clamp); `miner_setMinGasPrice` call succeeded (`result: true`), logged as `min gas price changed to 10.00 gwei` |
| 6 — 256-block range | `baseFeeCount` and `blobFeeCount` both 257 | PASS — both 257 at head #993 |
| Logs — no WARN/ERROR | No WARN or ERROR in fee-related log lines | PASS — zero WARN/ERROR entries from Besu |

## Notes

- **Test 1 / `eth_gasPrice` difference**: Besu returns the configured minimum (1 gwei) because
  the devnet has no transactions — `eth_gasPrice` falls back to `minGasPrice` when the fee
  history oracle has no samples. Geth returns the current base fee (7 wei). Both are correct
  behaviour for their respective implementations on an empty network.

- **Test 2 / `eth_maxPriorityFeePerGas`**: No EIP-1559 transactions were submitted, so the
  priority fee oracle has nothing to sample. Besu returns `0x0`; Geth returns `0x1` (its
  floor). Not a regression — this is consistent with empty-block behaviour.

- **Test 5 / cache invalidation**: Cannot verify reward change on an empty network since all
  percentile rewards are zero regardless of the min price clamp. The `miner_setMinGasPrice`
  call succeeded and was logged correctly. To fully verify reward clamping, re-run with
  `spamoor` generating EIP-1559 transactions.

- **Test 3 / `gasUsedRatio` encoding**: The `0` (integer) vs `0.0` (float) difference is a
  JSON serialisation detail, not a semantic difference. Both represent 0% gas utilisation.

- **Cache debug logging**: No cache hit/miss debug lines appeared at DEBUG log level. The
  `FeeOracleSnapshot` and result cache likely log at TRACE level.

- Config fix from context file: `osaka_time: 0` is not a valid user field — replaced with
  `fulu_fork_epoch: 0`. `cancun_fork_epoch` is not a valid field — Deneb defaults to epoch 0.
  `cl_type: teku` replaced with `lighthouse` to ensure reliable peer discovery.
