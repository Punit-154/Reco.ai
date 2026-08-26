from decimal import ROUND_HALF_UP, Decimal

__all__ = ["parse_rupees_to_paise", "rupees_from_paise"]


def parse_rupees_to_paise(value: str | int | Decimal) -> int:
    if isinstance(value, bool):
        raise TypeError("bool is not a valid money value")
    if isinstance(value, float):
        raise TypeError("float is forbidden for money; use str, int or Decimal")
    if isinstance(value, int):
        return value * 100
    cleaned = str(value).strip()
    if not cleaned:
        raise ValueError("empty money value")
    d = Decimal(cleaned)
    quantized = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if quantized != d:
        raise ValueError(f"more than two decimal places: {value}")
    return int(quantized * 100)


def rupees_from_paise(paise: int) -> str:
    if isinstance(paise, bool) or not isinstance(paise, int):
        raise TypeError("paise must be an int")
    return f"{(Decimal(paise) / 100).quantize(Decimal('0.01')):f}"
