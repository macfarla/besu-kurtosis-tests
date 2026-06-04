// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.0;

// Emits a predictable event on every call so eth_getLogs over a wide block
// range returns a large, deterministic payload.
contract LogSpammer {
    event Spam(address indexed sender, uint256 indexed seq, bytes32 data);

    uint256 public seq;

    function spam(uint256 count) external {
        for (uint256 i = 0; i < count; i++) {
            emit Spam(msg.sender, seq++, blockhash(block.number - 1));
        }
    }
}
