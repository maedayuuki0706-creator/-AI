import csv
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

START = int(sys.argv[1]) if len(sys.argv) > 1 else 3388
END = int(sys.argv[2]) if len(sys.argv) > 2 else 4150
OUT = Path(f"data/racers_{START}_{END}.csv")
BASE = "https://www.boatrace.jp/owpc/pc/data/racersearch"
ATLAS = "https://abeken1026395.github.io/pallas-mercato-7k9"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BoatAI-RacerDB/2.0)"}
BASE_FIELDS = ["登録番号","選手名","級別","支部","登録期"]
for metric in ("進入率","3連対率","平均ST","スタート順"):
    BASE_FIELDS += [f"{i}C{metric}" for i in range(1,7)]

session = requests.Session()
session.headers.update(HEADERS)

def clean(value):
    return re.sub(r"\s+", " ", str(value).replace("\xa0"," ").replace("　"," ")).strip()

def fetch(url, timeout=20):
    for attempt in range(4):
        try:
            r = session.get(url, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code not in (429,500,502,503,504):
                return None
        except requests.RequestException:
            pass
        time.sleep(2 ** attempt)
    return None

def labeled(soup, label):
    tag = soup.find(lambda t: t.name in ("dt","th") and clean(t.get_text()) == label)
    if not tag:
        return ""
    nxt = tag.find_next_sibling("dd" if tag.name == "dt" else "td")
    return clean(nxt.get_text()) if nxt else ""

def six_after_heading(soup, heading):
    node = soup.find(string=lambda x: x and heading in clean(x))
    if not node:
        return [""] * 6
    table = node.parent.find_next("table")
    values = [""] * 6
    if not table:
        return values
    for tr in table.find_all("tr"):
        cells = [clean(c.get_text()) for c in tr.find_all(["th","td"])]
        if len(cells) >= 2 and cells[0] in tuple("123456"):
            values[int(cells[0]) - 1] = cells[-1]
    return values

def flatten(prefix, obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            flatten(f"{prefix}_{k}" if prefix else str(k), v, out)
    elif isinstance(obj, (str,int,float,bool)) or obj is None:
        out["図鑑_" + prefix] = "" if obj is None else obj

def find_player(obj, toban, name):
    if isinstance(obj, list):
        for item in obj:
            hit = find_player(item, toban, name)
            if hit is not None:
                return hit
    elif isinstance(obj, dict):
        ident = clean(obj.get("toban") or obj.get("registration") or obj.get("registrationNo") or obj.get("id") or "")
        pname = clean(obj.get("name") or obj.get("playerName") or "")
        if ident == str(toban) or (pname and pname.replace(" ","") == name.replace(" ","")):
            return obj
        for value in obj.values():
            if isinstance(value, (list,dict)):
                hit = find_player(value, toban, name)
                if hit is not None:
                    return hit
    return None

ATLAS_JSON_CANDIDATES = [
    f"{ATLAS}/data/players.json",
    f"{ATLAS}/players/data.json",
    f"{ATLAS}/assets/players.json",
]

def atlas_fields(toban, name):
    for url in ATLAS_JSON_CANDIDATES:
        r = fetch(url)
        if not r:
            continue
        try:
            obj = r.json()
        except ValueError:
            continue
        player = find_player(obj, toban, name)
        if player is not None:
            out = {}
            flatten("", player, out)
            return out
    # Safe HTML fallback. No invented field names.
    for url in (f"{ATLAS}/players/{toban}/", f"{ATLAS}/players/?toban={toban}"):
        r = fetch(url)
        if not r:
            continue
        soup = BeautifulSoup(r.content, "html.parser")
        body = clean(soup.get_text(" "))
        if str(toban) not in body and name.replace(" ","") not in body.replace(" ",""):
            continue
        out = {}
        for tr in soup.find_all("tr"):
            cells = [clean(x.get_text()) for x in tr.find_all(["th","td"])]
            if len(cells) == 2 and cells[0] and cells[1]:
                out["図鑑_" + cells[0]] = cells[1]
        for dt in soup.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if dd:
                k, v = clean(dt.get_text()), clean(dd.get_text())
                if k and v:
                    out["図鑑_" + k] = v
        if out:
            return out
    return {}

def collect_racer(toban):
    rp = fetch(f"{BASE}/profile?toban={toban}")
    if not rp or "該当する選手が見つかりません" in rp.text:
        return None
    soup = BeautifulSoup(rp.content, "html.parser")

    # Prefer official structured racer-name elements. Reject UI words such as 設定.
    name = ""
    selectors = [
        ".is-fs18.is-bold",
        ".memberData_name",
        "[class*='name']",
    ]
    for selector in selectors:
        for el in soup.select(selector):
            candidate = clean(el.get_text())
            candidate = re.sub(r"（.*?）", "", candidate).strip()
            if candidate and candidate not in {"設定","検索","選手検索","メニュー"} and 2 <= len(candidate) <= 20:
                if re.search(r"[一-龥々ヶぁ-んァ-ヶ]", candidate):
                    name = candidate
                    break
        if name:
            break

    # Text fallback: find Japanese name close to the registration-number block.
    if not name:
        text = clean(soup.get_text(" "))
        marker_pos = text.find(str(toban))
        if marker_pos >= 0:
            around = text[max(0, marker_pos-150):marker_pos]
            candidates = re.findall(r"[一-龥々ヶぁ-んァ-ヶ]{1,8}\s+[一-龥々ヶぁ-んァ-ヶ]{1,8}", around)
            banned = {"選手 検索","登録 番号","級別 支部"}
            candidates = [x for x in candidates if x not in banned and "設定" not in x]
            if candidates:
                name = candidates[-1]
    if not name:
        return None

    row = {
        "登録番号": str(toban),
        "選手名": name,
        "級別": labeled(soup, "級別"),
        "支部": labeled(soup, "支部"),
        "登録期": labeled(soup, "登録期"),
    }
    rc = fetch(f"{BASE}/course?toban={toban}")
    if rc:
        cs = BeautifulSoup(rc.content, "html.parser")
        groups = [
            ("進入率","コース別進入率"),
            ("3連対率","コース別3連対率"),
            ("平均ST","コース別平均スタートタイミング"),
            ("スタート順","コース別スタート順"),
        ]
        for key, heading in groups:
            for i, value in enumerate(six_after_heading(cs, heading), 1):
                row[f"{i}C{key}"] = value
    row.update(atlas_fields(toban, row["選手名"]))
    return row

def save(rows):
    extras = sorted({k for row in rows for k in row if k not in BASE_FIELDS})
    fields = BASE_FIELDS + extras
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

def load_checkpoint():
    if not OUT.exists():
        return [], set()
    try:
        with OUT.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        done = {int(r["登録番号"]) for r in rows if clean(r.get("登録番号","")).isdigit()}
        print(f"RESUME saved_racers={len(rows)}", flush=True)
        return rows, done
    except Exception as e:
        print(f"RESUME_ERROR {e}", flush=True)
        return [], set()

def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows, done = load_checkpoint()
    processed = 0
    for n in range(START, END + 1):
        if n in done:
            continue
        row = collect_racer(n)
        if row:
            rows.append(row)
            print(f"OK {n} {row['選手名']} {row['級別']} atlas_fields={sum(k.startswith('図鑑_') for k in row)}", flush=True)
        else:
            print(f"SKIP {n}", flush=True)
        processed += 1
        if processed % 50 == 0:
            save(rows)
            print(f"CHECKPOINT processed={processed} saved_racers={len(rows)} last={n}", flush=True)
        time.sleep(0.8)
    save(rows)
    print(f"COMPLETE processed={processed} saved_racers={len(rows)} file={OUT}", flush=True)

if __name__ == "__main__":
    main()
