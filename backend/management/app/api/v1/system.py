"""Host metrics provided by the management service, independent of ROS."""
import math
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel
import psutil

router = APIRouter()


class HostMetrics(BaseModel):
    cpu_usage: float | None
    memory_usage: float | None
    cpu_temperature: float | None


def finite(value):
    return float(value) if value is not None and math.isfinite(value) else None


def cpu_temperature():
    try:
        sensors = psutil.sensors_temperatures()
        for name in ("coretemp", "k10temp", "cpu_thermal", "soc_thermal", "cpu-thermal"):
            values = [finite(entry.current) for entry in sensors.get(name, [])]
            values = [value for value in values if value is not None]
            if values:
                return round(max(values), 1)
    except (AttributeError, OSError, RuntimeError):
        pass
    # Don't label disk/GPU temperatures as CPU temperatures.
    for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
        try:
            kind = (zone / "type").read_text().strip().lower()
            if not any(name in kind for name in ("cpu", "soc", "x86_pkg")):
                continue
            value = finite(float((zone / "temp").read_text()) / 1000)
            if value is not None:
                return round(value, 1)
        except (OSError, ValueError):
            continue
    return None


@router.get("/system/status", response_model=HostMetrics)
def get_system_status():
    # A short measured sample avoids psutil's first-call 0% per worker thread.
    # This synchronous route runs in FastAPI's thread pool, not the event loop.
    try:
        cpu = finite(psutil.cpu_percent(interval=0.1))
    except (OSError, RuntimeError):
        cpu = None
    try:
        memory = finite(psutil.virtual_memory().percent)
    except (OSError, RuntimeError):
        memory = None
    return HostMetrics(cpu_usage=cpu, memory_usage=memory, cpu_temperature=cpu_temperature())
