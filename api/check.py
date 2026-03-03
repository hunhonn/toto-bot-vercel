import json
import os
import requests
import hashlib
import time
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
import pytz

from ._shared import fetch_page, parse_latest_draw_no, parse_next_jackpot_amount, is_next_draw_cascade

SGT = pytz.timezone("Asia/Singapore")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN","")
CHAT_ID = os.environ.get("CHAT_ID","")
JACKPOT_THRESHOLD = int(os.environ.get("JACKPOT_THRESHOLD", "9999999"))
TEST_KEY = os.environ.get("TEST_KEY","")
ALERT_STATE_FILE = os.environ.get("ALERT_STATE_FILE", "/tmp/toto_last_alert.json")

def _load_last_alert_signature() -> str:
    try:
        with open(ALERT_STATE_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            return str(payload.get("signature", ""))
    except Exception:
        return ""
    return ""

def _save_last_alert_signature(signature: str) -> None:
    try:
        with open(ALERT_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"signature": signature, "saved_at": datetime.now(SGT).isoformat()}, f)
    except Exception as e:
        print("Alert state save failed:", repr(e))

def _build_alert_signature(latest_draw_no, next_jackpot, cascade_next) -> str:
    payload = {
        "draw_no": latest_draw_no,
        "jackpot": next_jackpot,
        "cascade": bool(cascade_next),
        "threshold": JACKPOT_THRESHOLD,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def send_telegram(text: str) -> bool:
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    for attempt in range(3):
        try:
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code < 300:
                return True
            retryable = r.status_code in (429, 500, 502, 503, 504)
            print("Telegram failed", r.status_code, r.text)
            if not retryable or attempt == 2:
                return False
        except requests.RequestException as e:
            print("Telegram exception:", repr(e))
            if attempt == 2:
                return False
        time.sleep(0.6 * (2 ** attempt))
    return False

def is_draw_day_and_time(now_sgt: datetime, cascade_next: bool) -> bool:
    weekday = now_sgt.weekday()  # Monday=0 ... Sunday=6
    hour, minute = now_sgt.hour, now_sgt.minute

    # Default draw cutoff: 18:40 (6:40pm)
    cutoff_hour, cutoff_min = 18, 40

    # First Wednesday of month → cutoff at 19:40
    if weekday == 2 and now_sgt.day <= 7:  # Wednesday (2)
        cutoff_hour, cutoff_min = 19, 40

    # Normal TOTO draws: Mon (0), Thu (3)
    if weekday in (0, 3):
        return (hour > cutoff_hour or (hour == cutoff_hour and minute >= cutoff_min))

    # Cascade case: Friday (4) → draw at 21:30 instead of Thu
    if weekday == 4 and cascade_next:
        return (hour > 21 or (hour == 21 and minute >= 30))

    # Other lottery draws (Wed, Sat, Sun are 4D, not TOTO)
    return False

def get_next_draw_datetime(now_sgt: datetime, cascade_next: bool) -> datetime:
    # TOTO schedule used by this bot:
    # - Monday 18:40 SGT
    # - Thursday 18:40 SGT (normal)
    # - Friday 21:30 SGT (cascade)
    target_weekdays = [0, 4] if cascade_next else [0, 3]
    target_hour, target_minute = (21, 30) if cascade_next else (18, 40)

    for day_offset in range(0, 8):
        candidate_day = now_sgt + timedelta(days=day_offset)
        if candidate_day.weekday() not in target_weekdays:
            continue
        candidate_dt = candidate_day.replace(
            hour=target_hour,
            minute=target_minute,
            second=0,
            microsecond=0,
        )
        if candidate_dt > now_sgt:
            return candidate_dt

    # Fallback (should never happen): 7 days from now at target time
    return (now_sgt + timedelta(days=7)).replace(
        hour=target_hour,
        minute=target_minute,
        second=0,
        microsecond=0,
    )

def format_next_draw_label(next_draw_dt: datetime, cascade_next: bool) -> str:
    draw_type = "Cascade Draw" if cascade_next else "Normal Draw"
    return f"{next_draw_dt.strftime('%a, %d %b %Y, %I:%M %p')} SGT ({draw_type})"

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Optional dry run: /api/check?dry=1
        try:
            qs = parse_qs(urlparse(self.path).query)
            def allowed_test():
                return TEST_KEY and qs.get("key", [""])[0] == TEST_KEY

            # Quick Telegram test (no scraping, no time gating)
            if "test_telegram" in qs and allowed_test():
                ok = send_telegram("🔔 Toto bot test alert from Vercel production.")
                body = json.dumps({"test_telegram": True, "sent": ok}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            # 1) Get latest results page
            html = fetch_page()
            latest_draw_no = parse_latest_draw_no(html)
            next_jackpot = parse_next_jackpot_amount(html)

            # 2) Infer cascade for the NEXT draw
            cascade_next = False
            if latest_draw_no is not None:
                try:
                    cascade_next = is_next_draw_cascade(latest_draw_no)
                except Exception:
                    cascade_next = False

            # Allow bypass of time gate for testing
            bypass = allowed_test() and qs.get("bypass", ["0"])[0] == "1"

            # 3) Check draw day & time BEFORE doing anything else
            now_sgt = datetime.now(SGT)
            next_draw_dt = get_next_draw_datetime(now_sgt, cascade_next)
            next_draw_label = format_next_draw_label(next_draw_dt, cascade_next)
            if not bypass and not is_draw_day_and_time(now_sgt, cascade_next):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                body = json.dumps({
                    "skipped": True,
                    "next_draw_at_sgt": next_draw_label,
                    "cascade_next_draw": cascade_next,
                }).encode("utf-8")
                self.wfile.write(body)
                return

            # 4) Build result + decide whether to send Telegram
            result = {
                "latest_draw_no": latest_draw_no,
                "next_jackpot": next_jackpot,
                "cascade_next_draw": cascade_next,
                "next_draw_at_sgt": next_draw_label,
                "threshold": JACKPOT_THRESHOLD,
                "env": os.environ.get("VERCEL_ENV"),
            }
            alerted = False
            deduped = False
            should_alert = (next_jackpot and next_jackpot > JACKPOT_THRESHOLD) or cascade_next
            if should_alert:
                signature = _build_alert_signature(latest_draw_no, next_jackpot, cascade_next)
                last_signature = _load_last_alert_signature()
                if signature == last_signature:
                    deduped = True
                else:
                    lines = []
                    if next_jackpot and next_jackpot > JACKPOT_THRESHOLD:
                        lines.append(f"💰 TOTO jackpot exceeds S$10M — est: S${next_jackpot:,}")
                    if cascade_next:
                        lines.append("⚠️ Next draw is a Cascade Draw.")
                    lines.append(f"Next draw: {next_draw_label}")
                    if send_telegram("\n".join(lines)):
                        alerted = True
                        _save_last_alert_signature(signature)
            result["alerted"] = alerted
            result["deduped"] = deduped
            result["has_token"] = bool(TELEGRAM_TOKEN)
            result["has_chat_id"] = bool(CHAT_ID)

            # 5) Respond with JSON as usual
            body = json.dumps(result).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        except Exception as e:
            msg = {"error": str(e)}
            body = json.dumps(msg).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)