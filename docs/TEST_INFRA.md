# E2E Test Infra: MultiTierMediaPipeline Expansion

## Test Philosophy
- Opaque-box, requirement-driven: Kiểm thử từ giao diện người dùng (Telegram Fast-Path Regex, Bot API, và Pipeline Entrypoint).
- Phương pháp: 4 Tiers (Category-Partition, Boundary Value Analysis, Pairwise Combinatorial, Real-World Workload Testing trên Container Production).

## Feature Inventory & Test Mapping
| # | Feature | Source (Requirement) | Tier 1 (Coverage) | Tier 2 (Boundary) | Tier 3 (Pairwise) |
|---|---------|----------------------|:-----------------:|:-----------------:|:-----------------:|
| 1 | YouTube Shorts & Videos | ORIGINAL_REQUEST §R1 | ≥ 5 test cases | ≥ 5 test cases | ✓ |
| 2 | Facebook Reels & Watch | ORIGINAL_REQUEST §R1 | ≥ 5 test cases | ≥ 5 test cases | ✓ |
| 3 | Threads Video Extraction | ORIGINAL_REQUEST §R1 | ≥ 5 test cases | ≥ 5 test cases | ✓ |
| 4 | Giới hạn 50MB (VideoTooLargeError) | ORIGINAL_REQUEST §R1 | ≥ 5 test cases | ≥ 5 test cases | ✓ |
| 5 | Chunked Disk Streaming 64KB | ORIGINAL_REQUEST §R2 | ≥ 5 test cases | ≥ 5 test cases | ✓ |
| 6 | Fast-Path Regex & Bypass | ORIGINAL_REQUEST §R3 | ≥ 5 test cases | ≥ 5 test cases | ✓ |
| 7 | ReAct Agent Tool Integration | ORIGINAL_REQUEST §R3 | ≥ 5 test cases | ≥ 5 test cases | ✓ |
| 8 | Caption HTML & Fallback Plain Text | ORIGINAL_REQUEST §Acceptance | ≥ 5 test cases | ≥ 5 test cases | ✓ |
| 9 | 100% Zero-Disk-Leak | ORIGINAL_REQUEST §R3, Acceptance | ≥ 5 test cases | ≥ 5 test cases | ✓ |
| 10 | Production Raw Honest Test | ORIGINAL_REQUEST §Acceptance | 3 nền tảng | Edge URLs | ✓ |

## Test Architecture
- **Cục bộ (Local Unit & Mock Tests)**:
  - Vị trí: `services/ai-agent-service/tests/`
  - Thực thi: `.venv/Scripts/python.exe -m unittest discover tests`
- **Môi trường Production (Raw Honest Tests)**:
  - Container: `dashboard_ai_agent` trên `kirito-server` qua `ssh-bridge`
  - Thực thi: `docker exec dashboard_ai_agent python -c "..."`
  - Xác nhận trực tiếp: Trích xuất stream H.264/AAC, ffprobe codec kiểm tra, và xác nhận `/tmp/media_downloads/` sạch 0 file thừa.

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Nền Tảng / Đặc tính | Độ Phức Tạp |
|---|----------|---------------------|-------------|
| 1 | Người dùng gửi link YouTube Shorts trực tiếp qua Telegram | YouTube Shorts | Trung bình |
| 2 | Người dùng gửi link Facebook Reel rút gọn (`share/r` / `fb.watch`) kèm chữ "tải giùm anh" | Facebook Reels | Cao |
| 3 | Người dùng gửi link bài viết Threads chứa video | Threads SPA | Cao |
| 4 | Người dùng gửi link video YouTube dài dung lượng > 50MB | YouTube > 50MB | Trung bình |
| 5 | Video có tiêu đề chứa ký tự HTML đặc biệt (`<test>`, `&`, `"` ) | Caption formatting | Trung bình |
| 6 | Nhiều request đồng thời kiểm tra Semaphore(2) và Zero-Disk-Leak | Concurrency & Cleanup | Cao |
