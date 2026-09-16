"""Isolated benchmark entry; production defaults and .env are never rewritten."""
import os
import uvicorn
from app.core.config import Settings
if os.environ.get('BENCH_UNCAPPED') == '1':
    Settings.ros_pointcloud_max_hz = 0.0
uvicorn.run('app.main:app', host='127.0.0.1', port=int(os.environ['BENCH_PORT']),
            ws='websockets', ws_per_message_deflate=False, log_level='warning')
