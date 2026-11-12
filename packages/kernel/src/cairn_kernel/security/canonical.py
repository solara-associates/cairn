import json
import math
from collections.abc import Mapping, Sequence
from types import MappingProxyType

MAX_SAFE_INTEGER = 2**53 - 1


class CanonicalJSONError(ValueError):
    pass


def _key_sort_key(key: str) -> bytes:
    return key.encode("utf-16-be")


def _number(value: float) -> str:
    if isinstance(value, bool):
        raise CanonicalJSONError("booleans are not numbers")
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise CanonicalJSONError("integer is outside the JSON safe range")
        return str(value)
    if not math.isfinite(value):
        raise CanonicalJSONError("non-finite numbers are not allowed")
    return repr(value)


def _encode(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, Mapping):
        items = []
        for key in value:
            if not isinstance(key, str):
                raise CanonicalJSONError("object keys must be strings")
        for key in sorted(value, key=_key_sort_key):
            items.append(f"{json.dumps(key, ensure_ascii=False)}:{_encode(value[key])}")
        return "{" + ",".join(items) + "}"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "[" + ",".join(_encode(item) for item in value) + "]"
    raise CanonicalJSONError(f"unsupported JSON value: {type(value).__name__}")


def canonical_json(value: object) -> str:
    return _encode(value)


def freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        frozen = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalJSONError("object keys must be strings")
            frozen[key] = freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(freeze_json(item) for item in value)
    return value
