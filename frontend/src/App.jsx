import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import axios from 'axios';
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import { LayoutDashboard, BarChart2, Folder, Users, Settings, FileText, Search, Bell, User, MoreHorizontal, Activity, HardDrive, Wifi, Zap, Cpu, Server } from 'lucide-react';
import './index.css';
import './App.css';
import { parseCpu, parseRam, parseDisks, parseNetwork, parseProcesses, parseTemperature, parseVoltage } from './utils/parsers';

const API_BASE = '/api/metrics';

// Khoảng thời gian polling mặc định (ms)
const METRICS_INTERVAL_NORMAL = 10_000;
const METRICS_INTERVAL_SLOW   = 20_000; // Tự động chuyển khi SSH phản hồi chậm (> 5s)
const PROCESS_INTERVAL        = 30_000;
const ADAPTIVE_THRESHOLD_MS   = 5_000;  // Ngưỡng để xem SSH là "đang chậm"

function App() {
  const [processes, setProcesses]   = useState([]);
  const [system, setSystem]         = useState('');
  const [cpuHistory, setCpuHistory] = useState(Array(15).fill({ name: '', value: 0 }));
  const [ramData, setRamData]       = useState({ total: 0, used: 0, free: 0, cached: 0, percent: 0, swapTotal: 0, swapUsed: 0 });
  const [diskData, setDiskData]     = useState([]);
  const [networkData, setNetworkData] = useState({ rxSpeed: 0, txSpeed: 0, totalRx: 0, totalTx: 0, interfaceName: '' });
  const lastNetRef = useRef({ rx: 0, tx: 0, time: 0 });
  const [isServerModalOpen, setIsServerModalOpen] = useState(false);
  const [connections, setConnections]   = useState([]);
  const [selectedConnection, setSelectedConnection] = useState(null);
  const [temperature, setTemperature]   = useState(null);
  const [voltageData, setVoltageData]   = useState([]); // Array<{ label, value, status }>
  const [sysInfo, setSysInfo]           = useState({ kernel: 'N/A', hostname: 'N/A', os: 'N/A', cpuModel: 'N/A' });

  // Dùng ref để trigger refresh từ nút bấm mà không gây re-render thêm
  const refreshCounterRef = useRef(0);
  const [refreshTick, setRefreshTick] = useState(0);

  // --- Search debounce (300ms) — tránh filter lại 100+ dòng mỗi keystroke ---
  const [searchInput, setSearchInput]   = useState('');
  const [searchTerm, setSearchTerm]     = useState('');
  const searchDebounceRef               = useRef(null);

  const handleSearchChange = useCallback((e) => {
    const value = e.target.value;
    setSearchInput(value);
    clearTimeout(searchDebounceRef.current);
    searchDebounceRef.current = setTimeout(() => setSearchTerm(value), 300);
  }, []);

  const handleRefresh = () => {
    refreshCounterRef.current += 1;
    setRefreshTick(refreshCounterRef.current);
  };

  const formatSpeed = (bps) => {
    if (bps > 1024 * 1024) return (bps / (1024 * 1024)).toFixed(1) + ' MB/s';
    if (bps > 1024) return (bps / 1024).toFixed(1) + ' KB/s';
    return Math.max(0, bps).toFixed(0) + ' B/s';
  };

  const formatBytes = (bytes) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const formattedSystem = useMemo(() => {
    if (!system) return { uptime: 'Đang lấy dữ liệu...', load: '' };
    try {
      const parts = system.split('load average:');
      const loadStr = parts[1] ? parts[1].trim() : '';
      let upPart = parts[0] || system;
      const upIndex = upPart.indexOf('up ');
      if (upIndex !== -1) {
        let timeChunk = upPart.substring(upIndex + 3);
        const userIndex = timeChunk.indexOf(' user');
        if (userIndex !== -1) {
          timeChunk = timeChunk.substring(0, userIndex);
          const lastComma = timeChunk.lastIndexOf(',');
          if (lastComma !== -1) timeChunk = timeChunk.substring(0, lastComma);
        }
        let timeStr = timeChunk.trim();
        timeStr = timeStr.replace(/days?/g, 'ngày').replace(/mins?/g, 'phút');
        const timeMatch = timeStr.match(/(\d+):(\d+)/);
        if (timeMatch) {
          const h = parseInt(timeMatch[1], 10), m = parseInt(timeMatch[2], 10);
          timeStr = timeStr.replace(/\d+:\d+/, `${h} giờ ${m} phút`);
        }
        return { uptime: timeStr.replace(/,/g, ' ').replace(/\s+/g, ' ').trim() || system, load: loadStr };
      }
      return { uptime: system, load: '' };
    } catch {
      return { uptime: system, load: '' };
    }
  }, [system]);


  // ─── Effect 1: Lightweight metrics — poll mỗi 10 giây (adaptive) ────────────
  useEffect(() => {
    let isMounted    = true;
    let isFetching   = false;
    // Khoảng interval hiện tại: có thể tự tăng lên 20s khi SSH chậm
    let currentInterval = METRICS_INTERVAL_NORMAL;
    let timerId = null;

    const loadMetrics = async () => {
      if (isFetching) return;
      isFetching = true;
      const t0 = Date.now();

      try {
        const [sysRes, cpuRes, ramRes, diskRes, netRes, connRes, tempRes, voltRes, sysinfoRes] = await Promise.all([
          axios.get(`${API_BASE}/system`),
          axios.get(`${API_BASE}/cpu`),
          axios.get(`${API_BASE}/ram`),
          axios.get(`${API_BASE}/disk`),
          axios.get(`${API_BASE}/network`),
          axios.get(`${API_BASE}/connections`),
          axios.get(`${API_BASE}/temperature`),
          axios.get(`${API_BASE}/voltage`),
          axios.get(`${API_BASE}/sysinfo`),
        ]);

        if (!isMounted) return;

        // --- Adaptive backoff: đo thời gian phản hồi để tự điều chỉnh interval ---
        const elapsed = Date.now() - t0;
        const newInterval = elapsed > ADAPTIVE_THRESHOLD_MS ? METRICS_INTERVAL_SLOW : METRICS_INTERVAL_NORMAL;
        if (newInterval !== currentInterval) {
          console.info(`[Adaptive] SSH phản hồi ${elapsed}ms → chuyển interval sang ${newInterval / 1000}s`);
          currentInterval = newInterval;
          clearTimeout(timerId);
          timerId = setTimeout(schedule, currentInterval);
        }

        if (connRes.data?.data) setConnections(connRes.data.data);
        if (sysRes.data)        setSystem(sysRes.data.data);

        if (cpuRes.data?.data) {
          const cpuPercent = parseCpu(cpuRes.data.data);
          setCpuHistory(prev => {
            const timeStr = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
            return [...prev.slice(1), { name: timeStr, value: cpuPercent }];
          });
        }

        if (ramRes.data?.data)  setRamData(parseRam(ramRes.data.data));
        if (diskRes.data?.data) setDiskData(parseDisks(diskRes.data.data));

        if (netRes.data?.data) {
          const result = parseNetwork(netRes.data.data, lastNetRef.current);
          lastNetRef.current = { rx: result.totalRx, tx: result.totalTx, time: Date.now() };
          setNetworkData(result);
        }

        const temp = parseTemperature(tempRes?.data?.data);
        if (temp !== null) setTemperature(temp);

        // Parse voltage — chỉ update nếu có dữ liệu
        if (voltRes?.data?.data) {
          const volts = parseVoltage(voltRes.data.data);
          setVoltageData(volts);
        }

        // SysInfo — backend đã parse sẵn thành object
        if (sysinfoRes?.data) {
          setSysInfo(prev => ({ ...prev, ...sysinfoRes.data }));
        }

      } catch (error) {
        console.error('Lỗi lấy metrics:', error);
      } finally {
        isFetching = false;
      }
    };

    // Dùng setTimeout thay vì setInterval để interval có thể thay đổi động
    const schedule = () => {
      // Visibility API: không poll khi tab bị ẩn — tiết kiệm 100% SSH call khi không xem
      if (document.visibilityState === 'hidden') {
        timerId = setTimeout(schedule, 1000); // kiểm tra lại sau 1s
        return;
      }
      loadMetrics().finally(() => {
        if (isMounted) timerId = setTimeout(schedule, currentInterval);
      });
    };

    // Chạy ngay lần đầu, sau đó lên lịch
    loadMetrics().finally(() => {
      if (isMounted) timerId = setTimeout(schedule, currentInterval);
    });

    // Resume ngay khi tab được focus lại
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible' && isMounted) {
        clearTimeout(timerId);
        loadMetrics().finally(() => {
          if (isMounted) timerId = setTimeout(schedule, currentInterval);
        });
      }
    };
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      isMounted = false;
      clearTimeout(timerId);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [refreshTick]);


  // ─── Effect 2: Process list nặng — poll riêng mỗi 30 giây ──────────────────
  useEffect(() => {
    let isMounted      = true;
    let isFetchingProcs = false;
    let timerId        = null;

    const loadProcesses = async () => {
      if (isFetchingProcs) return;
      isFetchingProcs = true;
      try {
        const pRes = await axios.get(`${API_BASE}/processes`);
        if (!isMounted) return;
        if (pRes.data?.data) setProcesses(parseProcesses(pRes.data.data));
      } catch (error) {
        console.error('Lỗi lấy processes:', error);
      } finally {
        isFetchingProcs = false;
      }
    };

    const schedule = () => {
      if (document.visibilityState === 'hidden') {
        timerId = setTimeout(schedule, 1000);
        return;
      }
      loadProcesses().finally(() => {
        if (isMounted) timerId = setTimeout(schedule, PROCESS_INTERVAL);
      });
    };

    loadProcesses().finally(() => {
      if (isMounted) timerId = setTimeout(schedule, PROCESS_INTERVAL);
    });

    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible' && isMounted) {
        clearTimeout(timerId);
        loadProcesses().finally(() => {
          if (isMounted) timerId = setTimeout(schedule, PROCESS_INTERVAL);
        });
      }
    };
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      isMounted = false;
      clearTimeout(timerId);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [refreshTick]);

  // Màu sắc cho trạng thái voltage
  const voltageColor = (status) => {
    if (status === 'crit') return 'var(--accent-pink)';
    if (status === 'warn') return '#f0b429';
    return 'var(--accent-cyan)';
  };

  return (
    <div className="app-container">
      {/* Main Content Area */}
      <main className="main-content">
        <header className="top-header">
          <h1 className="title-glow">Server Dashboard</h1>
        </header>

        <div className="dashboard-grid">
          {/* Server Overview (Top Center) */}
          <section className="analytics-section">
            <div className="section-header">
              <h2>Server Overview</h2>
              <div className="filters">
                <button className="btn-cyan" onClick={handleRefresh}>Refresh</button>
              </div>
            </div>
            
            <div className="kpi-cards-grid">
              {/* CPU Card */}
              <div className="kpi-card glass-panel">
                <div className="kpi-header">
                  <span className="kpi-title">CPU Usage</span>
                  <div className="kpi-stats">
                    <span className="kpi-value">{cpuHistory[cpuHistory.length-1]?.value}%</span>
                    {temperature && temperature !== 'N/A' && <span className="kpi-sub" style={{color: 'var(--accent-pink)', marginLeft: '8px', fontSize: '1rem', fontWeight: 'bold'}}>{temperature}°C</span>}
                  </div>
                </div>
                <div className="kpi-chart">
                  <ResponsiveContainer width="100%" height={100}>
                    <AreaChart data={cpuHistory} margin={{ top: 5, right: 0, left: 0, bottom: 0 }}>
                      <defs>
                        <linearGradient id="colorCpu" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%"  stopColor="var(--accent-cyan)" stopOpacity={0.3}/>
                          <stop offset="95%" stopColor="var(--accent-cyan)" stopOpacity={0}/>
                        </linearGradient>
                      </defs>
                      <Tooltip cursor={{fill: 'transparent'}} contentStyle={{backgroundColor: 'var(--glass-bg)', borderColor: 'var(--glass-border)', color: '#fff'}} />
                      <Area type="monotone" dataKey="value" stroke="var(--accent-cyan)" fillOpacity={1} fill="url(#colorCpu)" strokeWidth={2} isAnimationActive={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* RAM Card */}
              <div className="kpi-card glass-panel" style={{ display: 'flex', flexDirection: 'column' }}>
                <div className="kpi-header">
                  <span className="kpi-title">RAM Usage</span>
                  <div className="kpi-stats">
                    <span className="kpi-value">{ramData.percent}%</span>
                    <span className="kpi-sub">{(ramData.used/1024).toFixed(1)}GB / {(ramData.total/1024).toFixed(1)}GB</span>
                  </div>
                </div>
                <div className="kpi-chart" style={{ flex: 1, minHeight: '80px' }}>
                  <ResponsiveContainer width="100%" height={90}>
                    <PieChart>
                      <Pie data={[{name: 'Used', value: ramData.percent, color: '#00f0ff'}, {name: 'Free', value: 100 - ramData.percent, color: 'rgba(255,255,255,0.05)'}]} innerRadius={30} outerRadius={40} paddingAngle={0} dataKey="value" stroke="none" startAngle={90} endAngle={-270}>
                        {[{color: '#00f0ff'}, {color: 'rgba(255,255,255,0.05)'}].map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip contentStyle={{backgroundColor: 'var(--glass-bg)', borderColor: 'var(--glass-border)', color: '#fff'}} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginTop: '5px', color: 'var(--text-secondary)' }}>
                  <div><span style={{color: '#00f0ff'}}>●</span> Cache: {(ramData.cached/1024).toFixed(1)}G</div>
                  <div><span style={{color: '#ff79c6'}}>●</span> Swap: {ramData.swapTotal > 0 ? `${(ramData.swapUsed/1024).toFixed(1)}G / ${(ramData.swapTotal/1024).toFixed(1)}G` : '0G / 0G'}</div>
                </div>
              </div>

              {/* Disks Card */}
              <div className="kpi-card glass-panel" style={{ overflowY: 'auto' }}>
                <div className="kpi-header" style={{ marginBottom: '10px' }}>
                  <span className="kpi-title">Disk Space</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '15px', zIndex: 1 }}>
                  {diskData.map((d, idx) => (
                    <div key={idx}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: '#fff', marginBottom: '5px' }}>
                        <span><HardDrive size={12} style={{marginRight: '5px', verticalAlign: 'middle'}}/>{d.mountPoint}</span>
                        <span style={{ color: 'var(--accent-purple)' }}>{d.usedStr} / {d.totalStr} ({d.percent}%)</span>
                      </div>
                      <div style={{ width: '100%', height: '8px', background: 'rgba(255,255,255,0.1)', borderRadius: '4px', overflow: 'hidden' }}>
                        <div style={{ width: `${d.percent}%`, height: '100%', background: 'linear-gradient(90deg, #9d4edd, #ff79c6)', borderRadius: '4px' }}></div>
                      </div>
                    </div>
                  ))}
                  {diskData.length === 0 && <span style={{color: 'var(--text-secondary)', fontSize: '0.85rem'}}>No disk info found</span>}
                </div>
              </div>

              {/* Network Card */}
              <div className="kpi-card glass-panel" style={{ display: 'flex', flexDirection: 'column' }}>
                <div className="kpi-header">
                  <span className="kpi-title">Network Traffic <span style={{fontSize: '0.75rem', color: 'var(--accent-purple)', fontWeight: 'normal', marginLeft: '5px'}}>{networkData.interfaceName || 'N/A'}</span></span>
                  <div className="kpi-stats" style={{ flexDirection: 'column', gap: '8px', alignItems: 'flex-start', marginTop: '15px' }}>
                    <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                      <Wifi size={18} color="#00f0ff" />
                      <span className="kpi-value" style={{ fontSize: '1.3rem' }}>{formatSpeed(networkData.rxSpeed)} <span style={{fontSize: '0.8rem', color:'var(--text-secondary)'}}>DN</span></span>
                    </div>
                    <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                      <Activity size={18} color="#ff79c6" />
                      <span className="kpi-value" style={{ fontSize: '1.3rem' }}>{formatSpeed(networkData.txSpeed)} <span style={{fontSize: '0.8rem', color:'var(--text-secondary)'}}>UP</span></span>
                    </div>
                  </div>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', marginTop: 'auto', paddingTop: '10px', color: 'var(--text-secondary)', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                  <div>Total DL: <strong style={{color: '#fff'}}>{formatBytes(networkData.totalRx)}</strong></div>
                  <div>Total UL: <strong style={{color: '#fff'}}>{formatBytes(networkData.totalTx)}</strong></div>
                </div>
              </div>

              {/* Voltage Card */}
              <div className="kpi-card glass-panel" style={{ display: 'flex', flexDirection: 'column' }}>
                <div className="kpi-header" style={{ marginBottom: '10px' }}>
                  <span className="kpi-title" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <Zap size={14} color="#f0b429" /> Voltage Rails
                  </span>
                </div>
                {voltageData.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', flex: 1, overflowY: 'auto' }}>
                    {voltageData.slice(0, 8).map((v, i) => (
                      <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.8rem' }}>
                        <span style={{ color: 'var(--text-secondary)', maxWidth: '60%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={v.label}>
                          {v.label}
                        </span>
                        <span style={{
                          color: voltageColor(v.status),
                          fontWeight: '700',
                          fontFamily: 'monospace',
                          fontSize: '0.85rem',
                          background: `${voltageColor(v.status)}18`,
                          padding: '2px 8px',
                          borderRadius: '8px',
                        }}>
                          {v.value} V
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', gap: '8px', color: 'var(--text-secondary)' }}>
                    <Zap size={28} color="rgba(255,255,255,0.15)" />
                    <span style={{ fontSize: '0.8rem' }}>N/A — sensors not found</span>
                  </div>
                )}
              </div>

            </div>
          </section>

          {/* Right Column */}
          <aside className="right-column">
            {/* Recent Activity */}
            <div className="glass-panel recent-activity">
              <div className="section-header">
                <h3>Recent Activity</h3>
                <MoreHorizontal size={16} />
              </div>
              <div className="activity-list">
                <div className="activity-item">
                  <Activity size={16} color="var(--accent-cyan)" />
                  <div className="act-info">
                    <p>Uptime check</p>
                    <small>{formattedSystem.uptime}</small>
                  </div>
                </div>
                <div className="activity-item">
                  <Activity size={16} color="var(--accent-pink)" />
                  <div className="act-info">
                    <p>SSH Connected</p>
                    <small>Just now</small>
                  </div>
                </div>
              </div>
            </div>

            {/* System Status Gauge */}
            <div className="glass-panel status-gauge" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <div className="section-header" style={{ width: '100%' }}>
                <h3>System Status</h3>
                <MoreHorizontal size={16} />
              </div>
              <div className="gauge-circle">
                <div className="gauge-inner">Online</div>
              </div>
              <div style={{ color: 'var(--text-secondary)', marginTop: '15px', textAlign: 'center', lineHeight: '1.5', fontSize: '0.8rem' }}>
                {system ? (
                  <>
                    <strong style={{ color: 'var(--accent-cyan)' }}>Uptime</strong><br />
                    {formattedSystem.uptime}
                    {formattedSystem.load && <><br /><span style={{fontSize: '0.75rem', opacity: 0.7}}>Load Average: {formattedSystem.load}</span></>}
                    {temperature && temperature !== 'N/A' && <><br /><span style={{fontSize: '0.85rem', color: 'var(--accent-pink)', fontWeight: 'bold', marginTop: '5px', display: 'inline-block'}}>Nhiệt độ: {temperature}°C</span></>}
                  </>
                ) : 'Fetching uptime...'}
              </div>
            </div>

            {/* Active Connections */}
            <div className="glass-panel team-members" style={{ marginBottom: '20px' }}>
              <div className="section-header">
                <h3>Active Connections</h3>
                <MoreHorizontal size={16} />
              </div>
              <div className="team-list">
                {connections.map((conn, idx) => (
                  <div className="team-item clickable" key={idx} onClick={() => setSelectedConnection(conn)}>
                    <div className="avatar" style={{background: 'var(--glass-border)'}}><User size={14}/></div>
                    <div className="team-info">
                      <p>{conn.user} <span style={{fontSize: '0.7rem', color: 'var(--accent-purple)'}}>({conn.terminal})</span></p>
                      <small>{conn.ip}</small>
                    </div>
                  </div>
                ))}
                {connections.length === 0 && <span style={{color: 'var(--text-secondary)', fontSize: '0.85rem'}}>No active connections</span>}
              </div>
            </div>

            {/* Server Info — live data */}
            <div className="glass-panel team-members clickable" onClick={() => setIsServerModalOpen(true)}>
              <div className="section-header">
                <h3>Server Info</h3>
                <MoreHorizontal size={16} />
              </div>
              <div className="team-list">
                <div className="team-item">
                  <div className="avatar"><Server size={14}/></div>
                  <div className="team-info">
                    <p>Hostname</p>
                    <small style={{ color: 'var(--accent-cyan)' }}>{sysInfo.hostname}</small>
                  </div>
                </div>
                <div className="team-item">
                  <div className="avatar"><Activity size={14}/></div>
                  <div className="team-info">
                    <p>OS</p>
                    <small>{sysInfo.os}</small>
                  </div>
                </div>
                <div className="team-item">
                  <div className="avatar"><Cpu size={14}/></div>
                  <div className="team-info">
                    <p>Kernel</p>
                    <small>{sysInfo.kernel}</small>
                  </div>
                </div>
              </div>
            </div>
          </aside>

          {/* Master Record Table */}
          <section className="glass-panel master-record">
            <div className="section-header">
              <h2>Master Record (Processes)</h2>
              <button className="btn-cyan" onClick={handleRefresh}>Refresh</button>
            </div>
            <div className="table-controls">
              <div className="search-bar glass-panel">
                <Search size={16} />
                {/* Debounce 300ms: tránh re-filter 100+ rows mỗi keystroke */}
                <input
                  type="text"
                  placeholder="Search..."
                  value={searchInput}
                  onChange={handleSearchChange}
                />
              </div>
            </div>

            <div style={{ maxHeight: '400px', overflowY: 'auto', paddingRight: '5px' }}>
              <table className="glass-table">
                <thead style={{ position: 'sticky', top: 0, background: '#ffffff', color: '#1c1c28', zIndex: 1, boxShadow: '0 2px 5px rgba(0,0,0,0.5)' }}>
                  <tr>
                    <th>PID</th>
                    <th>Name/Comm</th>
                    <th>User</th>
                    <th>Threads</th>
                    <th>CPU %</th>
                    <th>Memory</th>
                  </tr>
                </thead>
                <tbody>
                  {processes
                    .filter(p => !searchTerm || p.name.toLowerCase().includes(searchTerm.toLowerCase()) || p.user.toLowerCase().includes(searchTerm.toLowerCase()) || p.id.toString().includes(searchTerm))
                    .map(p => (
                    <tr key={p.id}>
                      <td>{p.id}</td>
                      <td>
                        <div style={{ fontWeight: '500' }}>{p.name}</div>
                        <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', maxWidth: '250px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={p.args}>{p.args}</div>
                      </td>
                      <td>{p.user}</td>
                      <td>{p.threads}</td>
                      <td><span className="status-badge" style={{color: 'var(--accent-cyan)'}}>{p.cpu}</span></td>
                      <td><span className="status-badge" style={{color: 'var(--accent-purple)'}}>{p.mem}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* Connection Modal */}
          {selectedConnection && (
            <div className="modal-overlay" onClick={() => setSelectedConnection(null)}>
              <div className="modal-content glass-panel" onClick={e => e.stopPropagation()}>
                <div className="section-header" style={{ marginBottom: '20px' }}>
                  <h3 style={{ margin: 0 }}>Chi tiết thiết bị truy cập</h3>
                  <button className="btn-close-modal" onClick={() => setSelectedConnection(null)}>X</button>
                </div>
                <div className="server-details-list">
                  <div className="detail-item"><strong>User:</strong> {selectedConnection.user}</div>
                  <div className="detail-item"><strong>IP Address:</strong> {selectedConnection.ip}</div>
                  <div className="detail-item"><strong>Terminal:</strong> {selectedConnection.terminal}</div>
                  <div className="detail-item"><strong>Login Time:</strong> {selectedConnection.loginTime}</div>
                </div>
              </div>
            </div>
          )}

          {/* Server Info Modal — enriched with all live data */}
          {isServerModalOpen && (
            <div className="modal-overlay" onClick={() => setIsServerModalOpen(false)}>
              <div className="modal-content glass-panel" style={{ width: '480px' }} onClick={e => e.stopPropagation()}>
                <div className="section-header" style={{ marginBottom: '20px' }}>
                  <h3 style={{ margin: 0 }}>Chi tiết Server</h3>
                  <button className="btn-close-modal" onClick={() => setIsServerModalOpen(false)}>X</button>
                </div>
                <div className="server-details-list">

                  {/* ── System Identity ── */}
                  <div className="detail-item"><strong>Hostname:</strong> <span style={{color:'var(--accent-cyan)'}}>{sysInfo.hostname}</span></div>
                  <div className="detail-item"><strong>OS:</strong> {sysInfo.os}</div>
                  <div className="detail-item"><strong>Kernel:</strong> {sysInfo.kernel}</div>
                  <div className="detail-item" style={{wordBreak:'break-all'}}><strong>CPU Model:</strong> {sysInfo.cpuModel}</div>

                  {/* ── Runtime ── */}
                  <div className="detail-item"><strong>Uptime:</strong> {system ? formattedSystem.uptime : 'Đang lấy dữ liệu...'}</div>
                  {formattedSystem.load && <div className="detail-item"><strong>Load Avg:</strong> {formattedSystem.load}</div>}
                  <div className="detail-item">
                    <strong>CPU Usage:</strong> {cpuHistory.length > 0 ? `${cpuHistory[cpuHistory.length - 1].value}%` : '0%'}
                    {temperature && temperature !== 'N/A' && <span style={{marginLeft: '10px', color: 'var(--accent-pink)', fontWeight: 'bold'}}>({temperature}°C)</span>}
                  </div>
                  <div className="detail-item">
                    <strong>RAM Usage:</strong> {ramData.percent}% ({(ramData.used/1024).toFixed(1)}GB / {(ramData.total/1024).toFixed(1)}GB)
                    <div style={{ marginTop: '5px', paddingLeft: '10px', fontSize: '0.85em', color: 'var(--text-secondary)' }}>
                      <div style={{ marginBottom: '3px' }}>- Cached: {(ramData.cached/1024).toFixed(1)} GB, Free: {(ramData.free/1024).toFixed(1)} GB</div>
                      <div>- Swap: {(ramData.swapUsed/1024).toFixed(1)} GB / {(ramData.swapTotal/1024).toFixed(1)} GB</div>
                    </div>
                  </div>
                  <div className="detail-item">
                    <strong>Disk Space:</strong>
                    <div style={{ marginTop: '5px', paddingLeft: '10px' }}>
                      {diskData.map((d, i) => (
                        <div key={i} style={{marginBottom: '5px'}}>- {d.mountPoint}: {d.usedStr} / {d.totalStr} ({d.percent}%)</div>
                      ))}
                    </div>
                  </div>
                  <div className="detail-item">
                    <strong>Network:</strong> {formatSpeed(networkData.rxSpeed)} Down / {formatSpeed(networkData.txSpeed)} Up
                    <div style={{ marginTop: '5px', paddingLeft: '10px', fontSize: '0.85em', color: 'var(--text-secondary)' }}>
                      <div style={{ marginBottom: '3px' }}>- Interface: <span style={{color: 'var(--accent-cyan)'}}>{networkData.interfaceName || 'N/A'}</span></div>
                      <div style={{ marginBottom: '3px' }}>- Total DL: {formatBytes(networkData.totalRx)}</div>
                      <div>- Total UL: {formatBytes(networkData.totalTx)}</div>
                    </div>
                  </div>

                  {/* ── Voltage Rails ── */}
                  <div className="detail-item">
                    <strong style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      <Zap size={14} color="#f0b429" /> Voltage
                    </strong>
                    {voltageData.length > 0 ? (
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px', paddingLeft: '10px' }}>
                        {voltageData.map((v, i) => (
                          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.82rem', background: 'rgba(255,255,255,0.03)', borderRadius: '6px', padding: '4px 8px' }}>
                            <span style={{ color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '55%' }} title={v.label}>{v.label}</span>
                            <span style={{ color: voltageColor(v.status), fontWeight: '700', fontFamily: 'monospace' }}>{v.value}V</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', paddingLeft: '10px' }}>N/A — sensors not installed</span>
                    )}
                  </div>

                </div>
              </div>
            </div>
          )}

        </div>
      </main>
    </div>
  );
}

export default App;
