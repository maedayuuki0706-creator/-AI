"""Private loopback race browser over read-only snapshots; no external requests."""
import argparse
from datetime import timedelta
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from analytics import VENUES, as_day
from desk import build, render, cell
from longitudinal import connect
from coverage_audit import manifest


def run(data, db, g1, port):
    @lru_cache(maxsize=4)
    def report(day,venue,number):
        a=SimpleNamespace(data=data,db=db,g1=g1,day=day,venue=venue,race=number,
            audit_start=(as_day(day)-timedelta(days=6)).strftime('%Y%m%d'),audit_end=day)
        pages,scen,*_=build(a)
        pages['ホーム・開催場']+=f'<p><a href="/?day={day}">この日のレース一覧へ</a></p>'
        return render(pages,scen)

    class Local(BaseHTTPRequestHandler):
        def do_GET(self):
            uri=urlsplit(self.path)
            if uri.path!='/':
                self.send_error(404);return
            q=parse_qs(uri.query)
            try:
                days=sorted(p.stem for p in (data/'race_cards').glob('[0-9]'*8+'.json'))
                if (data/'programs.sqlite').is_file():
                    db=connect(data/'programs.sqlite')
                    try: days=sorted(set(days)|{r[0] for r in db.execute('select day from source')})
                    finally: db.close()
                day=q.get('day',[days[-1]])[0];as_day(day)
                if 'venue' in q:
                    v=q['venue'][0];n=int(q['race'][0])
                    if v not in {f'{i:02}' for i in range(1,25)} or not 1<=n<=12: raise ValueError
                    html=report(day,v,n)
                else:
                    try:races=manifest(data/'race_cards'/f'{day}.json',day)
                    except (FileNotFoundError,ValueError):
                        if not (data/'programs.sqlite').is_file():raise
                        db=connect(data/'programs.sqlite')
                        try:races={(r[0],r[1]) for r in db.execute('select venue,race_no from schedule where day=?',(day,))}
                        finally:db.close()
                        if not races:raise ValueError('unknown schedule')
                    lineups=set()
                    if (data/'lineups.sqlite').is_file():
                        db=connect(data/'lineups.sqlite')
                        try:lineups={r[0] for r in db.execute('select distinct id from program_boat where id>=? and id<=?',(day+'0000',day+'9999'))}
                        finally:db.close()
                    links=[]
                    for v,n in sorted(races):
                        label=f'{VENUES[int(v)-1]} {n}R'
                        available=(data/'exhibition_log'/day/f'{v}_{n:02}.json').is_file()
                        if not available and f'{day}{v}{n:02}' in lineups:
                            available=True; label+='（番組・展示未収録）'
                        links.append(f'<li><a href="/?day={day}&amp;venue={v}&amp;race={n}">{cell(label)}</a></li>' if available else f'<li>{cell(label)}　未収録</li>')
                    options=''.join(f'<option {"selected" if d==day else ""}>{d}</option>' for d in days)
                    html='<html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>航跡 — 開催一覧</title><h1>航跡 — 開催一覧</h1><form><label>開催日 <select name="day">'+options+'</select></label><button>表示</button></form><ul>'+''.join(links)+'</ul></html>'
            except (IndexError,ValueError,FileNotFoundError,KeyError):
                self.send_error(404,'Date, complete schedule or verified race data unavailable');return
            body=html.encode();self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    HTTPServer(('127.0.0.1',port),Local).serve_forever()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('data','db','g1'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--port',type=int,default=8873)
    run(**vars(parser.parse_args()))
