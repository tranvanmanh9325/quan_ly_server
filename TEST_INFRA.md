# E2E Test Infra: High-Speed File Transfer Portal

## Test Philosophy
- Opaque-box, requirement-driven. Không phụ thuộc vào chi tiết nội bộ triển khai.
- Methodology: Category-Partition + Boundary Value Analysis (BVA) + Pairwise Combinatorial + Real-World Workload Testing.
- Đảm bảo 100% không phá vỡ 875+ tests cũ của hệ thống AI Agent.

## Feature Inventory
| # | Feature | Source (Requirement) | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|---|---------|----------------------|:------:|:------:|:------:|:------:|
| 1 | High-Throughput Storage & Session | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 2 | Chunked Streaming Upload 1MB | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 3 | HTTP 206 Partial Content Download | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 4 | Responsive Web Drop Portal UI | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 5 | Dynamic In-Memory QR Code Generator | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 6 | Telegram Bot Transfer Portal Card | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 7 | AI Agent Tool Scoping & Direct Return | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |
| 8 | System Prompt Section 2f & BLUF | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |

## Test Architecture
- Test runner: `python3 -m unittest discover -s tests` bên trong container `quan_ly_server-ai-agent-service` trên `kirito-server` (hoặc mock runtime môi trường độc lập).
- Test files:
  * `services/ai-agent-service/tests/test_file_transfer_engine.py`: Kiểm thử sâu Storage Manager, Chunked Streaming 1MB, Token URL-safe, Delayed Cleanup 30s, HTTP 206 Range headers.
  * `services/ai-agent-service/tests/test_file_transfer_portal.py`: Kiểm thử Web Portal HTML (<50KB, mime types preview), QR Code BytesIO in-memory, Telegram Bot Card format.
  * `services/ai-agent-service/tests/test_file_transfer_ai_agent.py`: Kiểm thử ReAct tool `create_file_transfer_portal`, Direct Return membership, Dynamic Scoping keyword matching, Token Budget Gate <= 700 tokens, System Prompt Section 2f.
  * `services/ai-agent-service/tests/test_file_transfer_e2e.py`: Kiểm thử tích hợp toàn trình (E2E) từ lúc Agent sinh portal -> Upload file -> Download file với Range header -> Tự dọn rác đĩa -> Xác nhận 100% Zero-Disk Leak.

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Laptop upload video 500MB lên Portal -> Điện thoại quét QR tải về qua HTTP 206 | F1, F2, F3, F4, F5 | Cao |
| 2 | Người dùng yêu cầu Tiểu Bảo Bảo "Bắn file PDF này sang iPad" -> Bot trả lời Turn 1 Direct Return kèm 2 link và ảnh QR | F5, F6, F7, F8 | Trung bình |
| 3 | Chế độ one_time=True: IDM tải đa luồng 16 connections -> Delayed Cleanup 30s không làm gián đoạn các luồng | F1, F3 | Cao |
| 4 | Quá hạn 24 giờ -> Background Sweeper tự động quét sạch phân vùng SSD | F1 | Trung bình |

## Coverage Thresholds
- Tier 1: >= 5 tests per feature (tối thiểu 40 tests)
- Tier 2: >= 5 tests per feature (boundary/error handling, tối thiểu 40 tests)
- Tier 3: Pairwise combinations (tối thiểu 8 tests)
- Tier 4: Real-world scenarios (tối thiểu 4 scenarios)
- **Tổng số tests mới mục tiêu: >= 90 tests**
- **Bảo toàn 100% 875+ tests hiện hữu (0 regressions)**.
