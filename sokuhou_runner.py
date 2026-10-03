"""Run Sokuhou independently of the long prediction watcher."""
from datetime import datetime
import os
from zoneinfo import ZoneInfo

import hit_alerts
import hit_alerts_fast
import persist_runtime_data
import sokuhou_character
import sokuhou_delivery
import sokuhou_health
import yuuki_hit_alerts


def run():
    if sokuhou_delivery.paused():
        print('Sokuhou delivery is paused by policy', flush=True)
        return 0
    day = datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y%m%d')
    sokuhou_character.install(hit_alerts)
    failed = 0
    for name, checker in [('main/mid/longshot', hit_alerts_fast.check_and_send), ('yuuki', yuuki_hit_alerts.run)]:
        try:
            count = checker(day)
            print(f'Sokuhou {name}: {count} confirmed receipts recorded', flush=True)
        except Exception as exc:
            failed = 1
            print(f'::error::Sokuhou {name} needs review: {type(exc).__name__}', flush=True)
    try:
        persist_runtime_data.persist(('data/hit_alert_deliveries.jsonl',
                                      'data/prototype3_delivery/hit_alerts/',
                                      'data/sokuhou_recovery/'))
    except Exception as exc:
        failed = 1
        print(f'::error::Sokuhou journal checkpoint failed: {type(exc).__name__}', flush=True)
    try:
        failed = max(failed, sokuhou_health.audit(day))
    except Exception as exc:
        failed = 1
        print(f'::error::Sokuhou receipt audit failed: {type(exc).__name__}', flush=True)
    return failed


if __name__ == '__main__':
    raise SystemExit(run())
