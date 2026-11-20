"""US N-number to ICAO 24-bit address.

The US civil block runs from A00001 (N1) through ADF7C7 (N99999). Letters I and O
are skipped, matching 14 CFR 47.15. The layout used here is the published
numeric order of that block: each first digit owns 101,711 addresses, a letter
suffix occupies a 601-address pocket (1 + 24 × 25), and deeper digits use
strides of 10,111, 951 and 35. This file is an original implementation of that
public layout, checked against published examples N1, N172SP and N12345.
"""

from __future__ import annotations

import re

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_TAIL = re.compile(r"^N([1-9][0-9]{0,4})([A-Z]{0,2})$")


def normalize_token(value: str) -> str:
    return re.sub(r"[\s-]", "", value).upper()


def n_number_to_hex(registration: str) -> str | None:
    text = normalize_token(registration)
    match = _TAIL.fullmatch(text)
    if not match:
        return None
    digits, letters = match.group(1), match.group(2)
    if any(ch not in ALPHABET for ch in letters):
        return None
    if len(digits) + len(letters) > 5:
        return None
    if len(letters) == 2 and len(digits) > 3:
        return None
    if len(letters) == 1 and len(digits) > 4:
        return None
    offset = _offset(digits, letters)
    if offset is None:
        return None
    return f"{0xA00001 + offset:06X}"


def _offset(digits: str, letters: str) -> int | None:
    nums = [int(ch) for ch in digits]
    offset = (nums[0] - 1) * 101711
    strides = (10111, 951, 35)
    if len(nums) == 5:
        if letters:
            return None
        for index, digit in enumerate(nums[1:4]):
            offset += 601 + digit * strides[index]
        offset += 25 + nums[4]
        return offset
    for index, digit in enumerate(nums[1:]):
        offset += 601 + digit * strides[index]
    if not letters:
        return offset
    first = ALPHABET.index(letters[0])
    if len(nums) <= 3:
        offset += 1 + first * 25
        if len(letters) == 2:
            offset += 1 + ALPHABET.index(letters[1])
        return offset
    if len(letters) == 1:
        return offset + 1 + first
    return None
