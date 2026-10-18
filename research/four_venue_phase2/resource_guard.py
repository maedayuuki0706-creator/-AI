"""Read-only repository runner contention check; research yields to other jobs."""
import argparse,json,os,urllib.request

def decide(runs,current_run_id):
    active=[r for r in runs if str(r.get('id'))!=str(current_run_id) and r.get('status') in {'queued','in_progress','waiting','pending','requested'}]
    return {'allowed':not active,'reason':'他ジョブ実行/待機中のため研究側を見送る' if active else '他の実行/待機ジョブなし',
            'other_active_runs':[{'id':r['id'],'name':r.get('name'),'status':r['status']} for r in active]}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--repository',required=True);p.add_argument('--run-id',required=True);a=p.parse_args()
    try:
        headers={'Accept':'application/vnd.github+json','User-Agent':'FourVenuePhase2Research'}
        token=os.environ.get('GITHUB_TOKEN')
        if token:headers['Authorization']='Bearer '+token
        runs=[]
        for status in ['queued','in_progress','waiting','pending','requested']:
            url='https://api.github.com/repos/'+a.repository+'/actions/runs?status='+status+'&per_page=100'
            with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=10) as response:d=json.load(response)
            if d.get('total_count',0)>100:raise ValueError('Active run list truncated; deny')
            runs.extend(d.get('workflow_runs',[]))
        result=decide(runs,a.run_id)
    except Exception as e:result={'allowed':False,'reason':'負荷確認に失敗・研究を見送る: '+str(e)[:180]}
    print(json.dumps(result,ensure_ascii=False))
