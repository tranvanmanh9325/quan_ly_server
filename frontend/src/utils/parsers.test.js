import { describe, it, expect } from 'vitest';
import { 
  parseCpu, parseRam, parseDisks, parseNetwork, parseProcesses, 
  parseTemperature, parseVoltage, parseLoadAverage, getMaxTemperature, parseDockerStats,
  formatVietnameseDateTime, formatLogLineTimestamp
} from './parsers';

describe('parsers.js unit tests', () => {

  it('parseCpu - should correctly extract CPU usage percentage', () => {
    const rawTop = '%Cpu(s):  6.5 us,  7.8 sy,  0.0 ni, 85.7 id,  0.0 wa';
    const cpu = parseCpu(rawTop);
    expect(cpu).toBe(14.3); // 100 - 85.7 = 14.3
  });

  it('parseCpu - should handle empty or invalid input gracefully', () => {
    expect(parseCpu('')).toBe(0);
    expect(parseCpu('invalid text')).toBe(0);
  });

  it('parseRam - should correctly parse free -m output', () => {
    const rawFree = `               total        used        free      shared  buff/cache   available
Mem:           15872        4210        8000         120        3662       11200
Swap:           2048         512        1536`;
    
    const ram = parseRam(rawFree);
    expect(ram.total).toBe(15872);
    expect(ram.used).toBe(4210);
    expect(ram.free).toBe(8000);
    expect(ram.cached).toBe(3662);
    expect(ram.swapTotal).toBe(2048);
    expect(ram.swapUsed).toBe(512);
    expect(ram.percent).toBeCloseTo(26.5, 1);
  });

  it('parseDisks - should parse df -h output correctly', () => {
    const rawDf = `Filesystem      Size  Used Avail Use% Mounted on
/dev/sda1        40G   15G   23G  40% /
/dev/sdb1       100G   80G   20G  80% /data`;
    
    const disks = parseDisks(rawDf);
    expect(disks.length).toBe(2);
    expect(disks[0].mountPoint).toBe('/');
    expect(disks[0].percent).toBe(40);
    expect(disks[1].mountPoint).toBe('/data');
    expect(disks[1].percent).toBe(80);
  });

  it('parseNetwork - should calculate rx/tx speeds based on deltas', () => {
    const rawNet = `Inter-|   Receive                                                | Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: 123456       10    0    0    0     0          0         0   123456       10    0    0    0     0       0          0
  eth0: 1000000     100    0    0    0     0          0         0  2000000      200    0    0    0     0       0          0`;

    const lastRef = { rx: 500000, tx: 1000000, time: Date.now() - 2000 };
    const net = parseNetwork(rawNet, lastRef);

    expect(net.interfaceName).toBe('eth0');
    expect(net.totalRx).toBe(1000000);
    expect(net.totalTx).toBe(2000000);
    expect(net.rxSpeed).toBeGreaterThan(0);
    expect(net.txSpeed).toBeGreaterThan(0);
  });

  it('parseProcesses - should parse ps output correctly', () => {
    const rawPs = `PID USER %CPU %MEM NLWP RSS COMMAND
1 root 0.1 0.2 1 4096 /sbin/init
1234 ubuntu 15.5 4.2 8 81920 node server.js --prod`;

    const procs = parseProcesses(rawPs);
    expect(procs.length).toBe(2);
    expect(procs[0].id).toBe('1');
    expect(procs[1].id).toBe('1234');
    expect(procs[1].cpu).toBe('15.5%');
    expect(procs[1].user).toBe('ubuntu');
    expect(procs[1].mem).toBe('80.0 MB');
  });

  it('parseTemperature - should parse sensors C° and status', () => {
    const rawSensors = `Core 0:        +45.0°C  (high = +80.0°C, crit = +100.0°C)
Package id 0:  +88.5°C  (high = +80.0°C, crit = +100.0°C)`;

    const temps = parseTemperature(rawSensors);
    expect(temps.length).toBe(2);
    expect(temps[0].status).toBe('ok');
    expect(temps[1].status).toBe('crit');
    expect(getMaxTemperature(temps)).toBe('88.5');
  });

  it('parseTemperature - should ignore fake Dell SMM CPU 97°C glitch', () => {
    const dellSensors = `coretemp-isa-0000
Adapter: ISA adapter
Package id 0:  +37.0°C  (high = +100.0°C, crit = +100.0°C)
Core 0:        +36.0°C  (high = +100.0°C, crit = +100.0°C)

dell_smm-isa-00de
Adapter: ISA adapter
Processor Fan: 5306 RPM  (min =    0 RPM, max = 4900 RPM)
CPU:            +97.0°C`;

    const temps = parseTemperature(dellSensors);
    expect(temps.some(t => t.label === 'CPU')).toBe(false);
    expect(getMaxTemperature(temps)).toBe('37.0');
  });

  it('parseLoadAverage - should parse load average string', () => {
    const rawUptime = ' 16:30:00 up 10 days,  4:12,  2 users,  load average: 0.45, 1.20, 2.15';
    const load = parseLoadAverage(rawUptime);
    expect(load.m1).toBe(0.45);
    expect(load.m5).toBe(1.20);
    expect(load.m15).toBe(2.15);
  });

  it('parseVoltage - should parse voltage readings from sensors output', () => {
    const rawSensors = `in0:          +1.216 V  (min =  +0.000 V, max =  +1.744 V)
+12V:        +12.096 V  (min = +10.800 V, max = +13.200 V)`;
    const voltages = parseVoltage(rawSensors);
    expect(voltages.length).toBeGreaterThan(0);
    expect(voltages[0].value).toBe('1.216');
  });

  it('parseDockerStats - should parse docker stats output line by line', () => {
    const rawStats = 'abc123|web_app|4.2%|128MiB / 2GiB|1.5kB / 3.2kB';
    const statsMap = parseDockerStats(rawStats);
    expect(statsMap['web_app']).toBeDefined();
    expect(statsMap['web_app'].cpu).toBe('4.2%');
    expect(statsMap['web_app'].mem).toBe('128MiB / 2GiB');
  });

  it('formatVietnameseDateTime - should format ISO and Syslog dates to DD/MM/YYYY HH:mm:ss', () => {
    expect(formatVietnameseDateTime('2026-08-06T04:20:14.309391+07:00')).toBe('06/08/2026 04:20:14');
    expect(formatVietnameseDateTime('2026-08-06 04:20:14')).toBe('06/08/2026 04:20:14');
    expect(formatVietnameseDateTime('Aug  6 04:20:14')).toContain('/2026 04:20:14');
  });

  it('formatLogLineTimestamp - should replace raw timestamp with Vietnamese format', () => {
    const rawLine = '2026-08-06T04:20:14.309391+07:00 kirito-server systemd[1]: Started session-317.scope.';
    const formatted = formatLogLineTimestamp(rawLine);
    expect(formatted).toBe('06/08/2026 04:20:14 kirito-server systemd[1]: Started session-317.scope.');
  });
});
