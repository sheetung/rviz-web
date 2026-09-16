import math
from pathlib import Path
import sys
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from simulation.scene import Flight, Patrol, World, load_map


def route(tmp_path):
    trajectory = np.zeros((10, 8))
    trajectory[:, 0] = np.arange(10)
    trajectory[:, 1] = np.linspace(0, 9, 10)
    trajectory[:, 2] = np.sin(trajectory[:, 1] / 3)
    trajectory[:, 7] = 1
    path = tmp_path / "trajectory.txt"
    np.savetxt(path, trajectory)
    return Patrol(path, height=1, speed=2)


def test_patrol_position_and_rotation_are_continuous_across_turns_and_cycles(tmp_path):
    patrol = route(tmp_path)
    boundaries = [0, patrol.flight_time, patrol.flight_time+patrol.turn_time,
                  2*patrol.flight_time+patrol.turn_time, patrol.period, 10000*patrol.period]
    for boundary in boundaries:
        a, yaw_a = patrol.pose(boundary-1e-5)
        b, yaw_b = patrol.pose(boundary+1e-5)
        assert np.linalg.norm(a-b) < .001
        assert abs(yaw_b-yaw_a) < .001
    assert np.allclose(patrol.pose(.7)[0], patrol.pose(.7+patrol.period*10000)[0])


def test_new_goal_preserves_state_reaches_hover_and_can_resume(tmp_path):
    patrol = route(tmp_path)
    flight = Flight(patrol, 2)
    bounds = np.array([[-50]*3, [50]*3])
    start = flight.state(3)
    target = start.position + [3, 2, 1]
    flight.command(target, 1.2, 3, bounds)
    assert np.allclose(flight.state(3).position, start.position)
    assert np.allclose(flight.state(3).velocity, start.velocity)
    now = 4
    before = flight.state(now)
    flight.command(target+[1, 1, 0], .2, now, bounds)
    assert np.allclose(flight.state(now).position, before.position)
    assert np.allclose(flight.state(now).velocity, before.velocity)
    arrived = now+flight.transfer.duration+.1
    assert np.allclose(flight.state(arrived).position, target+[1, 1, 0])
    assert flight.mode == "hover"
    assert np.linalg.norm(flight.state(arrived).velocity) == 0
    flight.resume(arrived)
    end = flight.transfer.started+flight.transfer.duration
    assert np.allclose(flight.state(end-1e-6).position, flight.state(end+1e-6).position, atol=.001)
    assert flight.mode == "patrol"


def test_lidar_nearest_sample_local_frame_and_range():
    # In this pose +world Y is +sensor X; two collinear surfaces must not both appear.
    world = World(np.array([[1, 3, 2], [1, 5, 2], [1, 50, 2]], dtype="<f4"))
    points = world.scan(np.array([1, 1, 2]), math.pi/2, radius=10)
    assert points.shape == (1, 4)
    assert np.allclose(points[0, :3], [2, 0, 0], atol=1e-5)


def test_binary_ply_reader(tmp_path):
    path = tmp_path / "map.ply"
    path.write_bytes(b"ply\nformat binary_little_endian 1.0\nelement vertex 2\n"
                     b"property float x\nproperty float y\nproperty float z\nend_header\n"+
                     np.array([[1, 2, 3], [4, 5, 6]], dtype="<f4").tobytes())
    assert np.array_equal(load_map(path), [[1, 2, 3], [4, 5, 6]])


def test_rejected_goal_does_not_replace_current_flight(tmp_path):
    import pytest
    flight = Flight(route(tmp_path), 2)
    bounds = np.array([[-10]*3, [10]*3])
    for position in (np.array([np.nan, 0, 0]), np.array([100, 0, 0])):
        with pytest.raises(ValueError):
            flight.command(position, 0, 2, bounds)
        assert flight.mode == "patrol"
        assert flight.goal is None


def test_generated_view_config_passes_management_schema(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    from app.api.v1.configs import FrontendConfig
    from simulate_uav import make_config
    config = make_config(route(tmp_path), "sim-test.rvizweb")
    validated = FrontendConfig.model_validate(config["config"])
    assert validated.fixedFrame == "sim_map"
    assert validated.position.odomTopic == "/sim/uav/odom"
    assert validated.goal.topic == "/goal_pose"
