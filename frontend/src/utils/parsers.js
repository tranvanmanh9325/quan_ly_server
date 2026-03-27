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
    const pctIdx = parts.findIndex(p => p.endsWith('%'));
    if (pctIdx === -1) continue;
    disks.push({
      percent:    parseInt(parts[pctIdx].replace('%', ''), 10),
      usedStr:    parts[pctIdx - 2],
      totalStr:   parts[pctIdx - 3],
      mountPoint: parts.slice(pctIdx + 1).join(' '),
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
  const rxSpeed = (timeDiff > 0 && lastRef.rx > 0) ? (totalRx - lastRef.rx) / timeDiff : 0;
  const txSpeed = (timeDiff > 0 && lastRef.tx > 0) ? (totalTx - lastRef.tx) / timeDiff : 0;

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

  for (const line of lines) {
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
  // Ưu tiên Package / Tdie / Tctl (đại diện cho toàn bộ chip)
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
  if (l.includes('12') || (measuredV > 10 && measuredV < 14)) return 12;
  if (l.includes('5')  || (measuredV > 4  && measuredV < 6))  return 5;
  if (l.includes('3.3')|| (measuredV > 2.8 && measuredV < 3.8)) return 3.3;
  if (l.includes('vcore') || l.includes('vcpu') || l.includes('vdd') || l.includes('core')) return 1.2;
  return 0; // không đoán được → không cảnh báo
}