"""Normalize raw measurement windows and preserve portable benchmark evidence."""
import argparse
import copy
import csv
import json
from pathlib import Path
import tarfile
from metrics import distribution

p=argparse.ArgumentParser()
p.add_argument('root',type=Path)
p.add_argument('output',type=Path)
a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
all_results=[]
batches=['baseline','shm-baseline','stress','limits','sustained','browser-pilot','browser-full','browser-auto-gpu','browser-fixed-repeat','fragment-diagnostic','fragment-sustained']
for batch in batches:
    file=a.root/batch/'results.json'
    if not file.exists():continue
    for i,original in enumerate(json.loads(file.read_text())):
        r=copy.deepcopy(original);c=r['case'];r['batch']=batch
        folder=file.parent/f'{i:02d}-{c["name"]}-{c["mode"]}'
        r['native_binary']=json.loads((file.parent/'environment.json').read_text())['native']
        if r.get('start') and r.get('end'):
            # Early baseline sampler could finish after the fixed data window.
            # Normalize all frame/source counters from timestamps, without changing CPU samples.
            end=min(r['end'],r['start']+c.get('seconds',15));duration=end-r['start']
            r['cpu_duration']=r.get('cpu_duration',r['duration'])
            r['measurement_end']=end;r['measurement_seconds']=duration
            for name in ['source','probe']:
                rows=[]
                for line in (folder/f'{name}.csv').read_text().splitlines():
                    now,stamp=map(int,line.split(','))
                    if r['start']*1e9<=now<=end*1e9:rows.append((now,stamp))
                r[name]={'frames':len(rows),'hz':len(rows)/duration,'age_ms':distribution([(n-s)/1e6 for n,s in rows])}
            traces=sorted(folder.glob('client-*.json'))
            for client,trace in zip(r.get('clients',[]),traces):
                raw=json.loads(trace.read_text());frames=[f for f in raw['frames'] if r['start']<=f[0]<=end]
                client.update(frames=len(frames),hz=len(frames)/duration,mib_s=sum(f[1] for f in frames)/1048576/duration,
                              age_ms=distribution([f[2] for f in frames]))
            for client in r.get('clients',[]):
                client['teardown_errors']=[e for e in client['errors'] if isinstance(e,str) and e.startswith('AssertionError: cannot reset()') and (client.get('closed_at') or 0)>end]
                client['measurement_errors']=[e for e in client['errors'] if e not in client['teardown_errors']]
            if 'browser' in r:
                browser=r['browser'];d=browser['end']-browser['start']
                r['browser_summary']={'seconds':d,'ws_hz':len(browser['frames'])/d,'worker_hz':len(browser['decodes'])/d,
                    'draw_fps':len(browser['draws'])/d,'new_frame_hz':len(browser['updates'])/d,
                    'worker_ms':distribution([x[1] for x in browser['decodes']]),
                    'first_draw_age_ms':distribution([x[1] for x in browser['updates']]),
                    'ws_age_ms':distribution([x[2] for x in browser['frames']]),
                    'draw_points':distribution([x[1] for x in browser['draws']]),
                    'stream_last_frame_gap_s':(browser['end']-browser['frames'][-1][0]/1000) if browser['frames'] else None,
                    'long_tasks':distribution(browser['longTasks']),'renderer':browser['renderer'],'errors':browser['errors'],
                    'browser_cpu_percent':sum(v for k,v in r['cpu_percent'].items() if k.startswith('chrome_') or k=='browser'),
                    'browser_rss_peak_sum_mib':sum(v['max'] for k,v in r['rss_mib'].items() if k.startswith('chrome_') or k=='browser')}
                del r['browser']
        all_results.append(r)
(a.output/'results.json').write_text(json.dumps(all_results,indent=2)+'\n')
columns=['batch','name','mode','points','target_hz','source_hz','dds_hz','clients','client_hz_min','total_mib_s','server_cpu_percent','receiver_cpu_percent','rss_peak_mib','age_p95_ms','ping_p95_ms','stop_reason','fatal']
with (a.output/'summary.csv').open('w') as f:
    writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader()
    for r in all_results:
        c=r['case'];clients=r.get('clients',[])
        writer.writerow(dict(batch=r['batch'],name=c['name'],mode=c['mode'],points=c['points'],target_hz=c['hz'],
          source_hz=r.get('source',{}).get('hz'),dds_hz=r.get('probe',{}).get('hz'),clients=len(clients),
          client_hz_min=min((x['hz'] for x in clients),default=None),total_mib_s=sum(x['mib_s'] for x in clients),
          server_cpu_percent=r.get('cpu_percent',{}).get('server'),receiver_cpu_percent=r.get('cpu_percent',{}).get('receiver'),
          rss_peak_mib=r.get('rss_mib',{}).get('server',{}).get('max'),
          age_p95_ms=max((x['age_ms']['p95'] or 0 for x in clients),default=None),
          ping_p95_ms=max((x['ping_ms']['p95'] or 0 for x in clients),default=None),stop_reason=r.get('stop_reason'),fatal=r.get('fatal')))
# Keep per-frame times, resource samples, exact plans and process logs, never map payloads.
with tarfile.open(a.output/'raw-evidence.tar.gz','w:gz') as archive:
    for batch in batches:
        folder=a.root/batch
        if folder.exists():
            for file in sorted(folder.rglob('*')):
                if file.is_file() and file.suffix in ('.json','.csv','.log'):
                    archive.add(file,arcname=str(file.relative_to(a.root)))
    for file in sorted(a.root.glob('*plan.json')):archive.add(file,arcname=file.name)
    for file in sorted(a.root.glob('*.json')):
        if file.stem in ['indoor','indoor_dense','outdoor']:archive.add(file,arcname=file.name)
print(f'{len(all_results)} cases collected into {a.output}')
