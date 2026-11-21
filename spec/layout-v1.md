# Layout v1: explicit packed-storage fixture

Status: **frozen, revision 1, 21 November 2026.** The machine-readable schema
and action corpus are in `fixtures/layout/packed-v1.json`. Implementations:
`contracts/solidity/PackedLayout.sol` (Solidity's own layout rules) and
`contracts/fe/layout` (Fe `SolSlot`/`SolMapping` raw-layout APIs).

| Slot | Content (byte offsets from the low end of the word) |
| --- | --- |
| 0 | `owner` address at offset 0, width 20; `paused` bool at offset 20, width 1; `limit` uint88 at offset 21, width 11 |
| 1 | Root of `balances`, a `mapping(address => uint256)`. The entry for `key` is at `keccak256(abi.encode(key, 1))`. Slot 1 itself stays zero. |

Interface: `setOwner(address)`, `setPaused(bool)`, `setLimit(uint88)`,
`setBalance(address,uint256)`, and the getters `owner()`, `paused()`,
`limit()`, `balanceOf(address)`. Each setter writes exactly its own field or
entry.

## What layout conformance checks (Fe, `src/layout.fe`)

1. **The schema itself.** Widths fit their kinds (address 20, bool 1,
   uint 1–32). Each field lies within the word (offset + width ≤ 32). Fields
   in one slot don't overlap. A mapping root isn't a packed-field slot and
   isn't repeated. Limits: 8 fields, 2 roots.
2. **For every action:**
   - bits outside the written field are unchanged (neighbor preservation);
   - every field decodes to the expected value;
   - every declared key's entry, at the slot derived by `cast index`, holds
     its expected value, and other keys' entries are unchanged;
   - every slot the transaction wrote (`SSTORE`s from the trace) is slot 0 or
     a declared entry slot. This is the runtime check of the adapter's
     no-aliasing invariant.

A passing result covers exactly slots 0 and 1, plus the entry slots of the
declared keys. It says nothing about any other slot, about other compilers'
layouts, or about upgrade safety.

## Not covered

Nested mappings, dynamic arrays, `bytes` and `string`, inherited layouts,
proxies, and storage outside the declared slots.
