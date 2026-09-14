"""Readable daily review: one overview and one complete message per venue."""
from datetime import datetime

from discord_formation import formation_summary
import direct_discord_notify as base

LABELS = {'main': '本線', 'cover': '抑え', 'outsiders': '穴'}
LINE = '━━━━━━━━━━━━'


def percent(value):
    return '—' if value is None else f'{value:.1f}%'


def money(stats):
    return (f"投資 {stats['settled_stake_yen']:,}円 → 回収 {stats['return_yen']:,}円"
            f"（返還 {stats['refund_yen']:,}円含む）\n"
            f"収支 {stats['profit_yen']:+,}円／回収率 {percent(stats['roi'])}")


def hit_text(stats):
    return f"{stats['virtual_hits']}/{stats['virtual_hit_samples']}R＝{percent(stats['hit_rate'])}"


def prediction_lines(race):
    summary = formation_summary(race.get('main') or [], race.get('cover') or [], race.get('outsiders') or [])
    lines = []
    for section in summary['sections']:
        forms = ' ／ '.join(item['text'] for item in section['formations'])
        lines += [f"**{LABELS[section['key']]}（{section['point_count']}点）**", forms]
    return lines


def race_field(rno, race):
    if race is None:
        return {'name': f'{rno}レース', 'value': '予想配信記録なし（成績集計の対象外）\n' + LINE, 'inline': False}
    official, uniform = race['official'], race['uniform']
    result = '／'.join(f"{combo}（{yen:,}円）" for combo, yen in official.get('payouts', {}).items())
    lines = prediction_lines(race)
    if official['status'] == 'pending':
        lines += ['結果：確認待ち', '判定：保留']
    elif official['status'] == 'void':
        lines += ['結果：中止・不成立', '判定：全点返還（的中率対象外）']
    elif official['status'] == 'special':
        lines += [f"結果：特払い {official['special_per_100']:,}円／100円", '判定：特払い（的中率対象外）']
    else:
        lines.append('**結果：' + result + '**')
        if not uniform['hit_eligible']:
            lines.append('判定：選んだ全点が返還（的中率対象外）')
        elif race['hit_sections']:
            lines.append('🎯 ' + '・'.join(LABELS[s] for s in race['hit_sections']) + '的中')
        else:
            lines.append('❌ 不的中')
    if official.get('refund_lanes'):
        lines.append('返還艇：' + '・'.join(map(str, official['refund_lanes'])) + '号艇')
    if official['status'] != 'pending':
        lines.append(f"全点各100円：{uniform['stake_yen']:,}円→{uniform['return_yen']:,}円（返還{uniform['refund_yen']:,}円含む）")
    if not race['plan_recorded']:
        lines.append('仮想投票：配分未記録')
    elif not race['stake_yen']:
        lines.append('仮想投票：見送り・0円')
    elif official['status'] != 'pending':
        lines.append(f"仮想記録：{race['stake_yen']:,}円→{race['return_yen']:,}円")
    sent = datetime.fromisoformat(race['sent_at']).astimezone(base.JST)
    phase = '直前更新' if race.get('phase') == 'final' else '暫定予想'
    lines.append(f'{phase}・{sent:%H:%M}送信記録')
    if official.get('source_url'):
        lines.append(f"[公式結果]({official['source_url']})")
    lines.append(LINE)
    return {'name': f"{rno}レース｜予想{len(race['picks'])}点", 'value': '\n'.join(lines), 'inline': False}


def _payload(title, description, fields):
    embed = {'title': title, 'description': description, 'color': 0x176B87, 'fields': fields,
             'footer': {'text': '3連単払戻は100円当たり。買い目は締切前の最新配信。結果待ち・全点返還・特払いは的中率対象外。'}}
    length = lambda s: len(s.encode('utf-16-le')) // 2
    total = length(title) + length(description) + length(embed['footer']['text'])
    total += sum(length(f['name']) + length(f['value']) for f in fields)
    if total > 6000 or len(fields) > 25 or any(length(f['value']) > 1024 for f in fields):
        raise ValueError('Daily venue report exceeds Discord embed limit')
    return {'embeds': [embed], 'allowed_mentions': {'parse': []}}


def report_payloads(report):
    day, actual, uniform = report['day'], report['totals'], report['uniform_totals']
    date = f'{day[:4]}/{day[4:6]}/{day[6:8]}'
    label = '暫定' if actual['pending_races'] or not report['coverage_verified'] else '記録分の結果照合済み'
    sections = report['section_totals']
    section_lines = [f"{LABELS[key]}：的中{hit_text(stats)}／{stats['bet_points']}点／回収率 {percent(stats['roi'])}"
                     for key, stats in sections.items()]
    phase_lines = [f"{'直前更新' if key == 'final' else '朝の予想' if key == 'morning' else '暫定更新'}：{hit_text(stats)}"
                   for key, stats in report['comparisons']['phase'].items()]
    points_lines = [f"{key}点：{hit_text(stats)}／回収率 {percent(stats['roi'])}"
                    for key, stats in sorted(report['comparisons']['points'].items(), key=lambda item: int(item[0]))]
    grade_lines = [f"評価{key}：{hit_text(stats)}" for key, stats in sorted(report['comparisons']['grade'].items())]
    missing = {}
    for key in report['missing_predictions']:
        jcd, rno = key.split(':')
        missing.setdefault(jcd, []).append(int(rno))
    missing_text = '\n'.join(f"{base.VENUES[jcd]}：{','.join(map(str, sorted(races)))}R" for jcd, races in sorted(missing.items())) or 'なし'
    issue = (f"予想内的中{uniform['virtual_hits']}Rに対し、仮想投票の的中は{actual['virtual_hits']}R。"
             'まず買い目の選別条件を検証する。\n'
             '直前更新・暫定予想、点数ごとに分けて記録を増やす。1日だけで優劣を確定しない。\n'
             '評価未記録の予想をA/B/Cに混ぜない。未配信は不的中に数えず、送信漏れとして追跡する。')
    fields = [
        {'name': '全予想を各点100円で検証', 'value': f"{uniform['bet_points']}点・{uniform['bet_units']}口\n的中 {hit_text(uniform)}\n" + money(uniform), 'inline': False},
        {'name': '配信時に記録した仮想投票', 'value': f"{actual['bet_races']}R・{actual['bet_points']}点・{actual['bet_units']}口\n的中 {hit_text(actual)}\n" + money(actual) + f"\n見送り {actual['pass_races']}R／配分未記録 {actual['unrecorded_plans']}R", 'inline': False},
        {'name': '本線・抑え・穴', 'value': '\n'.join(section_lines) or '対象なし', 'inline': False},
        {'name': '点数別／配信段階別', 'value': '\n'.join(points_lines + phase_lines) or '対象なし', 'inline': False},
        {'name': '記録された評価別', 'value': '\n'.join(grade_lines) or '対象なし', 'inline': False},
        {'name': '改善に向けた確認事項', 'value': issue, 'inline': False},
        {'name': '予想配信記録なし（集計外）', 'value': missing_text, 'inline': False}]
    overview = (f"{date}｜{label}\n開催{report['expected_races']}R／予想記録{actual['predicted_races']}R／記録なし{len(report['missing_predictions'])}R\n"
                f"結果確認 {actual['resolved_races']}R／結果待ち {actual['pending_races']}R\n"
                f"全予想の照合：{uniform['prediction_hits']}/{uniform['prediction_samples']}R。下の的中率は全点返還等を除く。\n"
                '全点100円は比較用の試算。仮想記録とは別集計です。')
    payloads = [_payload('全体日報｜' + date, overview, fields)]
    venues = sorted(set(report['venues']) | set(missing))
    for jcd in venues:
        races = {r['rno']: r for r in report['races'] if r['jcd'] == jcd}
        stats = report['venues'].get(jcd)
        if stats:
            u = stats['uniform']
            desc = (f"{label}／予想記録{stats['predicted_races']}/12R\n"
                    f"**全点各100円：的中 {hit_text(u)}**\n{money(u)}\n"
                    f"仮想記録：{stats['settled_stake_yen']:,}円→{stats['return_yen']:,}円／回収率 {percent(stats['roi'])}")
        else:
            desc = '予想配信記録なし。成績の集計対象外。'
        payloads.append(_payload(f'{base.VENUES[jcd]}｜{date} 日報', desc, [race_field(rno, races.get(rno)) for rno in range(1, 13)]))
    return payloads


def payload_text(payload):
    embed = payload['embeds'][0]
    lines = ['## ' + embed['title'], '', embed['description'], '']
    for field in embed['fields']:
        lines += ['### ' + field['name'], '', field['value'], '']
    lines.append(embed['footer']['text'])
    return '\n'.join(lines)
