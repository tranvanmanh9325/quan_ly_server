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
      total = parseInt(memParts[1], 10);
      used  = parseInt(memParts[2], 10);
      free  = parseInt(memParts[3], 10);
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
 * @param {string} raw - giá trị nhiệt độ thô (millidegrees hoặc độ C)
 * @returns {string|null} nhiệt độ định dạng "XX.X" hoặc 'N/A' hoặc null
 */
export function parseTemperature(raw) {
  if (!raw || raw === 'N/A') return 'N/A';
  const value = parseFloat(raw);
  if (isNaN(value)) return 'N/A';
  // Nếu > 1000 thì đang là millidegrees Celsius
  return (value > 1000 ? value / 1000 : value).toFixed(1);
}
