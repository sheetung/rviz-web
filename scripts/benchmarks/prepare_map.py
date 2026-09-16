"""Extract XYZ from the project's binary PLY exports, recording source identity."""
import argparse
import hashlib
import json
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('source', type=Path)
p.add_argument('output', type=Path)
a=p.parse_args()
if a.output.exists() or a.output.with_suffix(".json").exists():
    raise FileExistsError("Choose a new output path; existing evidence is never overwritten")
with a.source.open('rb') as f:
    header=[]
    while True:
        line=f.readline()
        if not line or len(header)>32: raise ValueError('Invalid PLY header')
        header.append(line.decode('ascii').strip())
        if header[-1]=='end_header': break
    assert 'format binary_little_endian 1.0' in header
    assert [s for s in header if s.startswith('property ')] == ['property float x','property float y','property float z']
    count=int(next(s for s in header if s.startswith('element vertex ')).split()[-1])
    data=f.read()
    assert len(data)==count*12
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_bytes(data)
    meta={'source':str(a.source.resolve()),'points':count,'bytes':len(data),'xyz_sha256':hashlib.sha256(data).hexdigest()}
    a.output.with_suffix('.json').write_text(json.dumps(meta,indent=2)+'\n')
    print(json.dumps(meta))
