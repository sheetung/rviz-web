"""Common descriptive statistics; no ROS or network dependencies."""
import statistics

def distribution(values):
    if not values: return {'n': 0, 'mean': None, 'p50': None, 'p95': None, 'max': None}
    values = sorted(values)
    return {'n': len(values), 'mean': statistics.mean(values), 'p50': values[len(values)//2],
            'p95': values[min(len(values)-1, int(len(values)*.95))], 'max': values[-1]}
