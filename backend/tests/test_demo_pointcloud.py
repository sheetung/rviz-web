import importlib.util
from pathlib import Path
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('demo_pointcloud', ROOT / 'scripts/demo_pointcloud.py')
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class LidarGeometryTests(unittest.TestCase):
    def test_coordinates_are_relative_to_translated_rotated_sensor(self):
        position = np.array([10., 20., 1.])
        world = np.array([[10., 22., 1.]])
        points = demo.scan(world, position, np.pi / 2, 8)
        np.testing.assert_allclose(points, [[2., 0., 0.]], atol=1e-6)

    def test_nearest_return_range_and_vertical_field_of_view(self):
        points = demo.scan(np.array([[2., 0., 0.], [4., 0., 0.], [9., 0., 0.], [1., 0., 5.]]), np.zeros(3), 0, 8)
        np.testing.assert_allclose(points, [[2., 0., 0.]])

    def test_motion_and_static_scene(self):
        first, yaw = demo.lidar_pose(0)
        second, later_yaw = demo.lidar_pose(1)
        self.assertFalse(np.allclose(first, second))
        self.assertNotEqual(yaw, later_yaw)
        np.testing.assert_allclose(np.linalg.norm(first[:2]), 2)
        world = demo.scene()
        points = demo.scan(world, first, yaw, 8)
        self.assertGreater(len(points), 100)
        self.assertTrue(np.isfinite(points).all())
        self.assertLessEqual(np.linalg.norm(points, axis=1).max(), 8.00001)


if __name__ == '__main__':
    unittest.main()
