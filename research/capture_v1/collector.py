"""Separate research state machine: prepare, exhibition revisions, freeze, review."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import fcntl
import json
import os
import tempfile

from research.scenario_v2.adapters import from_fusion
from research.scenario_v2.engine import JST, aware, digest, generate, reject_outcomes, review
from research.scenario_v2.run import write_once
from .sources import PublicClient, database_enrichment, identity, optional_foot, page_deadline
from . import parsers

REPOSITORY = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_state(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as stream:
            temp=Path(stream.name)
            stream.write((json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False)+"\n").encode())
            stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path)
    finally:
        if temp:temp.unlink(missing_ok=True)


class Collector:
    def __init__(self, out, *, client=None, clock=None, db_root=None, fusion_root=None, shared_cache=None,
                 foot_fetcher=None, fetch_foot=False, mode="live"):
        self.root=Path(out).resolve()
        if self.root == REPOSITORY or REPOSITORY in self.root.parents:
            raise ValueError("Research output must be outside the existing repository")
        for source in [db_root,fusion_root,shared_cache]:
            if source:
                source=Path(source).resolve()
                if self.root==source or self.root in source.parents or source in self.root.parents:
                    raise ValueError("Research output and read-only source must be disjoint")
        if mode not in {"live","replay"}:raise ValueError("Invalid mode")
        self.root.mkdir(parents=True,exist_ok=True)
        modefile=self.root/"mode.json"
        if modefile.exists() and read(modefile)["mode"]!=mode:raise ValueError("Do not mix live and replay storage")
        if not modefile.exists():write_once(modefile,{"mode":mode,"storage":"independent_research"})
        self.clock=clock or (lambda:datetime.now(JST))
        self.client=client or PublicClient(shared_cache, self.clock)
        self.db_root=db_root;self.fusion_root=Path(fusion_root) if fusion_root else None
        self.foot_fetcher=foot_fetcher or optional_foot
        self.fetch_foot=fetch_foot;self.mode=mode

    def step(self, meta):
        key=identity(meta);now=aware(self.clock())
        if self.mode=="live" and now.strftime("%Y%m%d")!=str(meta["day"]):
            deadline=datetime.strptime(str(meta["day"])+" "+meta["deadline"],"%Y%m%d %H:%M").replace(tzinfo=JST)
            if not (self.root/key/"forecast.json").exists() or not 0<(now-deadline).total_seconds()<=172800:
                raise ValueError("Live forecast creation is for today's races only; existing freezes may be reviewed for 48 hours")
        race=self.root/key;race.mkdir(exist_ok=True)
        with (race/"capture.lock").open("a") as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return {"race_id":key,"phase":"busy"}
            try:
                result=self._step(meta,race)
                atomic_state(race/"status.json",{**result,"checked_at":aware(self.clock()).isoformat()})
                return result
            except Exception as exc:
                atomic_state(race/"status.json",{"race_id":key,"phase":"error","error_type":type(exc).__name__,
                                                "reason":str(exc),"checked_at":aware(self.clock()).isoformat()})
                raise

    def _step(self,meta,race):
        key=identity(meta);now=aware(self.clock())
        deadline=datetime.strptime(str(meta["day"])+" "+meta["deadline"],"%Y%m%d %H:%M").replace(tzinfo=JST)
        remaining=(deadline-now).total_seconds()
        if (race/"forecast.json").exists():
            frozen=read(race/"forecast.json")
            if frozen["meta"]["deadline"]!=meta["deadline"]:
                raise ValueError("Deadline changed after freeze; retain original and investigate")
            if (race/"review.json").exists():return {"race_id":key,"phase":"reviewed"}
            if remaining > -180:return {"race_id":key,"phase":"frozen_waiting_result"}
            if (race/"result.json").exists():
                report=review(frozen,read(race/"result.json"))
                write_once(race/"review.json",report)
                return {"race_id":key,"phase":"reviewed","review_status":report["status"]}
            attempt=race/"result_attempt.json"
            if attempt.exists() and (now-aware(read(attempt)["at"])).total_seconds()<120:
                return {"race_id":key,"phase":"waiting_result"}
            atomic_state(attempt,{"at":now.isoformat()})
            envelope=self.client.read("raceresult",meta,max_age=60)
            self._check_envelope(envelope,meta)
            payout=parsers.parse_payout(envelope["html"])
            if payout["status"]=="pending":return {"race_id":key,"phase":"waiting_result"}
            result={"race_id":key,"status":payout["status"],"observed_at":envelope["fetched_at"],
                    "source_url":envelope["url"],"refund_lanes":payout["refund_lanes"]}
            if len(payout["payouts"])==1 and not result["refund_lanes"]:
                details=parsers.parse_result(envelope["html"],meta["day"],meta["jcd"],meta["rno"])
                result.update(trifecta=details["trifecta"],payout_per_100=details["payout_per_100"],winning_method=details["method"])
                if details["method"]=="恵まれ" or any(b["status"]!="finished" for b in details["finish"]):
                    result["status"]="accident"
                else:
                    result["boats"]=[{"lane":b["lane"],"racer_id":b["racer_id"],"finish":b["finish"],
                                      "actual_course":b.get("course"),"actual_st":b.get("st")} for b in details["finish"]]
            elif len(payout["payouts"])>1:result["status"]="special"
            report=review(frozen,result)
            write_once(race/"result.json",result);write_once(race/"review.json",report)
            return {"race_id":key,"phase":"reviewed","review_status":report["status"]}
        if remaining<180:
            if not (race/"missed.json").exists():
                write_once(race/"missed.json",{"race_id":key,"reason":"No valid source frozen >=3 minutes before deadline",
                                              "recorded_at":now.isoformat(),"mode":self.mode})
            return {"race_id":key,"phase":"missed_cutoff"}

        latest=race/"latest_data.json"
        if remaining<=240 and latest.exists():
            data=read(latest)
            age=(now-aware(data["meta"]["captured_at"])).total_seconds()
            if 0<=age<=90 and data["meta"]["deadline"]==meta["deadline"]:
                return self._save(data,meta,race)

        # Reuse an immutable research source only while it is fresh and identity-matched.
        data=None;reuse_error=None
        if self.fusion_root:
            path=self.fusion_root/"predictions"/str(meta["day"])/(key+".json")
            cp=self.fusion_root/"checkpoints"/str(meta["day"])/(key+".json")
            if path.exists() and cp.exists():
                original=read(path)
                age=(now-aware(original["created_at"])).total_seconds()
                if 0<=age<=90:
                    try:
                        if original.get("key")!=key:raise ValueError("Wrong cached research race")
                        if original.get("pre_race_weather",{}).get("entry_observed") is not True:raise ValueError("Source entry not observed")
                        data=from_fusion(original,read(cp))
                        if data["meta"]["deadline"]!=meta["deadline"]:raise ValueError("Source deadline mismatch")
                        if any(b.get("exhibition_time") is None for b in data["boats"]):raise ValueError("Source exhibition incomplete")
                    except (ValueError,KeyError) as exc:
                        reuse_error=str(exc);data=None

        state=read(race/"source_state.json") if (race/"source_state.json").exists() else {}
        if data is None:
            card=state.get("card")
            if card is None or (now-aware(card["fetched_at"])).total_seconds()>=300:
                envelope=self.client.read("racelist",meta,max_age=60)
                self._check_envelope(envelope,meta)
                if page_deadline(envelope["html"],meta["rno"])!=meta["deadline"]:raise ValueError("Official deadline changed")
                boats=parsers.parse_racelist_boats(envelope["html"])
                if len(boats)!=6:return {"race_id":key,"phase":"waiting_card"}
                card={"boats":boats,"fetched_at":envelope["fetched_at"],"source_url":envelope["url"]}
                state["card"]=card;atomic_state(race/"source_state.json",state)
                preparation={"race_id":key,"stage":"preparation","observed_at":envelope["fetched_at"],"boats":deepcopy(boats)}
                preparation["database"]=database_enrichment(self.db_root,preparation["boats"],meta,envelope["fetched_at"])
                p=race/"preparation"/(digest(preparation)+".json")
                if not p.exists():write_once(p,preparation)
            if remaining>3600:return {"race_id":key,"phase":"prepared"}
            now=aware(self.clock())
            if state.get("preview_attempt_at") and (now-aware(state["preview_attempt_at"])).total_seconds()<60:
                return {"race_id":key,"phase":"waiting_poll_interval"}
            # Persist attempts before I/O: failures must not cause a hot retry loop.
            state["preview_attempt_at"]=now.isoformat();atomic_state(race/"source_state.json",state)
            envelope=self.client.read("beforeinfo",meta,max_age=60);self._check_envelope(envelope,meta)
            if page_deadline(envelope["html"],meta["rno"])!=meta["deadline"]:raise ValueError("Official deadline changed")
            preview=parsers.parse_beforeinfo(envelope["html"])
            if preview["exhibition_count"]!=6 or not preview["entry_observed"]:
                return {"race_id":key,"phase":"waiting_exhibition","exhibition_count":preview["exhibition_count"]}
            boats=deepcopy(card["boats"])
            for b in boats:
                b.update(preview["boats"][b["lane"]]);b["course"]=b["predicted_course"]
                b["exhibition_st"]=b.get("exhibition_st_timing",b.get("exhibition_st"))
                b["observations"]=[{"field":"exhibition_time","observed_at":envelope["fetched_at"],"source":envelope["url"]}]
            foot_error=None;foot=None
            old_foot=state.get("foot")
            if old_foot and (aware(self.clock())-aware(old_foot["observed_at"])).total_seconds()<=90:
                foot=old_foot
            elif self.fetch_foot and remaining>=300:
                try:foot=self.foot_fetcher(meta,boats,self.clock)
                except Exception as exc:foot_error=type(exc).__name__+": "+str(exc)
                if foot:state["foot"]=foot;atomic_state(race/"source_state.json",state)
            if foot:
                reject_outcomes(foot)
                if not 0<=(aware(self.clock())-aware(foot["observed_at"])).total_seconds()<=90:raise ValueError("Foot timing is stale/future")
                by_lane={int(b["lane"]):b for b in foot["rows"]}
                if len(by_lane)!=6:raise ValueError("Incomplete foot lanes")
                for b in boats:
                    item=by_lane[b["lane"]]
                    if str(item["racer_id"])!=str(b["racer_id"]):raise ValueError("Foot roster mismatch")
                    for field in ["straight_time","turn_time","lap_time"]:b[field]=item.get(field)
                    b["observations"].append({"field":"foot_timings","observed_at":foot["observed_at"],"source":foot["source_url"]})
            observed=aware(self.clock()).isoformat()
            database=database_enrichment(self.db_root,boats,meta,observed)
            data={"meta":{**meta,"captured_at":observed,"source_observed_at":envelope["fetched_at"]},"boats":boats,
                  "environment":{k:v for k,v in preview.items() if k!="boats"},
                  "source":{"kind":"independent_official_collection","race_id":key,"card":{k:v for k,v in card.items() if k!="boats"},
                            "preview_url":envelope["url"],"preview_observed_at":envelope["fetched_at"],"database":database,
                            "foot_error":foot_error,"reuse_error":reuse_error,"baseline":"missing; no probabilities or virtual card fabricated"}}
            if database.get("snapshot_at"):data["meta"]["db_snapshot_at"]=database["snapshot_at"]

        return self._save(data,meta,race)

    def _save(self,data,meta,race):
        # Network/foot calls can consume the remaining time; recheck the real clock.
        key=identity(meta)
        if identity(data["meta"])!=key or data["meta"]["deadline"]!=meta["deadline"]:
            raise ValueError("Normalized snapshot race/deadline mismatch")
        deadline=datetime.strptime(str(meta["day"])+" "+meta["deadline"],"%Y%m%d %H:%M").replace(tzinfo=JST)
        generated=aware(self.clock())
        if (deadline-generated).total_seconds()<180:return {"race_id":key,"phase":"late_acquisition_not_frozen"}
        reject_outcomes(data)
        candidate=generate(data,mode=self.mode,now=generated.isoformat())
        candidate["collector_wall_clock_at"]=datetime.now(JST).isoformat()
        candidate["digest"]=digest({k:v for k,v in candidate.items() if k!="digest"})
        atomic_state(race/"latest_data.json",data)
        missing={str(b["lane"]):[f for f in ["straight_time","turn_time","lap_time"] if b.get(f) is None] for b in data["boats"]}
        revision=race/"revisions"/(candidate["input_digest"]+".json")
        if not revision.exists():write_once(revision,candidate)
        if (deadline-generated).total_seconds()<=240:
            write_once(race/"forecast.json",candidate)
            saved=aware(self.clock());eligible=(deadline-saved).total_seconds()>=180
            write_once(race/"local_receipt.json",{"forecast_digest":candidate["digest"],"saved_at":saved.isoformat(),
                                                   "eligible_local_freeze":eligible,"mode":self.mode,"remote_checkpoint_verified":False})
            return {"race_id":key,"phase":"frozen_local_only" if eligible else "late_local_save","missing":missing}
        return {"race_id":key,"phase":"exhibition_revision_saved","missing":missing}

    def _check_envelope(self,item,meta):
        if item.get("race_id")!=identity(meta):raise ValueError("Source race identity mismatch")
        age=(aware(self.clock())-aware(item["fetched_at"])).total_seconds()
        if not 0<=age<=90:raise ValueError("Source stale/future")
