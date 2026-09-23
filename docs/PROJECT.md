# Project: MultiTierMediaPipeline Expansion (YouTube, Facebook, Threads)

## Architecture

Hệ thống tải media đa nền tảng phân tầng cho máy chủ `kirito-server` (RAM 3.2GB, container limit 1800MB):

- **Tier 1 (TikWM API)**: Tải video TikTok & Douyin siêu tốc (< 1s), không watermark, hỗ trợ Album ảnh.
- **Tier 2 (Universal yt-dlp)**: Tải video YouTube (Shorts & Clip ngắn) và Facebook (Reels, Watch, Share). Ép buộc `source_address: 0.0.0.0` (IPv4) để tránh lỗi mạng IPv6 Docker bridge; tiền xử lý HTTP redirect cho link Facebook rút gọn; trích xuất MP4 AVC1/H.264 + AAC; Semaphore(2) giới hạn CPU.
- **Tier 3 (Playwright Headless Chromium)**: Trích xuất video Threads qua Network Sniffer bắt luồng CDN Meta (`fbcdn.net`), bỏ byte range query; Semaphore(1) bảo vệ RAM, giải phóng sớm ngay khi đóng Chromium trước khi stream 48MB.
- **Zero-RAM Chunked Disk Streaming**: Stream 64KB trực tiếp ra đĩa SSD `/tmp/media_downloads/` (nằm trên overlayfs SSD vật lý 400GB) với mô hình RAII `try...finally:` chống rò rỉ đĩa khi gặp `CancelledError`.
- **100% Zero-Disk-Leak**: 4 lớp bảo vệ (In-flight `MediaItem.cleanup()` bảo vệ an toàn `TEMP_MEDIA_DIR`, On-error unlink/rmtree, Proactive sweeper `cleanup_expired_media(600)`).
- **Fast-Path Gateway**: Nhận diện link media qua `_MEDIA_URL_REGEX` trong `telegram_bot.py`, bypass LLM ReAct loop (< 2s), gửi video trực tiếp kèm HTML caption có fallback plain text.
- **Agent Tool Gateway**: Tool `download_media_video` trong `ai_agent_tools.py` thuộc `DIRECT_RETURN_TOOLS`, phục vụ chat tự nhiên.

## Feature Inventory

| # | Feature | Description | Milestone | Source |
| --- | --------- | ------------- | ----------- | -------- |
| 1 | YouTube Shorts & Video | Nhận diện và tải video YouTube Shorts & Video ngắn dưới 50MB, định dạng MP4 AVC1/AAC, ép IPv4 `0.0.0.0` | M1 | ORIGINAL_REQUEST §R1, R2 |
| 2 | Facebook Reels & Watch | Nhận diện và tải Facebook Reels, Watch, Share, resolve redirect URL rút gọn trước khi vào yt-dlp | M1 | ORIGINAL_REQUEST §R1, R2 |
| 3 | Threads Video Extraction | Nhận diện link Threads (`threads.net/@.../post/...`), trích xuất qua Playwright Sniffer stream CDN Meta | M1 | ORIGINAL_REQUEST §R1, R2 |
| 4 | Dung lượng & Ngưỡng 50MB | Kiểm soát dung lượng 48MB/50MB qua Header, Stream chunks và metadata, ném `VideoTooLargeError` kèm link gốc | M1 | ORIGINAL_REQUEST §R1 |
| 5 | Chunked Disk Streaming 64KB | Ghi đĩa tạm từng chunk 64KB trực tiếp ra SSD `/tmp/media_downloads/`, bảo đảm Zero-RAM, Semaphore(2) | M1 | ORIGINAL_REQUEST §R2 |
| 6 | Fast-Path Bot Integration | Cập nhật `_MEDIA_URL_REGEX` và `_detect_fastpath_media_download` trong `telegram_bot.py`, phản hồi < 2s | M2 | ORIGINAL_REQUEST §R3 |
| 7 | ReAct Agent Tool Integration | Cập nhật `download_media_video`, scoping `is_media` trong `ai_agent_tools.py`, prompt trong `ai_agent.py` | M2 | ORIGINAL_REQUEST §R3 |
| 8 | Caption Formatting & Fallback | Caption HTML (`<b>`, `<i>`, `<code>`), tự động fallback sang Plain Text qua `f.seek(0)` khi lỗi parse entities | M2 | ORIGINAL_REQUEST §Acceptance |
| 9 | 100% Zero-Disk-Leak | Đảm bảo khối `try...finally: media_item.cleanup()` ở mọi nhánh, dọn sạch 0 file rác mồ côi | M1, M2 | ORIGINAL_REQUEST §R3, Acceptance |
| 10 | Production Raw Honest Test | Kiểm thử thực tế trên container `dashboard_ai_agent` với link YouTube Shorts, FB Reels, Threads thực tế | M3 | ORIGINAL_REQUEST §Acceptance |

## Milestones

| # | Name | Scope | Dependencies | Status |
| --- | ------ | ------- | ------------- | -------- |
| M1 | Core Pipeline & Multi-Platform Extractors | Nâng cấp `media_downloader.py`: IPv4 yt-dlp cho YouTube, resolve redirect cho Facebook, Playwright sniffer cho Threads, Chunked streaming 64KB, Zero-Disk-Leak, directory safety | None | **DONE** |
| M2 | Fast-Path Bot & AI Agent Tool Gateway | Nâng cấp `telegram_bot.py` (`_MEDIA_URL_REGEX`, `_detect_fastpath_media_download`, `send_video` fallback) và `ai_agent_tools.py` (`download_media_video`, `is_media`), `ai_agent.py` | M1 | **DONE** |
| M3 | Final Verification & Raw Honest Test | Kiểm thử đơn vị toàn diện + Raw Honest Test trên container production `dashboard_ai_agent`, xác thực 100% Zero-Disk-Leak | M1, M2 | **DONE** |

## Interface Contracts

### `media_downloader.py` ↔ `telegram_bot.py` & `ai_agent_tools.py`

- Khởi tạo: `pipeline = MultiTierMediaPipeline(http_client=self._http_client)`
- Gọi tải: `media_item: MediaItem = await pipeline.download(url: str)`
- Xử lý ngoại lệ:
  - `VideoTooLargeError`: Ngoại lệ khi video vượt ngưỡng 50MB, chứa thông báo chi tiết và dung lượng.
  - `MediaPipelineError`: Ngoại lệ khi tất cả các tầng tải thất bại.
- Dọn dẹp: Bắt buộc gọi `media_item.cleanup()` trong khối `finally`.

## Code Layout

- `services/ai-agent-service/app/services/media_downloader.py`: Core pipeline, Tiers, extractors, streaming, cleanup.
- `services/ai-agent-service/app/services/telegram_bot.py`: Telegram bot handlers, Fast-Path interceptor, `send_video`.
- `services/ai-agent-service/app/services/ai_agent_tools.py`: Tool registry, `download_media_video`, scoped tools.
- `services/ai-agent-service/app/services/ai_agent.py`: Agent system prompt, tool definitions.
- `services/ai-agent-service/tests/`: Unit tests, E2E tests.
