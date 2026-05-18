import secrets
import time


_CROCKFORD_BASE32 = "0123456789abcdefghjkmnpqrstvwxyz"


def _encode_base32(value: int, length: int) -> str:
    chars: list[str] = []
    for _ in range(length):
        chars.append(_CROCKFORD_BASE32[value & 0b11111])
        value >>= 5
    return "".join(reversed(chars))


def new_id(prefix: str) -> str:
    """Return a type-prefixed, ULID-compatible sortable identifier."""
    if not prefix or not prefix.islower() or not prefix.replace("_", "").isalnum():
        raise ValueError(f"invalid id prefix: {prefix!r}")

    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    randomness = secrets.randbits(80)
    suffix = _encode_base32((timestamp_ms << 80) | randomness, 26)
    return f"{prefix}_{suffix}"
