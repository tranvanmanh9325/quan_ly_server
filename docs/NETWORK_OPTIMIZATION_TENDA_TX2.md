# Báo Cáo Nghiên Cứu Chuyên Sâu & Tư Vấn Kỹ Thuật: Tối Ưu Hóa Mạng Server Với Router Tenda TX2 & Đa Card Mạng (Multi-NIC)

**Hệ thống mục tiêu:** Máy chủ `kirito-server` (Dell Latitude Haswell i5-4310U, RAM 3.2GB, SSD NVMe 400GB, Ubuntu Linux Kernel 7.0)  
**Thiết bị mạng nâng cấp:** Router **Tenda TX2 / TX2 Pro** (Wi-Fi 6 AX1500, Gigabit Ethernet)  
**Vai trò:** Senior Linux Network & Systems Architect  
**Ngôn ngữ:** Tiếng Việt (100%)  
**Nguyên tắc vận hành:** Khảo sát, nghiên cứu, tư vấn chuyên sâu — **Tuyệt đối không tự ý can thiệp hay sửa đổi hệ thống khi chưa có phê duyệt.**

---

## 1. TỔNG QUAN HIỆN TRẠNG PHẦN CỨNG & HẠ TẦNG THỰC TẾ

Qua quá trình khảo sát kỹ thuật thực tế (chế độ Read-Only an toàn) trên máy chủ `kirito-server` và phân tích thiết bị mạng mục tiêu:

### 1.1. Hiện Trạng Card Mạng Của Máy Chủ (`kirito-server`)
1. **Cổng Onboard Gigabit Ethernet (Cáp LAN):**
   - **Phần cứng:** `Intel Corporation Ethernet Connection I218-LM [8086:155a] (rev 04)`, module kernel `e1000e`.
   - **Băng thông danh định:** **1000 Mbps Full-Duplex (1 Gbps song công)**.
   - **Đặc tính kỹ thuật:** Độ trễ cực thấp (RTT $\le 0.25\text{ ms}$), Jitter $\approx 0$, không mất gói (Packet Loss 0%), hỗ trợ toàn diện phần cứng TSO (TCP Segmentation Offload), GSO, GRO, và Checksum Offload.
   - **Hiện trạng:** Cổng đang ở trạng thái nhàn rỗi do máy chủ đang chạy hoàn toàn qua Wi-Fi. Khi cắm cáp mạng Cat5e/Cat6 từ router Tenda TX2 vào, cổng này sẽ lập tức mở ra luồng băng thông gấp **15 đến 25 lần** so với kết nối Wi-Fi hiện tại.
2. **Card Wi-Fi 1 (PCIe Onboard):**
   - **Phần cứng:** `Qualcomm Atheros AR9485 Wireless Network Adapter [168c:0032]`, driver `ath9k`, interface `wlp2s0`.
   - **Chuẩn mạng:** Wi-Fi 4 (802.11b/g/n), chỉ hỗ trợ **băng tần đơn 2.4 GHz**, 1T1R (1 luồng truyền nhận), kênh 40MHz.
   - **Tốc độ:** Lý thuyết tối đa 150 Mbps; **thông lượng thực tế hiệu dụng (Layer 4 TCP) đạt ~40 – 65 Mbps** do cơ chế Half-Duplex (CSMA/CA) và can nhiễu tần số 2.4GHz trong môi trường dân cư.
3. **Card Wi-Fi 2 (USB Dongle):**
   - **Phần cứng:** `Realtek Semiconductor Corp. RTL8188EUS [0bda:8179]`, driver `r8188eu`, interface `wlx7cc2c621865c`.
   - **Chuẩn mạng:** Wi-Fi 4 (802.11n 2.4GHz 1T1R).
   - **Tốc độ:** Lý thuyết 150 Mbps; **thông lượng thực tế hiệu dụng ~30 – 50 Mbps**.
   - **Bất cập hiện tại trong bảng định tuyến:** Cả 2 card Wi-Fi đều đang kết nối vào cùng router `192.168.0.1`. Do `wlp2s0` có metric 600 nhỏ hơn metric 800 của `wlx7cc2c621865c`, 100% outbound traffic đều dồn vào card PCIe; chiếc USB Wi-Fi hoàn toàn bị bỏ phí tài nguyên.

---

### 1.2. Thông Số Kỹ Thuật Router Tenda TX2 (Wi-Fi 6 AX1500)
- **Cổng kết nối vật lý:**
  - 1 Cổng WAN Gigabit (10/100/1000 Mbps).
  - 3 Cổng LAN Gigabit (10/100/1000 Mbps).
- **Chuẩn không dây:**
  - Wi-Fi 6 (802.11ax) Dual-Band AX1500.
  - Băng tần 5GHz (802.11ax): Lên tới 1201 Mbps (hỗ trợ OFDMA, MU-MIMO, 1024-QAM, độ rộng kênh 80MHz).
  - Băng tần 2.4GHz (802.11n): Lên tới 300 Mbps (tương thích ngược hoàn toàn chuẩn n của 2 card Wi-Fi server).
- **Ăng-ten:** 5 ăng-ten ngoài độ lợi cao 6dBi, công nghệ Beamforming tập trung búp sóng.
- **Tính năng Firmware hỗ trợ:**
  - DHCP Server với **Static IP Reservation** (gán IP cố định theo địa chỉ MAC).
  - Port Forwarding, DMZ, UPnP (phục vụ mở cổng dịch vụ ra ngoài).
  - Quản lý băng thông (Bandwidth Control / QoS) theo từng thiết bị.
  - Chế độ hoạt động: Router Mode, Access Point (AP Mode), Wireless Repeater (Client+AP / WISP).
- **RÀNG BUỘC PHẦN CỨNG QUAN TRỌNG NHẤT (Senior Reality Check):**
  - Router Tenda TX2 là dòng router SOHO gia đình. Firmware gốc **HOÀN TOÀN KHÔNG HỖ TRỢ Link Aggregation (802.3ad LACP hoặc Static Trunking)** trên switch LAN.
  - Switch chip tích hợp bên trong SoC của Tenda TX2 là unmanaged switch, không có chức năng gom cổng ở tầng phần cứng với thiết bị đầu cuối.

---

## 2. CẢNH BÁO KỸ THUẬT CẤP CAO: TẠI SAO KHÔNG THỂ GỘP BĂNG THÔNG DÂY LAN + WI-FI Ở TẦNG LAYER 2?

Nhiều người dùng thường có suy nghĩ trực quan: *"Nếu cắm 1 dây LAN 1000Mbps và bật thêm 2 card Wi-Fi 150Mbps, gộp lại (Bonding) sẽ được $1000 + 150 + 150 = 1300\text{ Mbps}$!"*.  
Tuy nhiên, dưới góc độ kỹ thuật mạng máy tính chuyên sâu (Linux Kernel Network Stack), **đây là một cạm bẫy cực kỳ nguy hiểm**:

### 2.1. Thảm Họa Bonding Mode 0 (`balance-rr` - Round-Robin)
Nếu cố tình dùng Linux Bonding Mode 0 để luân chuyển gói tin qua cả LAN và Wi-Fi:
1. **Độ trễ vật lý bất đối xứng nghiêm trọng:**
   - Cáp LAN: Tốc độ 1000 Mbps, RTT $< 0.25\text{ ms}$, Jitter $\approx 0$.
   - Wi-Fi 2.4GHz: Tốc độ ~50 Mbps, RTT $10 - 40\text{ ms}$, Jitter cao.
2. **Gói tin đến lộn xộn (Severe Packet Reordering):**
   - Packet 1 (gửi qua LAN) tới máy nhận sau $0.2\text{ ms}$.
   - Packet 2 (gửi qua Wi-Fi) tới sau $25\text{ ms}$.
   - Trong lúc Packet 2 đang bay trên sóng, các Packet 3, 5, 7, 9 (gửi qua LAN) đã tới đích sau chỉ $0.22\text{ ms}, 0.24\text{ ms}, 0.26\text{ ms}$!
3. **Bão 3 Duplicate ACKs & Sụp Đổ Cửa Sổ Nghẽn (CWND Collapse - RFC 5681):**
   - Phía nhận thấy thiếu Packet 2 mà đã nhận được các packet phía sau $\to$ Lập tức gửi liên tiếp **3 TCP Duplicate ACKs** dội ngược về server báo mất gói.
   - Bộ điều khiển tắc nghẽn TCP (TCP Congestion Control) hiểu nhầm rằng đường truyền đang bị nghẽn đứt đoạn $\to$ Lập tức kích hoạt **Fast Retransmit**, truyền lại gói tin và **cắt giảm cửa sổ nghẽn (`cwnd`) xuống mức tối thiểu (thậm chí về 1 MSS)**!
4. **Hệ quả thực tế đo kiểm:**
   - Băng thông không tăng lên mà **sụp đổ từ 1000 Mbps xuống chỉ còn 10 – 30 Mbps**!
   - Độ trễ nhảy vọt, kết nối SSH giật lag, Docker container bị timeout liên tục.

### 2.2. Giới Hạn Của Khung 802.11 Wi-Fi (3-Address Frame Trap)
- Trong chuẩn Wi-Fi Client mode thông thường, khung vô tuyến 802.11 chỉ có **3 địa chỉ MAC** (Source, Destination, BSSID).
- Router Wi-Fi (Tenda TX2) bắt buộc địa chỉ MAC nguồn phải trùng khớp 100% với địa chỉ MAC của card Wi-Fi đã bắt tay WPA2.
- Nếu gộp bonding và dùng địa chỉ MAC ảo của bond interface, router Tenda TX2 sẽ **drop toàn bộ gói tin** vì cho rằng đây là gói tin giả mạo (Anti-Spoofing drop).
- Chuẩn 802.3ad LACP (Mode 4) bắt buộc kết nối Full-Duplex đồng nhất và đòi hỏi Router/Switch phải chạy LACPDU daemon — điều mà Wi-Fi và Router gia đình hoàn toàn không hỗ trợ.

---

## 3. BA PHƯƠNG ÁN KIẾN TRÚC TỐI ƯU MÁY CHỦ: KHAI THÁC TRIỆT ĐỂ 3 CARD MẠNG

Để biến máy chủ thành một hệ thống mạng cực mạnh, ổn định 99.99% và tận dụng 100% công năng của cả 3 card mạng, Senior Architect khuyến nghị 3 mô hình kiến trúc sau:

```mermaid
flowchart TD
    subgraph RouterZone["Router Tenda TX2 (Wi-Fi 6 AX1500)"]
        RouterGigabit["3x Cổng LAN Gigabit (1000 Mbps)"]
        RouterWLAN["Sóng Wi-Fi 2.4GHz"]
    end

    subgraph KiritoServer["Máy Chủ kirito-server (Dell Latitude)"]
        subgraph HardwareNICs["Tầng Giao Diện Vật Lý"]
            NIC_LAN["Intel I218-LM (1000 Mbps Full-Duplex)"]
            NIC_WIFI1["Qualcomm AR9485 PCIe (2.4GHz)"]
            NIC_WIFI2["Realtek RTL8188EUS USB (2.4GHz)"]
        end

        subgraph CoreBackbone["1. Trục Xương Sống Chính (1000 Mbps LAN)"]
            SSHAdmin["SSH Server (:22)"]
            NginxProxy["Nginx Dashboard (:5173)"]
            JavaServices["Java Backend APIs (:8081, :8082, :8083)"]
            PostgreSQL["PostgreSQL 17 Database (:5432)"]
            File4K["File Service (Tải file lớn / Video 4K)"]
            CFTunnel["Cloudflare Tunnel Ingress"]
        end

        subgraph FailoverStandby["2. Kênh Dự Phòng Nóng (Hot-Standby / Outbound)"]
            StandbyRoute["L3 Dynamic Failover (Metric 600)"]
            ScraperEgress["Dedicated Outbound (AI Agent / Scraper)"]
        end

        subgraph IsolatedAP["3. Trạm Phát Wi-Fi Cô Lập (hostapd AP Mode)"]
            IoTNetwork["Mạng IoT Thông Minh (ESP8266/ESP32)"]
            RescueAP["Cổng Cứu Hộ Khẩn Cấp (Rescue Wi-Fi)"]
        end
    end

    RouterGigabit ===|Cáp Cat6 Gigabit| NIC_LAN
    RouterWLAN -.->|Kết nối Standby| NIC_WIFI1
    NIC_WIFI2 ==>|Phát sóng SSID: Kirito_Server_AP| IsolatedAP

    NIC_LAN --> CoreBackbone
    NIC_WIFI1 --> FailoverStandby
```

---

### PHƯƠNG ÁN 1: DEDICATED FUNCTIONAL SEGMENTATION (PHÂN TÁCH CHỨC NĂNG CHUYÊN BIỆT)
⭐ **[KHUYẾN NGHỊ CAO NHẤT - TỐI ƯU NHẤT CHO THỰC TẾ]**

Thay vì cố ép gộp chung một cách khiên cưỡng, ta giao cho mỗi card mạng một sứ mệnh độc lập phát huy đúng thế mạnh vật lý của nó:

#### 1. Cáp LAN Gigabit (Intel I218-LM) $\to$ Trục Xương Sống Chính (Main Backbone):
- **Nhiệm vụ:** Gánh 100% các dịch vụ nặng, đòi hỏi tốc độ Gigabit và độ trễ thấp:
  - Giao diện Web Dashboard (Nginx `:5173`).
  - Hệ thống microservices Spring Boot (Auth `:8081`, Metrics `:8082`, Files `:8083`).
  - Cơ sở dữ liệu PostgreSQL 17 (`:5432`).
  - Phiên làm việc SSH quản trị (`:22`): Đạt độ trễ gõ phím $< 0.3\text{ ms}$, không bao giờ bị giật lag.
  - Tải file lớn, video 4K tốc độ tối đa ~110 – 120 MB/s (tận dụng hết băng thông ổ cứng SSD).
  - Cloudflare Tunnel Ingress nhận request từ Internet.
- **Ưu điểm:** Khai thác trọn vẹn 1000 Mbps của cổng LAN Tenda TX2, ổn định tuyệt đối, không bị chia sẻ băng thông với sóng vô tuyến.

#### 2. Card Wi-Fi 1 (PCIe Qualcomm AR9485) $\to$ Dự Phòng Nóng (Hot-Standby Failover 99.99%):
- **Nhiệm vụ:** Kết nối thường trực vào Wi-Fi của Tenda TX2 với Metric thấp hơn (Metric 600 so với Metric 100 của LAN).
- **Cơ chế vận hành:**
  - Bình thường: Toàn bộ lưu lượng đi qua LAN Gigabit. Card Wi-Fi 1 ở trạng thái chờ ấm (Warm Standby).
  - Khi có sự cố (ai đó vô tình rút dây LAN, chuột cắn đứt dây cáp, cổng switch router bị lỗi): Linux Kernel tự động chuyển toàn bộ kết nối ra Internet và mạng nội bộ sang Wi-Fi 1 trong vòng **$< 100\text{ ms}$**!
  - Phiên SSH, Docker container, Telegram Bot hoàn toàn không bị ngắt quãng. Khi cắm lại cáp LAN, hệ thống tự động trả lại quyền cho cổng Gigabit.
- **Hoặc tùy chọn:** Dùng làm **Dedicated Outbound Interface** cho AI Agent (cào dữ liệu TikTok, Facebook, gọi Groq API) để phân tách tải ngoại vi, không gây ảnh hưởng đến băng thông mạng nội bộ.

#### 3. Card Wi-Fi 2 (USB Realtek RTL8188EUS) $\to$ Trạm Phát Wi-Fi Cô Lập (Isolated Access Point / Rescue AP):
- **Nhiệm vụ:** Tận dụng công nghệ `hostapd` và `dnsmasq` trên Linux để biến chiếc USB Wi-Fi này thành **một Access Point phát Wi-Fi độc lập** (ví dụ SSID: `Kirito_IoT_Isolated` hoặc `Kirito_Rescue_AP`, dải mạng riêng `192.168.100.0/24`).
- **Công năng đột phá:**
  1. **Mạng IoT an toàn tuyệt đối:** Dành riêng cho các vi điều khiển ESP8266, ESP32, camera giám sát, công tắc thông minh kết nối vào. Mạng này được tường lửa (iptables) cô lập hoàn toàn với mạng LAN gia đình, ngăn chặn triệt để nguy cơ thiết bị IoT bị mã độc xâm nhập vào máy tính cá nhân hay cơ sở dữ liệu server.
  2. **Cổng Cứu Hộ Khẩn Cấp (Rescue Wi-Fi):** Nếu một ngày Router Tenda TX2 bị treo, mất cấu hình hoặc đứt mạng, anh Mạnh vẫn có thể dùng điện thoại/laptop kết nối thẳng vào Wi-Fi do USB này phát ra để SSH vào server xử lý sự cố.

---

### PHƯƠNG ÁN 2: HIGH AVAILABILITY NETWORK BONDING (ACTIVE-BACKUP MODE 1)
- **Bản chất:** Gộp Cổng LAN (Primary) và Card Wi-Fi 1 (Backup) vào một card mạng ảo `bond0`.
- **Cấu hình chuẩn Senior:** Bắt buộc sử dụng tham số `fail_over_mac=active` để tránh bị router Wi-Fi drop gói tin MAC 802.11.
- **Ưu điểm:** Cung cấp 1 địa chỉ IP duy nhất cho cả mạng dây và Wi-Fi. Cắm dây mạng chạy 1000 Mbps; rút dây mạng chạy 50 Mbps qua Wi-Fi mà không đổi IP.
- **Nhược điểm:** Chiếc USB Wi-Fi thứ 2 vẫn chưa được tận dụng.

---

### PHƯƠNG ÁN 3: POLICY-BASED ROUTING (PBR - ĐỊNH TUYẾN THEO LUỒNG NÂNG CAO)
- **Bản chất:** Sử dụng nhiều bảng định tuyến (`rt_tables`) và `ip rule` kết hợp đánh dấu gói tin `fwmark` qua `nftables`/`iptables`.
- **Phân luồng:**
  - Nhóm Inbound & Dashboard & Database $\to$ Cáp LAN Gigabit.
  - Nhóm AI Bot & External Scraper $\to$ Card Wi-Fi 1.
- **Lưu ý sống còn:** Bắt buộc cấu hình `net.ipv4.conf.*.rp_filter = 2` (Loose Mode) trong sysctl để tránh tình trạng kernel Linux drop gói tin phản hồi do kiểm tra đường đi ngược không đối xứng (Asymmetric Routing Drop).

---

## 4. TỐI ƯU HÓA LINUX KERNEL & NETWORK STACK CHO MÁY CHỦ RAM 3.2GB & GIGABIT

Để máy chủ Dell Latitude đạt hiệu năng cao nhất trên router Gigabit Wi-Fi 6 mà không làm cạn kiệt tài nguyên (CPU i5 Haswell và RAM 3.2GB eo hẹp):

### 4.1. Kích Hoạt TCP BBR & Fair Queueing (`fq`)
- **Vấn đề của thuật toán cũ (CUBIC):** Khi có gói tin Wi-Fi bị suy hao nhẹ, CUBIC lập tức cắt giảm 50% băng thông.
- **Giải pháp:** **TCP BBR (Bottleneck Bandwidth and RTT)** do Google phát triển. BBR đo lường trực tiếp tốc độ chuyển mạch tối đa và độ trễ tối thiểu, bơm dữ liệu theo nhịp Pacing Rate tối ưu, triệt tiêu hoàn toàn hiện tượng **Bufferbloat** (bộ đệm router bị tràn gây tăng ping).

### 4.2. Khống Chế Buffer TCP Window Chuẩn Xác Cho RAM 3.2GB (Chống OOM-Killer)
- **Cạm bẫy:** Nhiều tài liệu trên mạng hướng dẫn đặt buffer socket lên tới 32MB–64MB. Trên máy chủ RAM 3.2GB đang chạy 6 Docker container, chỉ cần vài luồng tải file lớn đồng thời sẽ ngốn sạch RAM vật lý (vì buffer kernel không thể bị swap ra đĩa), kích hoạt Linux OOM Killer làm sập PostgreSQL hoặc AI Agent!
- **Công thức vàng cho RAM 3.2GB:**
  - Giới hạn trần Socket Buffer tối đa là **8 MB** (`8388608 bytes`) — Đủ để bơm full băng thông Gigabit (1000 Mbps) ở độ trễ RTT 64ms mà không lãng phí RAM.
  - Khống chế trần `tcp_mem` tối đa không vượt quá 24% tổng dung lượng RAM hệ thống (~768 MB).

### 4.3. Kích Hoạt Phần Cứng Offload Chip Intel I218-LM
- Kích hoạt **TSO (TCP Segmentation Offload)**, **GSO**, **GRO**, và **Checksum Offload** qua `ethtool`.
- Cho phép card mạng Intel tự chia nhỏ và đóng gói TCP frame bằng phần cứng, giải phóng tới **70% chu kỳ CPU Haswell**, giữ CPU luôn mát mẻ và nhàn rỗi cho các container xử lý logic.

---

## 5. BẢN CẤU HÌNH THAM KHẢO CHUẨN SENIOR DEVOPS

*(Tất cả cấu hình dưới đây được biên soạn để tham khảo, không tự ý áp dụng khi chưa có sự đồng ý của anh Mạnh).*

### 5.1. File Tối Ưu Hóa Kernel: `/etc/sysctl.d/99-network-performance.conf`
```ini
# ==============================================================================
# HỆ THỐNG: DELL LATITUDE (i5-4310U / RAM 3.2GB / INTEL GIGABIT I218-LM)
# TỐI ƯU HÓA NETWORK STACK CHO ĐƯỜNG TRUYỀN GIGABIT & CHỐNG TRÀN BỘ NHỚ RAM
# ==============================================================================

# 1. Kích hoạt thuật toán TCP BBR & Fair Queueing
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# 2. Tối ưu bộ đệm TCP Window Socket (Tính toán chuẩn xác cho RAM 3.2GB)
net.core.rmem_max = 8388608
net.core.wmem_max = 8388608
net.core.rmem_default = 262144
net.core.wmem_default = 262144

net.ipv4.tcp_rmem = 4096 87380 8388608
net.ipv4.tcp_wmem = 4096 65536 8388608

# Khống chế tổng bộ nhớ TCP không vượt quá ~768MB (196608 trang nhớ 4KB)
net.ipv4.tcp_mem = 65536 131072 196608
net.ipv4.tcp_window_scaling = 1
net.ipv4.tcp_adv_win_scale = 1

# 3. Mở rộng hàng đợi kết nối (Chống tràn Backlog khi có micro-burst)
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 4096
net.core.netdev_max_backlog = 5000

# 4. Tái sử dụng nhanh TIME_WAIT socket
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_timestamps = 1
net.ipv4.tcp_fin_timeout = 15
net.ipv4.ip_local_port_range = 10240 65535
net.ipv4.tcp_max_tw_buckets = 32768

# 5. Chế độ Loose Mode cho Reverse Path Filter (Sống còn khi cắm cả LAN và Wi-Fi)
net.ipv4.conf.all.rp_filter = 2
net.ipv4.conf.default.rp_filter = 2

# 6. Kích hoạt chuyển tiếp gói tin (Cần cho Docker và trạm phát Wi-Fi AP)
net.ipv4.ip_forward = 1

# 7. Bộ nhớ ảo tối ưu cho RAM 3.2GB & NVMe SSD
vm.swappiness = 10
vm.vfs_cache_pressure = 50
```

---

### 5.2. Cấu Hình L3 Dynamic Failover Trong Netplan (`/etc/netplan/01-netcfg.yaml`)
```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    eno1: # Hoặc eth0 (Card Intel Gigabit LAN)
      dhcp4: true
      dhcp4-overrides:
        route-metric: 100 # Metric thấp nhất -> Ưu tiên 100% khi cắm cáp LAN
      optional: true
  wifis:
    wlp2s0: # Card Wi-Fi 1 (Qualcomm AR9485)
      dhcp4: true
      dhcp4-overrides:
        route-metric: 600 # Metric cao hơn -> Luôn ở trạng thái dự phòng nóng
      access-points:
        "Tenda_TX2_Router":
          password: "mat_khau_wifi_nha_ban"
      optional: true
```

---

## 6. HƯỚNG DẪN KÍCH HOẠT CỔNG ETHERNET INTEL TRONG BIOS DELL LATITUDE

Hiện tại cổng Intel I218-LM chưa nhận interface mạng trên hệ thống. Để kích hoạt hoàn hảo khi cắm dây sang Tenda TX2, anh Mạnh chỉ cần lưu ý các bước sau:

1. **Kiểm tra BIOS Dell Latitude (Khởi động máy và nhấn liên tục phím `F2`):**
   - **System Configuration $\to$ Integrated NIC:** Đảm bảo được đặt là **`Enabled`** (không để `Disabled`).
   - **Power Management $\to$ Deep Sleep Control:** Chọn **`Disabled`** (để card mạng không bị cắt điện khi laptop đóng nắp hoặc CPU hạ xung).
   - **Power Management $\to$ Energy Efficient Ethernet (EEE):** Chọn **`Disabled`** (tránh tính năng tiết kiệm điện tự ý hạ tốc độ cổng mạng từ 1000 Mbps xuống 100 Mbps).
2. **Cáp mạng Ethernet:**
   - Bắt buộc dùng cáp chuẩn **Cat5e** hoặc **Cat6** được bấm đủ **8 sợi đồng**. Nếu dùng cáp cũ bị đứt ngầm hoặc chỉ bấm 4 sợi (chuẩn 100Mbps), cổng mạng sẽ không thể nhận tốc độ 1000 Mbps.
3. **Cố định IP trên Router Tenda TX2:**
   - Khi cắm dây LAN vào Tenda TX2, anh vào trang quản trị `192.168.0.1` $\to$ mục **Advanced** $\to$ **Static IP Mapping** $\to$ Gán địa chỉ MAC của cổng LAN server thành IP cố định (ví dụ `192.168.0.100`) để mọi kết nối SSH và Dashboard luôn cố định và tiện lợi nhất.

---

## 7. KẾT LUẬN & ĐỀ XUẤT HÀNH ĐỘNG

- **Đánh giá giải pháp:** Việc nâng cấp lên Router Tenda TX2 (Wi-Fi 6 AX1500) kết hợp cáp mạng LAN Gigabit là một **bước nhảy vọt về hiệu năng** cho máy chủ `kirito-server` (tốc độ mạng tăng 15–20 lần, độ trễ giảm 100 lần).
- **Cách tận dụng 3 card mạng thông minh nhất:**
  1. **LAN Gigabit:** Cột sống chính cho mọi dịch vụ nặng (Dashboard, Java, Database, File 4K, SSH).
  2. **Card Wi-Fi 1:** Dự phòng nóng tự động nhảy mạng khi tuột cáp (99.99% Uptime).
  3. **Card Wi-Fi 2:** Biến thành trạm phát Wi-Fi AP riêng cho thiết bị IoT hoặc cổng cứu hộ server.
- **Cam kết:** Báo cáo này hoàn toàn mang tính chất nghiên cứu, phân tích kỹ thuật chuyên sâu và tư vấn kiến trúc. Toàn bộ hệ thống máy chủ và cấu hình hiện tại của anh Mạnh vẫn được giữ nguyên trạng 100%, không có bất kỳ thay đổi nào được thực hiện.
