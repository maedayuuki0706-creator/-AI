"""Strict live-input CLI. Refuses settled/stale sources, saves uncheckpointed output."""
import argparse
from datetime import datetime
import json
from pathlib import Path
from research.ultimate_fusion_v1 import engine as v1
from .core import fit,predict,save_immutable

def main():
    p=argparse.ArgumentParser();p.add_argument('--snapshot',required=True);p.add_argument('--observations')
    p.add_argument('--history-root',default='data/exhibition_log');p.add_argument('--output',required=True)
    a=p.parse_args();now=datetime.now(v1.JST).isoformat()
    raw=json.loads(Path(a.snapshot).read_text());snapshot=v1.prepare_live(raw,observed_at=now)
    history=[json.loads(x.read_text()) for x in sorted(Path(a.history_root).rglob('*.json'))]
    model=fit(history,snapshot['day'],snapshot['venue_code'])
    if model['training_races']<30:raise ValueError('insufficient_venue_history')
    observations=json.loads(Path(a.observations).read_text()) if a.observations else []
    report=predict(snapshot,model,observations,now=now)
    print(save_immutable(report,a.output))

if __name__=='__main__':main()
