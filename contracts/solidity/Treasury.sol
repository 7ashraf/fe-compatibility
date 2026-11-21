// SPDX-License-Identifier: MIT
pragma solidity 0.8.31;

/// Solidity reference implementation of spec/vendor/treasury-v0/treasury-v0.md (revision 1),
/// written from the specification for differential comparison with the Fe treasury.
contract Treasury {
    struct Grant {
        bool exists;
        address delegate;
        address recipient;
        uint256 cap;
        uint256 spent;
        uint256 expiresAt;
        bool active;
    }

    uint256 private constant MAX = type(uint256).max;
    uint256 private constant PAYMENT_GAS = 100_000;

    address private immutable _owner;
    uint256 private _nextGrantId;
    mapping(uint256 => Grant) private _grants;
    bool private transient _locked;

    error InvalidOwner();
    error Unauthorized();
    error InvalidAddress();
    error InvalidAmount();
    error InvalidExpiry();
    error GrantIdExhausted();
    error UnknownGrant(uint256 grantId);
    error InactiveGrant(uint256 grantId);
    error Expired(uint256 expiresAt, uint256 currentTime);
    error InvalidGrantState();
    error CapExceeded(uint256 remaining, uint256 requested);
    error InsufficientBalance(uint256 available, uint256 requested);
    error PaymentFailed();
    error Reentrant();
    error UnsupportedCall();

    event Deposited(address indexed sender, uint256 amount);
    event GrantCreated(
        uint256 indexed grantId, address indexed delegate, address indexed recipient, uint256 cap, uint256 expiresAt
    );
    event GrantRevoked(uint256 indexed grantId);
    event Spent(
        uint256 indexed grantId, address indexed delegate, address indexed recipient, uint256 amount, uint256 newSpent
    );

    constructor(address owner_) {
        if (owner_ == address(0)) revert InvalidOwner();
        _owner = owner_;
        _nextGrantId = 1;
    }

    /// Shared lock for every protected mutation; a busy lock is Reentrant().
    function _lock() private {
        if (_locked) revert Reentrant();
        _locked = true;
    }

    function _known(uint256 grantId) private view returns (bool) {
        return grantId != 0 && grantId != MAX && _grants[grantId].exists;
    }

    function deposit() external payable {
        _lock();
        if (msg.value != 0) emit Deposited(msg.sender, msg.value);
        _locked = false;
    }

    function createGrant(address delegate, address recipient, uint256 cap, uint256 expiresAt)
        external
        returns (uint256 grantId)
    {
        _lock();
        if (msg.sender != _owner) revert Unauthorized();
        if (delegate == address(0) || recipient == address(0)) revert InvalidAddress();
        if (cap == 0) revert InvalidAmount();
        if (expiresAt <= block.timestamp) revert InvalidExpiry();
        grantId = _nextGrantId;
        if (grantId == 0 || grantId == MAX) revert GrantIdExhausted();
        _grants[grantId] = Grant(true, delegate, recipient, cap, 0, expiresAt, true);
        _nextGrantId = grantId + 1;
        emit GrantCreated(grantId, delegate, recipient, cap, expiresAt);
        _locked = false;
    }

    function revoke(uint256 grantId) external {
        _lock();
        if (msg.sender != _owner) revert Unauthorized();
        if (!_known(grantId)) revert UnknownGrant(grantId);
        Grant storage grant = _grants[grantId];
        if (grant.active) {
            grant.active = false;
            emit GrantRevoked(grantId);
        }
        _locked = false;
    }

    function spend(uint256 grantId, uint256 amount) external {
        _lock();
        if (!_known(grantId)) revert UnknownGrant(grantId);
        Grant memory grant = _grants[grantId];
        if (msg.sender != grant.delegate) revert Unauthorized();
        if (!grant.active) revert InactiveGrant(grantId);
        if (amount == 0) revert InvalidAmount();
        if (block.timestamp >= grant.expiresAt) revert Expired(grant.expiresAt, block.timestamp);
        if (grant.delegate == address(0) || grant.recipient == address(0) || grant.cap == 0 || grant.spent > grant.cap) {
            revert InvalidGrantState();
        }
        uint256 remaining = grant.cap - grant.spent;
        if (amount > remaining) revert CapExceeded(remaining, amount);
        uint256 available = address(this).balance;
        if (amount > available) revert InsufficientBalance(available, amount);
        uint256 newSpent = grant.spent + amount;
        _grants[grantId].spent = newSpent;
        (bool ok,) = grant.recipient.call{value: amount, gas: PAYMENT_GAS}("");
        if (!ok) revert PaymentFailed();
        emit Spent(grantId, msg.sender, grant.recipient, amount, newSpent);
        _locked = false;
    }

    function owner() external view returns (address) {
        return _owner;
    }

    function nextGrantId() external view returns (uint256) {
        return _nextGrantId;
    }

    function treasuryBalance() external view returns (uint256) {
        return address(this).balance;
    }

    function getGrant(uint256 grantId)
        external
        view
        returns (bool, address, address, uint256, uint256, uint256, bool)
    {
        if (!_known(grantId)) return (false, address(0), address(0), 0, 0, 0, false);
        Grant memory g = _grants[grantId];
        return (true, g.delegate, g.recipient, g.cap, g.spent, g.expiresAt, g.active);
    }

    /// Empty calldata and unknown or short selectors (zero value) are unsupported.
    fallback() external {
        revert UnsupportedCall();
    }
}
