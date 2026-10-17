"""Research-only bounded official GETs and pure parsers; no dispatch imports."""
from datetime import datetime
from hashlib import sha256
import re
import threading
import urllib.request
from research.capture_v1 import parsers
from .engine import JST

class Official:
    def __init__(self):
        self.raw = {}
        self.observed = {}
        self.lock = threading.Lock()

    @staticmethod
    def official_url(kind, day, jcd=None, rno=None):
        if kind not in {'index','racelist','beforeinfo','raceresult'}: raise ValueError('Unsupported endpoint')
        query=f'hd={day}'
        if jcd is not None: query+=f'&jcd={int(jcd):02}'
        if rno is not None: query+=f'&rno={int(rno)}'
        return 'https://www.boatrace.jp/owpc/pc/race/'+kind+'?'+query

    def fetch(self, url):
        with self.lock:
            if url in self.raw: return self.raw[url]
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; BoatAI-Independent-Research/1.1)','Accept-Language':'ja'})
        with urllib.request.urlopen(req,timeout=25) as response:
            if response.geturl()!=url: raise ValueError('Unexpected official redirect')
            content=response.read(2000001)
        if len(content)>2000000: raise ValueError('Official response too large')
        raw=content.decode('utf-8',errors='replace')
        with self.lock:
            self.raw[url]=raw;self.observed[url]=datetime.now(JST).isoformat()
        return raw

    def deadlines(self,day,code):
        raw=self.fetch(self.official_url('racelist',day,code,1))
        text=parsers.textify(raw);pos=text.find('締切予定時刻')
        values=re.findall(r'(?:[01]?\d|2[0-3]):[0-5]\d',text[pos:pos+900]) if pos>=0 else []
        if len(values)<12:
            index=self.fetch(self.official_url('index',day))
            held=set(re.findall(r'(?:\?|&amp;|&)jcd=(\d{2})',index))
            if held and code not in held:return []
            raise ValueError('Official schedule missing/incomplete; never treat as zero races')
        times=[]
        for value in values[:12]:
            h,m=map(int,value.split(':'));times.append(f'{h:02}:{m:02}')
        if len(set(times))!=12:raise ValueError('Ambiguous official schedule')
        return times

    def parse_racelist_boats(self,day,code,rno):
        return parsers.parse_racelist_boats(self.fetch(self.official_url('racelist',day,code,rno)))

    @staticmethod
    def parse_beforeinfo(raw):
        parsed=parsers.parse_beforeinfo(raw)
        icons=re.findall(r'weather1_bodyUnitImage[^>]*class="[^"]*?is-wind(\d+)',raw)
        if not icons:icons=re.findall(r'class="[^"]*?is-wind(\d+)[^"]*"',raw)
        parsed['wind_direction_icon']=icons[0] if len(set(icons))==1 else None
        parsed['wind_direction']=None # icon-to-compass orientation needs source validation
        return parsed

    def envelope(self,url):
        raw=self.raw[url]
        return {'url':url,'observed_at':self.observed[url],
                'sha256':sha256(raw.encode()).hexdigest(),'html':raw}
