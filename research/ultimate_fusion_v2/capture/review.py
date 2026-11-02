"""Settled results cannot enter inference. No uncheckpointed forecasts in ROI."""
from research.ultimate_fusion_v1 import engine as e
from .checkpoint import verify_bundle

def review(bundle,receipt,result,observed_at):
    verify_bundle(bundle);key=bundle['race_id'];at=e.aware(observed_at)
    if receipt.get('sha256')!=e.digest({k:v for k,v in receipt.items() if k!='sha256'}):raise ValueError('receipt_digest_mismatch')
    if (receipt.get('race_id')!=key or receipt.get('bundle_sha256')!=bundle['sha256'] or receipt.get('report_sha256')!=bundle['report']['sha256']):raise ValueError('receipt_identity_mismatch')
    if receipt.get('status')!='confirmed_predeadline' or not e.aware(bundle['created_at'])<=e.aware(receipt['observed_remote_at'])<e.aware(bundle['deadline_at']):raise ValueError('no_predeadline_checkpoint')
    if result.get('race_id')!=key or at<e.aware(bundle['deadline_at']):raise ValueError('result_identity_or_time_invalid')
    if result.get('refund_lanes') or result.get('status')!='settled' or len(result.get('payouts',{}))!=1:
        return {'race_id':key,'status':'excluded_or_pending','reason':'refund_special_void_or_incomplete'}
    actual,paid=next(iter(result['payouts'].items()))
    if actual not in e.COMBOS or isinstance(paid,bool) or not isinstance(paid,int) or paid<=0:raise ValueError('invalid_payout')
    rows=bundle['report']['trifecta'];odds={x['combination']:x.get('official_odds') for x in rows}
    reports={}
    for model,field in [('fusion','research_picks'),('baseline','baseline_picks')]:
        picks=bundle['report'][field]
        if len(set(picks))!=10 or not set(picks)<=set(e.COMBOS):raise ValueError('invalid_frozen_card')
        reports[model]={'hit':actual in picks,'stake_yen':len(picks)*100,'return_yen':paid if actual in picks else 0}
    odd=odds.get(actual)
    return {'race_id':key,'status':'reviewed','mode':'checkpointed_prospective','result_observed_at':at.isoformat(),
            'actual':actual,'forecast_sha256':bundle['report']['sha256'],'receipt_sha256':receipt['sha256'],
            'official_predeadline_odds':odd,'odds_band':'unknown' if odd is None else '万舟帯' if odd>=100 else '中穴帯' if odd>=30 else '本線帯',
            'models':reports,'calibrated':False,'source_url':result.get('source_url')}
