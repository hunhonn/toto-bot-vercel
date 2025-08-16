# toto-bot-vercel

Minimal serverless TOTO watcher deployed on Vercel (Python).

Features
- Scrapes Singapore Pools TOTO results page to get:
  - Latest draw number
  - Next jackpot estimate
  - Whether upcoming draw is a cascade (3 consecutive Group 1 rollovers)
- Conditional Telegram alert when:
  - next_jackpot > JACKPOT_THRESHOLD (default 10,000,000), OR
  - Cascade draw detected
- Time gating: Only processes after official cutoff:
  - Monday / Thursday ≥ 18:40 SGT
  - (Cascade Friday) ≥ 21:30 SGT
  - Otherwise returns {"skipped": true}
- Daily cron (12:00 UTC ≈ 20:00 SGT) auto-hits /api/check

API
GET /api/check
Responses:
- {"skipped": true}
- {
    "latest_draw_no": <int|null>,
    "next_jackpot": <int|null>,
    "cascade_next_draw": <bool>,
    "threshold": <int>
  }
- {"error": "..."} on failure

Environment Variables
TELEGRAM_TOKEN  Bot token (omit to disable alerts)
CHAT_ID         Target chat/channel ID
JACKPOT_THRESHOLD  Override jackpot alert threshold (int)

Deployment (CLI)
npm i -g vercel
vercel link (select existing project)
vercel --prod

On push to main (if linked) production redeploys automatically.

Dependencies
Listed in requirements.txt (requests, pytz). Vercel auto-installs.

Cron (vercel.json)
Runs /api/check daily at 12:00 UTC. Additional manual hits after cutoff are fine.

Notes
- Telegram send skipped silently if TELEGRAM_TOKEN or CHAT_ID unset.
- Cascade detection: fetches latest 3 draws; if any had a Group 1 winner, cascade_next_draw = false.