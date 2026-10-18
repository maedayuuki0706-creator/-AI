"""Virtual card settlement from explicit official winners and refund lanes.

Refund is returned stake, not a winning payout. No inferred odds or ROI.
"""
def settle(picks,winners,refund_lanes,unit=100):
    if len(picks)!=10 or len(set(picks))!=10 or unit!=100:raise ValueError('Fixed ten tickets x 100 yen required')
    if not isinstance(refund_lanes,list) or any(x not in range(1,7) for x in refund_lanes):
        return {'stake_yen':1000,'return_yen':None,'refund_yen':None,'roi':None,'torigami':None,'reason':'公式返還情報なし'}
    if not isinstance(winners,dict) or not winners or any(not isinstance(v,int) or v<=0 for v in winners.values()):
        return {'stake_yen':1000,'return_yen':None,'refund_yen':None,'roi':None,'torigami':None,'reason':'公式出目/配当不足'}
    returned=[p for p in picks if set(map(int,p.split('-')))&set(refund_lanes)]
    if any(p in winners for p in returned):raise ValueError('Refunded ticket cannot also be an official winning ticket')
    winning=sum(winners.get(p,0) for p in picks if p not in returned);refund=len(returned)*unit
    return {'stake_yen':1000,'winning_return_yen':winning,'refund_yen':refund,'return_yen':winning+refund,'hit':any(p in winners for p in picks),
            'roi':None,'torigami':None,'reason':'払戻/返還は公式記録から計算。オッズ原本がないためROI/トリガミ率は依頼条件に従い不明'}
