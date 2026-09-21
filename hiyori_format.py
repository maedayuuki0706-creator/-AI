"""Compact, mobile-readable Discord cards for Hiyori predictions."""
from collections import OrderedDict
from datetime import datetime
from discord_formation import unique_picks
from direct_discord_notify import VENUES


def ticket_lines(picks):
    # Group only equal first/second places: never add an unselected ticket.
    groups = OrderedDict()
    for pick in unique_picks(picks):
        first, second, third = pick.split('-')
        groups.setdefault((first, second), []).append(third)
    return [f"{first}-{second}-{''.join(sorted(thirds))}  （{len(thirds)}点）"
            for (first, second), thirds in groups.items()]


def make_payload(request, analysis, rows):
    picks = unique_picks([row['combination'] for row in rows])
    head = int(max(analysis['heads'], key=analysis['heads'].get))
    lead = next(f for f in analysis['features'] if int(f['lane']) == head)
    boat = next((b for b in analysis.get('inputs', []) if int(b['lane']) == head), {})
    name = str(boat.get('name') or '').replace('\n', ' ').strip()
    date = datetime.strptime(request['day'], '%Y%m%d').strftime('%m/%d')
    lines = [f"🌤️ **日和AI｜{VENUES[request['jcd']]} {request['rno']}R**",
             f"⏰ **締切 {request['deadline']}** ｜ {date}", '',
             f"🎯 **軸候補：{head}号艇{' ' + name if name else ''}**", '',
             f"🎫 **3連単｜合計 {len(picks)}点**", '```',
             *ticket_lines(picks), '```']
    reasons = []
    used = lead.get('used', [])
    if 'course_rates' in used and lead.get('course_win_rate') is not None:
        reasons.append(f"・{lead['course']}コース1着率：{lead['course_win_rate']*100:.1f}%（{int(lead['course_samples'])}走）")
    if 'course_st' in used and lead.get('course_st') is not None:
        reasons.append(f"・コース別平均ST：{lead['course_st']:.2f}")
    ranks = lead.get('motor_last10_ranks') or []
    if 'motor_last10' in used and ranks:
        reasons.append(f"・モーター直近{len(ranks)}走：2着以内 {sum(r <= 2 for r in ranks)}回")
    if reasons:
        lines += ['', f'🔎 **{head}号艇の判断材料**', *reasons]
    lines += ['', '日和データ反映・検証運用中']
    source = analysis.get('source_url')
    if source:
        lines.append(f'[出走データを見る](<{source}>)')
    text = '\n'.join(lines)
    if len(text.encode('utf-16-le')) // 2 > 2000:
        raise ValueError('Hiyori card exceeds Discord text limit')
    return {'content': text, 'allowed_mentions': {'parse': []}, 'flags': 4096}
