# Phase 6 Iteration 2: Master Evaluation Suite & Evidence Dossier

Please refer to [`review-evidence/README.md`](review-evidence/README.md) for full details, artifact indexes, and verification runbooks.

## Summary & Verification Status
- **Target Main Commit**: `fbdb59138978d1a99b0b1e24a693c17a0ea4e516`
- **Evaluation Environment**: `kirito-server` (Container `dashboard_ai_agent`, RAM Limit: 1350MB)
- **Real Clip Evaluation (`tmpy8evxmno.mp4`)**:
  * 1945/1945 frames evaluated (100% full scan, 64.87s, 42.38 MB preview video).
  * Residual OCR: 655 frames with residual text (33.68%), 1290 frames clean (66.32% pass rate).
  * Outside Mask Fidelity: Mean SSIM = 0.9653, PSNR delta = 35.15 dB.
  * Audio Integrity: Bit-exact AAC stream copy (`ac4cf45e903fe539fcbe1cbff7999847`).
  * Worst 5 Penalty Frames: f1425 (3230.0), f1428 (2930.0), f1411 (2880.0), f1426 (2730.0), f1407 (2680.0).
- **Synthetic Held-Out Suite (21 Cases)**:
  * 21/21 cases evaluated authentically through pipeline.
  * 1 case PASS (`SYNTH_HELD_03`), 20 cases FAIL against frozen thresholds.
  * Zero gaming, 100% bit-exact synchronization between CSV and summary JSON.
- **Verification Command**:
  ```bash
  python3 tools/verify_evidence_integrity.py --evidence-dir review-evidence --thresholds config/frozen_thresholds.json
  ```
