# GMR Watchlist Radar — Mac mini MVP

Independent from main morning/close workflows. No Docker, GPU, paid API or broker. All times Asia/Shanghai. Default public watchlist contains 13 starter symbols. Personal config stays outside Git. Start with 13, scale to 20–50 only after live tests.

## Install (logged-in Mac)
Python 3.10+ and Git required.
```bash
mkdir -p ~/Projects
cd ~/Projects
git clone -b feature/intraday-radar https://github.com/Cacacarlos1221/global-market-radar.git gmr-intraday
cd gmr-intraday/intraday
bash install_mac.sh
```
Script creates venv, copies starter watchlist to ~/GMRData/watchlist.json only if absent, runs offline tests and last completed session live probe. LaunchAgent installed only if both pass. No API key. Dependency ranges not locked yet.

## Controls
```bash
cd ~/Projects/gmr-intraday/intraday
export GMR_CONFIG="$HOME/GMRData/watchlist.json"
.venv/bin/python radar.py status
.venv/bin/python radar.py pause
.venv/bin/python radar.py resume
.venv/bin/python radar.py probe
.venv/bin/python radar.py history  # label the latest completed session as historical
launchctl print "gui/$(id -u)/com.gmr.intraday"
open "$HOME/GMRData/output/index.html"
tail -n 40 "$HOME/GMRData/logs/stderr.log"
```
Edit ~/GMRData/watchlist.json; reloaded each tick, no restart. Removed codes retain history. Page refreshes every 60s and labels old or historical snapshots. Private remote browser needs separate Tailscale setup. No publicly exposed ports.

## Sessions & resource limits
LaunchAgent every 60s exits before AKShare import outside sessions. Calendar from AKShare/Sina; fail closed if stale. 09:15–09:30 calendar checks only (no auction quotes yet). Regular minutes 09:31–11:30 and 13:01–15:00; 15:01–15:10 catch-up/evaluation. Two workers max, one BLAS thread, nice=10, low priority I/O, 50s hard subprocess timeout. Slow endpoint can cause incomplete coverage; rotate ordering to reduce starvation. Logged-in account and awake system required. Sleep suspends sampling and may coalesce launchd ticks on wake. Missed signal windows are left empty. The tick retains one rotated copy of each 1 MiB service log.

## Storage and metrics
SQLite WAL at ~/GMRData/market.sqlite, unique code+timestamp, upsert. No raw bars in Git. The default provider is AKShare/Eastmoney. Set `"provider": "sina"` at the top level of the local watchlist to use AKShare/Sina. Both use unadjusted 1-minute bars and keep provider provenance in SQLite. Eastmoney volume is converted from lots to shares. Sina reports shares. Amount is in CNY. Sina labels bars at the end of the interval and returns the close auction in the 15:00 bar, with no separate 14:58 or 14:59 bars. Other missing minutes are flagged. Use `history` to backfill up to five sessions and publish a historical snapshot without creating signal or evaluation records. The live collector uses a conservative one-minute delay. The close cycle makes an integrity-checked SQLite backup and retains seven copies. Prior close uses previous 15:00 minute; corporate actions not corrected; auction excluded from VWAP; gaps disable metrics. Relative volume needs three complete previous same-time days. Frozen signals are stored in DB even if source bars subsequently corrected.

Experimental score 0–5: positive return, above VWAP, relative volume >=1.2, giveback <=35%, positive 15m return. Score >=4 top5; one freeze per 14:30–14:34 and 14:45–14:49 window, actual generated timestamp recorded. No sector rotation, budget filters, ST/limit checks, fees or ML yet. Next session gross hypothetical open/close/MFE/MAE from subsequent bar open, not real fill; no fees/slippage/limit checks. Incomplete results missing and retried, not zero. MFE is not realized P&L. No claimed historical strategy performance.

## Phase 2 operations

On an existing installation, generate plists without reinstalling dependencies or changing the database.

```bash
cd ~/Projects/gmr-intraday/intraday
.venv/bin/python deploy_agents.py
for label in com.gmr.intraday com.gmr.intraday.awake com.gmr.intraday.web com.gmr.intraday.sync; do
  launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1 ||
    launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/$label.plist"
done
```

The agents launch at login. The collector and sync launcher tick once per minute. The local terminal is at `http://127.0.0.1:18773/`. It reports the current service state alongside the snapshot's original date, and exposes only the radar outputs and service status. It shows a disk alert below 5 GiB free. For private HTTPS, sign in to Tailscale on the Mac and authorized clients, check existing routes with `tailscale serve status`, then use `tailscale serve --bg http://127.0.0.1:18773` on an unused Serve endpoint. Observe the printed tailnet URL. The Mac must be awake, connected and logged in.

The awake agent checks the current day's confirmed exchange calendar and uses a temporary idle-sleep assertion during the 09:13–15:10 Beijing trading-day operating window. Collection stops at lunch; the assertion bridges the midday break so the computer is awake for the afternoon session. It releases after close and on pause. This cannot wake an already sleeping machine. With the owner's approval and macOS set to Beijing time, a weekday 09:13 wake can be scheduled using `sudo pmset repeat wakeorpoweron MTWRF 09:13:00`. Check `pmset -g sched` first because a repeating rule replaces an existing repeating schedule. Check assertions with `pmset -g assertions`. System wake and login are separate.

## GitHub data synchronization

Initialize a separate private `global-market-radar-data` repository with a README and authenticate `gh` for the current Mac user. In the local watchlist set `sync.repository` to its full owner/name. Once permission to transfer the research data is confirmed, set `sync.enabled` and `sync.data_license_confirmed` to `true`. Verify with `GMR_CONFIG="$HOME/GMRData/watchlist.json" .venv/bin/python radar.py sync-now`.

The sync job checks repository visibility and commits only the latest generated JSON, system status, signals and evaluations. Ordinary session updates run every five minutes, with priority for new signals, evaluations and the closing snapshot. Upload retries back off to five minutes. The remote receipt and parent-SHA check support retries and concurrent watchlist editing. Read the most recent successful time from `~/GMRData/last_sync.json` or the private terminal. GitHub credentials stay in the authenticated CLI environment.

For remote watchlist updates, set local `remote_watchlist` to `true` and edit `config/watchlist.json` in the private repository's default branch. The JSON accepts a `stocks` array with `code` and `name` pairs. The collector reloads the last validated remote list without changing the local provider, runtime parameters or sync options. Toggle `remote_watchlist` off to use the local list immediately.

The GitHub Pages route `reports/intraday/index.html` reads only the manually reviewed text in `reports/intraday/approved-summary.json`. The allowed text fields are `market`, `metrics`, `candidates`, `evaluation`, `updated` and `status`. The morning pipeline preserves the homepage link when it regenerates the page.

## Acceptance
- Offline unit tests, live probe, compare sample price/volume to broker.
- 13 stocks, check coverage and latency, then 20–50 gradually.
- Activity Monitor CPU, memory pressure, swap, Dota 2 frame rate; no measured performance claim yet.
- Freeze actual signal time, verify next-day outcome, restart/interruptions, optional private sync.
- Before merge add sector/benchmark features, tradeability and budget filters, fees, richer tests and authorized web display.

Stop and reload the scheduler with the local configuration and database in place.
```bash
launchctl bootout "gui/$(id -u)/com.gmr.intraday"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.gmr.intraday.plist"
```
