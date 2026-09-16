"""Copy native sources and disable WS fragmentation for a diagnostic build only."""
import argparse
from pathlib import Path
import shutil
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('output',type=Path)
a=p.parse_args()
source=Path(__file__).resolve().parents[2]/'backend'
shutil.copytree(source,a.output,ignore=shutil.ignore_patterns('build','management','__pycache__'))
server=a.output/'src/server.cpp'
text=server.read_text()
anchor='    socket_.binary(writing_->binary);'
if text.count(anchor)!=1:raise RuntimeError('Native write implementation changed; review the diagnostic patch')
server.write_text(text.replace(anchor,'    socket_.auto_fragment(false); // benchmark-only diagnostic\n'+anchor))
print(a.output)
