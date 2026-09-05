#!/usr/bin/env python3
import argparse
import json
import math
import sys
from typing import Any, Dict, List, Optional


def generate_range_slices(
    total_items: int,
    num_slices: int,
    item_label: str = "item",
    base_brief: str = "",
) -> List[Dict[str, Any]]:
    if total_items < 0:
        raise ValueError(f"total_items must be non-negative, got {total_items}")
    if num_slices <= 0:
        raise ValueError(f"num_slices must be positive, got {num_slices}")

    slices: List[Dict[str, Any]] = []
    base_size = total_items // num_slices
    remainder = total_items % num_slices
    current_idx = 0

    for i in range(num_slices):
        count = base_size + (1 if i < remainder else 0)
        start_idx = current_idx
        end_idx = start_idx + count
        current_idx = end_idx

        if base_brief:
            brief = f"{base_brief} ({item_label}s {start_idx} to {end_idx}, count {count})"
        else:
            brief = f"Process {item_label}s from index {start_idx} to {end_idx} (count {count})."

        task: Dict[str, Any] = {
            "slice_id": f"slice_{i}",
            "start_idx": start_idx,
            "end_idx": end_idx,
            "count": count,
            "item_label": item_label,
            "brief": brief,
        }
        slices.append(task)

    return slices


def generate_matrix_slices(
    total_matrices: int = 300,
    num_slices: int = 30,
    repo_url: str = "",
) -> List[Dict[str, Any]]:
    slices = generate_range_slices(
        total_items=total_matrices,
        num_slices=num_slices,
        item_label="matrix",
        base_brief="Evaluate matrices against baseline AMD and record flop and fill ratios",
    )
    if repo_url:
        for s in slices:
            s["repo_url"] = repo_url
    return slices


def generate_seed_lottery(
    seeds_count: int = 100,
    base_seed: int = 42,
    coprime_stride: int = 17,
) -> List[Dict[str, Any]]:
    if seeds_count <= 0:
        raise ValueError(f"seeds_count must be positive, got {seeds_count}")
    modulus = 1_000_000
    if math.gcd(coprime_stride, modulus) != 1:
        raise ValueError(
            f"coprime_stride ({coprime_stride}) must be coprime to {modulus}"
        )

    lottery: List[Dict[str, Any]] = []
    for i in range(seeds_count):
        seed = (base_seed + i * coprime_stride) % modulus
        task: Dict[str, Any] = {
            "seed_id": f"seed_{i}",
            "seed": seed,
            "brief": f"Execute trial with random seed {seed}.",
        }
        lottery.append(task)

    return lottery


def generate_parameter_sweep(
    param_name: str,
    values: List[Any],
    base_brief: str,
) -> List[Dict[str, Any]]:
    tasks: List[Dict[str, Any]] = []
    for i, val in enumerate(values):
        task: Dict[str, Any] = {
            "sweep_id": f"{param_name}_{i}",
            "param_name": param_name,
            "param_value": val,
            "brief": f"{base_brief} with {param_name}={val}",
        }
        tasks.append(task)
    return tasks


def main() -> None:
    parser = argparse.ArgumentParser(description="Generic manifest generator for swarm dispatch.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    slice_parser = subparsers.add_parser("slices", help="Generate range partition manifest.")
    slice_parser.add_argument("--total-items", type=int, required=True)
    slice_parser.add_argument("--num-slices", type=int, required=True)
    slice_parser.add_argument("--label", type=str, default="item")
    slice_parser.add_argument("--brief", type=str, default="")

    seed_parser = subparsers.add_parser("seeds", help="Generate seed lottery manifest.")
    seed_parser.add_argument("--seeds-count", type=int, default=100)
    seed_parser.add_argument("--base-seed", type=int, default=42)
    seed_parser.add_argument("--coprime-stride", type=int, default=17)

    sweep_parser = subparsers.add_parser("sweep", help="Generate parameter sweep manifest.")
    sweep_parser.add_argument("--param-name", type=str, required=True)
    sweep_parser.add_argument("--values", type=str, nargs="+", required=True)
    sweep_parser.add_argument("--base-brief", type=str, required=True)

    args = parser.parse_args()

    if args.command == "slices":
        manifest = generate_range_slices(
            total_items=args.total_items,
            num_slices=args.num_slices,
            item_label=args.label,
            base_brief=args.brief,
        )
    elif args.command == "seeds":
        manifest = generate_seed_lottery(
            seeds_count=args.seeds_count,
            base_seed=args.base_seed,
            coprime_stride=args.coprime_stride,
        )
    elif args.command == "sweep":
        manifest = generate_parameter_sweep(
            param_name=args.param_name,
            values=args.values,
            base_brief=args.base_brief,
        )
    else:
        manifest = []

    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
