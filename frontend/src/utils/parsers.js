/**
 * Tất cả hàm parse dữ liệu thô từ SSH — thuần tuý (pure functions), không có side effect.
 * Tách ra để App.jsx gọn hơn và có thể unit test độc lập từng parser.
 */

/**
 * @param {string} raw - output của `top -bn1`
 * @returns {number} phần trăm CPU đang dùng (0-100)
 */
export function parseCpu(raw) {
  const match = raw.match(/(\d+\.\d+)\s+id/);
  if (!match) return 0;
  return Math.max(0, parseFloat((100 - parseFloat(match[1])).toFixed(1)));
}

/**
 * @param {string} raw - output của `free -m`
 * @returns {{ total, used, free, cached, percent, swapTotal, swapUsed }}
 */
export function parseRam(raw) {
  const lines = raw.split('\n');
  let total = 0, used = 0, free = 0, cached = 0, percent = 0, swapTotal = 0, swapUsed = 0;

  if (lines.length >= 2) {
    const memParts = lines[1].trim().split(/\s+/);
    if (memParts.length >= 4) {
      total  = parseInt(memParts[1], 10);
      used   = parseInt(memParts[2], 10);
      free   = parseInt(memParts[3], 10);
      cached = memParts.length >= 6 ? parseInt(memParts[5], 10) : 0;
      percent = total > 0 ? parseFloat(((used / total) * 100).toFixed(1)) : 0;
    }
    if (lines.length >= 3 && lines[2].startsWith('Swap:')) {
      const swapParts = lines[2].trim().split(/\s+/);
      if (swapParts.length >= 3) {
        swapTotal = parseInt(swapParts[1], 10);
        swapUsed  = parseInt(swapParts[2], 10);
      }
    }
  }
  return { total, used, free, cached, percent, swapTotal, swapUsed };
}

/**
 * @param {string} raw - output của `df -h`
 * @returns {Array<{ percent, usedStr, totalStr, mountPoint }>}
 */
export function parseDisks(raw) {
  const lines = raw.split('\n');
  const disks = [];
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line.startsWith('/dev/')) continue;
    const parts = line.split(/\s+/);
    // `df -h` luôn có thứ tự cột cố định: Filesystem Size Used Avail Use% Mounted
    // Dùng index cố định thay vì pctIdx - 3 để tránh sai khi tên thiết bị có khoảng trắng.
    if (parts.length < 6) continue;
    disks.push({
      totalStr:   parts[1],
      usedStr:    parts[2],
      percent:    parseInt(parts[4].replace('%', ''), 10),
      mountPoint: parts.slice(5).join(' '),
    });
  }
  return disks;
}

/**
 * @param {string} raw - output của `cat /proc/net/dev`
 * @param {{ rx: number, tx: number, time: number }} lastRef - ref.current từ React
 * @returns {{ rxSpeed, txSpeed, totalRx, totalTx, interfaceName }}
 */
export function parseNetwork(raw, lastRef) {
  const lines = raw.split('\n');
  let totalRx = 0, totalTx = 0, mainInterfaceName = '', maxRx = -1;

  for (let i = 2; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line || line.startsWith('lo:')) continue;
    const colonSplit = line.split(':');
    if (colonSplit.length !== 2) continue;
    const iface = colonSplit[0].trim();
    const stats = colonSplit[1].trim().split(/\s+/);
    const rx = parseInt(stats[0], 10) || 0;
    const tx = parseInt(stats[8], 10) || 0;
    totalRx += rx;
    totalTx += tx;
    if (rx > maxRx) { maxRx = rx; mainInterfaceName = iface; }
  }

  const now = Date.now();
  const timeDiff = (now - lastRef.time) / 1000;
  const rawRxSpeed = (timeDiff > 0 && lastRef.rx > 0) ? (totalRx - lastRef.rx) / timeDiff : 0;
  const rawTxSpeed = (timeDiff > 0 && lastRef.tx > 0) ? (totalTx - lastRef.tx) / timeDiff : 0;

  // Clamp về 0 khi kernel counter bị wrap hoặc container restart làm giá trị âm
  const rxSpeed = Math.max(0, rawRxSpeed);
  const txSpeed = Math.max(0, rawTxSpeed);

  return { rxSpeed, txSpeed, totalRx, totalTx, interfaceName: mainInterfaceName };
}

/**
 * @param {string} raw - output của `ps`
 * @returns {Array<{ id, user, cpu, memPercent, threads, mem, name, args }>}
 */
export function parseProcesses(raw) {
  const lines = raw.split('\n');
  return lines.slice(1).map(line => {
    const parts = line.trim().split(/\s+/);
    if (parts.length >= 7) {
      return {
        id: parts[0], user: parts[1], cpu: parts[2] + '%',
        memPercent: parts[3] + '%', threads: parts[4],
        mem: (parseInt(parts[5], 10) / 1024).toFixed(1) + ' MB',
        name: parts[6], args: parts.slice(7).join(' ') || parts[6],
      };
    }
    if (parts.length >= 5) {
      return {
        id: parts[0], user: parts[1], cpu: parts[2] + '%',
        memPercent: parts[3] + '%', threads: '-', mem: 'N/A',
        name: parts[4], args: parts.slice(4).join(' '),
      };
    }
    return null;
  }).filter(Boolean);
}

/**
 * Parse output của `sensors` (hoặc thermal_zone fallback) thành danh sách nhiệt độ.
 * Trả về array để Temperature card hiển thị từng core giống Voltage card.
 *
 * @param {string} raw - full text output từ `sensors` hoặc "label: millideg" per line
 * @returns {Array<{ label: string, value: string, status: 'ok'|'warn'|'crit' }>}
 */
export function parseTemperature(raw) {
  if (!raw || raw === 'N/A') return [];

  const results = [];
  const lines = raw.split('\n');

  // Regex khớp dòng nhiệt độ của sensors: "Core 0:  +44.0°C  (...)"
  // hoặc fallback thermal_zone: "thermal_zone0:  25000" (millidegrees)
  const sensorsRegex = /^(.+?):\s*([+-]?\d+\.?\d*)\s*°?C/i;
  const thermalZoneRegex = /^(.+?):\s*(\d{4,6})\s*$/; // millidegrees từ thermal_zone

  let currentAdapter = '';

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;

    // Theo dõi adapter block (ví dụ: dell_smm-isa-00de, coretemp-isa-0000)
    if (!trimmed.includes(':') || /^[a-z0-9_-]+-(isa|acpi|virtual|pci)-[0-9a-f]+$/i.test(trimmed)) {
      currentAdapter = trimmed.toLowerCase();
      continue;
    }

    let label = null;
    let tempC = null;

    const sm = line.match(sensorsRegex);
    if (sm) {
      label  = sm[1].trim();
      tempC  = parseFloat(sm[2]);
    } else {
      const tm = line.match(thermalZoneRegex);
      if (tm) {
        label  = tm[1].trim();
        tempC  = parseInt(tm[2], 10) / 1000;
        // Bỏ qua cảm biến ACPI ảo kẹt 25°C / 26.8°C
        if (tempC === 25 || tempC === 26.8) continue;
      }
    }

    if (label === null || tempC === null || isNaN(tempC)) continue;

    // Lọc bỏ cảm biến ảo kẹt 97°C/98°C từ driver dell_smm trên máy Dell
    if (currentAdapter.includes('dell_smm')) {
      if (label.toLowerCase() === 'cpu' || tempC >= 95) continue;
    }

    // Chỉ lấy các dòng nhiệt độ thực — bỏ voltage, fan, power
    const lowerLabel = label.toLowerCase();
    if (lowerLabel.includes('fan') || lowerLabel.includes('rpm') ||
        lowerLabel.includes('volt') || lowerLabel.includes(' v') ||
        lowerLabel.includes('power') || lowerLabel.includes('watt') ||
        lowerLabel.includes('curr') || tempC <= 0 || tempC > 120) continue;

    // Phân loại mức nhiệt
    let status = 'ok';
    if (tempC >= 85) status = 'crit';
    else if (tempC >= 70) status = 'warn';

    results.push({ label, value: tempC.toFixed(1), status });
  }

  return results;
}

/**
 * Lấy nhiệt độ tổng quan (Package / Tdie / Tctl hoặc max) từ array parseTemperature.
 * Dùng để hiển thị inline (CPU card cũ, modal...).
 *
 * @param {Array<{ label, value, status }>} temps
 * @returns {string|null} "XX.X" hoặc null nếu không có dữ liệu
 */
export function getMaxTemperature(temps) {
  if (!temps || temps.length === 0) return null;
  // Ưu tiên Package / Tdie / Tctl / CPU thermal (đại diện cho toàn bộ chip từ coretemp)
  const pkg = temps.find(t =>
    /package|tdie|tctl|cpu thermal/i.test(t.label)
  );
  if (pkg) return pkg.value;
  // Fallback: nhiệt độ cao nhất trong danh sách
  const max = temps.reduce((a, b) => parseFloat(a.value) >= parseFloat(b.value) ? a : b);
  return max.value;
}

/**
 * Parse output của lệnh `sensors` để lấy các chỉ số điện áp (voltage).
 * sensors liệt kê theo block chip, mỗi dòng dạng: "Label:  +X.XXX V  (min = ..., max = ...)"
 *
 * @param {string} raw - raw text từ `sensors`
 * @returns {Array<{ label: string, value: string, status: 'ok'|'warn'|'crit' }>}
 */
export function parseVoltage(raw) {
  if (!raw || raw === 'N/A') return [];

  const results = [];
  const lines = raw.split('\n');

  // Regex khớp dòng có đơn vị V (volt): tên + giá trị dạng +X.XXX V hoặc X.XXX V
  const voltageRegex = /^(.+?):\s*([+-]?\d+\.\d+)\s*V/i;

  for (const line of lines) {
    const match = line.match(voltageRegex);
    if (!match) continue;

    const label = match[1].trim();
    const value = parseFloat(match[2]);

    // Bỏ qua các dòng không liên quan (temp, fan, power)
    const lowerLabel = label.toLowerCase();
    if (lowerLabel.includes('temp') || lowerLabel.includes('fan') ||
        lowerLabel.includes('rpm')  || lowerLabel.includes('power') ||
        lowerLabel.includes('watt') || lowerLabel.includes('curr')) continue;

    // Phân loại trạng thái dựa trên tolerance ±10%
    let status = 'ok';
    const nominal = guessNominalVoltage(label, value);
    if (nominal > 0) {
      const deviation = Math.abs(value - nominal) / nominal;
      if (deviation > 0.1) status = 'crit';
      else if (deviation > 0.05) status = 'warn';
    }

    results.push({ label, value: value.toFixed(3), status });
  }

  return results;
}

/**
 * Đoán điện áp nominal dựa trên tên rail.
 * Dùng để tính deviation cho màu sắc cảnh báo.
 */
function guessNominalVoltage(label, measuredV) {
  const l = label.toLowerCase();
  if (l.includes('vcore') || l.includes('vcpu') || l.includes('vdd') || l.includes('core')) {
    if (measuredV >= 0.55 && measuredV <= 1.45) return measuredV; // Dynamic CPU Vcore range (0.55V - 1.45V)
    return 1.2;
  }
  if (l.includes('12') || (measuredV > 10 && measuredV < 14)) return 12;
  if (l.includes('5')  || (measuredV > 4  && measuredV < 6))  return 5;
  if (l.includes('3.3')|| (measuredV > 2.8 && measuredV < 3.8)) return 3.3;
  return 0; // không đoán được → không cảnh báo
}

/**
 * Format bytes per second into human readable speed
 */
export function formatSpeed(bps) {
  if (bps > 1024 * 1024) return (bps / (1024 * 1024)).toFixed(1) + ' MB/s';
  if (bps > 1024) return (bps / 1024).toFixed(1) + ' KB/s';
  return Math.max(0, bps).toFixed(0) + ' B/s';
}

/**
 * Format bytes into human readable sizes
 */
export function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * @param {string} raw - output của `cat /proc/diskstats`
 * @param {{ readBytes: number, writeBytes: number, time: number }} lastRef
 * @returns {{ readSpeed: string, writeSpeed: string, readSpeedRaw: number, writeSpeedRaw: number, totalReadBytes: number, totalWriteBytes: number }}
 */
export function parseDiskIo(raw, lastRef) {
  if (!raw) return { readSpeed: '0 B/s', writeSpeed: '0 B/s', readSpeedRaw: 0, writeSpeedRaw: 0, totalReadBytes: 0, totalWriteBytes: 0 };
  const safeRef = lastRef || { time: 0, readBytes: 0, writeBytes: 0 };
  const lines = raw.split('\n');
  let totalReadSectors = 0;
  let totalWriteSectors = 0;
  
  for (const line of lines) {
    if (!line.trim()) continue;
    const parts = line.split('|');
    if (parts.length >= 3) {
      totalReadSectors += parseInt(parts[1], 10) || 0;
      totalWriteSectors += parseInt(parts[2], 10) || 0;
    }
  }

  // 1 sector = 512 bytes
  const currentReadBytes = totalReadSectors * 512;
  const currentWriteBytes = totalWriteSectors * 512;

  const now = Date.now();
  const timeDiff = safeRef.time > 0 ? (now - safeRef.time) / 1000 : 0;
  
  let readSpeed = 0, writeSpeed = 0;
  if (timeDiff > 0 && safeRef.readBytes > 0) {
    readSpeed = Math.max(0, (currentReadBytes - safeRef.readBytes) / timeDiff);
    writeSpeed = Math.max(0, (currentWriteBytes - safeRef.writeBytes) / timeDiff);
  }

  return {
    readSpeed: formatSpeed(readSpeed),
    writeSpeed: formatSpeed(writeSpeed),
    readSpeedRaw: readSpeed,
    writeSpeedRaw: writeSpeed,
    totalReadBytes: currentReadBytes,
    totalWriteBytes: currentWriteBytes
  };
}

/**
 * Parse output of nvidia-smi
 * @param {string} raw
 * @returns {Array<{ name, temp, memUsed, memTotal, memPercent, utilPercent }>}
 */
export function parseGpu(raw) {
  if (!raw || raw.trim() === 'NO_GPU') return [];
  const lines = raw.trim().split('\n');
  return lines.map(line => {
    const parts = line.split('|');
    if (parts.length >= 5) {
      const name = parts[0].trim();
      const temp = parseInt(parts[1], 10) || 0;
      const memUsed = parseInt(parts[2], 10) || 0;
      const memTotal = parseInt(parts[3], 10) || 1;
      const utilPercent = parseInt(parts[4], 10) || 0;
      const memPercent = parseFloat(((memUsed / memTotal) * 100).toFixed(1));
      return { name, temp, memUsed, memTotal, memPercent, utilPercent };
    }
    return null;
  }).filter(Boolean);
}

/**
 * Extract 1m, 5m, 15m load average from uptime string
 * @param {string} uptimeStr
 */
export function parseLoadAverage(uptimeStr) {
  if (!uptimeStr) return { m1: 0, m5: 0, m15: 0 };
  const match = uptimeStr.match(/load average:\s*([0-9.,]+),\s*([0-9.,]+),\s*([0-9.,]+)/);
  if (match) {
    return {
      m1: parseFloat(match[1].replace(',', '.')),
      m5: parseFloat(match[2].replace(',', '.')),
      m15: parseFloat(match[3].replace(',', '.'))
    };
  }
  return { m1: 0, m5: 0, m15: 0 };
}

/**
 * Parse output của lệnh `sensors` để lấy tốc độ quạt (fan speed).
 *
 * @param {string} raw - raw text từ `sensors`
 * @returns {Array<{ label: string, value: number }>}
 */
export function parseFan(raw) {
  if (!raw || raw === 'N/A') return [];

  const results = [];
  const lines = raw.split('\n');
  const fanRegex = /^(.+?):\s*(\d+)\s*RPM/i;

  for (const line of lines) {
    const match = line.match(fanRegex);
    if (!match) continue;

    results.push({ label: match[1].trim(), value: parseInt(match[2], 10) });
  }

  return results;
}

/**
 * Parse output of docker stats --no-stream --format '{{.ID}}|{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.NetIO}}'
 * @param {string} raw
 * @returns {Record<string, { id: string, name: string, cpu: string, mem: string, netIO: string }>}
 */
export function parseDockerStats(raw) {
  if (!raw || raw.includes('DOCKER_NOT_FOUND') || raw.startsWith('ERROR')) return {};
  const map = {};
  const lines = raw.trim().split('\n');
  for (const line of lines) {
    const parts = line.split('|');
    if (parts.length >= 4) {
      const id = parts[0].trim();
      const name = parts[1].trim();
      const cpu = parts[2].trim();
      const mem = parts[3].trim();
      const netIO = parts.length >= 5 ? parts[4].trim() : '-';
      const statsObj = { id, name, cpu, mem, netIO };
      map[id] = statsObj;
      map[name] = statsObj;
    }
  }
  return map;
}

/**
 * Format Docker container status into a concise status descriptor
 * E.g. "Up 2 hours (healthy)" -> { isUp: true, label: "UP (2h)", full: "Up 2 hours (healthy)" }
 * @param {string} statusStr
 */
export function formatDockerStatus(statusStr = '') {
  if (!statusStr) return { isUp: false, label: 'OFFLINE', full: '' };
  const isUp = statusStr.toLowerCase().startsWith('up');
  
  if (!isUp) {
    const exitedMatch = statusStr.match(/Exited\s*\(\d+\)/i);
    return { isUp: false, label: exitedMatch ? exitedMatch[0] : 'EXITED', full: statusStr };
  }

  let uptime = statusStr
    .replace(/^Up\s+/i, '')
    .replace(/\s+ago$/i, '')
    .replace(/About a minute/i, '1m')
    .replace(/About an hour/i, '1h')
    .replace(/hours?/i, 'h')
    .replace(/minutes?/i, 'm')
    .replace(/seconds?/i, 's')
    .replace(/weeks?/i, 'w')
    .replace(/days?/i, 'd')
    .trim();

  return { isUp: true, label: `UP (${uptime})`, full: statusStr };
}

/**
 * Format port mappings into concise public ports string
 * @param {string} portsStr
 */
export function formatDockerPorts(portsStr = '') {
  if (!portsStr || portsStr === '—' || portsStr === '-') return null;
  const matches = portsStr.match(/(?:0\.0\.0\.0|:::|\[::\]):(\d+)->/g);
  if (matches && matches.length > 0) {
    const uniquePorts = [...new Set(matches.map(m => m.match(/:(\d+)->/)[1]))];
    return uniquePorts.slice(0, 2).map(p => `:${p}`).join(' ');
  }
  const simpleMatch = portsStr.match(/(\d+)\//);
  return simpleMatch ? `:${simpleMatch[1]}` : portsStr.slice(0, 10);
}

// Helper used by datetime formatters below
function pad2(num) {
  return String(num).padStart(2, '0');
}

/**
 * Format bất kỳ chuỗi thời gian hoặc dòng log thô sang chuẩn Việt Nam: DD/MM/YYYY HH:mm:ss
 *
 * @param {string|number|Date} input
 * @returns {string} Chuỗi thời gian chuẩn Việt Nam (ví dụ: 06/08/2026 04:20:14)
 */
export function formatVietnameseDateTime(input) {
  if (!input) return '';

  if (input instanceof Date || typeof input === 'number') {
    const d = new Date(input);
    if (isNaN(d.getTime())) return String(input);
    return pad2(d.getDate()) + '/' + pad2(d.getMonth() + 1) + '/' + d.getFullYear() + ' ' +
           pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds());
  }

  const str = String(input).trim();

  // 1. ISO-8601: 2026-08-06T04:20:14.309391+07:00 hoặc 2026-08-06 04:20:14
  const isoMatch = str.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})/);
  if (isoMatch) {
    const [, yyyy, mm, dd, hh, min, ss] = isoMatch;
    return `${dd}/${mm}/${yyyy} ${hh}:${min}:${ss}`;
  }

  // 2. Syslog BSD: Aug  6 04:20:14 hoặc Aug 06 04:20:14
  const monthMap = { jan:'01', feb:'02', mar:'03', apr:'04', may:'05', jun:'06', jul:'07', aug:'08', sep:'09', oct:'10', nov:'11', dec:'12' };
  const syslogMatch = str.match(/^([A-Za-z]{3})\s+(\d{1,2})\s+(\d{2}):(\d{2}):(\d{2})/);
  if (syslogMatch) {
    const [, monStr, dayStr, hh, min, ss] = syslogMatch;
    const mm = monthMap[monStr.toLowerCase()] || '01';
    const dd = pad2(parseInt(dayStr, 10));
    // Heuristic: if the parsed month is strictly in the future relative to the current month,
    // the log entry must belong to the previous year (e.g. a Dec log read in Jan).
    const now = new Date();
    const parsedMonthIndex = parseInt(mm, 10) - 1; // convert to 0-indexed
    const yyyy = parsedMonthIndex > now.getMonth() ? now.getFullYear() - 1 : now.getFullYear();
    return `${dd}/${mm}/${yyyy} ${hh}:${min}:${ss}`;
  }

  // Khác: Thử parse Date tiêu chuẩn — chỉ áp dụng cho chuỗi đủ dài để tránh
  // parse sai các giá trị ngắn/mơ hồ như "1", "Infinity", hoặc số đơn lẻ.
  if (str.length >= 10) {
    const d = new Date(str);
    if (!isNaN(d.getTime())) {
      return pad2(d.getDate()) + '/' + pad2(d.getMonth() + 1) + '/' + d.getFullYear() + ' ' +
             pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds());
    }
  }

  return str;
}


/**
 * Định dạng lại timestamp ở đầu mỗi dòng log thô theo chuẩn Việt Nam (DD/MM/YYYY HH:mm:ss)
 *
 * @param {string} line
 * @returns {string} Dòng log với timestamp chuẩn Việt Nam ở đầu
 */
export function formatLogLineTimestamp(line) {
  if (!line || typeof line !== 'string') return line;

  // Pattern 1: ISO 8601 (2026-08-06T04:20:14.309391+07:00 ...)
  const isoPattern = /^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)\s+(.*)$/;
  const isoMatch = line.match(isoPattern);
  if (isoMatch) {
    const formattedTs = formatVietnameseDateTime(isoMatch[1]);
    return `${formattedTs} ${isoMatch[2]}`;
  }

  // Pattern 2: BSD Syslog (Aug  6 04:20:14 ...)
  const syslogPattern = /^([A-Za-z]{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(.*)$/;
  const syslogMatch = line.match(syslogPattern);
  if (syslogMatch) {
    const formattedTs = formatVietnameseDateTime(syslogMatch[1]);
    return `${formattedTs} ${syslogMatch[2]}`;
  }

  return line;
}