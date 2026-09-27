"""PT1's exhibition-led three-boat BOX with distinct cover and longshots."""
from __future__ import annotations

from itertools import combinations, permutations
from math import isfinite, sqrt


POLICY = 'scent-box-exhibition-fusion-v1'


def _number(value):
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _probabilities(analysis):
    rows = {row['combination']: _number(row.get('probability'))
            for row in analysis['trifecta']}
    if len(rows) != 120 or any(p is None or p < 0 for p in rows.values()):
        raise ValueError('A complete 120-combination model is required')
    total = sum(rows.values())
    if total <= 0:
        raise ValueError('Empty model probabilities')
    return {combo: p / total for combo, p in rows.items()}


def select(existing, hiyori, odds, existing_native=(), hiyori_native=(), pt3_picks=()):
    """Return a deterministic card; odds and all exhibition evidence are observed inputs."""
    if existing.get('preview', {}).get('exhibition_count') != 6:
        raise ValueError('The six official exhibition records are required')
    if hiyori.get('preview', {}).get('exhibition_count') != 6:
        raise ValueError('The six Hiyori exhibition records are required')
    ep, hp = _probabilities(existing), _probabilities(hiyori)
    if ep.keys() != hp.keys():
        raise ValueError('The two models must cover the same combinations')
    mixed = {c: .5 * ep[c] + .5 * hp[c] for c in ep}
    boats = {int(b['lane']): b for b in hiyori['inputs']}
    if set(boats) != set(range(1, 7)):
        raise ValueError('Six unique boats are required')

    # A modest bonus for agreement between the live existing/Hiyori/PT3 cards.
    # The dominant term is the probability that exactly these three boats finish.
    votes = {lane: 0 for lane in boats}
    for card in (existing_native, hiyori_native, pt3_picks):
        for combo in list(card)[:10]:
            for lane in set(map(int, combo.split('-'))):
                votes[lane] += 1
    def six(lanes):
        return ['-'.join(map(str, p)) for p in permutations(lanes)]
    groups = []
    for lanes in combinations(range(1, 7), 3):
        combos = six(lanes)
        mass = sum(mixed[c] for c in combos)
        agreement = sum(votes[lane] for lane in lanes) / 90.0
        groups.append((mass + .018 * agreement, mass, lanes, combos))
    _, box_mass, lanes, box = max(groups, key=lambda g: (g[0], g[1], tuple(-n for n in g[2])))
    outside = sorted(set(boats) - set(lanes))

    # A coherent two-by-two formation, e.g. 1-45-23. Use two points when the
    # weaker two have little probability instead of paying for four by default.
    formations = []
    for head in lanes:
        seconds = sorted(set(lanes) - {head})
        for thirds in combinations(outside, 2):
            picks = [f'{head}-{second}-{third}' for second in seconds for third in thirds]
            formations.append((sum(mixed[c] for c in picks), head, seconds, thirds, picks))
    _, head, seconds, thirds, formation = max(
        formations, key=lambda f: (f[0], -f[1], tuple(-n for n in f[3])))
    ordered_cover = sorted(formation, key=lambda c: (-mixed[c], c))
    cover = formation if mixed[ordered_cover[-1]] >= .35 * mixed[ordered_cover[0]] else ordered_cover[:2]
    cover = sorted(cover, key=lambda c: (-mixed[c], c))

    # Odds are required to call something an "穴目". Unknown odds never become
    # zero odds or a fabricated value bet. This is a capped, experimental rule.
    excluded = set(box) | set(cover)
    long_candidates = []
    for combo, p in mixed.items():
        odd = _number(odds.get(combo))
        if combo in excluded or odd is None or odd < 30 or p < .002 or p * odd < .8:
            continue
        long_candidates.append((p * odd * sqrt(p), combo))
    longshots = [c for _, c in sorted(long_candidates, key=lambda r: (-r[0], r[1]))[:3]]
    picks = box + cover + longshots
    assert len(picks) == len(set(picks))

    marginals = {lane: sum(p for c, p in mixed.items() if str(lane) in c.split('-'))
                 for lane in boats}
    scent = max(lanes, key=lambda lane: (marginals[lane], -lane))
    observed_st = {lane: _number(boats[lane].get('exhibition_st')) for lane in boats}
    available_st = sorted(((st, lane) for lane, st in observed_st.items() if st is not None))
    attacker = (hiyori.get('race_shape') or {}).get('best_attack_lane')
    method = (hiyori.get('race_shape') or {}).get('best_attack_method')
    descriptions = {}
    for lane in lanes:
        parts = []
        if observed_st[lane] is not None:
            parts.append(f"展示ST {observed_st[lane]:.2f}")
            if len(available_st) == 6 and lane in [n for _, n in available_st[:2]]:
                parts.append('展示ST上位')
        if lane == attacker:
            parts.append(f'展開の攻め候補（{method}）' if method else '展開の攻め候補')
        parts.append(f'3着内推定 {marginals[lane]:.0%}')
        descriptions[str(lane)] = '・'.join(parts)
    chosen = [(mixed[c], _number(odds.get(c))) for c in picks]
    odds_complete = all(odd is not None and odd > 0 for _, odd in chosen)
    second_text = ''.join(map(str, seconds))
    third_text = ''.join(map(str, thirds))
    return {
        'selection_policy': POLICY,
        'box_lanes': list(lanes), 'box_picks': box,
        'cover_picks': cover, 'longshot_picks': longshots,
        'cover_formation': (f'{head}-{second_text}-{third_text}' if len(cover) == 4 else None),
        'main_picks': box, 'picks': picks, 'point_count': len(picks),
        'stake_yen': len(picks) * 100, 'box_mass': box_mass,
        'scent_lane': scent, 'boat_reasons': descriptions,
        'race_shape': hiyori.get('race_shape') or {},
        'probability_mass': sum(p for p, _ in chosen),
        'odds_complete': odds_complete,
        'estimated_return_yen': (sum(100 * p * odd for p, odd in chosen)
                                 if odds_complete else None),
    }
