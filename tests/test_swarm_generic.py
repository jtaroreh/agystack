#!/usr/bin/env python3
import math
import sys
import unittest
from pathlib import Path

SWARM_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "skills" / "swarm" / "scripts"
if not SWARM_SCRIPTS_DIR.exists():
    SWARM_SCRIPTS_DIR = Path.home() / ".gemini" / "config" / "plugins" / "agystack" / "skills" / "swarm" / "scripts"

sys.path.insert(0, str(SWARM_SCRIPTS_DIR))

from manifest_generator import (
    generate_parameter_sweep,
    generate_range_slices,
    generate_seed_lottery,
)
from result_harvester import extract_pareto_frontier


class TestSwarmGenericManifest(unittest.TestCase):
    def test_range_slices_exact_coverage(self):
        slices = generate_range_slices(total_items=100, num_slices=10, item_label="record")
        self.assertEqual(len(slices), 10)

        offset = 0
        for i, s in enumerate(slices):
            self.assertEqual(s["slice_id"], f"slice_{i}")
            self.assertEqual(s["start_idx"], offset)
            self.assertEqual(s["count"], 10)
            self.assertEqual(s["end_idx"], offset + 10)
            self.assertIn("records from index", s["brief"])
            offset = s["end_idx"]
        self.assertEqual(offset, 100)

    def test_range_slices_remainder_distribution(self):
        slices = generate_range_slices(total_items=25, num_slices=4)
        self.assertEqual(len(slices), 4)
        counts = [s["count"] for s in slices]
        self.assertEqual(counts, [7, 6, 6, 6])
        self.assertEqual(sum(counts), 25)

    def test_seed_lottery_uniqueness_and_coprimality(self):
        seeds_count = 200
        lottery = generate_seed_lottery(seeds_count=seeds_count, base_seed=123, coprime_stride=23)
        self.assertEqual(len(lottery), seeds_count)
        seeds = [t["seed"] for t in lottery]
        self.assertEqual(len(set(seeds)), seeds_count)

    def test_seed_lottery_rejects_non_coprime(self):
        with self.assertRaises(ValueError):
            generate_seed_lottery(seeds_count=10, coprime_stride=10)

    def test_parameter_sweep_generation(self):
        tasks = generate_parameter_sweep(
            param_name="threshold",
            values=[0.1, 0.2, 0.5],
            base_brief="Run calibration",
        )
        self.assertEqual(len(tasks), 3)
        self.assertEqual(tasks[0]["param_value"], 0.1)
        self.assertIn("threshold=0.1", tasks[0]["brief"])


class TestSwarmGenericHarvester(unittest.TestCase):
    def test_extract_pareto_frontier(self):
        trials = [
            {"id": "A", "score": 10.0, "fill_ratio": 5.0},
            {"id": "B", "score": 8.0, "fill_ratio": 6.0},
            {"id": "C", "score": 12.0, "fill_ratio": 8.0},
            {"id": "D", "score": 8.0, "fill_ratio": 4.0},
            {"id": "E", "score": 7.0, "fill_ratio": 4.5},
        ]
        frontier = extract_pareto_frontier(trials, metric_key="score", secondary_key="fill_ratio")
        frontier_ids = [t["id"] for t in frontier]
        self.assertEqual(frontier_ids, ["E", "D"])


if __name__ == "__main__":
    unittest.main()
