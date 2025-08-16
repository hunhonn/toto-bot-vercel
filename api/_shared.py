import base64
import re
import requests
from typing import Optional, Tuple

SP_RESULTS_URL = "https://www.singaporepools.com.sg/en/product/sr/Pages/toto_results.aspx"

DRAW_NO_RE = re.compile(r"Draw No\.\s*(\d+)")
NEXT_JACKPOT_RE = re.compile(r"Next Jackpot\.?\s*\$([\d,]+)")
NO_G1_TEXT = "Group 1 has no winner"

def _b64_draw(draw_no: int) -> str: 
    #SP uses base64 of draw number in ?sppl=
    raw = f"DrawNumber={draw_no}".encode("utf-8")
    return base64.b64encode(raw).decode("utf-8")

def fetch_page(draw_no: Optional[int] = None)-> str:
    if draw_no is None:
        url = SP_RESULTS_URL
    else:
        url = f"{SP_RESULTS_URL}?sppl={_b64_draw(draw_no)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TotoBot/1.0; +https://github.com/your-repo)"
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.text

def parse_latest_draw_no(html: str) -> Optional[int]:
    m = DRAW_NO_RE.search(html)
    return int(m.group(1)) if m else None

def parse_next_jackpot_amount(html: str) -> Optional[int]:
    m = NEXT_JACKPOT_RE.search(html)
    if not m:
        return None
    amt = int(m.group(1).replace(",", ""))
    return amt

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