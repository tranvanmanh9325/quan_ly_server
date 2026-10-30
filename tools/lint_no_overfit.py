#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/lint_no_overfit.py — Static Anti-Overfitting and Anti-Gaming Linter.
Milestone M0: Frozen Acceptance Judge Infrastructure.

Scans services/ai-agent-service/app/ and production scripts to enforce that:
1. No clip-specific strings/tokens are hardcoded:
   - "Soạn hợp đồng", "Ăn sáng", "Xong việc đi về", "2x tuổi", "tủ lạnh", "xe Porsche", "tmpy8evxmno"
2. No clip-specific frame indices are hardcoded in video logic:
   - F344, F350, F404, 708, 1582, 1743, 1945
3. No unscaled magic aspect ratios or fixed pixel coordinates:
   - 0.38 * h, 0.60 * h, 0.35 * h, 0.45 * h, min_subtitle_y = 450

Returns exit code 0 if 100% clean, non-zero if violations are detected.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

# ==============================================================================
# UPGRADED ANTI-OVERFITTING RULES (MILESTONE M0 ITERATION 2)
# ==============================================================================

# 1. Clip tokens (Both Vietnamese accented and unaccented, clip/commit IDs, magic colors)
FORBIDDEN_TOKENS = [
    # Vietnamese keywords (with and without diacritics)
    r"soạn hợp đồng", r"soan hop dong",
    r"ăn sáng", r"an sang",
    r"xong việc đi về", r"xong viec di ve",
    r"2x tuổi", r"2x tuoi",
    r"tủ lạnh", r"tu lanh",
    r"xe porsche",
    # Specific video clip & commit identifiers
    r"tmpy8evxmno",
    r"preview_tmpy8evxmno_clean",
    r"\b7553d10\b",
    # Hardcoded color simulation tokens
    r"\bpaper_bgr\b",
    r"218(?:\.0)?\s*,\s*230(?:\.0)?\s*,\s*234(?:\.0)?",
]

# Frame variables must be bound to prevent false positives on len(...) or HTTP status codes
FRAME_VARS = r"(?:frame_idx|f_idx|frame_num|frame|f|idx|cur_frame|current_frame|fidx|fnum)"

FORBIDDEN_FRAME_PATTERNS = [
    # Variable first: f == 350, f <= 404, f in [350, 404]
    rf"\b{FRAME_VARS}\s*(?:==|in|<=|>=|<|>)\s*\[?\s*(?:344|350|404|708|1582|1743|1945)\b",
    # Number first: 344 <= f, 350 == frame_idx
    rf"\b(?:344|350|404|708|1582|1743|1945)\s*(?:<=|>=|<|>|==)\s*{FRAME_VARS}\b",
    # Variable in range: f in range(344, 405)
    rf"\b{FRAME_VARS}\s+in\s+range\(\s*(?:344|350|404|708|1582|1743|1945)",
    # Anonymous range: in range(344, ...)
    r"\bin\s+range\(\s*(?:344|350|404|708|1582|1743|1945)",
    # Frame prefix token: F350, F708
    r"\bF(?:344|350|404|708|1582|1743|1945)\b",
]

FORBIDDEN_COORDINATE_PATTERNS = [
    # Bidirectional aspect ratio scalings (0.38, 0.60, 0.35, 0.45)
    r"(?:0\.38|0\.60|0\.35|0\.45)\s*\*\s*(?:h|height)\b",
    r"\b(?:h|height)\s*\*\s*(?:0\.38|0\.60|0\.35|0\.45)\b",
    # Fixed magic subtitle pixel offsets
    r"min_subtitle_y\s*=\s*450",
    # Car cabin Porsche coordinates
    r"\b(?:global_y|y|yy)\s*(?:>=|>|<=|<|==)\s*(?:285|290)\b",
    r"\b(?:285|290)\s*(?:<=|<|>=|>|==)\s*(?:global_y|y|yy)\b",
]

# Legacy and offline audit/test files that legitimately contain test video definitions
AUDIT_AND_LEGACY_FILES = {
    "verify_ground_truth_audit.py",
    "extract_ground_truth_complete.py",
    "verify_round3_independent.py",
    "verify_it5_results.py",
    "run_phase6_full_evaluation.py",
    "run_generality_tests.py",
    "test_complete_agent_suite.py",
    "render_master_v3.py",
    "render_master_v4.py",
    "render_master_v5.py",
    "render_master_v6.py",
    "render_master_v7.py",
    "render_it5_video.py",
    "render_it6_video.py",
    "render_round3_master.py",
    "render_round3_final.py",
    "render_phase6_preview.py",
    "gen_masks_fast.py",
    "export_motion_and_gates.py",
    "eval_9_direct.py",
    "generate_parent_check_collage.py",
}


class OverfitLinter:
    def __init__(self, root_dir: Path, include_legacy: bool = False, verbose: bool = False):
        self.root_dir = Path(root_dir)
        self.include_legacy = include_legacy
        self.verbose = verbose
        self.violations: List[Dict[str, Any]] = []

    def scan_file(self, file_path: Path):
        """Scans a single python file for forbidden overfit patterns."""
        if not self.include_legacy and file_path.name in AUDIT_AND_LEGACY_FILES:
            if self.verbose:
                print(f"[SKIP LEGACY/AUDIT] {file_path.name}")
            return

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            if self.verbose:
                print(f"[ERROR READING] {file_path}: {e}")
            return

        lines = content.splitlines()

        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            # Ignore pure comment lines if not containing forbidden frame patterns
            is_comment = stripped.startswith("#") or stripped.startswith("//")

            # 1. Check forbidden clip tokens
            for token_pat in FORBIDDEN_TOKENS:
                # In documentation / swagger string descriptions, don't trigger unless code assignment
                if re.search(token_pat, line, re.IGNORECASE):
                    # Check if it is swagger description or schema example
                    if "description=" in line or "example=" in line:
                        continue
                    if is_comment and "porsche" in token_pat:
                        continue

                    self.violations.append({
                        "file": str(file_path.relative_to(self.root_dir)),
                        "line": idx,
                        "rule": f"FORBIDDEN_TOKEN({token_pat})",
                        "content": stripped,
                    })

            # 2. Check forbidden frame numbers
            for frame_pat in FORBIDDEN_FRAME_PATTERNS:
                if re.search(frame_pat, line):
                    self.violations.append({
                        "file": str(file_path.relative_to(self.root_dir)),
                        "line": idx,
                        "rule": f"FORBIDDEN_FRAME_CONDITION({frame_pat})",
                        "content": stripped,
                    })

            # 3. Check forbidden coordinates
            for coord_pat in FORBIDDEN_COORDINATE_PATTERNS:
                if re.search(coord_pat, line):
                    self.violations.append({
                        "file": str(file_path.relative_to(self.root_dir)),
                        "line": idx,
                        "rule": f"FORBIDDEN_COORDINATE_BAND({coord_pat})",
                        "content": stripped,
                    })

    def scan_directory(self, dir_path: Path):
        """Recursively scan a directory for python files, ignoring runtime workspace and cache directories."""
        if not dir_path.exists():
            return
        ignored_dirs = {"workspace", "__pycache__", ".git", ".pytest_cache", ".venv", "venv", "node_modules"}
        for root, dirs, files in os.walk(dir_path):
            dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith(".")]
            for file in files:
                if file.endswith(".py"):
                    self.scan_file(Path(root) / file)

    def run(self, targets: Optional[List[str]] = None) -> bool:
        """Runs the linter across target directories."""
        self.violations.clear()

        if targets:
            for t in targets:
                p = self.root_dir / t
                if p.is_file():
                    self.scan_file(p)
                elif p.is_dir():
                    self.scan_directory(p)
        else:
            # Default target: services/ai-agent-service/app/ and scripts/
            app_dir = self.root_dir / "services" / "ai-agent-service" / "app"
            scripts_dir = self.root_dir / "scripts"
            self.scan_directory(app_dir)
            self.scan_directory(scripts_dir)

        return len(self.violations) == 0


def main():
    parser = argparse.ArgumentParser(description="Static Anti-Overfitting and Anti-Gaming Linter")
    parser.add_argument("--path", default=None, help="Specific file or directory to scan")
    parser.add_argument("--include-legacy", action="store_true", help="Include legacy offline renderers")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    linter = OverfitLinter(repo_root, include_legacy=args.include_legacy, verbose=args.verbose)

    targets = [args.path] if args.path else None
    passed = linter.run(targets)

    print("=" * 70)
    print("ANTI-OVERFITTING LINT SCAN RESULTS:")
    print("=" * 70)
    if passed:
        print("  [PASSED] 0 forbidden clip-specific tokens, frame conditions, or coordinate bands found!")
        print("=" * 70)
        sys.exit(0)
    else:
        print(f"  [FAILED] Found {len(linter.violations)} violations:")
        for v in linter.violations:
            print(f"  - {v['file']}:{v['line']} [{v['rule']}] -> {v['content']}")
        print("=" * 70)
        sys.exit(1)


if __name__ == "__main__":
    main()
