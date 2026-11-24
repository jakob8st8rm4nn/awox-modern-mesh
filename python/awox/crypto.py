"""Modern-Mesh ATT AES cryptography from the AwoX native library.

Each key and data block must contain exactly 16 bytes. Bytes, bytearray and
memoryview buffers are accepted and copied to immutable bytes before use.
ATT reverses the key, input block and output around standard AES-128.
Pure Python reference code, with no I/O and no constant-time guarantee.
Only the statically initialized AES mode is exposed; dormant CRC mode is not.
"""

# .rodata RVA 0x778 (standard AES S-box).
_SBOX = bytes.fromhex(
    "637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0"
    "b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b275"
    "09832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cf"
    "d0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2"
    "cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdb"
    "e0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08"
    "ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9e"
    "e1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16"
)
_INV_SBOX = bytes(_SBOX.index(i) for i in range(256))


def _block(value: bytes, name: str) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError(f"{name} must be a bytes-like buffer")
    size = value.nbytes if isinstance(value, memoryview) else len(value)
    if size != 16:
        raise ValueError(f"{name} must be exactly 16 bytes")
    block = bytes(value)
    # Validate the snapshot too, including mutable/custom buffer inputs.
    if len(block) != 16:
        raise ValueError(f"{name} must be exactly 16 bytes")
    return block


def _mul(a: int, b: int) -> int:
    result = 0
    while b:
        if b & 1:
            result ^= a
        a = ((a << 1) ^ (0x11B if a & 0x80 else 0)) & 255
        b >>= 1
    return result


def _round_keys(key: bytes) -> list[bytes]:
    expanded = list(key)
    rcon = 1
    while len(expanded) < 176:
        word = expanded[-4:]
        if len(expanded) % 16 == 0:
            word = [_SBOX[x] for x in word[1:] + word[:1]]
            word[0] ^= rcon
            rcon = _mul(rcon, 2)
        for x in word:
            expanded.append(expanded[-16] ^ x)
    return [bytes(expanded[i : i + 16]) for i in range(0, 176, 16)]


def _add_key(state: list[int], key: bytes) -> list[int]:
    return [a ^ b for a, b in zip(state, key)]


def _shift_rows(state: list[int], inverse: bool = False) -> list[int]:
    direction = -1 if inverse else 1
    return [
        state[4 * ((column + direction * row) % 4) + row]
        for column in range(4)
        for row in range(4)
    ]


def _mix_columns(state: list[int], inverse: bool = False) -> list[int]:
    factors = (14, 11, 13, 9) if inverse else (2, 3, 1, 1)
    output = []
    for column in range(4):
        values = state[4 * column : 4 * column + 4]
        for row in range(4):
            output.append(
                _mul(factors[0], values[row])
                ^ _mul(factors[1], values[(row + 1) % 4])
                ^ _mul(factors[2], values[(row + 2) % 4])
                ^ _mul(factors[3], values[(row + 3) % 4])
            )
    return output


def aes128_encrypt_block(key: bytes, plaintext: bytes) -> bytes:
    """Standard AES-128 block operation; native core RVAs 0xF80..0x1398."""
    key = _block(key, "key")
    plaintext = _block(plaintext, "plaintext")
    keys = _round_keys(key)
    state = _add_key(list(plaintext), keys[0])
    for round_number in range(1, 11):
        state = _shift_rows([_SBOX[x] for x in state])
        if round_number < 10:
            state = _mix_columns(state)
        state = _add_key(state, keys[round_number])
    return bytes(state)


def aes128_decrypt_block(key: bytes, ciphertext: bytes) -> bytes:
    """Standard inverse block operation; native inverse core RVA 0x1504."""
    key = _block(key, "key")
    ciphertext = _block(ciphertext, "ciphertext")
    keys = _round_keys(key)
    state = _add_key(list(ciphertext), keys[10])
    for round_number in range(9, -1, -1):
        state = [_INV_SBOX[x] for x in _shift_rows(state, inverse=True)]
        state = _add_key(state, keys[round_number])
        if round_number:
            state = _mix_columns(state, inverse=True)
    return bytes(state)


def aes_att_encryption(key: bytes, plaintext: bytes) -> bytes:
    """JNI-compatible AES mode: reverse(AES128(reverse(key), reverse(data)))."""
    return aes128_encrypt_block(
        _block(key, "key")[::-1], _block(plaintext, "plaintext")[::-1]
    )[::-1]


def aes_att_decryption(key: bytes, ciphertext: bytes) -> bytes:
    """Inverse of aes_att_encryption; JNI helper RVA 0x1B9C."""
    return aes128_decrypt_block(
        _block(key, "key")[::-1], _block(ciphertext, "ciphertext")[::-1]
    )[::-1]
