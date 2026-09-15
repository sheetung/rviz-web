"""Pure-data exporter regressions; run with python3 -m unittest discover -s scripts."""

from pathlib import Path
import tempfile
import unittest

import numpy as np

from export_glim_map import read_submap, voxel_filter


class ExportTests(unittest.TestCase):
    def test_voxel_deduplication_preserves_first_point(self):
        points = np.array([[0.01, 0, 0], [0.02, 0, 0], [-0.01, 0, 0], [1, 0, 0]])
        result = voxel_filter(points, 0.1)
        np.testing.assert_allclose(result, points[[0, 2, 3]])
        self.assertEqual(result.dtype, np.dtype("<f4"))

    def test_invalid_voxel(self):
        for size in [0, -1, float("nan"), float("inf")]:
            with self.assertRaises(ValueError):
                voxel_filter(np.zeros((1, 3)), size)

    def test_transform_and_exact_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "data.txt").write_text(
                "T_world_origin: \n0 -1 0 10\n1 0 0 20\n0 0 1 30\n0 0 0 1\n"
                "stamp: 1743002290.114873648\nstamp: 1743002290.214873649\n"
            )
            np.array([[1, 2, 3]], dtype="<f4").tofile(path / "points_compact.bin")
            points, stamp = read_submap(path)
            np.testing.assert_allclose(points, [[8, 21, 33]])
            self.assertEqual(stamp, 1743002290214873649)

    def test_nonfinite_points_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "data.txt").write_text(
                "T_world_origin: \n1 0 0 0\n0 1 0 0\n0 0 1 0\n0 0 0 1\nstamp: 1.0\n"
            )
            np.array([[float("nan"), 0, 0]], dtype="<f4").tofile(
                path / "points_compact.bin"
            )
            with self.assertRaises(ValueError):
                read_submap(path)


if __name__ == "__main__":
    unittest.main()
