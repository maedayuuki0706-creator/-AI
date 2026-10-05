"""Continue short production runs independently of cron, without restarting active jobs."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import time
import urllib.request

API = 'https://api.github.com/repos/maedayuuki0706-creator/-AI'
DISPATCHER = 'discord-delivery-v2-production.yml'
TARGETS = ('discord_notify.yml', 'prototype3-delivery.yml', 'sokuhou-delivery.yml',
           'hiyori-discord.yml', 'prototype12-delivery.yml')
INTERVAL_SECONDS = 300


def request(path, payload=None):
    token = os.getenv('GITHUB_TOKEN', '').strip()
    if not token:
        raise RuntimeError('Production wake-up requires GITHUB_TOKEN with actions:write')
    req = urllib.request.Request(API+path, method='GET' if payload is None else 'POST',
        data=None if payload is None else json.dumps(payload).encode(),
        headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
                 'Content-Type': 'application/json', 'User-Agent': 'boat-ai-delivery-v2-wakeup',
                 'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response) if response.status != 204 else {}


def wake(workflow, *, api=request, now=None, current_run_id='', continuation=False):
    now = now or datetime.now(timezone.utc)
    config = api('/actions/workflows/'+workflow)
    # Preserve workflows intentionally disabled by their owner.
    if config.get('state') != 'active':
        return {'workflow': workflow, 'status': 'disabled'}
    rows = api(f'/actions/workflows/{config["id"]}/runs?branch=main&per_page=5')['workflow_runs']
    others = [row for row in rows if str(row['id']) != str(current_run_id)]
    if any(row['status'] != 'completed' for row in others):
        return {'workflow': workflow, 'status': 'already_active'}
    if not continuation and others:
        last = max(datetime.fromisoformat(row['created_at'].replace('Z','+00:00')) for row in others)
        if (now-last).total_seconds() < INTERVAL_SECONDS:
            return {'workflow': workflow, 'status': 'recent_run'}
    payload = {'ref': 'main'}
    if continuation:
        payload['inputs'] = {'wake_reason': 'continuation'}
    # Do not retry an ambiguous POST: it may already have queued the next run.
    api(f'/actions/workflows/{config["id"]}/dispatches', payload)
    return {'workflow': workflow, 'status': 'requested', 'event': 'workflow_dispatch'}


def run_once(*, api=request, now=None, current_run_id='', targets=TARGETS):
    report = []
    for workflow in targets:
        try:
            report.append(wake(workflow, api=api, now=now))
        except Exception as exc:
            report.append({'workflow': workflow, 'status': 'error', 'error_type': type(exc).__name__})
    # A legacy job failure must not prevent continuing the V2 production dispatcher.
    report.append(wake(DISPATCHER, api=api, now=now, current_run_id=current_run_id,
                       continuation=True))
    return report


def main():
    if os.getenv('DISCORD_DELIVERY_V2_CONTINUATION_ENABLED', '1') == '0':
        print('Production continuation disabled; existing cron remains enabled', flush=True)
        return 0
    if os.getenv('GITHUB_REF') != 'refs/heads/main':
        print('Production wake-up skipped outside main', flush=True)
        return 0
    # Prevent a tight loop on days with no imminent races, while keeping every run short.
    started = os.getenv('DELIVERY_V2_RUN_STARTED_AT', '')
    if started:
        elapsed = (datetime.now(timezone.utc)-datetime.fromisoformat(started)).total_seconds()
        delay = max(0, 120-elapsed)
        while delay > 0:
            pause = min(30, delay)
            time.sleep(pause)
            delay -= pause
    try:
        report = run_once(current_run_id=os.getenv('GITHUB_RUN_ID', ''))
        print('Delivery wake-up '+json.dumps(report, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        print(f'::error::Delivery wake-up failed ({type(exc).__name__}); cron remains enabled', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
