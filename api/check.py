import json
import os
import requests
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

def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code >= 300:
            print("Telegram failed", r.status_code, r.text)
    except Exception as e:
        print("Telegram exception:", repr(e))

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

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Optional dry run: /api/check?dry=1
        try:
            qs = parse_qs(urlparse(self.path).query)
            def allowed_test():
                return TEST_KEY and qs.get("key", [""])[0] == TEST_KEY

            # Quick Telegram test (no scraping, no time gating)
            if "test_telegram" in qs and allowed_test():
                send_telegram("🔔 Toto bot test alert from Vercel production.")
                body = json.dumps({"test_telegram": True}).encode("utf-8")
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
            if not bypass and not is_draw_day_and_time(now_sgt, cascade_next):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"skipped": true}')
                return

            # 4) Build result + decide whether to send Telegram
            result = {
                "latest_draw_no": latest_draw_no,
                "next_jackpot": next_jackpot,
                "cascade_next_draw": cascade_next,
                "threshold": JACKPOT_THRESHOLD,
                "env": os.environ.get("VERCEL_ENV"),
            }
            alerted = False
            should_alert = (next_jackpot and next_jackpot > JACKPOT_THRESHOLD) or cascade_next
            if should_alert:
                lines = []
                if next_jackpot and next_jackpot > JACKPOT_THRESHOLD:
                    lines.append(f"💰 TOTO jackpot exceeds S$10M — est: S${next_jackpot:,}")
                if cascade_next:
                    lines.append("⚠️ Next draw is a Cascade Draw.")
                try:
                    send_telegram("\n".join(lines))
                    alerted = True
                except Exception as alert_err:
                    print("Alert error:", repr(alert_err))
            result["alerted"] = alerted
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