// SPDX-License-Identifier: MIT
pragma solidity 0.8.31;

/// Reference for spec/layout-v1.md. Solidity's own layout rules place these
/// declarations exactly at the reviewed positions:
///   slot 0: _owner (address) at byte 0, _paused (bool) at 20, _limit (uint88) at 21
///   slot 1: root of _balances; entry slot keccak256(abi.encode(key, 1))
contract PackedLayout {
    address private _owner;
    bool private _paused;
    uint88 private _limit;
    mapping(address => uint256) private _balances;

    function setOwner(address value) external {
        _owner = value;
    }

    function setPaused(bool value) external {
        _paused = value;
    }

    function setLimit(uint88 value) external {
        _limit = value;
    }

    function setBalance(address key, uint256 value) external {
        _balances[key] = value;
    }

    function owner() external view returns (address) {
        return _owner;
    }

    function paused() external view returns (bool) {
        return _paused;
    }

    function limit() external view returns (uint88) {
        return _limit;
    }

    function balanceOf(address key) external view returns (uint256) {
        return _balances[key];
    }
}
