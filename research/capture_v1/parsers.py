"""Research-only parser copies. Never import dispatch or live policy modules.
Pure parsing adapted from repository code; acquisition/storage are independent.
"""
import re
import html
import unicodedata

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

def parse_racelist_boats(raw: str) -> list[dict]:
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
                and all(nums[i] is None or 0 <= nums[i] <= 100 for i in (2,3,5,6,8,9,11,12))
                and (nums[7] is None or 1 <= nums[7] <= 999)
                and (nums[10] is None or 1 <= nums[10] <= 999)):
            return []
        boats.append({
            "lane": lane, "course": lane, "predicted_course": lane,
            "racer_id": registration[1], "current_class": registration[2], "name": re.sub(r"\s+", "", text[registration.end():].strip().split("\n")[0]),
            "avg_st": nums[0], "flying": int(fl[1]) > 0,
            "win_rate": nums[1], "top2_rate": nums[2], "top3_rate": nums[3],
            "local_win_rate": nums[4] if any(nums[4:7]) else None,
            "local_top2_rate": nums[5] if any(nums[4:7]) else None,
            "motor_number": int(nums[7]) if nums[7] is not None else None,
            "motor_top2_rate": nums[8], "motor_top3_rate": nums[9],
            "boat_number": int(nums[10]) if nums[10] is not None else None,
            "boat_top2_rate": nums[11], "boat_top3_rate": nums[12],
        })
    return sorted(boats, key=lambda x: x["lane"]) if {b["lane"] for b in boats} == set(range(1,7)) and len(boats)==6 else []

def parse_beforeinfo(raw: str) -> dict:
    result = {
        "boats": {}, "wind_speed": None, "wave_cm": None, "entry_observed": False,
        "air_temp_c": None, "water_temp_c": None,
    }
    for body in re.findall(r"<tbody\b[^>]*>(.*?)</tbody>", raw, re.I | re.S):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", body, re.I | re.S)
        lane = re.search(r'is-boatColor([1-6])', body)
        if not lane or len(cells) < 6 or "kg" not in textify(cells[3]):
            continue
        item = {}
        weight = re.fullmatch(r"(\d+(?:\.\d+)?)kg", textify(cells[3]))
        if weight:
            item["weight_kg"] = float(weight[1])
        if len(cells) > 12:
            adjustment = textify(cells[12]).strip()
            if re.fullmatch(r"\d+(?:\.\d+)?", adjustment):
                item["adjustment_weight_kg"] = float(adjustment)
        if len(cells) > 6:
            propeller = textify(cells[6]).strip()
            if propeller and propeller not in ("-", "－", "―", "—"):
                item["propeller_exchange"] = propeller
        if len(cells) > 7:
            parts = textify(cells[7]).strip()
            if parts:
                item["parts_exchange"] = re.sub(r"\s+", " ", parts)
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
            # Preserve the signed exhibition start timing for learning.
            # Normal .12 => +0.12, F.03 => -0.03. F timings are not used as a
            # live speed bonus; they are kept separately so we can learn how
            # each racer corrects from exhibition to the actual start.
            if re.fullmatch(r"(?:0)?\.\d+", st):
                timing = float(st)
                item["exhibition_st"] = timing
                item["exhibition_st_timing"] = timing
            else:
                flying_match = re.fullmatch(r"F(?:0)?\.(\d+)", st)
                if flying_match:
                    timing = -float("0." + flying_match.group(1))
                    item["exhibition_st_timing"] = timing
                    item["exhibition_f_depth"] = abs(timing)
    text = textify(raw)
    for key,label,unit in (("wind_speed","風速","m"),("wave_cm","波高","cm"),
                           ("air_temp_c","気温","°C"),("water_temp_c","水温","°C")):
        match = re.search(label+r"\s+(\d+(?:\.\d+)?)"+re.escape(unit),text)
        if match:
            result[key] = float(match[1])
    result["exhibition_count"] = sum("exhibition_time" in row for row in result["boats"].values())
    times = [row["exhibition_time"] for row in result["boats"].values() if "exhibition_time" in row]
    if len(times)==6:
        # Preserve both relative rank/delta and a bounded grade.
        average = sum(times)/6
        fastest = min(times)
        ranked = sorted(times)
        for row in result["boats"].values():
            if "exhibition_time" not in row:
                continue
            row["exhibition_delta"] = round(row["exhibition_time"] - fastest, 3)
            row["exhibition_rank"] = ranked.index(row["exhibition_time"]) + 1
            row["exhibition_grade"] = max(0,min(1,.5+(average-row["exhibition_time"])*2))
    sts = [row["exhibition_st"] for row in result["boats"].values() if row.get("exhibition_st") is not None]
    if len(sts) >= 4:
        best_st = min(sts)
        ranked_st = sorted(sts)
        for row in result["boats"].values():
            if row.get("exhibition_st") is None:
                continue
            row["exhibition_st_delta"] = round(row["exhibition_st"] - best_st, 3)
            row["exhibition_st_rank"] = ranked_st.index(row["exhibition_st"]) + 1
    return result

def clean(raw):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', html.unescape(re.sub(r'<[^>]+>', ' ', raw)))).strip()

def parse_result(raw, day, jcd, rno):
    finish = []
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', raw, re.S | re.I):
        cells = re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.S | re.I)
        if len(cells) != 4 or not re.search(r'is-boatColor[1-6]', row):
            continue
        position, lane, racer = clean(cells[0]), clean(cells[1]), clean(cells[2])
        m = re.match(r'(\d{4})\s+(.+)', racer)
        if not m or lane not in '123456' or len(lane) != 1:
            continue
        finish.append({'lane': int(lane), 'racer_id': m[1], 'name': m[2].replace(' ', ''),
                       'finish': int(position) if position in list('123456') else None,
                       'status': 'finished' if position in list('123456') else position})
    starts = re.findall(r'table1_boatImage1Number[^>]*>\s*([1-6])\s*</span>.*?table1_boatImage1Time[^>]*>(.*?)</span>', raw, re.S)
    for course, (lane, st_raw) in enumerate(starts, 1):
        for item in finish:
            if item['lane'] == int(lane):
                st = clean(st_raw).split(' ')[0]
                item.update(course=course, st=float(st) if re.fullmatch(r'\.?\d+', st) else None)
    text = clean(raw)
    method = re.search(r'決まり手\s+(逃げ|差し|まくり差し|まくり|抜き|恵まれ)', text)
    payout = re.search(r'3連単\s+([1-6])\s*-\s*([1-6])\s*-\s*([1-6])\s+[¥￥]([\d,]+)', text)
    wind = re.search(r'風速\s+(\d+)m', text)
    wave = re.search(r'波高\s+(\d+)cm', text)
    if len(finish) != 6 or not payout or len({x['racer_id'] for x in finish}) != 6:
        raise ValueError(f'Incomplete result {day} {jcd} {rno}')
    return {'day': day, 'jcd': jcd, 'rno': rno, 'finish': finish,
            'trifecta': '-'.join(payout.group(i) for i in (1,2,3)), 'payout_per_100': int(payout[4].replace(',', '')),
            'method': method[1] if method else None, 'wind_m': int(wind[1]) if wind else None,
            'wave_cm': int(wave[1]) if wave else None,
            'source_url': f'https://www.boatrace.jp/owpc/pc/race/raceresult?hd={day}&jcd={jcd}&rno={rno}'}

def parse_payout(raw):
    """Read the trifecta market only; unknown/suspended results stay pending."""
    text = clean(raw)
    market = next((body for body in re.findall(r'<tbody\b[^>]*>(.*?)</tbody>', raw, re.S | re.I)
                   if re.search(r'<td\b[^>]*>\s*3連単\s*</td>', body, re.S)), '')
    market_text = clean(market)
    payouts = {}
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', market, re.S | re.I):
        match = re.search(r'([1-6])\s*[-－]\s*([1-6])\s*[-－]\s*([1-6])\s+[¥￥]\s*([\d,]+)', clean(row))
        if match:
            combo = '-'.join(match.group(i) for i in (1, 2, 3))
            if len(set(combo.split('-'))) == 3:
                payouts[combo] = int(match[4].replace(',', ''))
    refund_lanes = set()
    for table in re.findall(r'<table\b[^>]*>(.*?)</table>', raw, re.S | re.I):
        if re.search(r'<th\b[^>]*>\s*返還\s*</th>', table):
            refund_lanes.update(int(x) for x in re.findall(r'numberSet1_number[^>]*>\s*([1-6])\s*</span>', table))
    # Some stored fixtures omit the refund panel, but keep the official F/L rows.
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', raw, re.S | re.I):
        cells = re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.S | re.I)
        if len(cells) == 4 and re.search(r'is-boatColor[1-6]', row):
            status, lane = clean(cells[0]), clean(cells[1])
            if status in {'F', 'L', '欠', 'K0', 'K1'} and re.fullmatch('[1-6]', lane):
                refund_lanes.add(int(lane))
    void = bool(re.search(r'不成立|全返還|中止', market_text)
                or re.search(r'(?:この)?レースは中止(?:となりました|です)', text)
                or re.search(r'<(?:p|div|td)\b[^>]*>\s*(?:レース中止|不成立)\s*</', raw))
    special = re.search(r'特払い\s*[¥￥]\s*([\d,]+)', market_text)
    status = 'void' if void else 'special' if special else 'settled' if payouts else 'pending'
    if '返還艇あり' in text and not refund_lanes and status == 'settled':
        status = 'pending'  # A refund must not silently become a losing ticket.
    return {'status': status, 'payouts': payouts, 'refund_lanes': sorted(refund_lanes),
            'special_per_100': int(special[1].replace(',', '')) if special else None}
