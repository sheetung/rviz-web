"""ROS-independent real-map lidar sampling and smooth, continuous UAV motion."""
from dataclasses import dataclass
from pathlib import Path
import math
import numpy as np


def load_map(path):
    """Read the binary XYZ PLY files produced by export_accumulating_map.py."""
    with Path(path).open("rb") as stream:
        header = []
        for _ in range(64):
            line = stream.readline()
            if not line:
                raise ValueError("Truncated PLY header")
            header.append(line.decode("ascii").strip())
            if header[-1] == "end_header":
                break
        else:
            raise ValueError("PLY header is too long")
        if header[:2] != ["ply", "format binary_little_endian 1.0"]:
            raise ValueError("Expected binary little-endian PLY")
        properties = [line for line in header if line.startswith("property")]
        if properties != ["property float x", "property float y", "property float z"]:
            raise ValueError("Expected an XYZ-only PLY exported by this project")
        count = int(next(line.split()[2] for line in header if line.startswith("element vertex ")))
        if not 0 < count <= 2_000_000:
            raise ValueError("Map must contain 1..2,000,000 points")
        points = np.fromfile(stream, dtype="<f4", count=count * 3)
        if points.size != count * 3 or stream.read(1):
            raise ValueError("PLY payload size mismatch")
    points = points.reshape(-1, 3)
    if not np.isfinite(points).all():
        raise ValueError("Map contains nonfinite points")
    return points


class World:
    def __init__(self, points, cell_size=8):
        self.points = points
        self.cell_size = cell_size
        keys, inverse = np.unique(np.floor(points / cell_size).astype(np.int32), axis=0, return_inverse=True)
        groups = np.split(np.argsort(inverse), np.cumsum(np.bincount(inverse))[:-1])
        self.cells = {tuple(key): points[index] for key, index in zip(keys, groups)}
        self.bounds = np.array([points.min(axis=0), points.max(axis=0)])

    def nearby(self, position, radius):
        low = np.floor((position - radius) / self.cell_size).astype(int)
        high = np.floor((position + radius) / self.cell_size).astype(int)
        chunks = [self.cells[(x, y, z)]
                  for x in range(low[0], high[0] + 1)
                  for y in range(low[1], high[1] + 1)
                  for z in range(low[2], high[2] + 1) if (x, y, z) in self.cells]
        return np.concatenate(chunks) if chunks else np.empty((0, 3), dtype="<f4")

    def scan(self, position, yaw, radius=30, columns=900, rings=48, noise=0, rng=None):
        """Closest map sample in each angular bin; approximate visibility, not mesh ray tracing."""
        delta = self.nearby(position, radius) - position
        c, s = math.cos(yaw), math.sin(yaw)
        local = delta @ np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
        distance = np.linalg.norm(local, axis=1)
        elevation = np.arctan2(local[:, 2], np.linalg.norm(local[:, :2], axis=1))
        visible = (distance > .35) & (distance <= radius) & (np.abs(elevation) < math.pi / 4)
        local, distance, elevation = local[visible], distance[visible], elevation[visible]
        if not len(local):
            return np.empty((0, 4), dtype="<f4")
        azimuth = np.arctan2(local[:, 1], local[:, 0])
        col = np.floor((azimuth + math.pi) * columns / (2 * math.pi)).astype(int) % columns
        row = np.clip(((elevation + math.pi / 4) * rings / (math.pi / 2)).astype(int), 0, rings - 1)
        ray = row * columns + col
        nearest = np.full(columns*rings, np.inf)
        np.minimum.at(nearest, ray, distance)
        candidates = np.flatnonzero(distance == nearest[ray])
        _, unique = np.unique(ray[candidates], return_index=True)
        selected = candidates[unique]
        local, distance = local[selected], distance[selected]
        if noise:
            noisy = np.clip(distance + rng.normal(0, noise, len(distance)), .35, radius)
            local *= (noisy / distance)[:, None]
        intensity = np.clip(220 / (1 + .025 * distance * distance), 1, 255)
        return np.column_stack((local, intensity)).astype("<f4")


@dataclass
class State:
    position: np.ndarray
    velocity: np.ndarray
    acceleration: np.ndarray
    yaw: float
    yaw_rate: float


class Patrol:
    def __init__(self, path, height=1.2, speed=2, turn_time=4):
        trajectory = np.loadtxt(path, ndmin=2)
        if (trajectory.shape[1] != 8 or len(trajectory) < 2 or
                not np.isfinite(trajectory).all() or not np.all(np.diff(trajectory[:, 0]) > 0)):
            raise ValueError("Invalid timestamped TUM trajectory")
        original = trajectory[:, 1:4]
        distance = np.r_[0, np.cumsum(np.linalg.norm(np.diff(original, axis=0), axis=1))]
        keep = np.r_[True, np.diff(distance) > 1e-5]
        distance, original = distance[keep], original[keep]
        self.length = float(distance[-1])
        if self.length < 1:
            raise ValueError("Patrol route must be at least one metre long")
        self.knots = np.linspace(0, self.length, max(4, math.ceil(self.length / .6) + 1))
        self.points = np.column_stack([np.interp(self.knots, distance, original[:, axis]) for axis in range(3)])
        self.points[:, 2] += height
        self.tangents = np.gradient(self.points, self.knots, axis=0)
        self.headings = np.unwrap(np.arctan2(self.tangents[:, 1], self.tangents[:, 0]))
        self.flight_time = math.pi * self.length / (2 * speed)
        self.turn_time = turn_time
        self.period = 2 * (self.flight_time + turn_time)

    def point(self, distance):
        i = int(np.clip(np.searchsorted(self.knots, distance) - 1, 0, len(self.knots) - 2))
        step = self.knots[i + 1] - self.knots[i]
        u = np.clip((distance - self.knots[i]) / step, 0, 1)
        return ((2*u**3-3*u*u+1)*self.points[i] + (u**3-2*u*u+u)*step*self.tangents[i] +
                (-2*u**3+3*u*u)*self.points[i+1] + (u**3-u*u)*step*self.tangents[i+1])

    def pose(self, elapsed):
        cycle = math.floor(elapsed / self.period)
        t = elapsed - cycle * self.period
        f, turn = self.flight_time, self.turn_time
        if t < f:
            d = self.length * (1 - math.cos(math.pi*t/f)) / 2
            yaw = np.interp(d, self.knots, self.headings)
        elif t < f + turn:
            d = self.length
            yaw = self.headings[-1] + math.pi * (1 - math.cos(math.pi*(t-f)/turn)) / 2
        elif t < 2*f + turn:
            d = self.length * (1 + math.cos(math.pi*(t-f-turn)/f)) / 2
            yaw = np.interp(d, self.knots, self.headings) + math.pi
        else:
            d = 0
            yaw = self.headings[0] + math.pi + math.pi * (1 - math.cos(math.pi*(t-2*f-turn)/turn)) / 2
        return self.point(d), float(yaw + cycle*2*math.pi)

    def state(self, elapsed):
        h = .01
        p, yaw = self.pose(elapsed)
        before, y0 = self.pose(elapsed-h)
        after, y1 = self.pose(elapsed+h)
        return State(p, (after-before)/(2*h), (after-2*p+before)/(h*h), yaw, (y1-y0)/(2*h))


class Transfer:
    """Quintic position/yaw transition preserving current position and velocity."""
    def __init__(self, initial, target, now, speed):
        distance = np.linalg.norm(target.position-initial.position)
        self.duration = max(2.5, 2*distance/speed, abs(target.yaw-initial.yaw)*1.5)
        self.started = now
        a = np.r_[initial.position, initial.yaw]
        b = np.r_[target.position, target.yaw]
        v0 = np.r_[initial.velocity, initial.yaw_rate]
        v1 = np.r_[target.velocity, target.yaw_rate]
        acc0 = np.r_[initial.acceleration, 0]
        acc1 = np.r_[target.acceleration, 0]
        t = self.duration
        self.coeff = np.zeros((6, 4))
        self.coeff[:3] = [a, v0*t, acc0*t*t/2]
        self.coeff[3:] = np.linalg.solve(
            [[1, 1, 1], [3, 4, 5], [6, 12, 20]],
            [b-self.coeff[:3].sum(axis=0), v1*t-self.coeff[1]-2*self.coeff[2],
             acc1*t*t-2*self.coeff[2]])
        self.target = target

    def state(self, now):
        u = np.clip((now-self.started)/self.duration, 0, 1)
        c = self.coeff
        p = np.array([u**i for i in range(6)]) @ c
        v = np.array([0]+[i*u**(i-1) for i in range(1, 6)]) @ c/self.duration
        a = np.array([0, 0]+[i*(i-1)*u**(i-2) for i in range(2, 6)]) @ c/self.duration**2
        return State(p[:3], v[:3], a[:3], float(p[3]), float(v[3]))


class Flight:
    def __init__(self, patrol, speed):
        self.patrol, self.speed = patrol, speed
        self.mode, self.origin, self.phase = "patrol", 0.0, 0.0
        self.transfer = None
        self.goal = None
        self.last_event = "Patrolling recorded route"

    def state(self, now):
        if self.mode == "patrol":
            return self.patrol.state(now-self.origin)
        if self.mode == "hover":
            return self.transfer.target
        if now >= self.transfer.started+self.transfer.duration:
            if self.mode == "return":
                self.origin = self.transfer.started+self.transfer.duration-self.phase
                self.mode = "patrol"
                self.last_event = "Patrolling recorded route"
                return self.patrol.state(now-self.origin)
            self.mode = "hover"
            self.last_event = "Goal reached; hovering and scanning"
            return self.transfer.target
        return self.transfer.state(now)

    def command(self, position, yaw, now, bounds):
        if not np.isfinite(position).all() or not math.isfinite(yaw):
            raise ValueError("Goal contains nonfinite values")
        if np.any(position < bounds[0]-2) or np.any(position > bounds[1]+2):
            raise ValueError("Goal is outside the recorded map bounds")
        current = self.state(now)
        if self.mode == "patrol":
            self.phase = now-self.origin
        yaw = current.yaw + (yaw-current.yaw+math.pi) % (2*math.pi)-math.pi
        target = State(np.array(position, dtype=float), np.zeros(3), np.zeros(3), yaw, 0.)
        self.transfer = Transfer(current, target, now, self.speed)
        self.mode, self.goal = "goal", target
        self.last_event = "Flying to received goal"

    def resume(self, now):
        if self.mode == "patrol":
            return
        current = self.state(now)
        target = self.patrol.state(self.phase)
        target.yaw = current.yaw + (target.yaw-current.yaw+math.pi) % (2*math.pi)-math.pi
        # Match the patrol's continuous angle branch on rejoin.
        current.yaw += self.patrol.state(self.phase).yaw-target.yaw
        target.yaw = self.patrol.state(self.phase).yaw
        self.transfer = Transfer(current, target, now, self.speed)
        self.mode, self.goal = "return", None
        self.last_event = "Returning to patrol route"
