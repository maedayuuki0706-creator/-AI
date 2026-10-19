"""Four-venue cited knowledge, source-change check and hypothesis plan.

STANDALONE research only; uses neither predictor nor delivery code.
Article content is NEVER copied to JSON. Published venue descriptions are
ideas to test, not verified coefficients. This tool cannot modify predictions.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
VENUES = {"03":"江戸川","16":"児島","23":"唐津","06":"浜名湖"}
SAFE_HOSTS = {
    "www.boatrace.jp", "www.boatrace-edogawa.com", "www.kojimaboat.jp",
    "www.boatrace-karatsu.jp", "boatrace-hamanako.jp", "www.boatrace-hamanako.jp"
}
SOURCE_TYPES = {"official_venue_overview","official_venue_hydrology",
                "official_motor_era","historical_official_editorial",
                "historical_official_study"}
_STATUSES = {"article_inspired_unvalidated", "holdout_pending", "rejected", "holdout_passed_for_review"}
_ISO_DATE = re.compile(r"20\d{2}-\d\d-\d\d$")
_MAX_DOWNLOAD = 800_000


def _read(file: Path):
    return json.loads(Path(file).read_text(encoding="utf-8"))


def _date(value):
    if not isinstance(value,str) or not _ISO_DATE.fullmatch(value):
        raise ValueError("Expected YYYY-MM-DD date")
    return datetime.strptime(value,"%Y-%m-%d").date()


def _source_host(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in SAFE_HOSTS or parsed.username or parsed.password or parsed.port:
        raise ValueError("Untrusted or non-official source URL "+str(url))
    return parsed.hostname


def validate_catalog(sources_obj, hypotheses_obj):
    if sources_obj.get("schema")!="venue-official-sources-v1":
        raise ValueError("Unexpected source registry schema")
    if hypotheses_obj.get("schema")!="venue-hypothesis-lab-v1":
        raise ValueError("Unexpected research hypothesis registry")
    if sources_obj.get("prediction_weight_allowed") is not False:
        raise ValueError("Article catalog must never control the model")
    _date(sources_obj["captured_on"])
    sources = {}
    by_venue = Counter()
    for source in sources_obj["sources"]:
        sid = source["source_id"]
        if sid in sources or not re.fullmatch(r"[a-z0-9][a-z0-9-]{6,80}",sid):
            raise ValueError("Duplicate/malformed citation ID")
        code=source["jcd"]
        if code not in VENUES or source.get("name")!=VENUES[code]:
            raise ValueError("Source has unknown venue")
        if source["kind"] not in SOURCE_TYPES:
            raise ValueError("Unrecognized venue source type")
        _source_host(source["url"])
        _date(source["observed_at"])
        if source.get("published_at") is not None:
            _date(source["published_at"])
        summary = source["summary"]
        if not isinstance(summary,str) or not 12 <= len(summary) <= 480:
            raise ValueError("Store only short authored summaries, not copied article text")
        if source.get("historical_predeadline_verified") is not False:
            raise ValueError("Old site pages cannot be treated as pre-race data receipts")
        sources[sid] = source
        by_venue[code]+=1
    if set(by_venue)!=set(VENUES):
        raise ValueError("Each of four venues needs cited source")
    active_ids = set()
    by_hypothesis = Counter()
    for hypo in hypotheses_obj["hypotheses"]:
        key = hypo["id"]
        if key in active_ids or not re.fullmatch(r"[a-z0-9][a-z0-9-]{8,90}",key):
            raise ValueError("Duplicate/malformed hypothesis")
        active_ids.add(key)
        code=hypo["jcd"]
        if code not in VENUES:
            raise ValueError("Unknown venue hypothesis")
        ids=hypo["source_ids"]
        if not ids or len(ids)!=len(set(ids)) or any(i not in sources or sources[i]["jcd"]!=code for i in ids):
            raise ValueError("Hypothesis must cite same-venue official source")
        if hypo["review_status"] not in _STATUSES:
            raise ValueError("Unsupported evidence status")
        if hypo["review_status"]=="holdout_passed_for_review":
            raise ValueError("Holdout pass requires independent result/receipt reviewer, not source importer")
        if hypo.get("predictive_weight") != 0 or hypo.get("auto_promote") is not False:
            raise ValueError("Article hypotheses must not automatically change predicted weights")
        if hypo.get("source_history_before_observation_verified") is not False:
            raise ValueError("No original pre-deadline timestamp in article source")
        if len(hypo.get("required_fields",[]))<2 or not hypo.get("testing_plan"):
            raise ValueError("No test design")
        by_hypothesis[code]+=1
    if set(by_hypothesis)!=set(VENUES):
        raise ValueError("Each venue must have independent research hypotheses")
    return {"source_count":len(sources),"hypothesis_count":len(active_ids),
            "source_by_venue":dict(by_venue),"hypotheses_by_venue":dict(by_hypothesis),
            "unverified_predictive_effects":len(active_ids),"prediction_weights_applied":0}


class _Title(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title=False
        self.bits=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()=="title":self.in_title=True
    def handle_endtag(self,tag):
        if tag.lower()=="title":self.in_title=False
    def handle_data(self,data):
        if self.in_title and sum(len(v) for v in self.bits)<240:
            self.bits.append(data)


class _SafeRedirect:
    """Use urllib without treating redirects to unapproved hosts as acceptable."""
    @staticmethod
    def fetch(url,timeout=14):
        from urllib.request import build_opener,HTTPRedirectHandler
        class StrictRedirect(HTTPRedirectHandler):
            def redirect_request(self,req,fp,code,msg,headers,newurl):
                _source_host(newurl)
                return super().redirect_request(req,fp,code,msg,headers,newurl)
        req=Request(url,headers={"User-Agent":"BoatResearchPublicSource/1.0 (one-off source verification)","Accept-Language":"ja","Accept":"text/html,application/xhtml+xml,application/pdf"})
        with build_opener(StrictRedirect()).open(req,timeout=timeout) as r:
            _source_host(r.geturl())
            body=r.read(_MAX_DOWNLOAD+1)
            if len(body)>_MAX_DOWNLOAD:raise ValueError("Official source too large; metadata check skipped")
            return r,body


def scan_sources(source_rows, *, fetcher=None, now=None, pause_seconds=0):
    """Optional bounded OFFLINE-ARTIFACT source scan: hashes/title only; no article bodies."""
    fetcher=fetcher or _SafeRedirect.fetch
    now=now or datetime.now(timezone.utc).isoformat()
    reports=[]
    for idx,src in enumerate(source_rows):
        if pause_seconds and idx:time.sleep(pause_seconds)
        row={"source_id":src["source_id"],"jcd":src["jcd"],"url":src["url"],
             "checked_at":now,"article_parsed_for_prediction":False,
             "source_available_predeadline":False}
        try:
            _source_host(src["url"])
            res,body=fetcher(src["url"])
            content_type = str(res.headers.get("Content-Type",""))
            if not content_type.lower().startswith(("text/html","application/xhtml+xml","application/pdf")):
                raise ValueError("Unexpected source content type")
            row.update(status="fetched",content_sha256=sha256(body).hexdigest(),
                       content_type=content_type,byte_count=len(body),
                       last_modified=res.headers.get("Last-Modified"),
                       etag=res.headers.get("ETag"))
            if content_type.lower().startswith(("text/html","application/xhtml+xml")):
                parser=_Title()
                parser.feed(body.decode("utf-8","replace"))
                row["document_title"]=" ".join("".join(parser.bits).split())[:200]
            else:
                row["document_title"]=src["title"]
        except (HTTPError,URLError,TimeoutError,UnicodeError,ValueError,OSError) as exc:
            row.update(status="unavailable",error_type=type(exc).__name__)
        reports.append(row)
    return reports


def report_md(sources,hypotheses,audit,fetch_logs=None):
    lines=["# 4場専門AI｜公式記事からの研究メモ（予想採用前）","",
           "この記事由来の情報はすべて**研究仮説**であり、実際の予想の場別係数は**0**。著作権に配慮し原文転載なし。","",
           f"- 一次情報：{audit['source_count']}件 ／ 別々の研究仮説：{audit['hypothesis_count']}件",
           "- 時系列外・標本数・公式の本番データの照合が完了するまで自動反映禁止",
           "- 『記事の事実』と『3連単の条件付き効果』は別。強風や潮位による外れの原因も未確定。",""]
    for code,name in VENUES.items():
        lines.extend([f"## {name}｜研究ノート", ""])
        for s in sources["sources"]:
            if s["jcd"]!=code:continue
            lines.append(f"- 元記事：[{s['title']}]({s['url']})（2026-10-19確認／公開時刻不明の場合あり）")
            lines.append(f"  - 要点：{s['summary']}")
        lines.append("")
        for h in hypotheses["hypotheses"]:
            if h["jcd"]!=code:continue
            lines.append(f"### {h['title']}（{h['priority']}／未検証）")
            lines.append(f"- 研究仮説：{h['proposition']}")
            lines.append(f"- 足りないデータ：{'、'.join(h['required_fields'])}")
            lines.append(f"- 検証方法：{h['testing_plan']}")
            lines.append(f"- 研究上の注意：{h['exclusion_notes']}")
            lines.append("")
    if fetch_logs is not None:
        lines.extend(["## 今回の公開元ページの更新確認（内容をAIに自動学習しない）",""])
        for r in fetch_logs:
            lines.append(f"- {r['jcd']} / {r['source_id']}：{r['status']}（sha256: {r.get('content_sha256','取得不可')}）")
    lines.extend(["## 今後の実装ゲート","",
        "1. まず6艇の締切前公式ソース、予想原本、1〜3着、全6艇本番ST、実進入、開催節・モーター世代を確認。",
        "2. 条件ごとの十分な標本、開催日・節で区切った時系列外検証、風/潮位の観測点・時刻一致を確認。",
        "3. 事前分布／展開仮説を扱い、モデル差分と従来予想を同じレース・同じ10点・締切前に別保存。",
        "4. 実際の展開の因果ラベルは映像レビューが確認できるまで『未判定』のまま保持。",
        "5. 条件が合格しても自動昇格禁止。元の配信・LOGを停止・変更せず、研究用差分として提案する。",""])
    return "\n".join(lines)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--fetch",action="store_true",help="Opt-in metadata-only official source check")
    p.add_argument("--pause",type=float,default=1.0)
    opts=p.parse_args()
    sources=_read(HERE/"official_sources.json")
    hypotheses=_read(HERE/"hypotheses.json")
    audit=validate_catalog(sources,hypotheses)
    if opts.pause<0.5:raise ValueError("Respect official site crawl gap")
    scan=scan_sources(sources["sources"],pause_seconds=opts.pause) if opts.fetch else None
    opts.out.mkdir(parents=True,exist_ok=True)
    (opts.out/"catalog_validation.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (opts.out/"article_study.md").write_text(report_md(sources,hypotheses,audit,scan),encoding="utf-8")
    if scan is not None:
        (opts.out/"source_hashes.json").write_text(json.dumps(scan,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"validation":audit,
        "source_scan":{k:sum(1 for s in scan or [] if s["status"]==k) for k in ["fetched","unavailable"]},
        "unavailable_sources":[{"source_id":s["source_id"],"error_type":s.get("error_type")} for s in scan or [] if s["status"]=="unavailable"],
        "source_titles_captured":[s["source_id"] for s in scan or [] if s["status"]=="fetched"]},ensure_ascii=False))
    return audit


if __name__=="__main__":main()
