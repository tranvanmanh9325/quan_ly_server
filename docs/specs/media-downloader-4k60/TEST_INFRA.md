# E2E Test Infra: Nâng Cấp Công Cụ Tải Video 20+ Nền Tảng & 4K/60fps Dual Distribution

## Test Philosophy

- **Opaque-box & Requirement-driven**: Thiết kế kiểm thử dựa trên yêu cầu từ `ORIGINAL_REQUEST.md`, độc lập hoàn toàn với cấu trúc nội bộ.
- **Phương pháp luận**: Category-Partition + Boundary Value Analysis (BVA) + Pairwise Combinatorial Testing + Real-World Workload Testing.
- **Empirical Verification (Kiểm thử thực nghiệm thô)**: Đo đạc thực tế trên môi trường máy chủ `kirito-server` với binary thật (`yt-dlp`, `ffmpeg`, `ffprobe`) và các liên kết video trực tiếp, kiểm tra độ phân giải, FPS và 0 rò rỉ đĩa/RAM.

## Feature Inventory Test Mapping

| # | Feature | Nguồn Yêu Cầu | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
| --- | --------- | --------------- | :------: | :------: | :------: | :------: |
| F1 | 20+ Platforms Regex & URL Normalizer | ORIGINAL_REQUEST §R1 | 24 | 10 | ✓ | ✓ |
| F2 | Universal Web Extractor Fallback | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| F3 | Max Resolution & 60fps Format Selection | ORIGINAL_REQUEST §R2 | 8 | 5 | ✓ | ✓ |
| F4 | FFmpeg Lossless Muxing & Moov Faststart | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| F5 | Dual Distribution: Lossless Part Chunking | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| F6 | Dual Distribution: Direct Link HTTP 206 | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| F7 | Telegram Fast-Path Interceptor Mở Rộng | ORIGINAL_REQUEST §R4 | 15 | 8 | ✓ | ✓ |
| F8 | AI Agent Tools & Dynamic Scoping Sync | ORIGINAL_REQUEST §R4 | 6 | 4 | ✓ | ✓ |
| F9 | AI Agent System Prompt Mục 2e & BLUF | ORIGINAL_REQUEST §R4 | 4 | 2 | ✓ | ✓ |
| F10 | Standardize LAN Base URL Port 8084 | Explorer 2 Survey | 3 | 2 | ✓ | ✓ |

## Test Architecture

- **Runner**: `pytest` và `python -m unittest` trong môi trường virtualenv của `services/ai-agent-service/` hoặc container `dashboard_ai_agent`.
- **Test File Layout**:
  - `tests/test_multi_platform_media.py`: Bộ test hồi quy mở rộng cho 20+ nền tảng regex, routing, tool scoping.
  - `tests/test_format_sort_60fps.py`: Bộ test chuyên sâu thuật toán `format_sort`, ưu tiên 4K/60fps, container muxing MP4 và moov atom faststart.
  - `tests/test_media_pipeline_20plus_platforms.py`: Bộ test E2E kiểm thử chuỗi xử lý tải từ nhận diện đến phân phối kép.
- **Empirical Harness**: Script kiểm thử thực nghiệm thô đo đạc `ffprobe` trên `kirito-server`.

## Real-World Application Scenarios (Tier 4)

| # | Scenario | Features Exercised | Mức Độ Phức Tạp |
| --- | ---------- | -------------------- | ----------------- |
| 1 | Tải YouTube Shorts / 4K60 Video qua FastPath | F1, F3, F4, F7 | Cao |
| 2 | Tải Twitch Clip 60fps qua ReAct Tool | F1, F3, F4, F8 | Trung bình |
| 3 | Tải Video > 50MB kích hoạt phân phối kép (Telegram Parts + HTTP 206 LAN/WAN) | F3, F5, F6, F7, F10 | Cao |
| 4 | Trích xuất âm thanh MP3 từ liên kết 20+ nền tảng mới | F1, F7 (audio intent preservation) | Trung bình |
| 5 | Tải video từ trang web bất kỳ qua Universal Extractor | F2, F3, F4, F7 | Cao |

## Coverage Thresholds

- **Tier 1 (Feature Coverage)**: $\ge 5$ test cases cho mỗi tính năng cốt lõi (Tổng $\ge 60$ cases).
- **Tier 2 (Boundary & Corner Cases)**: Bao phủ tham số query tracking (`?si=`), URL không hợp lệ, URL không có schema, lỗi định dạng.
- **Tier 3 (Cross-Feature Combinations)**: Kiểm thử tương tác giữa FastPath vs ReAct Tools, Video vs Audio intent, Single file vs Part Chunking.
- **Tier 4 (Real-World Workloads)**: Kiểm thử thực tế với link thật trên máy chủ `kirito-server`.
- **Hồi Quy Toàn Bộ (Regression Safety)**: 100% test suites hiện có của dự án (875+ tests bao gồm file transfer, audio pipeline, media storage) PASS 100%.
