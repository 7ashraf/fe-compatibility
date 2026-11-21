// SPDX-License-Identifier: MIT
pragma solidity 0.8.31;

/// Reference implementation of spec/meter-v0.md, written from the specification.
contract Meter {
    uint256 private constant LIMIT = 100;
    uint256 private _total;

    error EmptyQuantity();
    error TooLarge(uint256 quantity, uint256 limit);

    event Added(address indexed caller, uint256 quantity, uint256 total);

    function add(uint256 quantity) external returns (uint256) {
        if (quantity == 0) revert EmptyQuantity();
        if (quantity > LIMIT) revert TooLarge(quantity, LIMIT);
        _total += quantity;
        emit Added(msg.sender, quantity, _total);
        return _total;
    }

    function total() external view returns (uint256) {
        return _total;
    }
}
