# Project: Cổng Chuyển Tệp Siêu Tốc (High-Speed LAN & WAN File Transfer Portal)

## Architecture
- **Phân tách trách nhiệm (Separation of Concerns)**:
  * Toàn bộ logic lưu trữ và quản lý phiên truyền tệp được bao bọc độc lập trong `TransferStorageManager` (`app/services/transfer_storage_manager.py`), hoàn toàn tách biệt khỏi `MediaStorageManager` (tránh rủi ro phá vỡ 875+ tests media hiện hữu).
  * Router chuyên biệt `/api/ai/transfer` (`app/routers/file_transfer.py`) phục vụ cả API tải lên/tải xuống, trả về Web Portal HTML và ảnh QR Code PNG.
  * Phân vùng đĩa SSD riêng biệt: `/tmp/file_transfers/{token}/`, được bảo vệ bởi 3 tầng dọn rác (Startup prune, On-access expiry check, Periodic background sweeper loop 600s).
  * Bộ đệm truyền dữ liệu Upload: Cố định 1MB chunked streaming qua `aiofiles`, RAM $O(1) \le 2\text{MB}$/kết nối, an toàn tuyệt đối với trần RAM 3.2GB của `kirito-server`.
  * Bộ máy truyền dữ liệu Download: Hỗ trợ RFC 7233 Range requests (`HTTP 206 Partial Content`), zero-throttling đa luồng cho IDM/Safari/Chrome.
  * Bộ sinh mã QR Code in-memory: Sử dụng `qrcode` + `Pillow` (`io.BytesIO()`), 100% Zero-Disk Leak.
  * AI Agent ReAct Tool: Đăng ký `create_file_transfer_portal` vào `DIRECT_RETURN_TOOLS` tại 4 vị trí chốt, dynamic scoping keyword matching với token budget gate $\le 700$ tokens, System Prompt Section 2f độc lập (bảo toàn Section 2e).

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | High-Throughput Storage & Session Manager | `TransferStorageManager`, token URL-safe 32-bytes, metadata tracking, TTL 24h, one_time delayed cleanup (30s grace) | M1 | survey_1 |
| 2 | Chunked Disk Streaming Upload 1MB | `aiofiles` fixed buffer 1MB, zero-RAM leak (<2MB/conn), trần 3.2GB | M1 | survey_1 |
| 3 | HTTP 206 Partial Content & Zero-Throttling | RFC 7233 range requests, multi-thread download, bypass rate limit cho valid token | M1 | survey_1 |
| 4 | Responsive Web Drop Portal UI | Single-file HTML5/CSS3/Vanilla JS (<50KB), Dropzone upload MB/s + % + ETA, Preview iOS Safari/Desktop | M2 | survey_2 |
| 5 | Dynamic In-Memory QR Code Generator | `qrcode` + `Pillow` BytesIO PNG generation, zero-disk leak, RAM cleanup tức thì | M3 | survey_2 |
| 6 | Telegram Bot Transfer Portal Card | `send_photo_bytes`, LAN link (`192.168.0.100:8084`) & WAN link (`ngrok-free.dev`), TTL 24h format | M3 | survey_2 |
| 7 | AI Agent Direct Return Tool & Scoping | `create_file_transfer_portal` in `DIRECT_RETURN_TOOLS`, dynamic scoping, token budget gate | M4 | survey_3 |
| 8 | System Prompt Section 2f & BLUF Reflex | Turn 1 Tool-First Imperative reflex, dual-link & QR presentation | M4 | survey_3 |
| 9 | Comprehensive E2E Verification & Empirical Benchmark | 100% test suite pass (875+ cũ + tests mới) & đo lường throughput thực tế trên kirito-server | M5 | survey_1,2,3 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | M1: Transfer Storage Engine & HTTP 206 Router | `requirements.txt`, `transfer_storage_manager.py`, `file_transfer.py`, `main.py` mount & sweeper | none | DONE |
| 2 | M2: Responsive Web Drop Portal UI | Endpoint `/portal/{token}` trả về HTML5/CSS3/JS (<50KB), Dropzone MB/s & Preview | M1 | DONE |
| 3 | M3: In-Memory QR Generator & Telegram Card | `transfer_qr_generator.py`, endpoint `/qr/{token}`, `telegram_bot.py` card integration | M1 | DONE |
| 4 | M4: AI Agent Tool Scoping & Prompt Section 2f | `ai_agent_tools.py` (`DIRECT_RETURN_TOOLS`, scoping), `ai_agent.py` (Section 2f) | M1, M3 | DONE |
| 5 | M5: E2E Verification & kirito-server Benchmark | Test runner 875+ tests, E2E tests, empirical upload/download test trên kirito-server | M1, M2, M3, M4 | DONE |

## Interface Contracts
### `TransferStorageManager`
- `create_session(filename: Optional[str] = None, mode: str = "upload", one_time: bool = False, ttl_hours: int = 24) -> TransferRecord`
- `get_session(token: str) -> Optional[TransferRecord]`
- `save_upload_stream(token: str, filename: str, stream: AsyncIterator[bytes]) -> TransferRecord`
- `get_file_path(token: str) -> Optional[Path]`
- `schedule_delayed_cleanup(token: str, delay_seconds: int = 30) -> None`
- `delete_session(token: str) -> bool`
- `sweep_expired() -> int`

### Router `/api/ai/transfer`
- `POST /api/ai/transfer/create` -> `TransferCreateResponse` (token, lan_url, wan_url, expires_at)
- `POST /api/ai/transfer/upload/{token}` (multipart / stream) -> `TransferUploadResponse`
- `GET /api/ai/transfer/portal/{token}` -> `HTMLResponse` (Web Drop Portal <50KB)
- `GET /api/ai/transfer/download/{token}` -> `StreamingResponse` / `FileResponse` (HTTP 206 Partial Content)
- `GET /api/ai/transfer/qr/{token}` -> `Response(media_type="image/png")`
- `GET /api/ai/transfer/info/{token}` -> `TransferInfoResponse` (filename, size, state, ttl)

### AI Agent Tool `create_file_transfer_portal`
- Parameters: `file_name: Optional[str] = None`, `mode: str = "upload"`, `one_time: bool = False`
- Return: formatted text containing LAN link, WAN link, QR code reference and TTL.

## Code Layout
- `services/ai-agent-service/requirements.txt`: Bổ sung `aiofiles>=24.1.0` và `qrcode[pil]>=7.4.2`
- `services/ai-agent-service/app/services/transfer_storage_manager.py`: Core storage & lifecycle
- `services/ai-agent-service/app/services/transfer_qr_generator.py`: In-memory QR generator
- `services/ai-agent-service/app/routers/file_transfer.py`: FastAPI Router `/api/ai/transfer`
- `services/ai-agent-service/app/main.py`: Router registration and background sweeper
- `services/ai-agent-service/app/services/telegram_bot.py`: Telegram Bot card integration
- `services/ai-agent-service/app/services/ai_agent_tools.py`: Tool definition & scoping
- `services/ai-agent-service/app/services/ai_agent.py`: System prompt Section 2f & ReAct reflex
- `services/ai-agent-service/tests/test_file_transfer_engine.py`: Unit & integration tests for M1
- `services/ai-agent-service/tests/test_file_transfer_portal.py`: Unit & integration tests for M2-M4
- `services/ai-agent-service/tests/test_file_transfer_e2e.py`: E2E test suite for M5

## RÀNG BUỘC SỐNG CÒN (CRITICAL CONSTRAINTS)
1. TUYỆT ĐỐI KHÔNG đụng chạm, không stage, không commit và không push bất kỳ file nào thuộc thư mục `android-app/`.
2. Git commit messages BẮT BUỘC viết hoàn toàn bằng tiếng Anh.
3. Mọi giao tiếp, kế hoạch, giải thích, báo cáo BẮT BUỘC viết hoàn toàn bằng tiếng Việt.
4. Sau khi hoàn thành, BẮT BUỘC kiểm thử thực tế thô (Empirical Test) đo lường tốc độ upload/download thực tế trên máy chủ `kirito-server` và xác nhận 100% test suite pass (cả unit tests mới và toàn bộ 875+ tests cũ).
