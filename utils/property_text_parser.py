import re
import json
from typing import Any
from utils.gemini_helper import query_gemini

def _match(patterns: list[str], text: str) -> str | None:
    for pattern in patterns:
        found = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if found:
            return found.group(1).strip()
    return None

def _number(value: str | None, default: float = 0) -> float:
    try:
        # Strip currency symbols and clean commas
        clean_val = str(value).replace("$", "").replace(",", "").strip()
        return float(clean_val)
    except (AttributeError, TypeError, ValueError):
        return default

def parse_property_description(raw_text: str) -> dict[str, Any]:
    """Extract facts from raw Zillow, Realtor, or MLS listing text using Gemini or regex fallback."""
    text = raw_text.replace("\u00a0", " ").replace("\r\n", "\n").strip()
    
    # 1. Try parsing with Gemini first for 100% accuracy on complex copy-pastes
    try:
        prompt = f"""
        You are an expert real estate data parser. Extract the following properties from this real estate listing and return a JSON object:
        - "address": The street address (e.g. "9517 Stanley Street, Chilliwack, BC V2P 3Y7")
        - "price": The purchase or sold price as integer (e.g. 565000)
        - "beds": The number of bedrooms as float or int (e.g. 3)
        - "baths": The number of bathrooms as float or int (e.g. 2)
        - "sqft": The finished interior square footage as integer (e.g. 1249)
        - "strata_fee": Monthly strata fee as float (0 for detached house)
        - "property_tax": Annual property tax as float (e.g. 3100)
        - "assessed_value": Total assessed value (e.g. 682100)
        - "year_built": Year built as integer (e.g. 1945)
        - "property_type": The property type (e.g. "Detached House", "Condo", "Townhouse")
        - "mls_number": The MLS listing ID (e.g. "R3112875")
        - "lot_area": Lot size in square feet as integer (e.g. 7418)

        Listing Text:
        {text}

        Return ONLY a JSON object with these keys. No other conversational text.
        """
        
        response_text = query_gemini(prompt, response_json=True)
        if response_text:
            clean_json = re.sub(r"^```json\s*", "", response_text.strip())
            clean_json = re.sub(r"\s*```$", "", clean_json.strip())
            data = json.loads(clean_json)
            
            # Map variables and return
            return {
                "address": data.get("address"),
                "price": str(data.get("price", "")),
                "beds": int(_number(str(data.get("beds", 1)), 1)),
                "baths": _number(str(data.get("baths", 1)), 1),
                "sqft": int(_number(str(data.get("sqft", 800)), 800)),
                "strata_fee": _number(str(data.get("strata_fee", 0.0)), 0.0),
                "property_tax": _number(str(data.get("property_tax", 0.0)), 0.0),
                "assessed_value": _number(str(data.get("assessed_value", 0.0)), 0.0),
                "year_built": int(_number(str(data.get("year_built", 2000)), 2000)),
                "property_type": data.get("property_type") or "Detached House",
                "mls_number": data.get("mls_number") or "N/A",
                "lot_area": _number(str(data.get("lot_area", 0.0)), 0.0),
                "skytrain_walk_minutes": 15,
                "skytrain_station": "Unknown Transit",
                "est_rent": 2200,
                "growth_score": 6,
            }
    except Exception as e:
        print(f"[Parser] Gemini parser failed, using regex fallback. Error: {e}")

    # 2. Regex Fallback if Gemini is not configured/available
    money = r"(?:C\s*\$|CAD\s*\$?|\$)\s*([\d,]+(?:\.\d{1,2})?)"

    price = _match([
        rf"^\s*{money}\s*$",
        rf"(?:list(?:ing)?\s*price|price|asking|sold price)\s*[:\-]?\s*{money}",
    ], text)
    
    address = _match([
        r"^\s*((?:#\s*\d{1,5}[-\s]+)?\d{1,6}(?:[- ]\d{1,6})?\s+[^\n,]+,\s*[^\n,]+,\s*[A-Z]{2}(?:\s+[A-Z]\d[A-Z]\s*\d[A-Z]\d)?)\s*$",
        r"(?:address|location)\s*:\s*([^\n]+)",
        r"^\s*((?:#\s*\d{1,5}[-\s]+)?\d{1,6}\s+[A-Za-z0-9.' -]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Way|Lane|Ln|Boulevard|Blvd|Crescent|Cres|Court|Ct)(?:,?\s+[^\n]+)?)\s*$",
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
        r"Land\s+Size\s*.*?\(\s*([\d,]+)\s*(?:sqft|sq\.?\s*ft|sqft)\s*\)",
        r"lot\s+size\s*~?([\d,]+)\s*(?:sqft|sq\.?\s*ft|sqft)",
    ], text)
    
    tax = _match([
        r"annual\s+tax\s+amount\s*:\s*(?:C\s*)?\$\s*([\d,]+(?:\.\d+)?)",
        r"property\s+tax\s*[:\-]?\s*(?:C\s*)?\$\s*([\d,]+(?:\.\d+)?)",
        r"property\s+taxes\s*(?:C\s*)?\$\s*([\d,]+(?:\.\d+)?)",
    ], text)
    
    assessed = _match([
        r"(?:assessed\s+value|assessed|assessment)\s*[:\-]?\s*(?:C\s*)?\$\s*([\d,]+(?:\.\d+)?)",
        r"2026\s+(?:C\s*\$|CAD\s*\$?|\$)?[\d,]+\s+(?:C\s*\$|CAD\s*\$?|\$)?[\d,]+\s+(?:C\s*\$|CAD\s*\$?|\$)?([\d,]+)",
        r"202\d\s+Land\s+\$?[\d,]+\s+Impr\.\s+\$?[\d,]+\s+Total\s+\$?([\d,]+)",
    ], text)
    
    year = _match([
        r"\b(?:year\s+)?built(?:\s+in)?\s*[:\-]?\s*((?:18|19|20)\d{2})",
        r"Age\s+\d+\s+years\s+\(((?:18|19|20)\d{2})\)"
    ], text)
    
    mls = _match([
        r"\bMLS(?:®)?\s*(?:#|number|no\.?|:)?\s*[:#]?\s*([A-Z0-9-]+)"
    ], text)
    
    property_type = _match([
        r"property\s+subtype\s*:\s*([^\n]+)",
        r"property\s+type\s*[:\-]?\s*\n?\s*([A-Za-z0-9 ]+)",
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
        "property_type": property_type or "Detached House",
        "mls_number": mls or "N/A",
        "lot_area": _number(lot_area),
        "skytrain_walk_minutes": 15,
        "skytrain_station": "Unknown Transit",
        "est_rent": 2200,
        "growth_score": 6,
    }
