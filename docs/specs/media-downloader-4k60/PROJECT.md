# Project: Nâng Cấp Toàn Diện Công Cụ Tải Video Mạng Xã Hội 20+ Nền Tảng (4K/60fps Dual Distribution)

## Architecture

- **MultiTierMediaPipeline (`app/services/media_downloader.py`)**:
  - Tier 1: TikWM API chuyên dụng cho TikTok / Douyin (tải video không watermark tốc độ cao, giữ nguyên direct MP3).
  - Tier 2: `yt-dlp` Core Engine với thuật toán lựa chọn định dạng đa chiều thông qua `format_sort: ["res", "fps", "quality", "size", "br"]` và `format: "bestvideo+bestaudio/best"`, tự động mux lossless thành container MP4 tiêu chuẩn thông qua FFmpeg.
  - Tier 3: Playwright Chromium Network Sniffer cho Threads và các trang dynamic hydration phức tạp.
  - Universal Extractor Fallback: Kích hoạt bộ trích xuất vạn năng của `yt-dlp` cho bất kỳ URL video web nào không khớp danh sách cụ thể.
  - Stream Container Faststart: Tự động dịch chuyển `moov atom` lên đầu tệp (`-movflags +faststart`) qua `merger` và `videoremuxer` postprocessors để cho phép streaming tức thì.
  - Concurrency & Zero-RAM Disk Streaming: Duy trì `asyncio.Semaphore(2)` bảo vệ CPU 2 cores, chunked disk streaming 64KB/1MB trực tiếp ra SSD NVMe `/tmp/media_downloads/`, thu hồi RAM qua `reclaim_memory_background(0.2s)` và quét rác đĩa trong khối `finally`.

- **Mô Hình Phân Phối Kép (Dual-Track Distribution Engine)**:
  - Trường hợp video $\le 50\text{MB}$: Gửi trực tiếp qua Telegram Bot bằng `send_video` (`supports_streaming=True`, full metadata). Fallback sang `send_document_file` streaming đĩa nếu gặp lỗi HTML parse hoặc codec Telegram.
  - Trường hợp video $> 50\text{MB}$ (Video 4K / 1080p60 dung lượng lớn): Kích hoạt đồng thời 2 kênh:
    - Kênh 1 (Telegram Lossless Part Chunking): Dùng `VideoChunker.split_video()` (`ffmpeg -c copy`) cắt video thành các Part $\le 48\text{MB}$ trong $< 1.5\text{s}$, giữ nguyên 100% 4K/60fps gốc, gửi tuần tự lên Telegram kèm Streaming Purge (`os.unlink` ngay từng part sau khi gửi xong).
    - Kênh 2 (Direct Server Download Link): Chuyển giao tệp sang `media_storage_manager` cung cấp 2 đường dẫn tải trực tiếp nguyên khối tệp gốc: LAN Gigabit (`http://192.168.0.100:8084/api/ai/media/download/...`) tốc độ 50-100MB/s và WAN Ngrok Internet toàn cầu. Endpoint hỗ trợ chuẩn `HTTP 206 Partial Content` (Range requests) cho phép resume và multi-thread download (IDM).

- **Telegram Fast-Path Interceptor & AI Agent Tools**:
  - `_MEDIA_URL_REGEX` trong `telegram_bot.py`: Mở rộng nhận diện 24+ nền tảng (YouTube, Shorts, Twitch, Vimeo, Dailymotion, Rumble, Streamable, Loom, Facebook, Instagram, Twitter/X, Threads, Reddit, Pinterest, TikTok, Douyin, CapCut, Xiaohongshu/RedNote, Weibo, Bilibili, Kuaishou, Lemon8, Likee, Bluesky...) kèm Universal Fallback.
  - `_detect_fastpath_media_download`: Bóc tách URL, phân loại chuẩn xác giữa ý định tải video và trích xuất âm thanh MP3, bỏ qua LLM (Zero-LLM Latency).
  - `ai_agent_tools.py`: Cập nhật tool `download_media_video` và đồng bộ Dynamic Scoping (`has_media_link`, `is_media`).
  - `ai_agent.py`: Cập nhật System Prompt Mục 2e khẳng định năng lực tải 4K/60fps từ 20+ nền tảng và phản xạ BLUF "Dạ CÓ!".

## Feature Inventory

| # | Feature | Description | Milestone | Source | Status |
| --- | --------- | ------------- | ----------- | -------- | -------- |
| 1 | 20+ Platforms Regex & URL Normalizer | Nhận diện 20+ nền tảng, bóc tách tracking params (?si=, ?mibextid=, ?share_id=...) và unwrap shortlinks | M1 | ORIGINAL_REQUEST §R1 | **DONE** |
| 2 | Universal Web Extractor Fallback | Hỗ trợ tải video từ bất kỳ URL web nào qua generic yt-dlp fallback | M1 | ORIGINAL_REQUEST §R1 | **DONE** |
| 3 | Max Resolution & 60fps Format Selection | `format_sort: ["res", "fps", "quality", "size", "br"]` & `format: "bestvideo+bestaudio/best"` ưu tiên 4K/60fps | M1 | ORIGINAL_REQUEST §R2 | **DONE** |
| 4 | FFmpeg Lossless Muxing & Moov Faststart | Ghép nối lossless container MP4 và nhúng moov atom faststart cho cả merger & videoremuxer | M1 | ORIGINAL_REQUEST §R2 | **DONE** |
| 5 | Dual Distribution: Lossless Part Chunking | FFmpeg `-c copy` chia part $\le 48\text{MB}$ trong $< 1.5\text{s}$, gửi Telegram kèm Streaming Purge | M2 | ORIGINAL_REQUEST §R3 | **DONE** |
| 6 | Dual Distribution: Direct Link HTTP 206 | Cung cấp link LAN Gigabit (`:8084`) & WAN Ngrok tải file gốc 4K60 với HTTP 206 Partial Content | M2 | ORIGINAL_REQUEST §R3 | **DONE** |
| 7 | Telegram Fast-Path Interceptor Mở Rộng | Nhận diện 20+ nền tảng, phân biệt rành mạch video vs audio, bypass LLM tức thì | M2 | ORIGINAL_REQUEST §R4 | **DONE** |
| 8 | AI Agent Tools & Dynamic Scoping Sync | Đồng bộ mô tả tool `download_media_video` và dynamic scoping keywords trong `ai_agent_tools.py` | M2 | ORIGINAL_REQUEST §R4 | **DONE** |
| 9 | AI Agent System Prompt Mục 2e & BLUF | Cập nhật tri thức trợ lý Tiểu Bảo Bảo trong `ai_agent.py` về tải 4K/60fps 20+ platforms | M2 | ORIGINAL_REQUEST §R4 | **DONE** |
| 10 | Standardize LAN Base URL Port 8084 | Chuẩn hóa `LAN_DOWNLOAD_BASE_URL` trong `media_storage_manager.py` trỏ về port `8084` | M2 | Explorer 2 Survey | **DONE** |
| 11 | Opaque-Box E2E Test Suite (Tiers 1-4) | Thiết kế bộ test toàn diện: Tier 1 (Coverage 20+), Tier 2 (BVA/Edge), Tier 3 (Cross), Tier 4 (Real-world) | M3 | ORIGINAL_REQUEST §Acceptance Criteria | **DONE** |
| 12 | Empirical Verification trên kirito-server | Kiểm thử thực tế thô với link thật 60fps/4K, đo đạc `ffprobe`, kiểm chứng phân phối kép và 100% test pass | M3 | ORIGINAL_REQUEST §Acceptance Criteria | **DONE** |

## Milestones

| # | Name | Scope | Dependencies | Status |
| --- | ------ | ------- | ------------- | -------- |
| M1 | MultiTierMediaPipeline Core Upgrade | `media_downloader.py`: format_sort 4K/60fps, format chain, moov faststart, 20+ platform regex/extractor, universal fallback | none | **DONE** |
| M2 | Dual Distribution & Telegram / Agent Integration | `telegram_bot.py`, `ai_agent_tools.py`, `ai_agent.py`, `media_storage_manager.py`: Fastpath 20+, Dual-Track delivery, tool scoping, prompt 2e, port 8084 | M1 | **DONE** |
| M3 | E2E Testing Suite & Empirical Verification | `tests/test_multi_platform_media.py`, `tests/test_format_sort_60fps.py`, `tests/test_media_pipeline_20plus_platforms.py`, empirical live test trên kirito-server | M1, M2 | **DONE** |

## Interface Contracts

### `MultiTierMediaPipeline` (`media_downloader.py`)

- `download(url: str) -> MediaItem`:
  - Nhận diện URL, thực hiện tải video chất lượng cao nhất (4K/60fps nếu có).
  - Trả về `MediaItem` với `file_path`, `title`, `duration`, `width`, `height`, `fps`, `file_size`, `is_temp_file`.
- `_sync_ytdlp_download(url: str, out_tmpl: str) -> Dict[str, Any]`:
  - Áp dụng `format_sort: ["res", "fps", "quality", "size", "br"]`.
  - Áp dụng `format: "bestvideo+bestaudio/best"`.
  - Áp dụng `postprocessor_args: {"merger": ["-movflags", "+faststart"], "videoremuxer": ["-movflags", "+faststart"]}`.
- `download_audio(url: str) -> MediaItem`:
  - Trích xuất MP3 320kbps CBR / Direct CDN MP3, giữ nguyên 100% logic Dual-Engine đã kiểm chứng.

### `TelegramBot` (`telegram_bot.py`)

- `_detect_fastpath_media_download(text: str) -> Optional[FastPathMediaIntent]`:
  - Nhận diện 20+ nền tảng mạng xã hội và Universal URL fallback.
  - Phân loại chính xác `media_type="video"` hoặc `media_type="audio"`.
- `handle_media_download(chat_id, user_id, intent)`:
  - Nếu video $\le 50\text{MB}$: Gửi trực tiếp qua `send_video()`.
  - Nếu video $> 50\text{MB}$: Gửi lossless parts qua `VideoChunker.split_video()` và đính kèm 2 Direct Links (LAN `:8084` + WAN Ngrok).

### `AIAgentTools` (`ai_agent_tools.py`)

- `download_media_video(url: str, caption: Optional[str] = None)`:
  - Hỗ trợ 20+ nền tảng, video 4K/60fps, trả về kết quả trực tiếp hoặc kích hoạt phân phối kép.
- Dynamic Scoping: `has_media_link` và `is_media` nhận diện toàn bộ domain và từ khóa của 20+ nền tảng.

## Code Layout

- `services/ai-agent-service/app/services/media_downloader.py`: MultiTierMediaPipeline, format_sort, faststart, universal fallback (DONE)
- `services/ai-agent-service/app/services/telegram_bot.py`: _MEDIA_URL_REGEX, fast-path interceptor, dual-track delivery
- `services/ai-agent-service/app/services/ai_agent_tools.py`: Tool definition & dynamic scoping keywords
- `services/ai-agent-service/app/services/ai_agent.py`: System prompt Mục 2e
- `services/ai-agent-service/app/services/media_storage_manager.py`: LAN base URL port 8084 standardization
- `services/ai-agent-service/tests/test_multi_platform_media.py`: Bộ test nền tảng mở rộng
- `services/ai-agent-service/tests/test_format_sort_60fps.py`: Bộ test chuyên biệt kiểm tra format_sort và 60fps
- `services/ai-agent-service/tests/test_media_pipeline_20plus_platforms.py`: Bộ test E2E 20+ nền tảng

## RÀNG BUỘC TUYỆT ĐỐI (CRITICAL CONSTRAINTS)

1. TUYỆT ĐỐI KHÔNG đụng chạm, không stage, không commit và không push bất kỳ file nào thuộc thư mục `android-app/`.
2. Git commit messages BẮT BUỘC viết hoàn toàn bằng tiếng Anh.
3. Mọi giải thích, báo cáo, tài liệu BẮT BUỘC viết hoàn toàn bằng tiếng Việt chỉn chu, chuyên nghiệp.
4. Sau khi hoàn thành, BẮT BUỘC kiểm thử thực tế thô (empirical verification) với các link thực tế và bộ test tự động trước khi kết luận.
