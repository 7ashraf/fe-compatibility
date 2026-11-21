// SPDX-License-Identifier: MIT
pragma solidity 0.8.31;

/// Shared test fixtures. The same bytecode is deployed in every world, so they
/// are part of the environment, not of either implementation under test.

interface ITreasury {
    function spend(uint256 grantId, uint256 amount) external;
}

/// Payment recipient that rejects every ETH transfer.
contract RejectingRecipient {
    error Rejected();

    receive() external payable {
        revert Rejected();
    }
}

/// Payment recipient that tries to re-enter spend() during the payment and
/// records the outcome. The callback must fail with the treasury's Reentrant().
contract ReentrantRecipient {
    event Callback(bool success, bytes data);

    address private immutable _treasury;
    uint256 private immutable _grantId;

    constructor(address treasury, uint256 grantId) {
        _treasury = treasury;
        _grantId = grantId;
    }

    receive() external payable {
        (bool ok, bytes memory data) = _treasury.call(abi.encodeCall(ITreasury.spend, (_grantId, 1)));
        emit Callback(ok, data);
    }
}

/// Delegate contract that makes two spends in one transaction; the second must
/// work after the first one unlocks.
contract Batcher {
    function twice(address treasury, uint256 grantId, uint256 amount) external {
        ITreasury(treasury).spend(grantId, amount);
        ITreasury(treasury).spend(grantId, amount);
    }
}
