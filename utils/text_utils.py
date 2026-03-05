"""
utils/text_utils.py
Common text-processing helpers used across Friday modules.
"""

import re
import string
from typing import List, Optional


def normalize(text: str) -> str:
    """Lowercase, strip punctuation and extra whitespace."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def contains_any(text: str, keywords: List[str]) -> bool:
    """Return True if text contains any of the keywords (case-insensitive)."""
    t = text.lower()
    return any(kw.lower() in t for kw in keywords)


def extract_after(text: str, trigger: str) -> Optional[str]:
    """
    Return the portion of text that follows the first occurrence of *trigger*.
    Example: extract_after("open chrome please", "open") -> "chrome please"
    """
    idx = text.lower().find(trigger.lower())
    if idx == -1:
        return None
    remainder = text[idx + len(trigger):].strip()
    return remainder if remainder else None


def extract_time(text: str) -> Optional[str]:
    """
    Extract a time string from natural language, e.g. "7 pm", "14:30", "7:30 am".
    Returns the matched string or None.
    """
    patterns = [
        r"\b(\d{1,2}:\d{2}\s*(?:am|pm)?)\b",
        r"\b(\d{1,2}\s*(?:am|pm))\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def parse_time_to_hhmm(time_str: str) -> Optional[str]:
    """
    Convert a time string like '7 pm', '7:30 am', '14:30' to 'HH:MM' (24-hour).
    Returns None if parsing fails.
    """
    import re
    time_str = time_str.strip().lower()

    # Handle "HH:MM am/pm"
    m = re.match(r"^(\d{1,2}):(\d{2})\s*(am|pm)?$", time_str)
    if m:
        h, mi, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
        if ampm == "pm" and h != 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        return f"{h:02d}:{mi:02d}"

    # Handle "H am/pm"
    m = re.match(r"^(\d{1,2})\s*(am|pm)$", time_str)
    if m:
        h, ampm = int(m.group(1)), m.group(2)
        if ampm == "pm" and h != 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        return f"{h:02d}:00"

    return None


def clean_app_name(name: str) -> str:
    """Strip common filler words from an app name command."""
    fillers = ["please", "for me", "now", "quickly", "up"]
    result = name.strip()
    for f in fillers:
        result = re.sub(rf"\b{f}\b", "", result, flags=re.IGNORECASE)
    return result.strip()
