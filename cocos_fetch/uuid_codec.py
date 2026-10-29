"""Cocos Creator compressed-UUID codec.

Cocos Creator stores asset UUIDs in build manifests in a 22-character
"compressed" form to save space:

    standard:   fc991dd7-0033-4b80-9d41-c8a86a702e59   (32 hex digits = 128 bits)
    compressed: fcmR3XADNLgJ1ByKhqcC5Z                 (2 hex + 20 base64 chars)

The first two hex digits are kept as-is. The remaining 30 hex digits
(120 bits) are packed into 20 base64 characters (6 bits each): every pair
of base64 characters carries 12 bits, i.e. exactly three hex digits.
"""

BASE64_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_B64_INDEX = {c: i for i, c in enumerate(BASE64_CHARS)}
_HEX = "0123456789abcdef"


def _format_uuid(hex32: str) -> str:
    return f"{hex32[:8]}-{hex32[8:12]}-{hex32[12:16]}-{hex32[16:20]}-{hex32[20:]}"


def decode_uuid(s: str) -> str:
    """Expand a 22-char compressed UUID into the standard 8-4-4-4-12 form.

    Strings that are not compressed UUIDs (wrong length, or already contain
    dashes) are returned unchanged, because manifests mix both kinds of keys.
    """
    if len(s) != 22 or "-" in s:
        return s

    out = [s[:2]]
    for i in range(2, 22, 2):
        hi = _B64_INDEX[s[i]]        # 6 bits
        lo = _B64_INDEX[s[i + 1]]    # 6 bits  -> 12 bits = 3 hex digits
        out.append(_HEX[hi >> 2])                       # top 4 bits of hi
        out.append(_HEX[((hi & 0b11) << 2) | (lo >> 4)])  # low 2 of hi + top 2 of lo
        out.append(_HEX[lo & 0b1111])                   # low 4 bits of lo
    return _format_uuid("".join(out))


def encode_uuid(uuid: str) -> str:
    """Inverse of :func:`decode_uuid`: compress a standard UUID to 22 chars."""
    hex32 = uuid.replace("-", "").lower()
    if len(hex32) != 32:
        raise ValueError(f"not a UUID: {uuid!r}")

    out = [hex32[:2]]
    for i in range(2, 32, 3):
        bits = int(hex32[i:i + 3], 16)          # 12 bits
        out.append(BASE64_CHARS[bits >> 6])     # top 6 bits
        out.append(BASE64_CHARS[bits & 0x3F])   # low 6 bits
    return "".join(out)
