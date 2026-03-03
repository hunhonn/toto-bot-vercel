import base64
import re
import requests
import time
from html import unescape
from typing import Optional

SP_RESULTS_URL = "https://www.singaporepools.com.sg/en/product/sr/Pages/toto_results.aspx"

DRAW_NO_PATTERNS = [
    re.compile(r"Draw\s*No\.?\s*(\d+)", re.IGNORECASE),
    re.compile(r"Draw\s*Number\s*[:#]?\s*(\d+)", re.IGNORECASE),
    re.compile(r"Results\s*for\s*Draw\s*(\d+)", re.IGNORECASE),
]
NEXT_JACKPOT_PATTERNS = [
    re.compile(r"Next\s*Jackpot\.?\s*\$\s*([\d,]+)", re.IGNORECASE),
    re.compile(r"Estimated\s*Jackpot\.?\s*\$\s*([\d,]+)", re.IGNORECASE),
    re.compile(r"Jackpot\s*Prize\s*\$\s*([\d,]+)", re.IGNORECASE),
]
NO_G1_TEXT = "Group 1 has no winner"

_TAG_RE = re.compile(r"<[^>]+>")

def _b64_draw(draw_no: int) -> str: 
    #SP uses base64 of draw number in ?sppl=
    raw = f"DrawNumber={draw_no}".encode("utf-8")
    return base64.b64encode(raw).decode("utf-8")

def _normalize_html_to_text(html: str) -> str:
    text = _TAG_RE.sub(" ", html)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def _extract_first_int(patterns, text: str) -> Optional[int]:
    for pattern in patterns:
        m = pattern.search(text)
        if m:
            return int(m.group(1).replace(",", ""))
    return None

def fetch_page(draw_no: Optional[int] = None)-> str:
    if draw_no is None:
        url = SP_RESULTS_URL
    else:
        url = f"{SP_RESULTS_URL}?sppl={_b64_draw(draw_no)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TotoBot/1.0; +https://github.com/your-repo)"
    }
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            last_err = e
            if attempt < 2:
                time.sleep(0.6 * (2 ** attempt))
    raise last_err

def parse_latest_draw_no(html: str) -> Optional[int]:
    draw_no = _extract_first_int(DRAW_NO_PATTERNS, html)
    if draw_no is not None:
        return draw_no
    normalized = _normalize_html_to_text(html)
    return _extract_first_int(DRAW_NO_PATTERNS, normalized)

def parse_next_jackpot_amount(html: str) -> Optional[int]:
    amount = _extract_first_int(NEXT_JACKPOT_PATTERNS, html)
    if amount is not None:
        return amount
    normalized = _normalize_html_to_text(html)
    return _extract_first_int(NEXT_JACKPOT_PATTERNS, normalized)

def had_no_g1_winner(html: str) -> bool:
    return NO_G1_TEXT.lower() in html.lower()

def is_next_draw_cascade(latest_draw_no: int) -> bool:
    #cascade triggers after 3 consecutive draws without a G1 winner
    #check last 3 draws.
    for dn in (latest_draw_no,latest_draw_no-1,latest_draw_no-2):
        h = fetch_page(dn)
        if not had_no_g1_winner(h):
            return False
    return True 