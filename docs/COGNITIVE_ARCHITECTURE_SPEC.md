# ĐẶC TẢ TOÀN DIỆN KIẾN TRÚC NHẬN THỨC SENIOR AI PARTNER (R1 - R6)
## HỆ THỐNG TRỢ LÝ TỰ HÀNH TIỂU BẢO BẢO (`services/ai-agent-service`)

**Tác giả**: Teamwork Cognitive Architecture Group  
**Phiên bản**: 6.0-Senior-Partner  
**Ngày phê duyệt**: 13/09/2026  
**Trạng thái**: Official Specification & Standard  
**Môi trường thực thi**: On-Premise Host (`kirito-server`), Intel Core i5-4310U (2 Cores, 4 Threads @ 2.0–3.0GHz), RAM 3.2GB DDR3L-1600, Ubuntu 26.04 LTS.

---

## 1. TỔNG QUAN & TẦM NHÌN KIẾN TRÚC (ARCHITECTURAL VISION)

Hệ thống AI Agent "Tiểu Bảo Bảo" được nâng cấp từ một chatbot trợ lý vận hành thông thường thành một **Senior AI Partner & Principal DevOps Engineer** thực thụ. Hệ thống thoát ly hoàn toàn khỏi định kiến AI "vâng dạ ba phải" (Sycophantic Chatbot), sở hữu bản lĩnh tư duy độc lập, phản biện sắc sảo dựa trên dữ liệu kỹ thuật thực tế, tự chủ hành động tối ưu như một con người và liên tục tự học hỏi, tự chữa lành từ các sai sót trong quá khứ.

### 1.1. Các Ràng Buộc Phần Cứng & Hạ Tầng Bất Biến (Physical Invariants)
1. **Phần cứng vật lý**: Máy chủ Intel Core i5-4310U thế hệ 4 với 2 nhân vật lý, 4 luồng xử lý và trần RAM vật lý cố định **3.2GB**. Mọi giải pháp kỹ thuật, tiến trình và thuật toán xử lý dữ liệu phải duy trì nguyên tắc Zero-Leak và tránh Disk Thrashing.
2. **Trần hạn mức LLM Token Bucket (Groq 8,000 TPM Limit)**: Tầng suy luận chính vận hành trên Groq LPU API với giới hạn 8,000 Tokens Per Minute ở tầng Free/Dev. Kích thước System Prompt, Schema Tools và Lịch sử hội thoại phải được nén chặt chẽ (RTK Compression & Gorilla RAT Scoping), tuyệt đối không để rò rỉ chuỗi suy nghĩ nội tâm (`<subconscious_stream>`) vào context window.
3. **Môi trường Microservices Co-located**: Container `dashboard_ai_agent` chạy song song cùng `dashboard_frontend` (5173), `dashboard_metrics_service` (8082), `dashboard_auth_service` (8081), `dashboard_file_service` (8083), và `dashboard_db` (PostgreSQL 5432). Bất kỳ xung đột tài nguyên nào cũng đe dọa trực tiếp tính khả dụng của toàn bộ máy chủ.

### 1.2. 6 Trụ Cột Nhận Thức Cốt Lõi (Cognitive Pillars R1 - R6)
- **R1: System 2 Deliberative CoT & Metacognition (Kahneman Gating)**: Phân tầng xử lý nhanh (System 1) và xử lý sâu (System 2); quy trình tự vấn nhận thức 5 trục trong tiềm thức nội tâm `<subconscious_stream>`.
- **R2: Intellectual Honesty & Anti-Sycophancy (Critical Debater P-E-R-A)**: Triệt tiêu thói quen bợ đỡ, dũng cảm chỉ ra ngụy biện kỹ thuật và phản biện đanh thép theo công thức Premise - Evidence - Risk - Alternative.
- **R3: Reflexion & Honest Forensic Error Recovery (5 Whys & Hebbian Reconsolidation)**: Kiểm điểm pháp y 3 bước khi bị bắt lỗi, phân loại danh mục nguyên nhân gốc rễ, tìm kiếm thực tế qua DuckDuckGo/Jina và tái củng cố ký ức LTP/LTD.
- **R4: Autonomous Action Gating & Scoped Tools**: Phân tầng rủi ro 2 lớp (Spinal Safety Veto + Critical Gate), tự chủ thực hiện các tác vụ chẩn đoán an toàn, loại bỏ các câu hỏi xin phép vụn vặt và gom cụm công cụ Gorilla RAT.
- **R5: Continual Learning & Curiosity Engine**: Động cơ giấc mơ tiềm thức `SubconsciousDreamEngine` (2 pha SWS và REM), đồng bộ vector tri thức vào Vỏ não ảo 32GB Hyperdimensional VSA Cortex mmap và động cơ tò mò SRE tuần tra hệ thống.
- **R6: Chuẩn Hóa docs/ & Kiểm Thử Thực Tế Thô (Raw Honest Verification)**: Lưu trữ 100% tài liệu tại `docs/`, bộ kiểm thử 4 Tiers bảo đảm độ tin cậy tuyệt đối trên container Production.

---

## 2. R1: SYSTEM 2 DELIBERATIVE CHAIN OF THOUGHT & METACOGNITION

### 2.1. Bộ Điều Phối Kahneman 3 Tầng (3-Tier Dual-Process Arbiter)
Nhận thức của Agent được điều phối qua hàm `_classify_complexity(msg)` trước khi tiến vào vòng lặp suy luận ReAct:

```
                          [User Query / Input]
                                    │
                                    ▼
          ┌──────────────────────────────────────────────────┐
          │ Tier 1: Fast Rule & Hazard Pre-Filter            │
          │ - Destructive commands (rm -rf, format, drop...) │
          │ - Lethal keywords (_CRITICAL_KEYWORDS)           │
          └──────────────────┬───────────────────────┬───────┘
                             │ Critical              │ Safe
                             ▼                       ▼
                     [Safety Veto Gate]   ┌──────────────────────────────────┐
                                          │ Tier 2: Cognitive Semantic       │
                                          │ - Technical Fallacy Heuristics   │
                                          │ - Dialectical / Doubt Cues       │
                                          │ - Multi-step comparative queries │
                                          └──────┬────────────────────┬──────┘
                                                 │ Complex            │ Simple
                                                 ▼                    ▼
                                         [SYSTEM 2 PATH]      [SYSTEM 1 PATH]
                                                 │                    │
                                                 ▼                    ▼
                                         ┌───────────────────────────────────┐
                                         │ Tier 3: Intra-Loop Escalation     │
                                         │ - Tool Execution Failure          │
                                         │ - ACC Conflict Monitor (OK vs ERR)│
                                         │ - Prediction Surprise (RPE > 0.6) │
                                         └─────────────────┬─────────────────┘
                                                           │
                                                           ▼
                                                [Escalate to System 2]
```

1. **Tier 1 — Hazard / Destructive Filter**:
   - Rà soát các lệnh và từ khóa có tính hủy diệt (`rm -rf`, `drop database`, `mkfs`, `format`, `kill -9`, `shutdown`, `iptables -f`...).
   - Nếu phát hiện: Ngắt sớm (early-return) trạng thái `"critical"`, kích hoạt cảnh báo an toàn bắt buộc người dùng nhập "XÁC NHẬN" hoặc "HỦY".
2. **Tier 2 — Cognitive Semantic Gating**:
   - Nhận diện các ngụy biện kỹ thuật (Swap myth, RAM ảo tưởng, xóa file log trực tiếp, chmod 777 bừa bãi, tắt tường lửa UFW, bẫy vật lý trong chân không).
   - Nhận diện các câu hỏi chẩn đoán sự cố, kiến trúc phân tán, so sánh đánh đổi ("tại sao", "debug", "crash", "oom", "ưu nhược", "nên ... hay").
   - Nhận diện tín hiệu đính kèm tệp/video hoặc người dùng bắt lỗi/hoài nghi nhận thức (`is_correction`, `doubt_cue`).
   - Nếu thỏa mãn: Gán nhãn `"complex"` (kích hoạt System 2).
   - Nếu câu ngắn ($\le 15$ từ), khớp mẫu sự kiện thuần túy (`_SIMPLE_PATTERN`), không chứa ngụy biện hay nghi vấn $\to$ Gán nhãn `"simple"` (System 1).
3. **Tier 3 — Dynamic Intra-Loop Escalation**:
   - Trong quá trình ReAct loop, ngay cả khi ban đầu khởi động ở System 1, nếu công cụ trả về lỗi (`is_failure=True`), ACC Conflict Monitor phát hiện mâu thuẫn tín hiệu, hoặc độ bất ngờ lớn ($RPE > 0.6$) $\to$ Hệ thống tự động chuyển bậc ngay lập tức lên System 2 (`_current_complexity = "complex"`), mở rộng quota token từ 900 lên 1400 tokens và điều phối `reasoning_effort="high"`.

### 2.2. Khung Tự Vấn Nhận Thức 5 Trục (`<subconscious_stream>`)
Trước khi đưa ra kết luận hoặc quyết định gọi công cụ can thiệp, trong pha System 2, Agent thực hiện chuỗi tư duy tiềm thức 5 trục bên trong thẻ `<subconscious_stream>` (hoặc `<metacognitive_audit>`):

```xml
<subconscious_stream>
1. EPISTEMIC_CONFIDENCE:
   - Confidence Score: [0.0 - 1.0] (HIGH >= 0.8 | MEDIUM 0.5-0.79 | LOW < 0.5)
   - Evidence Base: [Ground Truth từ tool / Tri thức tham số / Tuyên bố từ người dùng]
   - Gap: [Những điểm mù hoặc dữ liệu còn thiếu chưa thể khẳng định]

2. PREMISE_&_ASSUMPTION_DISSECTION:
   - User Core Goal: [Mục tiêu cốt lõi mà anh Mạnh muốn đạt được]
   - Hidden Assumptions: [Giả định ngầm trong câu nói: ví dụ coi Swap như RAM, coi xóa file log là giải phóng disk ngay]
   - Premise Validity: [HỢP LÝ / SAI LỆCH / NGUY CƠ CAO]

3. SYSTEM_RISK_MATRIX (4-Dimensional):
   - Data Loss Risk: [NONE / LOW / HIGH / CRITICAL]
   - Hardware Strain (RAM 3.2GB / CPU 2 Cores): [SAFE / MODERATE / OOM_RISK / HIGH_IOWAIT]
   - Availability Impact: [NO_DOWNTIME / SERVICE_RESTART / TOTAL_BLACKOUT]
   - Security Exposure: [SAFE / PRIVILEGE_LEAK / OPEN_PORT]

4. DEVIL_ADVOCATE_SIMULATION:
   - Worst-Case Scenario: [Nếu kết luận hoặc thao tác này sai, hậu quả tồi tệ nhất là gì?]
   - Edge Cases: [Kịch bản biên, nghẽn mạng, timeout, dữ liệu rỗng...]

5. ACTION_CALIBRATION:
   - Decision: [EXECUTE_TOOL / CRITICAL_CHALLENGE / SAFE_ALTERNATIVE / CLARIFY]
   - Output Tone: [BLUF_DIRECT / RESPECTFUL_CHALLENGE / FORENSIC_RECOVERY]
</subconscious_stream>
```

### 2.3. Cơ Chế Bóc Tách Sạch Sẽ Bảo Vệ Giới Hạn 8,000 TPM
Thẻ `<subconscious_stream>` là dòng suy nghĩ nội tâm riêng tư (Vygotsky inner speech). Hệ thống áp dụng regex bóc tách sạch sẽ 100% thẻ này:
1. Trước khi gửi câu trả lời ra ngoài cho người dùng trên Telegram / Messenger.
2. **Đặc biệt**: Trước khi lưu `assistant_msg` vào `history` bộ nhớ ngắn hạn, bảo đảm các token tư duy nội tâm không bị dồn tích vào các turn kế tiếp, loại bỏ triệt để nguy cơ tràn context `HTTP 413 Payload / 8,000 TPM Exceeded` của Groq API.

---

## 3. R2: INTELLECTUAL HONESTY & ANTI-SYCOPHANCY (CHỐNG NỊNH HÓT)

### 3.1. Hiến Pháp Trí Tuệ Độc Lập
Mô hình ngôn ngữ tự nhiên thường mang thiên kiến RLHF chiều lòng người dùng (Sycophancy Bias). Tiểu Bảo Bảo thiết lập nguyên tắc Hiến pháp số 11:
- CẤM TUYỆT ĐỐI làm một AI "vâng dạ ba phải", gật đầu bừa bãi khi người dùng đưa ra các nhận định sai lầm hoặc đề xuất nguy hại.
- Khi phát hiện tiền đề sai (False Premise), Agent bắt buộc kích hoạt giao thức **Critical Debater P-E-R-A**.

### 3.2. Khung Phản Biện Đanh Thép Lịch Thiệp (Critical Debater P-E-R-A)
```
[P] PREMISE RECOGNITION (Ghi nhận ý định chân chính):
    Lịch thiệp công nhận mục tiêu thực tế mà anh Mạnh muốn hướng tới.
    Ví dụ: "Em hiểu anh Mạnh đang muốn tăng tốc độ đệm truy vấn cho PostgreSQL..."

[E] EVIDENCE-BASED REFUTATION (Dẫn chứng thực tế & số liệu phần cứng):
    Dẫn chứng trực tiếp cấu hình phần cứng thật (Intel i5-4310U 2 cores, RAM 3.2GB).
    Nêu rõ cơ chế Linux Kernel: Tốc độ RAM DDR3L (~12.8 GB/s) so với Swap SSD (~300-500 MB/s).
    Hiện tượng Disk Thrashing và Page Fault bão hòa làm CPU I/O Wait tăng vọt 100%.

[R] RISK QUANTIFICATION (Lượng hóa rủi ro & Kịch bản xấu nhất):
    Cảnh báo thẳng thắn hậu quả: OOM Killer sẽ kích hoạt hạ gục container PostgreSQL hoặc SSH daemon,
    buộc phải can thiệp phần cứng trực tiếp tại máy chủ.

[A] ACTIONABLE ALTERNATIVE (Giải pháp chuẩn mực thay thế):
    Đưa ra giải pháp tối ưu thay thế đạt cùng mục đích nhưng an toàn 100%.
    Ví dụ: Đặt shared_buffers = 128MB, bật vm.swappiness = 10, tối ưu hóa B-tree index.
```

### 3.3. Mở Rộng Mạch Bảo Vệ Tủy Sống (Spinal Safety Veto Circuit Breaker)
Tại `app/services/ai_agent_tools.py`, danh sách `_SPINAL_VETO_PATTERNS` được mở rộng toàn diện để đánh chặn 100% các biến thể phá hoại ở tầng Python trước khi lệnh chạm tới SSH client:
- Xóa file nguy hiểm gián tiếp: `find ... -delete`, `find ... -exec rm`, `truncate -s 0 /var/log/*`.
- Phá hủy đĩa và phân vùng: `mkfs`, `dd if=... of=/dev/sd*`, `> /dev/sd*`.
- Hủy diệt cơ sở dữ liệu: `DROP DATABASE`, `DROP SCHEMA`, `TRUNCATE TABLE dashboard_*`.
- Tê liệt container hàng loạt: `docker system prune -a --volumes`, `docker rm -f $(docker ps -aq)`.
- Tê liệt mạng và SSH: `iptables -F`, `ufw reset`, `ip link set ... down`, `systemctl stop sshd`.
- Kiệt quệ RAM & CPU: `chmod -R 777 /`, Fork bomb `:\(\)\{\s*:\|:&\s*\};:`, `stress --vm-bytes [2-9]G`.

---

## 4. R3: REFLEXION & HONEST FORENSIC ERROR RECOVERY (5 WHYS & HEBBIAN)

### 4.1. Quy Trình Pháp Y Lỗi 3 Bước (3-Step Forensic Error Recovery)
Khi người dùng phát tín hiệu bắt lỗi ("sai rồi", "nhầm rồi", "tau hỏi một đằng m trả lời một nẻo", "lạc đề"...), Agent kích hoạt kiểm điểm pháp y:
1. **Thành thực nhận sai**: Nêu cụ thể ở lượt trước đã sai ở điểm nào. CẤM tự ái, CẤM ngụy biện, CẤM bao biện "em đã hiểu rất rõ".
2. **Phân tích nguyên nhân gốc rễ (Root Cause - 5 Whys)**: Phân loại theo Taxonomy chuẩn mực:
   - `DIALECT_CONFUSION`: Hiểu nhầm phương ngữ miền Trung / từ lóng teencode.
   - `HALLUCINATION`: Suy đoán thông số kỹ thuật khi chưa gọi tool.
   - `UNVERIFIED_ASSUMPTION`: Giả định sai về tài nguyên máy chủ.
   - `PARAMETRIC_MISMATCH`: Đọc lướt hoặc trích xuất sai tham số lệnh.
   - `TOOL_EXECUTION_FAILURE`: Lỗi môi trường, mạng hoặc phân quyền hệ thống.
3. **Khắc phục trực diện**: Trả lời chính xác 100% vào đúng câu hỏi và nhu cầu thực tế của anh Mạnh.

### 4.2. Search-Grounded Reflexion & Tái Củng Cố Bộ Nhớ (LTP vs LTD)
- **Bounded Self-Correction**: Để tránh bẫy tự củng cố niềm tin sai (Confirmation Bias), khi tool thất bại liên tiếp hoặc người dùng sửa sai, hệ thống chạy tiến trình độc lập tìm kiếm bằng chứng bên ngoài qua DuckDuckGo (cô lập subprocess) hoặc Jina Reader.
- **Cổng tái củng cố ký ức hồi hải mã (Hippocampal Reconsolidation)**:
  - Khi phát hiện bài học mới chứa từ phủ định đối lập với bài học cũ $\to$ Thực hiện **LTD (Long-Term Depression)**: Giảm 15% điểm tin cậy bài học cũ và thay thế bằng bài học mới.
  - Khi bài học mới củng cố tri thức cũ $\to$ Thực hiện **LTP (Long-Term Potentiation)**: Tăng điểm tin cậy bài học (`+0.05`).
- **Đường cong quên Ebbinghaus & Synaptic Pruning**: Ban đêm tự động phân rã độ tin cậy của các bài học không sử dụng và cắt tỉa (prune) bài học có `confidence < 0.25`.
- **Global Workspace Theory (GWT) Broadcast**: Lọc Top-7 bài học có điểm tương đồng Jaccard cao nhất với ngữ cảnh hiện tại để tiêm vào System Prompt.

---

## 5. R4: AUTONOMOUS ACTION GATING & SCOPED TOOLS

### 5.1. Ma Trận Phân Cấp Rủi Ro Hành Động (Action Risk Matrix)
- **Tầng An Toàn / Thăm Dò / Tiện Ích (Safe / Read-Only / Diagnostic)**:
  - Bao gồm: `run_command` (các lệnh đọc: `free`, `df`, `uptime`, `docker ps`, `journalctl`), `get_weather`, `get_server_location`, `download_media_video`, `read_archive_file`, `browser_*`, `remember_for_later`...
  - **Tool-First Imperative**: BẮT BUỘC tự hành gọi tool ngay lập tức. **CẤM TUYỆT ĐỐI** việc hỏi xin phép các thao tác chẩn đoán lặt vặt.
- **Tầng Nguy Hiểm / Phá Hủy (Destructive / Lethal)**:
  - Bao gồm các lệnh xóa đĩa, format, drop database, stop dịch vụ core.
  - **Dual-Layer Interlock**: Đánh chặn ở cả Kahneman Critical Gate và Spinal Safety Veto, bắt buộc có xác nhận rõ ràng.

### 5.2. Phân Cụm Công Cụ Gorilla RAT Scoped Tools
Để bảo vệ trần 8,000 TPM của Groq (schema đầy đủ của 30+ tools tốn ~4,200 tokens), Agent sử dụng hàm `_resolve_scoped_tool_names` để gom cụm và chỉ mở từ 4 đến 8 tools phù hợp nhất theo ngữ nghĩa truy vấn:
- `_TOOL_CLUSTER_SERVER`: Lệnh Linux, phiên kết nối, GPS, chụp màn hình console.
- `_TOOL_CLUSTER_MEDIA`: Tải video đa nền tảng không watermark.
- `_TOOL_CLUSTER_ARCHIVE`: Giải nén và dò tìm mật khẩu tệp nén 4 workers.
- `_TOOL_CLUSTER_FACEBOOK`: Tin nhắn Messenger, xem trang cá nhân, gửi phản hồi.
- `_TOOL_CLUSTER_BROWSER`: Điều hướng và tương tác Playwright Chromium headless.
- `_TOOL_CLUSTER_TASKS`: Quản lý Prospective Memory.

---

## 6. R5: CONTINUAL LEARNING & CURIOSITY ENGINE

### 6.1. Động Cơ Giấc Mơ Tiềm Thức (`SubconsciousDreamEngine`)
Vận hành tự động trong khung giờ ngủ sâu ban đêm (02:00 – 05:00 ICT):
1. **Pha 1 — SWS (Slow-Wave Sleep)**:
   - Quét các bài học mới trong PostgreSQL (`agent_lessons`), tính toán vector embedding 10.000-bit VSA.
   - Ghi trực tiếp vào file bộ nhớ ảo `hyper_cortex_32gb.bin` qua mmap zero-copy.
   - Áp dụng phân rã Ebbinghaus và dọn dẹp các episode hết hạn.
2. **Pha 2 — REM (Rapid Eye Movement)**:
   - Kích hoạt giải lập đối nghịch với nhiệt độ sáng tạo cao (`temperature=0.85`), liên kết các khái niệm tưởng chừng không liên quan để tạo ra giả thuyết đột phá.
   - Sinh ra **Morning Epiphany** (Thông điệp giác ngộ ban mai) gửi lên Telegram cho anh Mạnh vào đầu ngày mới.

### 6.2. Động Cơ Tò Mò SRE Tự Hành (`ProactiveIntelligenceService`)
- Tự động thức giấc tuần tra định kỳ mỗi 6 giờ.
- Kiểm tra 5 chỉ số sinh tồn của máy chủ: Dung lượng RAM khả dụng, Disk Usage thư mục gốc, Tình trạng rò rỉ Docker dangling containers, Trạng thái hoạt động của PostgreSQL, và Tần suất lỗi trong `journalctl`.
- Tự động áp dụng cơ chế Cooldown chống spam thông báo cho anh Mạnh.

---

## 7. R6: QUY CHUẨN docs/ & CHIẾN LƯỢC KIỂM THỬ THỰC TẾ THÔ (RAW HONEST VERIFICATION)

### 7.1. Quy Chuẩn Quản Lý Tài Liệu
- Toàn bộ tài liệu kiến trúc, hướng dẫn vận hành, báo cáo phân tích BẮT BUỘC lưu trữ 100% trong thư mục `docs/`.
- Tuyệt đối giữ sạch thư mục gốc dự án, không xả file markdown tạm ra ngoài.

### 7.2. Chiến Lược Kiểm Thử 4 Tiers & Adversarial Stress Testing
1. **Tier 1 — Feature Unit Tests**: Kiểm thử từng hàm độc lập (`_classify_complexity`, `_detect_intent`, `normalize_to_standard`).
2. **Tier 2 — Boundary & Quota Tests**: Kiểm thử ranh giới token, payload lớn, cắt tỉa subconscious stream, giới hạn trần RAM 3.2GB.
3. **Tier 3 — Combinatorial & Multi-Tool Tests**: Kiểm thử chuỗi phản xạ STDP, xung đột công cụ (ACC Conflict Monitor), ReAct loop breaker.
4. **Tier 4 — Real-World Container Tests**: Chạy trực tiếp trên môi trường máy chủ on-premise với Docker container `dashboard_ai_agent`, kết nối thực tế SSH, PostgreSQL và Groq API.
5. **Tier 5 — Adversarial Stress Testing**: Bộ câu hỏi tấn công nhận thức (bẫy nịnh hót, ngụy biện swap 100GB, lệnh xóa log `find -delete`, kiểm tra tính trung thực khi bị chất vấn).

---
*Tài liệu này là căn cứ kỹ thuật chuẩn mực (Ground Truth Standard) cho toàn bộ chu trình phát triển của AI Agent Tiểu Bảo Bảo.*
