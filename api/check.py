import json
import os
import requests
from http.server import BaseHTTPRequestHandler

from ._shared import fetch_page, parse_latest_draw_no, parse_next_jackpot_amount, is_next_draw_cascade

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN","")
CHAT_ID = os.environ.get("CHAT_ID","")
JACKPOT_THRESHOLD = int(os.environ.get("JACKPOT_THRESHOLD", "10000000"))

def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    url = f"https:api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": True
    }
    requests.post(url,json = payload, timeout=10)

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Optional dry run: /api/check?dry=1
        try:
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

            # 3) Build result
            result = {
                "latest_draw_no": latest_draw_no,
                "next_jackpot": next_jackpot,
                "cascade_next_draw": cascade_next,
                "threshold": JACKPOT_THRESHOLD,
            }

            # 4) Decide whether to notify
            # NOTE: This endpoint is stateless; it will notify every time the condition is true.
            # If you want "notify once per draw", wire in a KV/Redis key and remember the last notified draw.
            dry = ("?dry=1" in self.path) or ("&dry=1" in self.path)
            should_alert = (next_jackpot is not None and next_jackpot > JACKPOT_THRESHOLD) or cascade_next

            if should_alert and not dry:
                lines = []
                if next_jackpot is not None and next_jackpot > JACKPOT_THRESHOLD:
                    lines.append(f"💰 <b>TOTO jackpot exceeds S$10M</b> — est: <b>S${next_jackpot:,}</b>")
                if cascade_next:
                    lines.append("⚠️ <b>Next draw is a Cascade Draw</b> (after 3 consecutive no-winner draws).")
                if latest_draw_no:
                    lines.append(f"(Latest draw checked: #{latest_draw_no})")
                send_telegram("\n".join(lines))

            # 5) Respond JSON
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