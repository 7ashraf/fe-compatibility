# Codec v1: standalone ABI fixture

Status: **frozen, revision 1, 21 November 2026.** The target ABI is
[codec-v1.abi.json](codec-v1.abi.json). Both `contracts/solidity/Codec.sol` and
`contracts/fe/codec` implement it independently. The golden vectors are in
`fixtures/abi/codec-v1.json`.

The fixture exists to test ABI conformance: canonical encoding of the supported
shapes, custom-error bytes, an indexed event, and the handling of malformed
calldata. It has no business logic beyond echoing inputs.

## Interface

| Signature | Returns | Mutability | Behavior |
| --- | --- | --- | --- |
| `constructor(address initialOwner)` | — | nonpayable | Zero owner reverts `InvalidOwner()`; otherwise stores the owner immutably. |
| `statics(uint8 small, int16 delta, address who, bool flag)` | `(uint8, int16, address, bool)` | pure | Returns its inputs unchanged. |
| `wide(uint256 a, int256 b)` | `(uint256, int256)` | pure | Returns its inputs unchanged. |
| `point((uint64 x, address owner) p)` | `(address, uint256)` | pure | Returns `(p.owner, p.x)`. The input is one static tuple. |
| `echo(bytes payload)` | `bytes` | nonpayable | If `payload.length > 64`, reverts `TooLong(length, 64)`. Otherwise emits `Echoed(msg.sender, length)` and returns the payload. |
| `owner()` | `address` | view | The constructor's owner. |

| Error | Payload |
| --- | --- |
| `InvalidOwner()` | none |
| `TooLong(uint256 length, uint256 max)` | actual length, then 64 |

| Event | Indexed | Data |
| --- | --- | --- |
| `Echoed(address,uint256)`, non-anonymous | `sender` | `length` |

**Validation order for `echo`:** decoding happens first, then the length check,
then the event, then the return.

## Malformed calldata

Rejections from compiler-generated dispatch and ABI decoding have no specified
payload. For those vectors, the strict claim covers only the status (the call
reverts) and the absence of logs. Revert bytes are recorded but never compared.

Each malformed vector is classified first by the Fe ABI validator. Its
`expected_outcome` is one of two values:

- **`reject`:** the Solidity ABI specification does not allow the calldata to be
  decoded. This covers:
  - an unknown selector,
  - empty or truncated calldata,
  - a value outside its declared type (dirty high bits on `uint8` or
    `address`, an unextended `int16`, a `bool` other than 0 or 1),
  - a dynamic length that runs past the calldata.

  Both implementations must revert.
- **`unspecified`:** the calldata is decodable but not canonical. This covers a
  non-canonical in-bounds offset, nonzero padding, and trailing bytes. Each
  compiler's behavior is recorded, and the two implementations are compared
  with each other (status only). A difference is reported as a finding to
  review, not as a compiler vulnerability.

## Not covered

The fixture doesn't cover:

- Arrays, nested dynamic types, strings, or multiple dynamic arguments.
- Signed or unsigned widths other than 8, 16, 64, and 256.
- Value sent to nonpayable functions.
- Gas.
