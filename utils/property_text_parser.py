import re
from typing import Any


def _match(patterns: list[str], text: str) -> str | None:
    for pattern in patterns:
        found = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if found:
            return found.group(1).strip()
    return None


def _number(value: str | None, default: float = 0) -> float:
    try:
        return float(value.replace(",", ""))
    except (AttributeError, TypeError, ValueError):
        return default


def parse_property_description(raw_text: str) -> dict[str, Any]:
    """Extract facts from raw Zillow, Realtor, or MLS listing text."""
    text = raw_text.replace("\u00a0", " ").replace("\r\n", "\n").strip()
    money = r"(?:C\s*\$|CAD\s*\$?|\$)\s*([\d,]+(?:\.\d{1,2})?)"

    price = _match([
        rf"^\s*{money}\s*$",
        rf"(?:list(?:ing)?\s*price|price|asking)\s*[:\-]?\s*{money}",
    ], text)
    address = _match([
        r"^\s*(\d{1,6}(?:[- ]\d{1,6})?\s+[^\n,]+,\s*[^\n,]+,\s*[A-Z]{2}(?:\s+[A-Z]\d[A-Z]\s*\d[A-Z]\d)?)\s*$",
        r"(?:address|location)\s*:\s*([^\n]+)",
        r"^\s*(\d{1,6}\s+[A-Za-z0-9.' -]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Way|Lane|Ln|Boulevard|Blvd|Crescent|Cres|Court|Ct)(?:,?\s+[^\n]+)?)\s*$",
    ], text)
    beds = _match([
        r"^\s*(\d+(?:\.\d+)?)\s*\n\s*bed(?:room)?s?\b",
        r"\b(\d+(?:\.\d+)?)\s*bed(?:room)?s?\b",
        r"\bbed(?:room)?s?\s*[:\-]?\s*(\d+(?:\.\d+)?)",
    ], text)
    baths = _match([
        r"^\s*(\d+(?:\.\d+)?)\s*\n\s*bath(?:room)?s?\b",
        r"\b(\d+(?:\.\d+)?)\s*bath(?:room)?s?\b",
        r"\bbath(?:room)?s?\s*[:\-]?\s*(\d+(?:\.\d+)?)",
    ], text)
    sqft = _match([
        r"total\s+interior\s+livable\s+area\s*:\s*([\d,]+(?:\.\d+)?)\s*(?:sq\.?\s*ft|sqft)",
        r"^\s*([\d,]+(?:\.\d+)?)\s*\n\s*(?:sq\.?\s*ft|sqft)\b",
        r"\b([\d,]+(?:\.\d+)?)\s*(?:sq\.?\s*ft|sqft)\b",
    ], text)
    lot_area = _match([
        r"lot\s+(?:size\s*:\s*)?([\d,]+(?:\.\d+)?)\s*(?:square\s+feet|sq\.?\s*ft|sqft)",
        r"([\d,]+(?:\.\d+)?)\s*(?:square\s+feet|sq\.?\s*ft|sqft)\s+lot",
    ], text)
    tax = _match([
        r"annual\s+tax\s+amount\s*:\s*(?:C\s*)?\$\s*([\d,]+(?:\.\d+)?)",
        r"property\s+tax\s*[:\-]?\s*(?:C\s*)?\$\s*([\d,]+(?:\.\d+)?)",
    ], text)
    assessed = _match([
        r"(?:assessed\s+value|assessed|assessment)\s*[:\-]?\s*(?:C\s*)?\$\s*([\d,]+(?:\.\d+)?)",
    ], text)
    year = _match([r"\b(?:year\s+)?built(?:\s+in)?\s*[:\-]?\s*((?:18|19|20)\d{2})"], text)
    mls = _match([r"\bMLS(?:®)?\s*(?:#|number|no\.?|:)\s*[:#]?\s*([A-Z0-9-]+)"], text)
    property_type = _match([
        r"property\s+subtype\s*:\s*([^\n]+)",
        r"^\s*((?:single\s*family|townhouse|condo(?:minium)?|apartment|duplex|triplex)[^\n]*)$",
    ], text)
 
    return {
        "address": address,
        "price": price,
        "beds": int(_number(beds, 1)),
        "baths": _number(baths, 1),
        "sqft": int(_number(sqft, 800)),
        "strata_fee": 0.0,
        "property_tax": _number(tax),
        "assessed_value": _number(assessed),
        "year_built": int(_number(year, 2000)),
        "property_type": property_type or "Unknown",
        "mls_number": mls or "N/A",
        "lot_area": _number(lot_area),
        "skytrain_walk_minutes": 15,
        "skytrain_station": "Unknown Transit",
        "est_rent": 2200,
        "growth_score": 6,
    }
