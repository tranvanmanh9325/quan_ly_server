# TEST_INFRA.md — Kiến Trúc Hạ Tầng Kiểm Thử E2E True Autonomous AI Agent (Tiers 1-4)

## Dự án: Quản Lý Máy Chủ & Trợ Lý Tự Hành Cao Cấp Tiểu Bảo Bảo (`services/ai-agent-service`)

- **Kiến trúc trọng tâm**: True Autonomous AI Agent (R1 - R5)
- **Quy chuẩn kiểm thử**: Opaque-box, Behavior-driven, Strict Tri-Tier Action Risk Gating, Zero-Facade Integrity
- **Môi trường thực thi**: Python Standard `unittest.IsolatedAsyncioTestCase` & `pytest`
- **Tệp kiểm thử trung tâm**: `services/ai-agent-service/tests/test_autonomous_goal_e2e.py`
- **Tương thích**: Python 3.10+ (đã xác minh trên Python 3.11 và Python 3.14)
- **Chính sách tài nguyên**: Zero-Resource Leak (`-W error::ResourceWarning` sạch 100%)

---

## 1. Triết Lý Kiểm Thử & Chống Gian Lận (Test Integrity Protocol)

1. **Opaque-Box & Requirement-Driven**:
   - Toàn bộ ca kiểm thử được thiết kế dựa trên yêu cầu từ `ORIGINAL_REQUEST.md` (mục `## 2026-10-01T14:02:21Z`) và hợp đồng giao diện `PROJECT.md`.
   - Mỗi test case trả lời câu hỏi cốt lõi: *"Nếu test case này thất bại, năng lực tự hành hoặc chốt chặn an toàn nào của AI Agent bị vi phạm?"*

2. **Chống Gian Lận & Zero-Facade**:
   - Tuyệt đối không viết facade tests (test giả vờ luôn pass).
   - Logic an toàn sử dụng trực tiếp bộ phân loại `classify_action_risk` và các mẫu `_SPINAL_VETO_PATTERNS` từ `app.services.ai_agent_tools`.
   - Lệnh nguy hiểm (Tier 3 Lethal) phải bị chặn triệt để và chuyển sang `waiting_approval`.
   - Cooldown 30 phút (`_REMEDIATION_COOLDOWN_SECONDS = 1800`) được tính toán dựa trên `datetime` thực tế.
   - Giới hạn phản biện `MAX_REFLECTION_CYCLES = 2` chặn đứng vòng lặp vô hạn.

3. **Mô Hình Kiểm Thử Phân Tầng 4 Tiers**:
   - **Tier 1: Feature Coverage** — Kiểm thử từng tính năng cốt lõi (R1, R2, R3, R4) trong điều kiện happy-path độc lập.
   - **Tier 2: Boundary & Corner Cases** — Phân tích giá trị biên, rủi ro phá hủy Tier 3, lỗi kết nối DB, kiệt sức retry, trần token budget.
   - **Tier 3: Cross-Feature Combinations** — Kiểm thử tương tác chéo đa tính năng (R1+R2, R3+R1, R4+R1).
   - **Tier 4: Real-World Application Scenarios** — Kịch bản vận hành thực tế end-to-end trên máy chủ `kirito-server`.

---

## 2. Ma Trận Tính Năng & Phân Tầng Kiểm Thử (Feature Inventory & Mapping)

| Mã | Tính Năng (Feature) | Nguồn Yêu Cầu | Module Trọng Tâm | Tier 1 (Happy) | Tier 2 (Boundary) | Tier 3 (Cross) | Tier 4 (Real-World) |
|---|-------------------|--------------|------------------|:--------------:|:-----------------:|:--------------:|:-------------------:|
| **R1** | **Autonomous Goal Engine** | ORIGINAL_REQUEST R1 | `autonomous_goal_worker.py` | 5 tests | 4 tests | Pairwise | Scenario 2 |
| **R2** | **Self-Evaluation & Reflection Loop** | ORIGINAL_REQUEST R2 | `ai_agent.py`<br>`memory_service.py` | 3 tests | 2 tests | Pairwise | Scenario 1, 2 |
| **R3** | **Proactive Action Execution** | ORIGINAL_REQUEST R3 | `proactive_service.py` | 3 tests | 3 tests | Pairwise | Scenario 1 |
| **R4** | **Conversational Goal Management** | ORIGINAL_REQUEST R4 | `ai_agent_tools.py` | 2 tests | 2 tests | Pairwise | Scenario 1, 2 |
| **TỔNG** | **Bộ kiểm thử E2E phân tầng** | **PROJECT.md** | `test_autonomous_goal_e2e.py` | **13 tests** | **11 tests** | **3 tests** | **2 scenarios** |

**Tổng số test cases**: **29 tests** (100% PASS, 0 failure, 0 error).

---

## 3. Đặc Tả Chi Tiết 4 Tiers

### 3.1. Tier 1: Feature Coverage (Bao Phủ Tính Năng Cốt Lõi)
- `test_t1_r1_01_create_goal_and_initial_status`: Tạo goal qua `AutonomousGoalWorker.create_goal`, xác nhận `task_id` hợp lệ, trạng thái ban đầu là `pending`, `current_step = 0`.
- `test_t1_r1_02_execute_safe_step_progression`: Thực thi step an toàn (`df -h /`), xác nhận bước chuyển sang `completed`, kết quả ghi nhận vào `step["result"]`.
- `test_t1_r1_03_multi_step_execution_success`: Thực thi tuần tự 2 bước an toàn (`df -h` -> `uptime`), xác nhận chuyển trạng thái `pending` -> `running` -> `completed`.
- `test_t1_r1_04_list_goals_and_status_filtering`: Liệt kê và lọc mục tiêu theo trạng thái (`pending`, `completed`).
- `test_t1_r1_05_proactive_telegram_reporting_on_completion`: Gửi tin nhắn chủ động tới Telegram bot khi mục tiêu hoàn thành.
- `test_t1_r2_01_fast_evaluation_goal_achieved`: Fast evaluation xác nhận `achieved=True` khi kết quả công cụ đáp ứng mục tiêu.
- `test_t1_r2_02_fast_evaluation_goal_not_achieved`: Fast evaluation xác nhận `achieved=False` và tạo phản biện `[Reflection]` khi kết quả công cụ có lỗi.
- `test_t1_r2_03_reflection_injection_format`: Định dạng chuỗi phản biện inject vào prompt của iteration kế tiếp.
- `test_t1_r3_01_decide_remediation_disk_alert`: `_decide_remediation` phát hiện alert đĩa và chọn đúng hành động Tier 1 `docker_prune` (`docker system prune -f`, `auto_execute=True`).
- `test_t1_r3_02_decide_remediation_ram_alert`: `_decide_remediation` phát hiện alert RAM và chọn đúng hành động Tier 1 `drop_caches` (`sync && echo 3 > /proc/sys/vm/drop_caches`, `auto_execute=True`).
- `test_t1_r3_03_execute_remediation_before_after_reporting`: Thu thập metrics trước/sau và gửi báo cáo Telegram chi tiết dung lượng giải phóng.
- `test_t1_r4_01_intent_keywords_scope_goal_tools`: Phát hiện từ khóa intent ("theo dõi", "tự động", "mục tiêu", "goal") và nạp nhóm `_TOOL_CLUSTER_GOALS`.
- `test_t1_r4_02_conversational_goal_tools_execution_mock`: Thực thi mock 3 tools `create_autonomous_goal`, `list_autonomous_goals`, `cancel_autonomous_goal`.

### 3.2. Tier 2: Boundary & Corner Cases (Biên Khắc Nghiệt & Chốt Chặn An Toàn)
- `test_t2_r1_01_empty_goal_handling`: Xử lý an toàn khi goal rỗng hoặc chỉ có khoảng trắng, không crash hệ thống.
- `test_t2_r1_02_invalid_tool_args_retry_exhaustion`: Step gặp lỗi liên tiếp -> retry tối đa `max_retries = 3` rồi chuyển sang `failed`, lưu `error_message` và alert Telegram.
- `test_t2_r1_03_db_connection_fallback_to_inmemory`: Tự động fallback về `InMemoryTaskStore` khi DB pool không khả dụng hoặc lỗi kết nối.
- `test_t2_r1_04_block_tier3_lethal_command_to_waiting_approval`: Chặn đứng toàn bộ lệnh Tier 3 Lethal (`rm -rf /`, `mkfs.ext4`, `dd if=/dev/zero`, `:(){ :|:& };:`, `drop database`, `iptables -F`, `ufw reset`), chuyển sang `waiting_approval` và gửi alert Telegram yêu cầu xác nhận.
- `test_t2_r2_01_max_reflection_cycles_prevents_infinite_loop`: Khi chu kỳ phản biện đạt `MAX_REFLECTION_CYCLES = 2`, ép buộc `force_synthesis = True` để chặn vòng lặp vô hạn.
- `test_t2_r2_02_lesson_recording_in_memory_service_on_failure`: Trích xuất và lưu bài học kinh nghiệm vào `AgentMemoryService` khi tác vụ thất bại sau retries.
- `test_t2_r3_01_remediation_cooldown_30_minutes_blocks_repeat`: Cơ chế cooldown 30 phút (`_REMEDIATION_COOLDOWN_SECONDS = 1800`) chặn lặp lại remediation cho cùng một hành động trong vòng 1800 giây.
- `test_t2_r3_02_remediation_allowed_after_cooldown_expires`: Cho phép thực thi lại sau khi đã hết thời gian cooldown 30 phút.
- `test_t2_r3_03_tier2_alert_requires_approval`: Các cảnh báo rủi ro cao (restart container, renew SSL) được gán `tier = 2` và `auto_execute = False` (không tự chạy).
- `test_t2_r4_01_token_budget_limit_max_8_tools`: Duy trì trần tối đa 8 tools khi câu hỏi kích hoạt nhiều intent cùng lúc, bảo đảm token budget cho Groq API.
- `test_t2_r4_02_cancel_nonexistent_goal_graceful`: Hủy goal không tồn tại xử lý graceful, trả về `False` không ném unhandled exception.

### 3.3. Tier 3: Cross-Feature Combinations (Tương Tác Chéo Đa Tính Năng)
- `test_t3_r1_r2_step_failure_triggers_evaluation_and_reflection`: Bước thực thi trong goal gặp lỗi -> kích hoạt evaluation node -> sinh reflection định hướng.
- `test_t3_r3_r1_remediation_spawns_autonomous_monitoring_task`: Sau khi Proactive Remediation dọn rác đĩa, tự động tạo mục tiêu tự hành trong `AutonomousGoalWorker` để theo dõi đĩa trong 1 giờ.
- `test_t3_r4_r1_chat_tool_creates_task_worker_picks_up`: Người dùng gọi tool từ chat Telegram -> task được ghi nhận -> worker quét và thực thi tự động.

### 3.4. Tier 4: Real-World Application Scenarios (Kịch Bản Vận Hành Thực Tế)
- `test_t4_scenario1_disk_cleanup_and_telegram_alert`: Mô phỏng trọn vẹn chu trình cứu hộ đĩa 89% -> tự động prune -> đo before/after (89% -> 73%, giải phóng 5.7GB) -> báo cáo Telegram -> ghi nhớ bài học vào memory.
- `test_t4_scenario2_multi_step_system_maintenance`: Mô phỏng trọn vẹn quy trình bảo trì máy chủ 3 bước (kiểm tra disk, dọn log journalctl, kiểm tra container docker) tự hành 100% không cần người dùng can thiệp.

---

## 4. Hướng Dẫn Vận Hành & Lệnh Kiểm Thử

### Lệnh chạy chính thức (Standard Unittest Runner)
```bash
# Thiết lập PYTHONPATH và chạy kiểm thử kèm kiểm tra rò rỉ tài nguyên
$env:PYTHONPATH="services/ai-agent-service"
python -W error::ResourceWarning -m unittest services/ai-agent-service/tests/test_autonomous_goal_e2e.py
```

### Lệnh kiểm tra cú pháp (Compileall Verification)
```bash
python -m compileall -q services/ai-agent-service/tests/test_autonomous_goal_e2e.py
```

### Kết quả đo lường thực tế
```
Ran 29 tests in 0.178s
OK
Exit code: 0
```
