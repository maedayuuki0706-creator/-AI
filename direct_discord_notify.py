"""Direct BOAT RACE official -> prediction engine -> Discord notifier.

No dependency on the ChatGPT Site API. The scheduled path is:
BOAT RACE official data -> local prediction_engine.py -> Discord webhook.
Every delivered prediction is also appended to data/prediction_log.jsonl so a
daily learner can compare it with official results later.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import html
import json
import os
from pathlib import Path
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from prediction_engine import analyze_race
from race_context import previous_form
import racer_profiles
import tide_context
from discord_formation import formation_summary, formation_lines
from discord_notification_policy import message_payload
from race_notices import withdrawal_lanes, notice_message, read_notices, record_notice

JST = ZoneInfo("Asia/Tokyo")
BASE = "https://www.boatrace.jp/owpc/pc/race"
UA = "Boat-AI-Navi/3.2 (+direct-discord-notifier)"
LOG_PATH = Path("data/prediction_log.jsonl")
VENUES = {
    "01":"桐生","02":"戸田","03":"江戸川","04":"平和島","05":"多摩川","06":"浜名湖",
    "07":"蒲郡","08":"常滑","09":"津","10":"三国","11":"びわこ","12":"住之江",
    "13":"尼崎","14":"鳴門","15":"丸亀","16":"児島","17":"宮島","18":"徳山",
    "19":"下関","20":"若松","21":"芦屋","22":"福岡","23":"唐津","24":"大村",
}


@lru_cache(maxsize=256)
def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja-JP,ja;q=0.9"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", errors="replace")


def textify(raw: str) -> str:
    raw = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<style\b[^>]*>.*?</style>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"</(?:td|th|tr|li|p|div|h[1-6])>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw).replace("\u3000", " ")
    raw = unicodedata.normalize("NFKC", raw)
    raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
    raw = re.sub(r"\n+", "\n", raw)
    return "\n".join(line.strip() for line in raw.splitlines() if line.strip())


def detect_event_grade(raw: str) -> str | None:
    """Detect the meeting grade from the official race page without using racer class labels."""
    upper = unicodedata.normalize("NFKC", raw).upper()
    if re.search(r'(?:IS-|GRADE[-_ ]?)G1\\b|G[Ⅰ１1]', upper):
        return "G1"
    if re.search(r'(?:IS-|GRADE[-_ ]?)G2\\b|G[Ⅱ２2]', upper):
        return "G2"
    if re.search(r'(?:IS-|GRADE[-_ ]?)G3\\b|G[Ⅲ３3]', upper):
        return "G3"
    return None


def official_url(kind: str, day: str, jcd: str | None = None, rno: int | None = None) -> str:
    q = {"hd": day}
    if jcd is not None:
        q["jcd"] = jcd
    if rno is not None:
        q["rno"] = str(rno)
    return f"{BASE}/{kind}?{urllib.parse.urlencode(q)}"


def discover_venues(day: str) -> list[str]:
    raw = fetch(official_url("index", day))
    found = re.findall(r"(?:\?|&amp;|&)jcd=(\d{2})", raw)
    return sorted({x for x in found if x in VENUES})


def deadlines(day: str, jcd: str) -> list[str]:
    text = textify(fetch(official_url("racelist", day, jcd, 1)))
    pos = text.find("締切予定時刻")
    if pos < 0:
        return []
    chunk = text[pos:pos + 900]
    times = re.findall(r"(?:[01]?\d|2[0-3]):[0-5]\d", chunk)
    out: list[str] = []
    for t in times:
        h, m = map(int, t.split(":"))
        norm = f"{h:02d}:{m:02d}"
        if norm not in out:
            out.append(norm)
        if len(out) == 12:
            break
    return out


def parse_racelist_boats(day: str, jcd: str, rno: int) -> list[dict]:
    raw = fetch(official_url("racelist", day, jcd, rno))
    boats = []
    for body in re.findall(r"<tbody\b[^>]*>(.*?)</tbody>", raw, re.I | re.S):
        lane_match = re.search(r'is-boatColor([1-6])', body)
        text = textify(body)
        registration = re.search(r"(\d{4})\s*/\s*(A1|A2|B1|B2)\b", text)
        if not lane_match or not registration:
            continue
        cells = re.findall(r'<td\b[^>]*>(.*?)</td>', body, re.I | re.S)
        if len(cells) < 8:
            return []
        start_text = textify(cells[3])
        fl = re.search(r"F\s*(\d+)\s*\nL\s*(\d+)\s*\n", start_text)
        if not fl:
            return []
        # Keep cell positions: a rookie's '-' average ST must not shift the
        # national win rate into ST and invalidate all six racers.
        vals = [start_text[fl.end():].strip()]
        for cell in cells[4:8]:
            values = textify(cell).splitlines()
            if len(values) != 3:
                return []
            vals.extend(values)
        if any(not re.fullmatch(r'(?:\d+(?:\.\d+)?|[-－―—])', value) for value in vals):
            return []
        nums = [float(value) if re.fullmatch(r'\d+(?:\.\d+)?', value) else None for value in vals]
        lane = int(lane_match[1])
        if not ((nums[0] is None or 0 <= nums[0] <= 1)
                and (nums[1] is None or 0 <= nums[1] <= 10)
                and all(nums[i] is None or 0 <= nums[i] <= 100 for i in (2,3,5,6,8,9))):
            return []
        boats.append({
            "lane": lane, "course": lane, "predicted_course": lane,
            "racer_id": registration[1], "name": re.sub(r"\s+", "", text[registration.end():].strip().split("\n")[0]),
            "avg_st": nums[0], "flying": int(fl[1]) > 0,
            "win_rate": nums[1], "top2_rate": nums[2], "top3_rate": nums[3],
            "local_win_rate": nums[4] if any(nums[4:7]) else None,
            "local_top2_rate": nums[5] if any(nums[4:7]) else None,
            "motor_number": int(nums[7]) if nums[7] is not None else None, "motor_top2_rate": nums[8], "motor_top3_rate": nums[9],
        })
    return sorted(boats, key=lambda x: x["lane"]) if {b["lane"] for b in boats} == set(range(1,7)) and len(boats)==6 else []


def parse_beforeinfo(raw: str) -> dict:
    result = {"boats": {}, "wind_speed": None, "wave_cm": None, "entry_observed": False}
    for body in re.findall(r"<tbody\b[^>]*>(.*?)</tbody>", raw, re.I | re.S):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", body, re.I | re.S)
        lane = re.search(r'is-boatColor([1-6])', body)
        if not lane or len(cells) < 6 or "kg" not in textify(cells[3]):
            continue
        item = {}
        for key, idx, lo, hi in (("exhibition_time",4,5,10),("tilt",5,-1,3)):
            try:
                value = float(textify(cells[idx]))
                if lo <= value <= hi:
                    item[key] = value
            except ValueError:
                pass
        result["boats"][int(lane[1])] = item
    starts = re.findall(r'table1_boatImage1Number[^>]*>\s*([1-6])\s*</span>.*?table1_boatImage1Time[^>]*>(.*?)</span>', raw, re.S)
    if len(starts)==6 and {int(lane) for lane,_ in starts}==set(range(1,7)):
        result["entry_observed"] = True
        for course,(lane,value) in enumerate(starts,1):
            item = result["boats"].setdefault(int(lane),{})
            item["predicted_course"] = course
            st = textify(value)
            item["exhibition_flying"] = st.startswith("F")
            if re.fullmatch(r"(?:0)?\.\d+",st):
                item["exhibition_st"] = float(st)
    text = textify(raw)
    for key,label,unit in (("wind_speed","風速","m"),("wave_cm","波高","cm")):
        match = re.search(label+r"\s+(\d+(?:\.\d+)?)"+unit,text)
        if match:
            result[key] = float(match[1])
    result["exhibition_count"] = sum("exhibition_time" in row for row in result["boats"].values())
    times = [row["exhibition_time"] for row in result["boats"].values() if "exhibition_time" in row]
    if len(times)==6:
        # Relative time only; missing turn/straight/pit grades remain unknown.
        average = sum(times)/6
        for row in result["boats"].values():
            row["exhibition_grade"] = max(0,min(1,.5+(average-row["exhibition_time"])*2))
    return result


def parse_odds(raw: str) -> dict:
    body = re.search(r'<tbody[^>]*class=["\'][^"\']*\bis-p3-0\b[^"\']*["\'][^>]*>(.*?)</tbody>', raw, re.I|re.S)
    if not body:
        return {}
    cells = re.findall(r'<td[^>]*class=["\'][^"\']*\boddsPoint\b[^"\']*["\'][^>]*>(.*?)</td>', body[1], re.I|re.S)
    if len(cells)!=120:
        return {}
    odds={}
    for row in range(20):
        for first in range(1,7):
            second=[n for n in range(1,7) if n!=first][row//4]
            third=[n for n in range(1,7) if n not in (first,second)][row%4]
            try:
                value=float(textify(cells[row*6+first-1]).replace(',',''))
                if 1 <= value < 1000000:
                    odds[f'{first}-{second}-{third}']=value
            except ValueError:
                pass
    return odds


def analyze_official(day: str, jcd: str, rno: int) -> dict | None:
    racelist_raw = fetch(official_url('racelist',day,jcd,rno))
    if withdrawal_lanes(racelist_raw):
        return None
    event_grade = detect_event_grade(racelist_raw)
    boats=parse_racelist_boats(day,jcd,rno)
    if len(boats)!=6:
        return None
    try:
        preview=parse_beforeinfo(fetch(official_url('beforeinfo',day,jcd,rno)))
    except Exception:
        preview={"boats":{},"exhibition_count":0,"entry_observed":False,"wind_speed":None,"wave_cm":None}
    try:
        odds=parse_odds(fetch(official_url('odds3t',day,jcd,rno)))
    except Exception:
        odds={}
    try:
        race_times = deadlines(day, jcd)
        race_hhmm = race_times[int(rno) - 1] if len(race_times) >= int(rno) else None
        preview["tide"] = tide_context.get_tide_context(day, jcd, race_hhmm)
    except Exception:
        preview["tide"] = {"applicable": False, "available": False, "status": "tide_context_error"}
    form=previous_form(day,jcd,boats)
    for boat in boats:
        boat.update(preview['boats'].get(boat['lane'],{}))
        # Persistent individual tendencies: actual-course history, course
        # strength, venue exposure, ST and winning-method profile.
        racer_profiles.apply_profile(boat, str(jcd).zfill(2))
        if boat['lane'] in form:
            boat['previous_day_score_delta']=form[boat['lane']]['score_delta']
    result=analyze_race({'race':{'venue':VENUES[jcd],'wind_speed':preview['wind_speed']},'boats':boats,'trifecta_odds':odds})
    heads={lane:sum(p['probability'] for p in result['trifecta'] if p['combination'].startswith(f'{lane}-')) for lane in range(1,7)}
    ranking=sorted(heads,key=heads.get,reverse=True)
    top,gap=heads[ranking[0]],heads[ranking[0]]-heads[ranking[1]]
    grade=None if preview['exhibition_count']<6 else 'A' if top>=.45 and gap>=.20 else 'B' if top>=.30 and gap>=.08 else 'C'
    result.update(inputs=boats,preview=preview,heads=heads,grade=grade,previous_form=form,
                  jcd=str(jcd).zfill(2),event_grade=event_grade,
                  balanced_head_mode=(str(jcd).zfill(2) == "05" and event_grade == "G1"))
    return result


def engine_picks(day: str, jcd: str, rno: int) -> tuple[list[str], float | None]:
    result=analyze_official(day,jcd,rno)
    return ([row['combination'] for row in result['trifecta'][:6]],result['confidence']) if result else ([],None)


def parse_focus(day: str, jcd: str, rno: int) -> list[str]:
    text = textify(fetch(official_url("pcexpect", day, jcd, rno)))
    start = text.find("予想フォーカス")
    if start < 0:
        return []
    end = text.find("この予想に対する自信度", start)
    block = text[start:end if end > start else start + 1200]
    picks: list[str] = []
    for a, op, b, c in re.findall(r"(?<!\d)([1-6])\s*([=-])\s*([1-6])\s*-\s*([1-6])(?!\d)", block):
        candidates = [f"{a}-{b}-{c}", f"{b}-{a}-{c}"] if op == "=" else [f"{a}-{b}-{c}"]
        for p in candidates:
            if len(set(p.split("-"))) == 3 and p not in picks:
                picks.append(p)
    for a, b, c in re.findall(r"(?<!\d)([1-6])\s*-\s*([1-6])\s*-\s*([1-6])(?!\d)", block):
        p = f"{a}-{b}-{c}"
        if len({a,b,c}) == 3 and p not in picks:
            picks.append(p)
    return picks[:8]


def beforeinfo_available(day: str, jcd: str, rno: int) -> bool:
    try:
        return parse_beforeinfo(fetch(official_url('beforeinfo',day,jcd,rno)))['exhibition_count']==6
    except Exception:
        return False


def send_discord(content: str, *, notify_everyone: bool = False) -> None:
    url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is missing")
    payload = json.dumps(message_payload(content, notify_everyone=notify_everyone), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type":"application/json","User-Agent":UA}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        if r.status not in (200, 204):
            raise RuntimeError(f"Discord HTTP {r.status}")


def load_deliveries() -> set[tuple]:
    existing=set()
    if LOG_PATH.exists():
        for line in LOG_PATH.read_text(encoding='utf-8').splitlines():
            try:
                row=json.loads(line)
                existing.add((row['day'],row['jcd'],int(row['rno']),row.get('phase','final')))
            except (ValueError,KeyError,TypeError):
                continue
    return existing


def log_prediction(record: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True,exist_ok=True)
    with LOG_PATH.open('a',encoding='utf-8') as f:
        f.write(json.dumps(record,ensure_ascii=False,sort_keys=True)+'\n')
        f.flush()
        os.fsync(f.fileno())


def minutes_until(now: datetime, hhmm: str) -> float:
    h,m=map(int,hhmm.split(':'))
    return (now.replace(hour=h,minute=m,second=0,microsecond=0)-now).total_seconds()/60


def load_policy() -> dict:
    return json.loads(Path('notification_policy.json').read_text(encoding='utf-8'))


def valid_six_boats(analysis, policy):
    if not policy.get('require_six_boats', True):
        return True
    boats = analysis.get('inputs') or []
    return len(boats) == 6 and {b.get('lane') for b in boats} == set(range(1,7))


def unavailable_race_status(day, jcd, rno):
    try:
        lanes = withdrawal_lanes(fetch(official_url('racelist', day, jcd, rno)))
    except Exception:
        lanes = []
    if lanes:
        return 'withdrawn', '・'.join(map(str, lanes)) + '号艇が欠場のため予想対象外。'
    return 'unavailable', '6艇の出走データを確認できないため予想対象外。公式の欠場は未確認です。'


def send_race_notice(day, jcd, rno, deadline, kind, reason, *, now=None, dry_run=False):
    if not load_policy().get('notify_race_status', True):
        return False
    current = now if dry_run and now is not None else datetime.now(JST)
    if current.strftime('%Y%m%d') != day or minutes_until(current, deadline) < load_policy()['final_min_lead_minutes']:
        return False
    key = (day, jcd, int(rno), kind)
    sent = {(r.get('day'), r.get('jcd'), r.get('rno'), r.get('status')) for r in read_notices()}
    if key in sent:
        return False
    message = notice_message(VENUES.get(jcd, jcd), rno, kind, reason)
    if dry_run:
        print(message)
        return True
    send_discord(message)
    record_notice({'day': day, 'jcd': jcd, 'venue': VENUES.get(jcd, jcd), 'rno': int(rno),
                   'deadline': deadline, 'status': kind, 'reason': reason,
                   'sent_at': datetime.now(JST).isoformat(), 'record_type': 'race_status'})
    print(f'sent status {jcd} {rno}R {kind}')
    return True


def ai_skip_reason(analysis, policy):
    preview = analysis.get('preview') or {}
    rule = policy['other_venues']
    reasons = []
    if analysis.get('grade') not in rule['grades']:
        reasons.append(f"AI評価{analysis.get('grade') or '未確定'}が選別基準外")
    for name, label, unit, limit in (('wind_speed', '風速', 'm', rule['max_wind_m']), ('wave_cm', '波高', 'cm', rule['max_wave_cm'])):
        value = preview.get(name)
        if value is None:
            reasons.append(label + 'が未確認')
        elif value > limit:
            reasons.append(f'{label}{value}{unit}が基準{limit}{unit}を超過')
    if not any(p.get('expected_value') is not None and p['expected_value'] >= rule['min_expected_value'] and p['probability'] >= rule['min_pick_probability'] for p in analysis.get('trifecta', [])):
        reasons.append('確率・期待値の条件を満たす買い目なし')
    return '／'.join(reasons) or 'AI選別条件に達していないため。'


def required_venue(policy,day,jcd):
    required = policy.get('all_races',{}).get(day,[])
    return '*' in required or jcd in required


def due_phase(policy,now,jcd,deadline,delivered,rno):
    day=now.strftime('%Y%m%d');lead=minutes_until(now,deadline)
    if lead<policy['final_min_lead_minutes']:
        return None
    if lead<=policy['final_max_lead_minutes']:
        return None if (day,jcd,rno,'final') in delivered else 'final'
    if required_venue(policy,day,jcd) and now.hour>=policy['preliminary_start_hour_jst']:
        return None if any((day,jcd,rno,p) in delivered for p in ('morning','preliminary','final')) else 'preliminary'
    return None


def selected_by_ai(analysis,policy):
    rule=policy['other_venues'];preview=analysis['preview']
    if analysis['grade'] not in rule['grades'] or preview['exhibition_count']<6:
        return False
    if preview['wind_speed'] is None or preview['wave_cm'] is None:
        return False
    if preview['wind_speed']>rule['max_wind_m'] or preview['wave_cm']>rule['max_wave_cm']:
        return False
    return any(p.get('expected_value') is not None and p['expected_value']>=rule['min_expected_value'] and p['probability']>=rule['min_pick_probability'] for p in analysis['trifecta'])


def displayed_picks(analysis,required):
    rows=analysis['trifecta']
    if not required:
        candidates=[p for p in rows if p.get('expected_value') is not None and p['expected_value']>=1.10 and p['probability']>=.02]
        return sorted(candidates,key=lambda p:p['expected_value'],reverse=True)[:6]
    picks=rows[:4]
    represented={p['combination'].split('-')[0] for p in picks}
    for row in rows:
        head=row['combination'].split('-')[0]
        if head not in represented:
            picks.append(row);represented.add(head)
            if len(picks)==6:break
    for row in rows:
        if len(picks)>=6:break
        if row not in picks:picks.append(row)
    return picks


def make_analysis_message(day,jcd,rno,deadline,phase,analysis,rows,required):
    preview=analysis['preview'];boats={b['lane']:b for b in analysis['inputs']}
    label='朝の暫定予想' if phase=='preliminary' else '直前更新' if required else 'AI選別'
    lines=[f'🚤 **{VENUES[jcd]} {rno}レース｜{label}**',f'{day[4:6]}/{day[6:8]}　締切 **{deadline}**', '━━━━━━━━━━━━',
        f"評価：{analysis['grade'] or '展示待ち'} / 展示 {preview['exhibition_count']}/6艇"]
    if required:lines.append('全レース配信枠（見送り判断も含む）')
    summary=formation_summary([p['combination'] for p in rows[:3]], [p['combination'] for p in rows[3:]])
    lines+=['━━━━━━━━━━━━', *formation_lines(summary), '━━━━━━━━━━━━']
    lines+=['','**AI展開の想定**']
    leader=max(analysis['heads'],key=analysis['heads'].get)
    course=boats[leader]['predicted_course']
    pattern='逃げ' if course==1 else '差し・まくり' if course==2 else 'まくり・まくり差し'
    alternative=sorted(analysis['heads'],key=analysis['heads'].get,reverse=True)[1]
    lines.append(f'{leader}号艇（想定{course}コース）の{pattern}を比較。対抗{alternative}号艇の頭も検討。')
    lines+=['','**AI着順の推定確率**']
    for lane in range(1,7):
        probabilities=[sum(p['probability'] for p in analysis['trifecta'] if int(p['combination'].split('-')[position])==lane)*100 for position in range(3)]
        lines.append(f'{lane}号艇｜1着 {probabilities[0]:.1f}% / 2着 {probabilities[1]:.1f}% / 3着 {probabilities[2]:.1f}%')
    lines+=['','**判断材料（6艇）**']
    for lane in range(1,7):
        b=boats[lane];form=analysis['previous_form'].get(lane)
        def display(value, digits=2):
            return f'{value:.{digits}f}' if value is not None else '未記録'
        line=f"{lane} {b['name']}：全国勝率 {display(b['win_rate'])} / モーター2連率 {display(b['motor_top2_rate'],1)}% / 平均ST {display(b['avg_st'])}"
        if b.get('flying'):line+=' / F持ち'
        if form:line+=' / 前日 '+ '・'.join(str(x)+'着' if isinstance(x,int) else str(x) for x in form['finishes'])
        if b.get('exhibition_time') is not None:line+=f" / 展示 {b['exhibition_time']:.2f}"
        lines.append(line)
    wind=preview['wind_speed'];wave=preview['wave_cm']
    lines.append(f"風速 {str(wind)+'m' if wind is not None else '未取得'} / 波高 {str(wave)+'cm' if wave is not None else '未取得'} / 進入 {'展示順を反映' if preview['entry_observed'] else '枠なり仮定'}")
    if any(b.get('exhibition_flying') for b in boats.values()):lines.append('展示Fあり：速さの加点には使わず、平均STを重視。')
    if phase=='preliminary' or preview['exhibition_count']<6:lines.append('判断：展示待ち。直前データで再判定。')
    elif not selected_by_ai(analysis,load_policy()):lines.append('判断：AI選別基準外。全レース配信の参考予想。')
    else:lines.append('判断：条件に合う候補あり。公開オッズの変動に注意。')
    if not any(p.get('odds') for p in rows):lines.append('オッズ：未公開・期待値は未判定')
    for p in rows:
        if p.get('odds') is not None:lines.append(f"{p['combination']}　{p['odds']:.1f}倍 / 推定EV {p['expected_value']:.2f}")
    lines+=['','※確率・EVは未校正のモデル推定値。前日成績は小幅な参考補正です。',official_url('racelist',day,jcd,rno)]
    return '\n'.join(lines)


def run_once(now: datetime | None=None, *, force_test=False,dry_run=False) -> int:
    now=(now or datetime.now(JST)).astimezone(JST)
    fetch.cache_clear()
    if force_test:
        if not dry_run:send_discord('✅ **競艇AIナビ 通知テスト**\n'+now.isoformat())
        return 0
    policy=load_policy();day=now.strftime('%Y%m%d')
    # Midnight BOAT RACE can have late races after 22:00. Keep same-day
    # notifications active through 23:59 JST; after midnight the <08:00 guard
    # naturally keeps the next day quiet until racing hours resume.
    if now.hour<8:
        print('Outside race notification hours');return 0
    venues=set(discover_venues(day))|(set(policy.get('all_races',{}).get(day,[]))-{'*'})
    delivered=load_deliveries();targets=[];failures=0
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(deadlines,day,jcd):jcd for jcd in venues}
        for future in as_completed(jobs):
            jcd=jobs[future]
            try:times=future.result()
            except Exception:failures+=1;continue
            for rno,deadline in enumerate(times,1):
                phase=due_phase(policy,now,jcd,deadline,delivered,rno)
                if phase:targets.append((jcd,rno,deadline,phase))
    sent=0
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(analyze_official,day,jcd,rno):(jcd,rno,deadline,phase) for jcd,rno,deadline,phase in targets}
        for future in as_completed(jobs):
            jcd,rno,deadline,phase=jobs[future]
            try:
                analysis=future.result()
            except Exception as e:
                failures += 1
                print(f'Official analysis failed {jcd} {rno}R: {type(e).__name__}')
                try:
                    send_race_notice(day,jcd,rno,deadline,'unavailable','公式データを取得できません。欠場の確定情報ではありません。',now=now,dry_run=dry_run)
                except Exception as notice_error:
                    print(f'Status delivery failed {jcd} {rno}R: {type(notice_error).__name__}')
                continue
            try:
                if not analysis or not valid_six_boats(analysis, policy):
                    kind, reason = unavailable_race_status(day,jcd,rno)
                    send_race_notice(day,jcd,rno,deadline,kind,reason,now=now,dry_run=dry_run)
                    print(f'Excluded race: {jcd} {rno}R {kind}')
                    continue
                required=required_venue(policy,day,jcd)
                current=now if dry_run else datetime.now(JST)
                if current.strftime('%Y%m%d')!=day or minutes_until(current,deadline)<policy['final_min_lead_minutes']:continue
                waiting = list(analysis.get('delivery_wait_reasons') or [])
                if phase == 'final' and analysis['preview']['exhibition_count'] < 6:
                    waiting.append(f"展示データ {analysis['preview']['exhibition_count']}/6艇。そろうまで判断保留です。")
                if waiting:
                    send_race_notice(day,jcd,rno,deadline,'waiting','／'.join(dict.fromkeys(waiting)),now=now,dry_run=dry_run)
                    continue
                if not required and not selected_by_ai(analysis,policy):
                    send_race_notice(day,jcd,rno,deadline,'pass',ai_skip_reason(analysis,policy),now=now,dry_run=dry_run)
                    continue
                rows=displayed_picks(analysis,required)
                message=make_analysis_message(day,jcd,rno,deadline,phase,analysis,rows,required)
                if dry_run:
                    print(message+'\n');continue
                send_discord(message)
                combos=[p['combination'] for p in rows]
                summary=formation_summary(combos[:3],combos[3:])
                log_prediction({'day':day,'jcd':jcd,'venue':VENUES[jcd],'rno':rno,'deadline':deadline,
                    'phase':phase,'sent_at':current.isoformat(),'source':'独自AI・前日参考補正','model_version':analysis['model_version'],
                    'grade':analysis['grade'],'exhibition':analysis['preview']['exhibition_count']==6,
                    'main':combos[:3],'cover':combos[3:],'all_picks':combos,'heads':analysis['heads'],
                    'preview':{
                        'wind_speed':analysis.get('preview',{}).get('wind_speed'),
                        'wave_cm':analysis.get('preview',{}).get('wave_cm'),
                        'entry_observed':analysis.get('preview',{}).get('entry_observed'),
                        'exhibition_count':analysis.get('preview',{}).get('exhibition_count'),
                        'boats':analysis.get('preview',{}).get('boats',{}),
                        'tide':analysis.get('preview',{}).get('tide',{}),
                    },
                    'tactical_inputs':[{
                        'lane':b.get('lane'),
                        'predicted_course':b.get('predicted_course') or b.get('course'),
                        'avg_st':b.get('avg_st'),
                        'exhibition_st':b.get('exhibition_st'),
                        'exhibition_flying':bool(b.get('exhibition_flying')),
                        'exhibition_grade':b.get('exhibition_grade'),
                    } for b in (analysis.get('inputs') or [])],
                    'message_format':'formation-v1','point_count':summary['point_count'],'formation_sections':summary['sections'],
                    'previous_form':analysis['previous_form']})
                delivered.add((day,jcd,rno,phase));sent+=1
                print(f'sent {jcd} {rno}R {phase}')
            except Exception as e:
                failures+=1;print(f'Notification failed {jcd} {rno}R: {type(e).__name__}')
    print(f'completed targets={len(targets)} sent={sent} failures={failures} dry_run={dry_run}')
    return 1 if failures else 0


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--test',action='store_true');parser.add_argument('--dry-run',action='store_true');args=parser.parse_args()
    try:return run_once(force_test=args.test,dry_run=args.dry_run)
    except Exception as e:print(f'Notifier error: {type(e).__name__}');return 1


if __name__=='__main__':
    sys.exit(main())
