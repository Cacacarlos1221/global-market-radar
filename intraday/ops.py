"""LaunchAgent operations for the local GMR radar."""
import argparse
import base64
import datetime as dt
import hashlib
import html
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import re
import shutil
import subprocess
import time
from urllib.parse import quote, urlsplit

import radar

RECORD = re.compile(r"\d{4}-\d{2}-\d{2}_(?:1430|1445)\.json")
REPO = re.compile(r"[\w.-]+/global-market-radar-data", re.ASCII)
MANIFEST = "intraday/sync.json"


def cached(path):
    try:
        result = json.loads(path.read_text())
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def age(value, t):
    try:
        return (t - dt.datetime.fromisoformat(value).replace(tzinfo=radar.TZ)).total_seconds()
    except (ValueError, TypeError):
        return float("inf")


def trading_day(t):
    calendar = cached(radar.HOME / "calendar.json")
    day = t.date().isoformat()
    if t.weekday() >= 5:
        return False
    if calendar.get("checked") == day:
        return day in calendar.get("dates", [])
    return None


def status(t):
    tick = cached(radar.HOME / "heartbeat.json")
    snapshot = cached(radar.OUT / "latest.json")
    phase = radar.session(t)
    expected = trading_day(t)
    if (radar.HOME / "paused").exists():
        state = "paused"
    elif expected is False or phase == "idle":
        state = "closed"
    elif age(tick.get("time"), t) > 150 or tick.get("result") == "failed":
        state = "interrupted"
    elif expected is None:
        state = "calendar_pending"
    elif phase == "preopen":
        state = "preopen"
    elif snapshot.get("phase") == "historical" or age(snapshot.get("generated_at"), t) > 180:
        state = "stale"
    elif not any(x.get("status") == "ok" for x in snapshot.get("stocks", [])):
        state = "interrupted"
    else:
        state = "live" if phase == "open" else "closing"
    space = shutil.disk_usage(radar.HOME)
    return {"time": radar.stamp(t), "state": state, "phase": phase, "snapshot_phase": snapshot.get("phase"),
            "snapshot_time": snapshot.get("generated_at"), "market_day": snapshot.get("market_day"),
            "last_tick": tick.get("time"), "free_bytes": space.free, "low_disk": space.free < 5 * 1024**3,
            "last_sync": cached(radar.HOME / "last_sync.json").get("time"),
            "sync_error": cached(radar.HOME / "sync_error.json").get("error")}


LABELS = {"paused":"采集已暂停", "closed":"休市／非采集时段", "interrupted":"采集中断",
          "calendar_pending":"等待确认交易日历", "preopen":"盘前准备", "stale":"数据已过期",
          "live":"盘中采集", "closing":"收盘补采"}


def record_files(kind):
    return sorted((p for p in (radar.OUT / kind).glob("*.json")
                   if RECORD.fullmatch(p.name) and p.is_file() and not p.is_symlink()), reverse=True)


def dashboard():
    state = status(radar.now())
    display = LABELS[state["state"]]
    if state["snapshot_phase"] == "historical":
        display += " · 当前表格为历史验收快照"
    elif state["state"] == "closed" and state["snapshot_time"]:
        display += " · 当前表格为最近一次快照"
    if state["low_disk"]:
        display += " · 磁盘可用空间低于 5 GiB"
    details = [f'<p role="status"><strong>{html.escape(display)}</strong></p>',
               '<p><a href="/status.json">系统状态</a> · <a href="/latest.json">行情 JSON</a></p>']
    for kind, label in (("signals", "尾盘信号"), ("evaluation", "次日评估")):
        links = "".join(f'<li><a href="/{kind}/{p.name}">{p.stem}</a></li>' for p in record_files(kind)[:20])
        details.append(f"<section><h2>{label}</h2>" + (f"<ul>{links}</ul>" if links else "<p>暂无记录。</p>") + "</section>")
    page = radar.OUT / "index.html"
    if page.is_file():
        source = page.read_text()
    else:
        source = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="60"><h1>GMR 自选股雷达</h1><p>等待首个行情快照。</p></html>'
    source = re.sub(r'<p id="freshness".*?</script>', "", source, count=1, flags=re.S)
    banner = details.pop(0)
    if "</h1>" in source:
        source = source.replace("</h1>", "</h1>" + banner, 1)
    else:
        source = banner + source
    return source.replace("</html>", "".join(details) + "</html>").encode()


class WebHandler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(2)
        super().setup()

    def log_message(self, *args):
        pass

    def do_HEAD(self):
        self.serve(False)

    def do_GET(self):
        self.serve(True)

    def serve(self, body):
        path = urlsplit(self.path).path
        mime = "application/json"
        if path in ("/", "/index.html"):
            content, mime = dashboard(), "text/html; charset=utf-8"
        elif path == "/status.json":
            content = json.dumps(status(radar.now()), ensure_ascii=False).encode()
        else:
            file = radar.OUT / "latest.json" if path == "/latest.json" else None
            match = re.fullmatch(r"/(signals|evaluation)/([^/]+)", path)
            if match and RECORD.fullmatch(match[2]):
                file = radar.OUT / match[1] / match[2]
            if file is None or file.is_symlink() or not file.is_file():
                self.send_error(404)
                return
            content = file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if body:
            self.wfile.write(content)


def awake_window(t):
    minute = t.hour * 60 + t.minute
    if t.weekday() >= 5 or not 553 <= minute < 911 or (radar.HOME / "paused").exists():
        return False
    confirmed = trading_day(t)
    if confirmed is not None:
        return confirmed
    # Bridge the scheduled 09:13 wake until the collector refreshes today's
    # calendar. This reads only the recent calendar and starts no market requests.
    calendar = cached(radar.HOME / "calendar.json")
    try:
        checked = dt.date.fromisoformat(calendar["checked"])
    except (KeyError, TypeError, ValueError):
        return False
    return minute < 557 and 0 <= (t.date() - checked).days <= 7 and t.date().isoformat() in calendar.get("dates", [])


def keep_awake():
    if not awake_window(radar.now()):
        return
    # caffeinate releases on controller exit, including an unexpected exit.
    command = ["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())]
    with subprocess.Popen(command) as assertion:
        try:
            while assertion.poll() is None and awake_window(radar.now()):
                time.sleep(5)
        finally:
            if assertion.poll() is None:
                assertion.terminate()


def gh(*args, data=None):
    command = ["gh", *args]
    if data is not None:
        command += ["--input", "-"]
    try:
        return json.loads(subprocess.check_output(
            command, input=None if data is None else json.dumps(data), text=True,
            stderr=subprocess.DEVNULL, timeout=9,
        ))
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise RuntimeError(f"GitHub request failed ({type(exc).__name__})") from exc


def read_at(repo, path, revision):
    query = """query($owner:String!, $name:String!, $expression:String!) {
      repository(owner:$owner,name:$name){object(expression:$expression){... on Blob{text byteSize}}}
    }"""
    owner, name = repo.split("/")
    reply = gh("api", "graphql", data={"query":query, "variables":{
        "owner":owner, "name":name, "expression":f"{revision}:{path}"}})
    blob = reply["data"]["repository"]["object"]
    if blob is None:
        return {}
    if blob["byteSize"] > 1_000_000:
        raise ValueError("remote JSON exceeds size limit")
    data = json.loads(blob["text"])
    if not isinstance(data, dict):
        raise ValueError("remote JSON must be an object")
    return data


def critical_key(t, snapshot):
    day = t.date().isoformat()
    files = [p.stem for p in record_files("signals") if p.stem.startswith(day + "_")]
    if snapshot.get("market_day") == day and snapshot.get("phase") == "close":
        files.append(day + ("_final" if t.strftime("%H:%M") >= "15:11" else "_close"))
        files.extend("eval_" + p.stem for p in record_files("evaluation")
                     if time.time() - p.stat().st_mtime < 900)
    return files


def upload_files(t):
    data = {f"intraday/{kind}/{p.name}": p.read_bytes()
            for kind in ("signals", "evaluation") for p in record_files(kind)}
    latest = radar.OUT / "latest.json"
    if latest.exists() and not latest.is_symlink():
        data["intraday/latest.json"] = latest.read_bytes()
    state = status(t)
    state.update(last_sync=radar.stamp(t), sync_error=None)
    data["intraday/status.json"] = json.dumps(state, ensure_ascii=False).encode()
    return data


def upload(repo, branch, head, files, receipt, keys, t):
    previous = receipt.get("hashes", {})
    changed = {path: data for path, data in files.items()
               if hashlib.sha256(data).hexdigest() != previous.get(path)}
    # Send bounded batches. Remaining history is picked up on the next tick.
    backlog = [name for name in changed if name not in ("intraday/latest.json", "intraday/status.json")]
    for path in backlog[30:]:
        changed.pop(path)
    hashes = {**previous, **{name: hashlib.sha256(data).hexdigest() for name, data in changed.items()}}
    result = {"time": radar.stamp(t), "critical": keys, "hashes": hashes, "pending": max(0, len(backlog)-30)}
    changed[MANIFEST] = json.dumps(result, sort_keys=True).encode()
    mutation = """mutation($input:CreateCommitOnBranchInput!) {
      createCommitOnBranch(input:$input){commit{oid}}
    }"""
    reply = gh("api", "graphql", data={"query":mutation, "variables":{"input":{
        "branch":{"repositoryNameWithOwner":repo,"branchName":branch},
        "expectedHeadOid":head, "message":{"headline":"Update GMR research snapshot"},
        "fileChanges":{"additions":[{"path":path, "contents":base64.b64encode(data).decode()}
                                    for path, data in changed.items()]},
    }}})
    result["commit"] = reply["data"]["createCommitOnBranch"]["commit"]["oid"]
    radar.atomic(radar.HOME / "last_sync.json", result)


def sync(force=False):
    cfg = radar.load_config()
    config = cfg.get("sync", {})
    remote_enabled = cfg.get("remote_watchlist", False) is True
    allowed = config.get("enabled") is True and config.get("data_license_confirmed") is True
    if force and not allowed:
        raise ValueError("enable private sync and confirm the data license first")
    if not remote_enabled and not allowed:
        return
    t = radar.now()
    snapshot = cached(radar.OUT / "latest.json")
    keys = critical_key(t, snapshot)
    local = cached(radar.HOME / "last_sync.json")
    error = cached(radar.HOME / "sync_error.json")
    pending = local.get("pending", 0) or error.get("upload_failed", False)
    active = trading_day(t) is True and radar.session(t) != "idle"
    if not force and age(error.get("time"), t) < min(300, 60 * error.get("failures", 0)):
        return
    final_pending = (snapshot.get("phase") == "close" and snapshot.get("market_day") == t.date().isoformat()
                     and keys != local.get("critical") and t.strftime("%H:%M") <= "16:00")
    ready = allowed and (force or ((active or pending or final_pending) and (
        pending or age(local.get("time"), t) >= 300 or keys != local.get("critical"))))
    if not ready and (not remote_enabled or age(cached(radar.HOME / "watchlist_poll.json").get("time"), t) < 300):
        return
    repo = config.get("repository", "")
    if not REPO.fullmatch(repo):
        raise ValueError("configure an independent global-market-radar-data repository")
    try:
        info = gh("api", f"repos/{repo}")
        if info.get("visibility") != "private" or info["full_name"].lower() != repo.lower():
            raise ValueError("data repository must be private")
        branch = info["default_branch"]
        head = gh("api", f"repos/{repo}/branches/{quote(branch, safe='')}")["commit"]["sha"]
        if remote_enabled and age(cached(radar.HOME / "watchlist_poll.json").get("time"), t) >= 300:
            try:
                incoming = read_at(repo, "config/watchlist.json", head)
                if incoming:
                    stocks = radar.validate_stocks(incoming["stocks"])
                    radar.atomic(radar.HOME / "remote_stocks.json", {"stocks": stocks})
            except (RuntimeError, ValueError, KeyError, TypeError) as exc:
                radar.atomic(radar.HOME / "watchlist_error.json", {"time": radar.stamp(t), "error": type(exc).__name__})
            else:
                (radar.HOME / "watchlist_error.json").unlink(missing_ok=True)
            radar.atomic(radar.HOME / "watchlist_poll.json", {"time": radar.stamp(t)})
        if ready:
            receipt = read_at(repo, MANIFEST, head)
            if force or receipt.get("pending") or age(receipt.get("time"), t) >= 300 or keys != receipt.get("critical"):
                upload(repo, branch, head, upload_files(t), receipt, keys, t)
            elif receipt:
                radar.atomic(radar.HOME / "last_sync.json", receipt)
        (radar.HOME / "sync_error.json").unlink(missing_ok=True)
    except (RuntimeError, ValueError, KeyError) as exc:
        radar.atomic(radar.HOME / "sync_error.json", {
            "time": radar.stamp(t), "error": type(exc).__name__, "upload_failed": bool(ready),
            "failures": error.get("failures", 0) + 1})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["web", "awake"])
    action = parser.parse_args().action
    if action == "web":
        with HTTPServer(("127.0.0.1", 18773), WebHandler) as server:
            server.serve_forever()
    else:
        keep_awake()
