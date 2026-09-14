"""Durable intent and acknowledgement; never blindly retry an unknown POST."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

import notification_audit as audit
from persist_notification_state import checkpoint

OUTBOX_ROOT = Path('data/notification_outbox')


class DeadlinePassed(RuntimeError):
    pass


class SendRejected(RuntimeError):
    pass


class SendUnknown(RuntimeError):
    pass


def post_json(url, payload, *, can_send=None, pause=time.sleep):
    if not url:
        raise SendRejected('Discord connection is missing')
    parts = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parts.query))
    query['wait'] = 'true'
    target = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))
    request = urllib.request.Request(target, data=json.dumps(payload, ensure_ascii=False).encode(),
                                    headers={'Content-Type':'application/json','User-Agent':'Boat-AI-Navi/4.0'}, method='POST')
    for attempt in range(3):
        if can_send is not None and not can_send():
            raise DeadlinePassed('Send cutoff passed')
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                message = json.load(response)
            if not str(message.get('id','')).isdigit() or not str(message.get('channel_id','')).isdigit():
                raise SendUnknown('Discord returned no message/channel ID')
            return message
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                try:
                    delay = float(json.loads(exc.read()).get('retry_after',1))
                except (ValueError, TypeError):
                    delay = 1
                if 0 <= delay <= 30:
                    audit.emit('send_retry',http_status=429,retry_after=delay)
                    pause(delay+.25)
                    continue
            if 400 <= exc.code < 500:
                raise SendRejected(f'Discord HTTP {exc.code}') from None
            raise SendUnknown(f'Discord HTTP {exc.code}; delivery outcome unknown') from None
        except SendUnknown:
            raise
        except Exception as exc:
            raise SendUnknown('Discord acknowledgement failed: '+type(exc).__name__) from None
    raise SendRejected('Discord rate limit')


def record_key(record):
    return ':'.join(str(record.get(k,'')) for k in ('day','jcd','rno','phase','record_type','destination','digest'))


def outbox_path(records):
    digest=hashlib.sha256('\n'.join(record_key(r) for r in records).encode()).hexdigest()
    return OUTBOX_ROOT / records[0]['day'] / (digest+'.json')


def save(path, obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    with temp.open('w',encoding='utf-8') as stream:
        json.dump(obj,stream,ensure_ascii=False,sort_keys=True)
        stream.write('\n');stream.flush();os.fsync(stream.fileno())
    temp.replace(path)


def evidence(record):
    return {key:record.get(key) for key in ('day','jcd','rno','phase','deadline','record_type')}


def deliver(content, records, *, sender, writer, can_send=None):
    path=outbox_path(records)
    old=json.loads(path.read_text()) if path.exists() else {}
    if old.get('status')=='confirmed':
        for row in old['records']:
            writer(row)
        audit.emit('skip_reason',**evidence(records[0]),reason='already_acknowledged')
        return False
    if old.get('status') in ('intent','unknown'):
        audit.emit('skip_reason',**evidence(records[0]),reason='send_outcome_unknown')
        raise SendUnknown('An earlier POST has no conclusive acknowledgement')
    state={'status':'intent','records':records,'run_id':audit.RUN_ID,
           'content_sha256':hashlib.sha256(content.encode()).hexdigest()}
    save(path,state)
    audit.emit('send_started',**evidence(records[0]),record_count=len(records))
    try:
        checkpoint(required=True)
    except Exception:
        save(path,{**state,'status':'not_sent'})
        checkpoint()
        raise
    try:
        if can_send is not None and not can_send():
            raise DeadlinePassed('Send cutoff passed')
        message=sender(content,can_send=can_send)
        if not isinstance(message,dict) or not str(message.get('id','')).isdigit() or not str(message.get('channel_id','')).isdigit():
            raise SendUnknown('Discord acknowledgement has no message/channel ID')
    except (SendRejected,DeadlinePassed) as exc:
        save(path,{**state,'status':'not_sent'})
        audit.emit('skip_reason' if isinstance(exc,DeadlinePassed) else 'send_failed',**evidence(records[0]),
                   reason='deadline_before_send' if isinstance(exc,DeadlinePassed) else 'discord_rejected',
                   error_type=type(exc).__name__)
        checkpoint()
        raise
    except Exception as exc:
        save(path,{**state,'status':'unknown'})
        audit.emit('send_unknown',**evidence(records[0]),error_type=type(exc).__name__)
        checkpoint()
        raise
    acknowledged=[{**record,'sent_at':datetime.now(audit.JST).isoformat(),
                   'message_id':message['id'],'channel_id':message['channel_id'],
                   'run_id':audit.RUN_ID,'run_attempt':audit.RUN_ATTEMPT,
                   'content_sha256':state['content_sha256']} for record in records]
    save(path,{**state,'status':'confirmed','message_id':message['id'],'records':acknowledged})
    for row in acknowledged:
        audit.emit('send_success',**evidence(row),message_id=row['message_id'],channel_id=row['channel_id'])
    try:
        for row in acknowledged:
            writer(row)
            audit.emit('persist_success',**evidence(row),scope='local',message_id=row['message_id'])
    except Exception as exc:
        audit.emit('persist_failed',**evidence(records[0]),scope='local',error_type=type(exc).__name__)
        raise
    finally:
        checkpoint(required=True)
    return True


def recover_predictions(writer, existing):
    for path in sorted(OUTBOX_ROOT.glob('*/*.json')):
        state=json.loads(path.read_text())
        if state.get('status')!='confirmed':
            continue
        for row in state.get('records',[]):
            if row.get('record_type') or row.get('phase') not in ('morning','preliminary','final'):
                continue
            key=(row['day'],row['jcd'],int(row['rno']),row['phase'])
            if key not in existing:
                writer(row);existing.add(key)
                audit.emit('persist_success',**evidence(row),scope='local_recovery',message_id=row['message_id'])
    return existing
