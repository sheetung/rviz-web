"""ROS2 map benchmark: isolated native source, direct DDS probe and WS clients.

Source ROS2 before running. All processes are local children and cleaned up.
Results include actual source rate; requested rate alone is not throughput.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import statistics
import struct
import subprocess
import sys
import time
import urllib.request

import psutil
import websockets
from websockets.asyncio.client import ClientConnection
from websockets.frames import Frame, OP_BINARY, OP_CONT

ROOT = Path(__file__).resolve().parents[2]
TOPIC = '/benchmark/map'
MIB = 1024**2

from metrics import distribution

def command(mode, operation, request_id, **params):
    method = {'subscribe': 'topics.subscribe', 'ping': 'ping'}[operation]
    return json.dumps({'version': 2, 'id': request_id, 'method': method, 'params': params})

def expected_hash(source, points):
    import numpy as np
    original = np.fromfile(source, dtype='<f4').reshape(-1, 3)
    indices = np.arange(points, dtype=np.int64)
    indices = indices * len(original) // points if points <= len(original) else indices % len(original)
    return hashlib.sha256(original[indices].tobytes()).hexdigest()

class Client:
    def __init__(self, mode, url, points, digest, slow=False, track_fragments=False):
        self.mode, self.url, self.points, self.digest, self.slow = mode, url, points, digest, slow
        self.track_fragments = track_fragments
        self.first_message_fragments = None
        self.ready = asyncio.Event()
        self.frames, self.pings, self.errors = [], [], []
        self.pending = {}
        self.validated = False
        self.last_stamp = None
        self.duplicates = 0
        self.closed_at = None
        self.socket = None
        self.measure_start = self.measure_end = float('inf')
    async def run(self):
        owner = self
        class ObservedConnection(ClientConnection):
            fragment_count = 0
            def process_event(self, event):
                if owner.first_message_fragments is None and isinstance(event, Frame) and event.opcode in (OP_BINARY, OP_CONT):
                    self.fragment_count += 1
                    if event.fin: owner.first_message_fragments = self.fragment_count
                return super().process_event(event)
        extra = {'create_connection':ObservedConnection} if self.track_fragments else {}
        try:
            async with websockets.connect(self.url, proxy=None, compression=None, max_size=20*MIB,
                                           max_queue=1 if self.slow else 2, close_timeout=.3, **extra) as socket:
                self.socket = socket
                await socket.send(command(self.mode, 'subscribe', 'subscribe', topic=TOPIC, type='sensor_msgs/msg/PointCloud2'))
                async for raw in socket:
                    now = time.time()
                    if isinstance(raw, bytes):
                        assert raw[:4] == b'RVPC' and raw[4] == 1
                        length = struct.unpack_from('<I', raw, 8)[0]
                        message = json.loads(raw[12:12+length])['msg']
                        offset = (12+length+3)&~3
                        assert message['width']*message['height'] == self.points
                        assert message['point_step'] == 12 and len(raw)-offset == self.points*12
                        stamp = message['header']['stamp']
                        ns = stamp['sec']*1000000000 + stamp.get('nanosec', stamp.get('nsec', 0))
                        if not self.validated:
                            assert hashlib.sha256(memoryview(raw)[offset:]).hexdigest() == self.digest
                            self.validated = True
                        if self.measure_start <= now <= self.measure_end:
                            self.frames.append((now, len(raw), (time.time_ns()-ns)/1e6, ns))
                            if self.last_stamp == ns: self.duplicates += 1
                        self.last_stamp = ns
                    else:
                        message = json.loads(raw)
                        if message.get('id') == 'subscribe':
                            assert message.get('ok', message.get('success', False)), message
                            self.ready.set()
                            if self.slow:
                                await asyncio.Event().wait()
                        elif message.get('id') in self.pending:
                            sent = self.pending.pop(message['id'])
                            if self.measure_start <= now <= self.measure_end: self.pings.append((now, (time.perf_counter()-sent)*1000))
                        elif message.get('op') == 'error' or message.get('ok') is False or message.get('msg', {}).get('error'):
                            if len(self.errors) < 8: self.errors.append(message)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.closed_at = time.time()
            self.errors.append(f'{type(e).__name__}: {e}')
            self.ready.set()
    async def ping(self):
        while True:
            await asyncio.sleep(.5)
            if self.socket is None: continue
            key = str(time.perf_counter_ns())
            self.pending[key] = time.perf_counter()
            try: await self.socket.send(command(self.mode, 'ping', key))
            except Exception: return
    def summary(self, duration):
        return {'frames': len(self.frames), 'hz': len(self.frames)/duration,
                'mib_s': sum(f[1] for f in self.frames)/MIB/duration,
                'age_ms': distribution([f[2] for f in self.frames]),
                'ping_ms': distribution([p[1] for p in self.pings]),
                'pending_pings': len(self.pending), 'payload_sha256_valid': self.validated,
                'first_message_fragments':self.first_message_fragments, 'duplicates': self.duplicates, 'errors': self.errors, 'closed_at': self.closed_at}

async def scenario(case, args, index):
    target = args.output / f'{index:02d}-{case["name"]}-{case["mode"]}'
    target.mkdir()
    if case['mode'] != 'v2':
        raise ValueError('Only native v2 benchmark plans are supported')
    env = dict(os.environ, ROS_DOMAIN_ID=str(args.domain), ROS_LOCALHOST_ONLY='1',
               ROS_LOG_DIR=str(target/'roslogs'))
    if args.dds_profile:
        env.update(FASTRTPS_DEFAULT_PROFILES_FILE=str(args.dds_profile.resolve()), ROS_LOCALHOST_ONLY='0')
    processes, logs, tasks, clients = {}, [], [], []
    samples = []
    start = end = None
    def spawn(name, cmd):
        log = (target/f'{name}.log').open('w'); logs.append(log)
        process = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        processes[name] = process
        return process
    try:
        source = args.maps / f'{case.get("map", "indoor")}.xyz'
        points = case['points']
        digest = expected_hash(source, points)
        native = True
        server_cmd = [str(args.native), '--port', str(args.port)]
        spawn('server', server_cmd)
        endpoint = f'http://127.0.0.1:{args.port}'+'/api/v2/ros/health'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def healthy():
            try:
                with opener.open(endpoint, timeout=.5) as r: return r.status==200
            except Exception: return False
        for _ in range(100):
            if await asyncio.to_thread(healthy): break
            if processes['server'].poll() is not None: raise RuntimeError('Server startup failed')
            await asyncio.sleep(.1)
        else: raise RuntimeError('Server readiness timeout')
        spawn('source', [str(args.source), 'publish', str(source), str(points), str(case['hz']), str(target/'source.csv')])
        spawn('probe', [str(args.source), 'probe', str(target/'probe.csv')])
        url = f'ws://127.0.0.1:{args.port}'+'/ws/v2/ros'
        if case.get('browser'):
            env['BROWSER_GL']=case.get('gl','swiftshader')
            env.update(ROS_V2_PROXY_TARGET=f'http://127.0.0.1:{args.port}', RVIZWEB_MANAGEMENT_PORT=str(args.port), APP_PORT=str(args.port+2))
            # Vite config resolves .env relative to frontend; launch from that directory.
            preview_cmd = ['node', str(ROOT/'frontend/node_modules/vite/bin/vite.js'), 'preview', '--host', '127.0.0.1', '--port', str(args.port+2)]
            preview_log=(target/'preview.log').open('w'); logs.append(preview_log)
            processes['preview']=subprocess.Popen(preview_cmd, cwd=ROOT/'frontend', env=env, stdout=preview_log, stderr=subprocess.STDOUT, start_new_session=True)
            await asyncio.sleep(1)
            spawn('browser', ['node', str(ROOT/'scripts/benchmarks/browser.cjs'), f'http://127.0.0.1:{args.port+2}/', str(target.resolve())])
            ready=target/'browser-ready.json'
            for _ in range(450):
                if ready.exists(): break
                if processes['browser'].poll() is not None: raise RuntimeError('Browser startup failed')
                await asyncio.sleep(.1)
            else: raise RuntimeError('Browser readiness timeout')
            start=json.loads(ready.read_text())['start']
        else:
            for i in range(case.get('clients', 1)+case.get('slow', 0)):
                c = Client(case['mode'], url, points, digest, slow=i>=case.get('clients', 1), track_fragments=case.get('count_fragments',False)); clients.append(c)
                tasks.append(asyncio.create_task(c.run()))
                await asyncio.wait_for(c.ready.wait(), 12)
                if c.errors: raise RuntimeError(c.errors)
                if not c.slow: tasks.append(asyncio.create_task(c.ping()))
            await asyncio.sleep(case.get('warmup', 3))
            start = time.time()
        planned_end = start + case.get('seconds', 15)
        for c in clients: c.measure_start=start; c.measure_end=planned_end
        proc = {name: psutil.Process(p.pid) for name, p in processes.items()}
        proc['receiver'] = psutil.Process()
        if case.get('browser'):
            for i,child in enumerate(proc['browser'].children(recursive=True)): proc[f'chrome_{i}']=child
        initial = {n: sum(p.cpu_times()[:2]) for n,p in proc.items()}
        stop_reason = None
        def sample_resources():
            sample = {'time': time.time(), 'available_mib': psutil.virtual_memory().available/MIB}
            for name, p in proc.items():
                memory=p.memory_full_info()
                sample[name] = {'rss_mib': memory.rss/MIB, 'pss_mib':getattr(memory,'pss',0)/MIB, 'uss_mib':getattr(memory,'uss',0)/MIB, 'cpu_s': sum(p.cpu_times()[:2])}
            return sample
        while time.time() < planned_end:
            sample = await asyncio.to_thread(sample_resources)
            samples.append(sample)
            if sample['server']['rss_mib'] > 1024 or sample['available_mib'] < 1024:
                stop_reason = 'memory_guard'; break
            if processes['server'].poll() is not None:
                stop_reason = 'server_exited'; break
            await asyncio.sleep(max(0,min(.5,planned_end-time.time())))
        actual_end=time.time()
        end = min(actual_end,planned_end)
        cpu = {n: (sum(p.cpu_times()[:2])-initial[n])/(actual_end-start)*100 for n,p in proc.items()}
        for c in clients: c.measure_end=end
        if case.get('browser'):
            (target/'browser-stop').touch()
            await asyncio.to_thread(processes['browser'].wait, timeout=12)
        after_slow = None
        if case.get('slow'):
            if native:
                extra_connections=[]
                try:
                    # Fill all remaining slots after the slow sender timeout.
                    for _ in range(16-case.get('clients',1)):
                        extra_connections.append(await websockets.connect(url,proxy=None,compression=None,open_timeout=2,close_timeout=.2))
                    after_slow={'free_slots':len(extra_connections),'expected_free_slots':16-case.get('clients',1)}
                    try:
                        extra=await websockets.connect(url,proxy=None,open_timeout=2,close_timeout=.2)
                        await extra.close();after_slow['connection_17_rejected']=False
                    except Exception:after_slow['connection_17_rejected']=True
                except Exception as error:
                    after_slow={'free_slots':len(extra_connections),'error':str(error)}
                finally:
                    await asyncio.gather(*(s.close() for s in extra_connections),return_exceptions=True)
            else:
                async with websockets.connect(url,proxy=None,compression=None,close_timeout=.2) as check:
                    await check.send(json.dumps({'op':'get_system_status','id':'after-slow'}))
                    for _ in range(10):
                        reply=json.loads(await asyncio.wait_for(check.recv(),3))
                        if reply.get('id')=='after-slow':
                            after_slow=reply;break
        # Finish receiving before cancellation; cancelling mid-fragment can trip
        # the websockets 16 assembler during close (outside the measurement window).
        await asyncio.gather(*(c.socket.close() for c in clients if c.socket), return_exceptions=True)
        for t in tasks: t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        duration = end-start
        result = {'case':case, 'start':start, 'end':end, 'duration':duration, 'cpu_duration':actual_end-start, 'stop_reason':stop_reason,
                  'after_slow':after_slow, 'payload_sha256':digest, 'cpu_percent':cpu, 'rss_mib':{},
                  'clients':[c.summary(duration) for c in clients if not c.slow]}
        if case.get('browser'):
            result['browser']=json.loads((target/'browser.json').read_text())
        for name in proc:
            rss = [s[name]['rss_mib'] for s in samples]
            result['rss_mib'][name] = {'pss_mean':statistics.mean(s[name]['pss_mib'] for s in samples), 'uss_mean':statistics.mean(s[name]['uss_mib'] for s in samples), **distribution(rss), 'first_3s':statistics.mean(rss[:6]),'last_3s':statistics.mean(rss[-6:])}
    except Exception as e:
        result = {'case':case, 'fatal':f'{type(e).__name__}: {e}', 'start':start, 'end':end}
    finally:
        for t in tasks: t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for p in processes.values():
            if p.poll() is None: os.killpg(p.pid, signal.SIGTERM)
        for p in processes.values():
            try: await asyncio.to_thread(p.wait, timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL); p.wait()
        for log in logs: log.close()
    if start and end:
        for name in ('source','probe'):
            rows=[]
            for line in (target/f'{name}.csv').read_text().splitlines():
                now,stamp=map(int,line.split(','))
                if start*1e9 <= now <= end*1e9: rows.append((now,stamp))
            result[name]={'frames':len(rows),'hz':len(rows)/(end-start),'age_ms':distribution([(n-s)/1e6 for n,s in rows])}
    result['exit_codes']={n:p.returncode for n,p in processes.items()}
    (target/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    (target/'resources.json').write_text(json.dumps(samples))
    for i,c in enumerate(clients):
        if not c.slow: (target/f'client-{i}.json').write_text(json.dumps({'frames':c.frames,'pings':c.pings}))
    compact={'name':case['name'],'mode':case['mode'],'source_hz':result.get('source',{}).get('hz'),
             'dds_hz':result.get('probe',{}).get('hz'),'client_hz':[round(c['hz'],2) for c in result.get('clients',[])],
             'cpu':result.get('cpu_percent',{}).get('server'),'rss_max':result.get('rss_mib',{}).get('server',{}).get('max'),
             'fatal':result.get('fatal'), 'stop_reason':result.get('stop_reason')}
    print(json.dumps(compact), flush=True)
    return result

async def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    meta = {'platform':platform.platform(),'cpu_count':psutil.cpu_count(),'ram_mib':psutil.virtual_memory().total/MIB,
            'python':sys.version,'websockets':websockets.__version__,'domain':args.domain,'port':args.port,
            'started':time.time(),'native':str(args.native),'source':str(args.source),'dds_profile':str(args.dds_profile) if args.dds_profile else None}
    (args.output/'environment.json').write_text(json.dumps(meta,indent=2))
    cases=json.loads(args.plan.read_text()); results=[]
    for i,case in enumerate(cases):
        print(f'RUN {i+1}/{len(cases)} {case}',flush=True)
        results.append(await scenario(case,args,i))
        (args.output/'results.json').write_text(json.dumps(results,indent=2)+'\n')
        if results[-1].get('stop_reason')=='memory_guard': break
        await asyncio.sleep(1)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--maps',type=Path,default=Path('/tmp/rviz-map-bench'))
    p.add_argument('--source',type=Path,default=Path('/tmp/rviz-map-bench/build/map_source'))
    p.add_argument('--native',type=Path,default=ROOT/'backend/build/ros2/rvizweb_native')
    p.add_argument('--dds-profile',type=Path)
    p.add_argument('--domain',type=int,default=191);p.add_argument('--port',type=int,default=18191)
    asyncio.run(main(p.parse_args()))
