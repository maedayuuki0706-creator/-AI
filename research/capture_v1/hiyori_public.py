"""Read public Boat Race Biyori data through the site's normal page requests."""
from __future__ import annotations

from datetime import datetime
from html.parser import HTMLParser
import http.cookiejar
import json
import re
import urllib.parse
import urllib.request

BASE = 'https://kyoteibiyori.com/'


class Inputs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        item = dict(attrs)
        if tag == 'input' and item.get('name'):
            self.values[item['name']] = item.get('value', '')


def fetch_race(day, jcd, rno):
    datetime.strptime(day, '%Y%m%d')
    if not 1 <= int(jcd) <= 24 or not 1 <= int(rno) <= 12:
        raise ValueError('Invalid race identity')
    identity = {'hiduke': day, 'place_no': int(jcd), 'race_no': int(rno)}
    url = BASE + 'race_shusso.php?' + urllib.parse.urlencode(identity)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    headers = {'User-Agent': 'Boat-AI-Hiyori/1.0', 'Referer': url}
    with opener.open(urllib.request.Request(url, headers=headers), timeout=8) as response:
        page = response.read().decode('utf-8')
    inputs = Inputs()
    inputs.feed(page)
    for name, value in identity.items():
        if str(inputs.values.get(name)) != str(value):
            raise ValueError('Hiyori page race identity mismatch')
    token = re.search(r'CSRF_TOKEN\s*=\s*["\x27]([^"\x27]+)', page)
    if not token:
        raise ValueError('Hiyori public page token is missing')
    details = dict(identity, season=2021, term=1, type=0, grade=0)
    # These parameters mirror race_shusso.js GetRaceDetail; rates use explicit
    # course*_ave fields from its public response, not these legacy season labels.
    for name in ('race_name', 'kaisai_key', 'taikai_count', 'group_no'):
        details[name] = inputs.values[name]

    def read(endpoint, payload):
        request = urllib.request.Request(BASE + endpoint,
            data=urllib.parse.urlencode(payload).encode(), headers=headers)
        with opener.open(request, timeout=8) as response:
            return json.load(response)

    data = read('request_race_shusso_detail_v4.php',
                {'data': json.dumps(details, ensure_ascii=False), 'token': token[1]})
    rows = data.get('race_list') if isinstance(data, dict) else None
    if not isinstance(rows, list) or len(rows) != 6:
        raise ValueError('Hiyori public race data is incomplete')
    if {int(row.get('course', 0)) for row in rows} != set(range(1, 7)):
        raise ValueError('Hiyori lane data is incomplete')
    for row in rows:
        if any(str(row.get(name)) != str(value) for name, value in identity.items()):
            raise ValueError('Hiyori response race identity mismatch')
    try:
        preview = read('request_chokuzen_info_v2.php', {'data': json.dumps(identity)})
    except Exception:
        preview = []
    # Never persist session tokens or the site's user-memo section.
    return {'source_url': url, 'rows': rows, 'preview': preview,
            'motor_last10': (data.get('kako_list') or {}).get('motor_kako10') or [],
            'front_entry': data.get('maeduke_list') or [],
            'maintenance': data.get('chukan_seibi_list') or []}
