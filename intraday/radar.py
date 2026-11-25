"""GMR watchlist radar: isolated, CPU-only, local research. All times Asia/Shanghai."""
import argparse
import concurrent.futures as cf
import datetime as dt
import fcntl
import html
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import statistics
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
ROOT = Path(__file__).resolve().parent
HOME = Path(os.environ.get("GMR_DATA_DIR", str(Path.home() / "GMRData"))).expanduser()
CONFIG = Path(os.environ.get("GMR_CONFIG", str(ROOT / "watchlist.json")))
OUT = HOME / "output"
SCHEMA = """CREATE TABLE IF NOT EXISTS bars(
code TEXT, ts TEXT, open REAL, high REAL, low REAL, close REAL,
shares REAL, amount REAL, observed_at TEXT, PRIMARY KEY(code,ts));
CREATE TABLE IF NOT EXISTS signals(
day TEXT, slot TEXT, payload TEXT, PRIMARY KEY(day,slot));
CREATE TABLE IF NOT EXISTS evaluations(
day TEXT, slot TEXT, payload TEXT, PRIMARY KEY(day,slot));"""

def now():
    return dt.datetime.now(TZ)

def stamp(t):
    return t.strftime("%Y-%m-%d %H:%M:%S")

def atomic(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(path)

def load_config():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    stocks = cfg["stocks"]
    codes = [s["code"] for s in stocks]
    if not codes or len(codes) > 100 or len(set(codes)) != len(codes):
        raise ValueError("watchlist: 1–100 distinct codes")
    if any(not re.fullmatch(r"(?:[036]\d{5})", c) for c in codes):
        raise ValueError("MVP supports Shanghai/Shenzhen A shares only")
    if not 1 <= int(cfg["workers"]) <= 2:
        raise ValueError("workers must be 1 or 2")
    return cfg

def db():
    HOME.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(HOME / "market.sqlite", timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn

def session(t):
    minute = t.hour * 60 + t.minute
    if 555 <= minute < 570:
        return "preopen"
    if 570 <= minute <= 690 or 780 <= minute <= 900:
        return "open"
    if 901 <= minute <= 910:
        return "close"
    return "idle"

def market_bar(ts):
    t = dt.datetime.fromisoformat(ts)
    m = t.hour * 60 + t.minute
    return t.second == 0 and (571 <= m <= 690 or 781 <= m <= 900)

def patch_timeout(seconds):
    import requests
    original = requests.sessions.Session.request
    def bounded(self, *args, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = seconds
        return original(self, *args, **kwargs)
    requests.sessions.Session.request = bounded

def calendar(ak, t):
    path = HOME / "calendar.json"
    today = t.date().isoformat()
    try:
        cached = json.loads(path.read_text())
        if cached["checked"] == today and max(cached["dates"]) >= today:
            return cached["dates"]
    except (OSError, ValueError, KeyError):
        pass
    df = ak.tool_trade_date_hist_sina()
    dates = sorted({str(x)[:10] for x in df["trade_date"]})
    if not dates or max(dates) < today:
        raise RuntimeError("exchange calendar does not cover today; no trading assumed")
    atomic(path, {"checked": today, "dates": dates})
    return dates

def normalize(code, records, cutoff, observed):
    result = []
    for r in records:
        try:
            ts = stamp(dt.datetime.fromisoformat(str(r["时间"])))
            if ts > cutoff or not market_bar(ts):
                continue
            o, h, l, c, v, a = [float(r[k]) for k in
                ("开盘", "最高", "最低", "收盘", "成交量", "成交额")]
            if not all(math.isfinite(x) for x in (o,h,l,c,v,a)):
                continue
            if min(o,h,l,c) <= 0 or l > min(o,c) or h < max(o,c) or v < 0 or a < 0:
                continue
            # Eastmoney stock minute volume is in lots (100 shares), amount in CNY.
            shares = v * 100
            if shares > 0 and not (l * .95 <= a / shares <= h * 1.05):
                continue  # refuse inconsistent volume/amount units
            if shares == 0 and a != 0:
                continue
            result.append((code,ts,o,h,l,c,shares,a,observed))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return result

def fetch(ak, code, start, cutoff):
    df = ak.stock_zh_a_hist_min_em(symbol=code, period="1", adjust="",
                                 start_date=start, end_date=cutoff)
    return normalize(code, df.to_dict("records"), cutoff, stamp(now()))

def save(conn, rows):
    conn.executemany("""INSERT INTO bars VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(code,ts) DO UPDATE SET open=excluded.open,high=excluded.high,
        low=excluded.low,close=excluded.close,shares=excluded.shares,
        amount=excluded.amount,observed_at=excluded.observed_at""", rows)
    conn.commit()

def day_rows(conn, code, day, cutoff="23:59:59"):
    return list(conn.execute("SELECT * FROM bars WHERE code=? AND ts BETWEEN ? AND ? ORDER BY ts",
        (code, day+" 00:00:00", day+" "+cutoff)))

def expected_times(end):
    return [f"{m//60:02d}:{m%60:02d}:00" for m in range(571,901)
            if (m<=690 or m>=781) and f"{m//60:02d}:{m%60:02d}:00" <= end]

def features(conn, stock, t, dates, cutoff):
    code = stock["code"]
    day = t.date().isoformat()
    rows = day_rows(conn, code, day, cutoff)
    info = {"code":code, "name":stock["name"], "status":"missing", "score":None}
    if not rows:
        return info
    last = rows[-1]
    end = last["ts"][11:]
    lag = (t - dt.datetime.fromisoformat(last["ts"]).replace(tzinfo=TZ)).total_seconds()
    expected = expected_times(end)
    complete = [r["ts"][11:] for r in rows] == expected
    vol = sum(r["shares"] for r in rows)
    amount = sum(r["amount"] for r in rows)
    price = last["close"]
    prior = [d for d in dates if d < day][-5:]
    prev = day_rows(conn,code,prior[-1]) if prior else []
    prev_close = prev[-1]["close"] if prev and prev[-1]["ts"].endswith("15:00:00") else None
    samples = []
    for d in prior:
        old = day_rows(conn,code,d,end)
        if [r["ts"][11:] for r in old] == expected:
            samples.append(sum(r["shares"] for r in old))
    vwap = amount / vol if vol and complete else None
    rel = vol / statistics.mean(samples) if complete and len(samples)>=3 and statistics.mean(samples)>0 else None
    peak = max(r["high"] for r in rows)
    ret = price/prev_close-1 if prev_close else None
    giveback = (peak-price)/(peak-prev_close) if prev_close and peak>prev_close else None
    momentum = price/rows[-16]["close"]-1 if complete and len(rows)>=16 else None
    stale = lag > 180 and not (session(t)=="close" and end=="15:00:00")
    status = "stale" if stale else ("ok" if complete else "incomplete")
    eligible = status=="ok" and all(x is not None for x in (ret,vwap,rel,giveback,momentum))
    # Experimental 0–5 score, not a calibrated probability or executable advice.
    score = sum([ret>0, price>vwap, rel>=1.2, giveback<=.35, momentum>0]) if eligible else None
    info.update(status=status, as_of=last["ts"], observed_at=last["observed_at"],
        price=price, change_pct=ret*100 if ret is not None else None,
        vwap=vwap, relative_volume=rel, baseline_days=len(samples),
        giveback=giveback, momentum_15_pct=momentum*100 if momentum is not None else None,
        shares=vol, amount=amount, minute_coverage=len(rows)/max(1,len(expected)), score=score)
    return info

def freeze(conn,t,items,errors):
    day=t.date().isoformat()
    hm=t.strftime("%H:%M")
    for slot,end in (("14:30","14:35"),("14:45","14:50")):
        if not slot <= hm < end:
            continue
        if conn.execute("SELECT 1 FROM signals WHERE day=? AND slot=?",(day,slot)).fetchone():
            continue
        # Freeze actual observation time, never pretend the delayed signal existed at slot.
        eligible=[x for x in items if x["score"] is not None and x["score"]>=4]
        eligible.sort(key=lambda x:(-x["score"],x["code"]))
        payload={"schema_version":1,"strategy":"watchlist_rules_v1","day":day,"slot":slot,
            "generated_at":stamp(t),"universe":items,"errors":errors,"candidates":eligible[:5],
            "warning":"research only; no live execution or limit-up/board permission checks"}
        conn.execute("INSERT INTO signals VALUES(?,?,?)",(day,slot,json.dumps(payload,ensure_ascii=False)))
        conn.commit()
        atomic(OUT/"signals"/f"{day}_{slot.replace(':','')}.json",payload)

def evaluate(conn,t,dates):
    today=t.date().isoformat()
    for sig in conn.execute("SELECT * FROM signals WHERE day<?",(today,)).fetchall():
        following=next((d for d in dates if d>sig["day"]),None)
        if following is None or following>today:
            continue
        if following==today and t.strftime("%H:%M")<"15:02":
            continue
        if conn.execute("SELECT 1 FROM evaluations WHERE day=? AND slot=?",(sig["day"],sig["slot"])).fetchone():
            continue
        payload=json.loads(sig["payload"])
        generated=dt.datetime.fromisoformat(payload["generated_at"])
        earliest=generated.replace(second=0,microsecond=0)+dt.timedelta(minutes=2)
        results=[]
        for c in payload["candidates"]:
            entry=[r for r in day_rows(conn,c["code"],sig["day"]) if r["ts"]>=stamp(earliest) and r["shares"]>0]
            nextday=day_rows(conn,c["code"],following)
            if not entry or [r["ts"][11:] for r in nextday]!=expected_times("15:00:00") or nextday[0]["shares"]<=0:
                results.append({"code":c["code"],"status":"missing_or_untradable"})
                continue
            buy=entry[0]["open"]
            results.append({"code":c["code"],"status":"hypothetical_gross","entry_bar":entry[0]["ts"],
                "entry_price":buy,"next_open_pct":(nextday[0]["open"]/buy-1)*100,
                "next_close_pct":(nextday[-1]["close"]/buy-1)*100,
                "mfe_pct":(max(r["high"] for r in nextday)/buy-1)*100,
                "mae_pct":(min(r["low"] for r in nextday)/buy-1)*100})
        out={"day":sig["day"],"slot":sig["slot"],"target_day":following,"evaluated_at":stamp(t),
            "results":results,"warning":"gross hypothetical bar-price returns; no fees, slippage, limit checks; MFE is not realizable return"}
        # Retry missing records later instead of treating missing as zero.
        atomic(OUT/"evaluation"/f"{sig['day']}_{sig['slot'].replace(':','')}.json",out)
        if all(r["status"]!="missing_or_untradable" for r in results):
            conn.execute("INSERT INTO evaluations VALUES(?,?,?)",(sig["day"],sig["slot"],json.dumps(out,ensure_ascii=False)))
            conn.commit()

def publish_local(payload):
    atomic(OUT/"latest.json",payload)
    rows=[]
    for s in sorted(payload["stocks"],key=lambda s:(s["score"] is None,-(s["score"] or 0),s["code"])):
        def show(key):
            x=s.get(key)
            return "—" if x is None else (f"{x:.2f}" if isinstance(x,float) else html.escape(str(x)))
        rows.append("<tr>"+"".join(f"<td>{show(k)}</td>" for k in
          ("code","name","status","as_of","price","change_pct","vwap","relative_volume","score"))+"</tr>")
    page="""<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GMR Watchlist Radar</title><meta http-equiv="refresh" content="60"><style>
body{font:15px system-ui;margin:24px;color:#17202a;background:#f6f8fa}table{border-collapse:collapse;background:white;width:100%}td,th{padding:10px;text-align:left;border-bottom:1px solid #ddd;white-space:nowrap}.table{overflow:auto}small{color:#666}</style>
<h1>GMR 自选股雷达</h1><p>更新时间（北京时间）："""+html.escape(payload["generated_at"])+"""</p>
<p>评分为实验规则；缺失或延迟数据不参加评分。仅供研究。页面每60秒刷新。</p><div class="table"><table>
<thead><tr><th>代码</th><th>名称</th><th>状态</th><th>行情时间</th><th>价格</th><th>涨跌幅%</th><th>VWAP</th><th>相对量比</th><th>评分/5</th></tr></thead><tbody>"""+''.join(rows)+"""</tbody></table></div></html>"""
    tmp=OUT/"index.html.tmp"
    tmp.write_text(page,encoding="utf-8")
    tmp.replace(OUT/"index.html")

def sync_private(cfg,t):
    s=cfg.get("sync",{})
    if not s.get("enabled"):
        return
    import shutil
    raw=s.get("private_repo_path")
    if not raw:
        raise ValueError("private_repo_path required")
    dest=Path(raw).expanduser().resolve()
    if dest==ROOT.parent.resolve() or not (dest/".git").exists():
        raise ValueError("sync requires a separate cloned private repository")
    env=dict(os.environ,GIT_TERMINAL_PROMPT="0",GH_PROMPT_DISABLED="1")
    def run(args):
        return subprocess.check_output(args,cwd=dest,env=env,text=True,stderr=subprocess.STDOUT,timeout=15).strip()
    remote=s.get("remote","origin")
    branch=s.get("branch","main")
    if run(["git","branch","--show-current"])!=branch or run(["git","status","--porcelain"]):
        raise RuntimeError("sync clone must be on configured branch and clean")
    url=run(["git","remote","get-url",remote])
    match=re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?",url)
    if not match or run(["gh","repo","view",match.group(1),"--json","visibility","--jq",".visibility"])!="PRIVATE":
        raise RuntimeError("refusing sync to unverified private GitHub repository")
    run(["git","pull","--ff-only",remote,branch])
    target=dest/"intraday"
    target.mkdir(exist_ok=True)
    paths=[]
    for source in [OUT/"latest.json",*sorted((OUT/"signals").glob("*.json")),*sorted((OUT/"evaluation").glob("*.json"))]:
        p=target/source.relative_to(OUT)
        p.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,p)
        paths.append(str(p.relative_to(dest)))
    run(["git","add","--",*paths])
    if run(["git","status","--porcelain"]):
        run(["git","commit","-m","intraday research snapshot "+stamp(t)])
    run(["git","push",remote,branch])

def cycle(probe=False):
    cfg=load_config()
    t=now()
    phase=session(t)
    if not probe and (t.weekday()>=5 or phase=="idle" or (HOME/"paused").exists()):
        return
    HOME.mkdir(parents=True,exist_ok=True)
    patch_timeout(float(cfg["request_timeout_seconds"]))
    import akshare as ak
    dates=calendar(ak,t)
    day=t.date().isoformat()
    if probe:
        sample_day=max(d for d in dates if d<day or (d==day and t.hour>=15))
        code=cfg["stocks"][0]["code"]
        rows=fetch(ak,code,sample_day+" 00:00:00",sample_day+" 15:00:00")
        if not rows:
            raise RuntimeError("probe returned no validated minutes; verify API / volume unit")
        print(json.dumps({"status":"ok","code":code,"sample_day":sample_day,"rows":len(rows),"last_bar":rows[-1][1]},ensure_ascii=False))
        return
    if day not in dates or phase=="preopen":
        return
    conn=db()
    cutoff=min(t.replace(second=0,microsecond=0)-dt.timedelta(minutes=1),
               t.replace(hour=15,minute=0,second=0,microsecond=0))
    cutoff_str=stamp(cutoff)
    stocks=cfg["stocks"]
    # Rotate each minute to avoid permanent starvation when endpoint is slow.
    offset=(t.hour*60+t.minute)*int(cfg["workers"])%len(stocks)
    stocks=stocks[offset:]+stocks[:offset]
    errors={}
    begin=time.monotonic()
    with cf.ThreadPoolExecutor(max_workers=int(cfg["workers"])) as pool:
        pending={}
        queue=iter(stocks)
        def submit():
            try:
                s=next(queue)
            except StopIteration:
                return False
            code=s["code"]
            last=conn.execute("SELECT MAX(ts) FROM bars WHERE code=?",(code,)).fetchone()[0]
            start=last[:10] if last else (t.date()-dt.timedelta(days=10)).isoformat()
            pending[pool.submit(fetch,ak,code,start+" 00:00:00",cutoff_str)]=code
            return True
        for _ in range(int(cfg["workers"])):
            submit()
        while pending:
            done,_=cf.wait(pending,timeout=1,return_when=cf.FIRST_COMPLETED)
            for f in done:
                code=pending.pop(f)
                try:
                    rows=f.result()
                    if not rows:
                        errors[code]="empty_or_invalid"
                    else:
                        save(conn,rows)
                except Exception as e:
                    errors[code]=type(e).__name__
                if time.monotonic()-begin<32:
                    submit()
            if time.monotonic()-begin>=32:
                for s in queue:
                    errors[s["code"]]="cycle_budget_exceeded"
    t=now()
    items=[features(conn,s,t,dates,cutoff_str[11:]) for s in cfg["stocks"]]
    freeze(conn,t,items,errors)
    if phase=="close":
        evaluate(conn,t,dates)
    publish_local({"schema_version":1,"generated_at":stamp(t),"phase":phase,"source":"akshare/eastmoney",
                   "stocks":items,"errors":errors,"watchlist_size":len(items)})
    conn.close()
    print(stamp(t), "quotes",len(items),"errors",len(errors),flush=True)

def tick():
    t=now()
    if t.weekday()>=5 or session(t)=="idle" or (HOME/"paused").exists():
        return
    HOME.mkdir(parents=True,exist_ok=True)
    with (HOME/"cycle.lock").open("w") as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return
        timeout=int(load_config()["cycle_timeout_seconds"])
        try:
            subprocess.run([sys.executable,__file__,"cycle"],timeout=timeout,check=True)
        except (subprocess.TimeoutExpired,subprocess.CalledProcessError) as e:
            print(stamp(now()),"cycle failed:",type(e).__name__,file=sys.stderr)
            return
        # Separate sync process and lock: do not delay the next acquisition tick.
        if load_config().get("sync",{}).get("enabled"):
            subprocess.Popen([sys.executable,__file__,"sync"],start_new_session=True,
                             stdout=sys.stdout,stderr=sys.stderr)

def sync_command():
    t=now()
    cfg=load_config()
    if not cfg.get("sync",{}).get("enabled") or not (OUT/"latest.json").exists():
        return
    with (HOME/"sync.lock").open("w") as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return
        last=HOME/"last_sync.json"
        try:
            prior=dt.datetime.fromisoformat(json.loads(last.read_text())["time"]).replace(tzinfo=TZ)
            if (t-prior).total_seconds()<int(cfg["sync_interval_minutes"])*60:
                return
        except (OSError,ValueError,KeyError):
            pass
        sync_private(cfg,t)
        atomic(last,{"time":stamp(t)})

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["tick","cycle","probe","sync","pause","resume","status"])
    action=parser.parse_args().action
    if action=="tick": tick()
    elif action=="cycle": cycle()
    elif action=="probe": cycle(probe=True)
    elif action=="sync": sync_command()
    elif action=="pause":
        HOME.mkdir(parents=True,exist_ok=True)
        (HOME/"paused").touch()
    elif action=="resume": (HOME/"paused").unlink(missing_ok=True)
    else:
        p=OUT/"latest.json"
        print(json.dumps({"data_dir":str(HOME),"config":str(CONFIG),"paused":(HOME/"paused").exists(),
            "last_snapshot":json.loads(p.read_text()).get("generated_at") if p.exists() else None,
            "session":session(now())},ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
