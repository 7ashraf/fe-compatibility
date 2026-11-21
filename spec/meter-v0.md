# Meter v0 — Phase 0 observation-path fixture

A deliberately tiny contract, frozen before either implementation was written.
Both `contracts/solidity/Meter.sol` and `contracts/fe/meter` implement it
independently. It exists to prove the raw observation path, not as a
compatibility claim about a realistic contract.

| Item | Specification |
| --- | --- |
| Constructor | No arguments, non-payable. Total starts at 0. |
| `add(uint256 quantity) returns (uint256)` | Non-payable. Validation order: (1) `quantity == 0` reverts `EmptyQuantity()`; (2) `quantity > 100` reverts `TooLarge(uint256 quantity, uint256 limit)` with `limit = 100`. Otherwise total += quantity, emit `Added`, and return the new total. |
| `total() returns (uint256)` | View. Returns the current total. |
| Event | `Added(address indexed caller, uint256 quantity, uint256 total)`. `caller` is the transaction sender. Data is `quantity` then `total`. |
| Other calldata | Unknown selectors revert. Phase 0 does not compare unknown-selector payloads. |

Canonical selectors (computed with `cast sig` / `cast sig-event`) are checked
by the Phase 0 runner against both compiled ABIs.

## Phase 0 action sequence

All calls come from Anvil account 0, each in its own mined block. Block timestamps
are 1700000001, 1700000002, … in both worlds.

1. `add(5)` → success, returns 5, emits `Added(sender, 5, 5)`
2. `add(0)` → `EmptyQuantity()`
3. `add(200)` → `TooLarge(200, 100)`
4. `add(100)` → success, returns 105 (boundary: equal to the limit is allowed)
5. `total()` → 105 (sent as a transaction so it has the same observation shape)
