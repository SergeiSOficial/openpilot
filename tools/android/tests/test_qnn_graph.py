"""Standard-library checks for the prepared Java runner/artifact contract; no inference."""
import ast
import hashlib
import json
import math
from pathlib import Path
import struct
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "tools/android/.cache/qnn-quantized"


class QnnGraphArtifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (OUT / "manifest.json").is_file():
            raise unittest.SkipTest("Prepare qnn_graph.py artifacts first")
        cls.manifest = json.loads((OUT / "manifest.json").read_text())

    def test_source_and_file_hashes(self):
        with (ROOT / "openpilot/selfdrive/modeld/models/driving_supercombo.onnx").open("rb") as stream:
            self.assertEqual(hashlib.file_digest(stream, "sha256").hexdigest(), self.manifest["source"]["sha256"])
        self.assertFalse(self.manifest["host_inference_executed"])
        self.assertFalse(self.manifest["target_execution_verified"])
        for name, expected in self.manifest["sha256"].items():
            self.assertEqual(name, Path(name).name)
            with (OUT / name).open("rb") as stream:
                self.assertEqual(hashlib.file_digest(stream, "sha256").hexdigest(), expected, name)

    def test_external_model_contract(self):
        expected_inputs = [("new_img", 2, [2, 6, 128, 256]), ("desire", 1, [8]),
            ("traffic_convention", 1, [1, 2]), ("action_t", 1, [1, 2]),
            ("state_img_q", 2, [2, 5, 6, 128, 256]), ("state_desire_q", 1, [100, 1, 8]),
            ("state_feat_q", 1, [96, 1, 512])]
        expected_outputs = [("outputs", 1, [1, 2576]), ("next_state_img_q", 2, [2, 5, 6, 128, 256]),
                            ("next_state_desire_q", 1, [100, 1, 8]), ("next_state_feat_q", 1, [96, 1, 512])]
        for alias in ("fp32_original", "fp32", "calibration"):
            model = self.manifest["models"][alias]
            self.assertEqual([(v["name"], v["dtype"], v["shape"]) for v in model["inputs"]], expected_inputs)
            self.assertEqual([(v["name"], v["dtype"], v["shape"]) for v in model["outputs"][:4]], expected_outputs)
        self.assertFalse(self.manifest["conv"]["mapping_verified"])
        for direction in ("inputs", "outputs"):
            self.assertEqual(self.manifest["models"]["conv_qdq"][direction][0]["dtype"], 1)

    def test_calibration_return_budget_and_coverage(self):
        tensors = self.manifest["calibration_tensors"]
        by_name = {value["name"]: value for value in tensors}
        self.assertEqual(len(by_name), len(tensors))
        for value in tensors:
            self.assertEqual(value["dtype"], 1)
            self.assertEqual(value["bytes"], math.prod(value["shape"]) * 4)
        self.assertTrue({"desire", "traffic_convention", "action_t", "state_desire_q", "state_feat_q"} <= set(by_name))
        grouped = []
        for group in self.manifest["calibration_groups"]:
            self.assertLessEqual(len(group["outputs"]), 8)
            self.assertEqual(group["bytes"], sum(by_name[name]["bytes"] for name in group["outputs"]))
            self.assertLessEqual(group["bytes"], 128 * 1024 * 1024)
            grouped.extend(group["outputs"])
        self.assertEqual(grouped, [value["name"] for value in tensors])
        self.assertEqual(self.manifest["calibration_limits"]["intended_calibration_frames"], list(range(40)))

    def test_support_npz_is_safe_deterministic_npy_data(self):
        for alias in ("conv_fp16", "conv_fp32", "conv_qdq"):
            model = self.manifest["models"][alias]
            with zipfile.ZipFile(OUT / model["input_file"]) as archive:
                self.assertEqual(archive.namelist(), [value["name"] + ".npy" for value in model["inputs"]])
                for value in model["inputs"]:
                    entry = archive.getinfo(value["name"] + ".npy")
                    self.assertEqual(entry.date_time, (1980, 1, 1, 0, 0, 0))
                    data = archive.read(entry)
                    self.assertEqual(data[:6], b"\x93NUMPY")
                    self.assertIn(data[6], (1, 2))
                    width = 2 if data[6] == 1 else 4
                    length = struct.unpack("<H" if width == 2 else "<I", data[8:8 + width])[0]
                    header = ast.literal_eval(data[8 + width:8 + width + length].decode("ascii").strip())
                    self.assertEqual(list(header["shape"]), value["shape"])
                    self.assertFalse(header["fortran_order"])
                    expected = {10: ("<f2", 2), 1: ("<f4", 4)}[value["dtype"]]
                    self.assertEqual(header["descr"], expected[0])
                    self.assertEqual(len(data) - 8 - width - length, math.prod(value["shape"]) * expected[1])


if __name__ == "__main__":
    unittest.main()
