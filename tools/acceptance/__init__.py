#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/acceptance — Frozen Acceptance Judge & Anti-Gaming Framework.
Milestone M0.
"""

from tools.acceptance.metrics import (
    StreamingMetricsAccumulator,
    compute_dhash,
    compute_psnr,
    compute_ssim,
    evaluate_audio_integrity,
    evaluate_c1_residual_text,
    evaluate_c2_collateral_damage,
    evaluate_c3_reconstruction_fidelity,
    evaluate_c4_temporal_consistency,
    evaluate_c5_negatives,
    evaluate_c6_artifacts,
    evaluate_c7_av_integrity,
    evaluate_c8_resource_limits,
    evaluate_frame_pair,
)
from tools.acceptance.phrase_lists import FROZEN_SCOPE_PHRASES, evaluate_scope_parser, get_frozen_phrases
from tools.acceptance.sabotage_suite import SabotageSuiteRunner
from tools.acceptance.synthetic_generator import P_CASES, SyntheticBenchmarkGenerator
from tools.acceptance.thresholds import GLOBAL_THRESHOLDS, FrozenJudgeThresholds

__all__ = [
    "compute_psnr",
    "compute_ssim",
    "compute_dhash",
    "evaluate_c1_residual_text",
    "evaluate_c2_collateral_damage",
    "evaluate_c3_reconstruction_fidelity",
    "evaluate_c4_temporal_consistency",
    "evaluate_c5_negatives",
    "evaluate_c6_artifacts",
    "evaluate_c7_av_integrity",
    "evaluate_c8_resource_limits",
    "evaluate_frame_pair",
    "evaluate_audio_integrity",
    "StreamingMetricsAccumulator",
    "FROZEN_SCOPE_PHRASES",
    "evaluate_scope_parser",
    "get_frozen_phrases",
    "SabotageSuiteRunner",
    "SyntheticBenchmarkGenerator",
    "P_CASES",
    "GLOBAL_THRESHOLDS",
    "FrozenJudgeThresholds",
]
