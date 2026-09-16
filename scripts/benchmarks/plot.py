"""Generate static performance figures from collect.py's normalized results."""
import argparse
import json
from pathlib import Path
import statistics
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
p=argparse.ArgumentParser();p.add_argument('results',type=Path);a=p.parse_args()
rows=json.loads(a.results.read_text());out=a.results.parent
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.facecolor':'white'})
colors={'v1':'#64748b','v1-uncapped':'#64748b','v2':'#0284c7','diagnostic':'#16a34a'}
fig,axes=plt.subplots(2,2,figsize=(12,8),layout='constrained')
base=[r for r in rows if r['batch']=='shm-baseline' and not r.get('fatal')]
labels=['Indoor 190k @10Hz','Indoor 393k @5Hz','Outdoor 315k @5Hz'];points=[189966,393362,315397]
for mode,offset in [('v1',-.18),('v2',.18)]:
    groups=[[r for r in base if r['case']['mode']==mode and r['case']['points']==n] for n in points]
    cpu=[statistics.mean(r['cpu_percent']['server'] for r in g) for g in groups]
    age=[statistics.mean(r['clients'][0]['age_ms']['p95'] for r in g) for g in groups]
    x=np.arange(3)+offset
    for ax,y in [(axes[0,0],cpu),(axes[0,1],age)]:
        bars=ax.bar(x,y,.34,label=mode,color=colors[mode]);ax.bar_label(bars,fmt='%.1f',padding=3,fontsize=9)
        ax.set_xticks(range(3),labels,rotation=10);ax.margins(y=.2);ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
axes[0,0].set(title='Equal map output: backend CPU',ylabel='CPU % (100% = one core)');axes[0,0].legend()
axes[0,1].set(title='Equal map output: source to WebSocket',ylabel='Mean run P95 message age (ms)')
for ax,n,title in [(axes[1,0],189966,'190k points / 2.17 MiB per map'),(axes[1,1],650000,'650k points / 7.44 MiB per map')]:
    for batch,mode,label,color,style in [('stress','v1-uncapped','v1, rate cap disabled',colors['v1'],'-'),('stress','v2','Current v2',colors['v2'],'-'),('fragment-diagnostic','v2','v2 diagnostic, no fragmentation',colors['diagnostic'],'--')]:
        data=sorted([r for r in rows if r['batch']==batch and r['case']['mode']==mode and r['case']['points']==n and not r.get('fatal') and not r['case'].get('count_fragments') and r['case'].get('clients',1)==1],key=lambda r:r['case']['hz'])
        if data:ax.plot([r['case']['hz'] for r in data],[r['clients'][0]['hz'] for r in data],style,marker='o',color=color,label=label)
    ax.set(title=title,xlabel='Requested source rate (Hz)',ylabel='Received map updates (Hz)');ax.grid(alpha=.2);ax.legend(fontsize=8)
fig.suptitle('ROS 2 map benchmark | same-host SHM | current v2 vs Python v1',fontsize=14)
fig.savefig(out/'performance.png',dpi=170)
fig.savefig(out/'performance.svg')
browser=[r for r in rows if 'browser_summary' in r and r['batch'] in ['browser-pilot','browser-full']]
if browser:
    fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
    labels=[r['case']['name'].replace('browser-','')+'\n'+r['case']['mode'] for r in browser]
    x=np.arange(len(browser));width=.36
    for key,offset,label,color in [('draw_fps',-.18,'POINTS draw calls / s','#0284c7'),('new_frame_hz',.18,'New map first draws / s','#16a34a')]:
        bars=axes[0].bar(x+offset,[r['browser_summary'][key] for r in browser],width,label=label,color=color);axes[0].bar_label(bars,fmt='%.1f',padding=2,fontsize=8)
    axes[0].set_xticks(x,labels,rotation=25);axes[0].legend(fontsize=8);axes[0].set_ylabel('Rate / s')
    bars=axes[1].bar(x,[r['browser_summary']['first_draw_age_ms']['p95'] or 0 for r in browser],color='#f59e0b');axes[1].bar_label(bars,fmt='%.0f',padding=2,fontsize=8)
    axes[1].set_xticks(x,labels,rotation=25);axes[1].set_ylabel('Source to first draw submission P95 (ms)')
    for ax in axes:ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True);ax.margins(y=.2)
    fig.suptitle('Production UI | Chromium SwiftShader software WebGL | 1440 x 900, DPR 1')
    fig.savefig(out/'browser-performance.png',dpi=170)
print(out/'performance.png')
