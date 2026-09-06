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


class TestParetoFrontier(unittest.TestCase):
    def test_default_maximization(self):
        trials = [
            {"id": "A", "score": 10.0, "fill_ratio": 5.0},
            {"id": "B", "score": 8.0, "fill_ratio": 9.0},
            {"id": "C", "score": 12.0, "fill_ratio": 4.0},
            {"id": "D", "score": 7.0, "fill_ratio": 3.0},
            {"id": "E", "score": 12.0, "fill_ratio": 8.0},
        ]
        frontier = extract_pareto_frontier(trials, metric_key="score", secondary_key="fill_ratio")
        frontier_ids = [t["id"] for t in frontier]
        self.assertEqual(frontier_ids, ["E", "B"])

    def test_minimization_mode(self):
        trials = [
            {"id": "A", "score": 10.0, "fill_ratio": 5.0},
            {"id": "B", "score": 8.0, "fill_ratio": 6.0},
            {"id": "C", "score": 12.0, "fill_ratio": 8.0},
            {"id": "D", "score": 8.0, "fill_ratio": 4.0},
            {"id": "E", "score": 7.0, "fill_ratio": 4.5},
        ]
        frontier = extract_pareto_frontier(
            trials,
            metric_key="score",
            secondary_key="fill_ratio",
            maximize=False,
        )
        frontier_ids = [t["id"] for t in frontier]
        self.assertEqual(frontier_ids, ["E", "D"])

    def test_co_optimal_candidate_retention(self):
        trials = [
            {"id": "A1", "score": 10.0, "fill_ratio": 5.0},
            {"id": "A2", "score": 10.0, "fill_ratio": 5.0},
            {"id": "B", "score": 8.0, "fill_ratio": 4.0},
        ]
        frontier = extract_pareto_frontier(trials)
        frontier_ids = [t["id"] for t in frontier]
        self.assertEqual(frontier_ids, ["A1", "A2"])

        frontier_min = extract_pareto_frontier(trials, maximize=False)
        frontier_min_ids = [t["id"] for t in frontier_min]
        self.assertEqual(frontier_min_ids, ["B"])

        co_min_trials = [
            {"id": "M1", "score": 2.0, "fill_ratio": 1.0},
            {"id": "M2", "score": 2.0, "fill_ratio": 1.0},
            {"id": "M3", "score": 5.0, "fill_ratio": 3.0},
        ]
        frontier_co_min = extract_pareto_frontier(co_min_trials, maximize=False)
        frontier_co_min_ids = [t["id"] for t in frontier_co_min]
        self.assertEqual(frontier_co_min_ids, ["M1", "M2"])

    def test_empty_and_single_item_inputs(self):
        self.assertEqual(extract_pareto_frontier([]), [])

        single = [{"id": "only", "score": 42.0, "fill_ratio": 0.9}]
        self.assertEqual(extract_pareto_frontier(single), single)

        single_min = [{"id": "only", "score": 42.0, "fill_ratio": 0.9}]
        self.assertEqual(extract_pareto_frontier(single_min, maximize=False), single_min)


TestSwarmGenericHarvester = TestParetoFrontier


if __name__ == "__main__":
    unittest.main()
