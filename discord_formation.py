"""Lossless formation display for the combinations selected by the model."""
from itertools import combinations, product
import re


def unique_picks(picks):
    result = []
    for pick in picks:
        if not isinstance(pick, str) or not re.fullmatch(r'[1-6]-[1-6]-[1-6]', pick) or len(set(pick.split('-'))) != 3:
            raise ValueError('Invalid trifecta combination')
        if pick not in result:
            result.append(pick)
    return result


def expand_formation(text):
    positions = text.split('-')
    if len(positions) != 3 or any(not re.fullmatch(r'[1-6]+', position) for position in positions):
        raise ValueError('Invalid trifecta formation')
    return {'-'.join(order) for order in product(*positions) if len(set(order)) == 3}


def _projection(picks):
    orders = [pick.split('-') for pick in picks]
    return '-'.join(''.join(sorted({order[position] for order in orders})) for position in range(3))


def compress_picks(picks):
    """Merge only formations whose expansion exactly equals the original picks."""
    picks = unique_picks(picks)
    if not picks:
        return []
    whole = _projection(picks)
    if expand_formation(whole) == set(picks):
        return [{'text': whole, 'point_count': len(picks)}]
    groups = [{pick} for pick in picks]
    while True:
        best = None
        for i, j in combinations(range(len(groups)), 2):
            merged = groups[i] | groups[j]
            text = _projection(merged)
            if expand_formation(text) != merged:
                continue
            rank = (len(merged), -len(text), -i, -j)
            if best is None or rank > best[0]:
                best = (rank, i, j, merged)
        if best is None:
            break
        _, i, j, merged = best
        groups[i] = merged
        del groups[j]
    return [{'text': _projection(group), 'point_count': len(group)} for group in groups]


def formation_summary(main, cover=(), outsiders=()):
    seen = set()
    sections = []
    for key, title, picks in (
        ('main', '◎ 本線', main),
        ('cover', '○ 押さえ・別の頭', cover),
        ('outsiders', '△ 穴候補', outsiders),
    ):
        accepted = [pick for pick in unique_picks(picks) if pick not in seen]
        seen.update(accepted)
        if accepted:
            sections.append({'key': key, 'title': title, 'point_count': len(accepted), 'formations': compress_picks(accepted)})
    return {'point_count': len(seen), 'sections': sections}


def formation_lines(summary):
    lines = ['**3連単フォーメーション**']
    for section in summary['sections']:
        lines.append(f"**{section['title']}（{section['point_count']}点）**")
        lines.extend(f"`{item['text']}`（{item['point_count']}点）" for item in section['formations'])
    lines.append(f"**合計 {summary['point_count']}点（重複除外）**")
    return lines
