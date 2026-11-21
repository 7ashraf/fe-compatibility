// SPDX-License-Identifier: MIT
pragma solidity 0.8.31;

/// Reference implementation of spec/codec-v1.md, written from the specification.
contract Codec {
    struct Point {
        uint64 x;
        address owner;
    }

    uint256 private constant MAX_PAYLOAD = 64;
    address private immutable _owner;

    error InvalidOwner();
    error TooLong(uint256 length, uint256 max);

    event Echoed(address indexed sender, uint256 length);

    constructor(address initialOwner) {
        if (initialOwner == address(0)) revert InvalidOwner();
        _owner = initialOwner;
    }

    function statics(uint8 small, int16 delta, address who, bool flag)
        external
        pure
        returns (uint8, int16, address, bool)
    {
        return (small, delta, who, flag);
    }

    function wide(uint256 a, int256 b) external pure returns (uint256, int256) {
        return (a, b);
    }

    function point(Point calldata p) external pure returns (address, uint256) {
        return (p.owner, p.x);
    }

    function echo(bytes calldata payload) external returns (bytes memory) {
        if (payload.length > MAX_PAYLOAD) revert TooLong(payload.length, MAX_PAYLOAD);
        emit Echoed(msg.sender, payload.length);
        return payload;
    }

    function owner() external view returns (address) {
        return _owner;
    }
}
