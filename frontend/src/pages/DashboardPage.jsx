import React, { useState } from 'react';
import axios from 'axios';
import { useOutletContext } from 'react-router-dom';
import { AreaChart, Area, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import { Search, Zap, Server, Activity, HardDrive, Wifi } from 'lucide-react';
import { formatBytes, formatSpeed } from '../utils/parsers';

export default function DashboardPage() {
  const { 
    system, sysInfo, cpuHistory, ramData, diskData, 
    networkData, temperatureData, voltageData, fanData, diskIoData, gpuData, loadAvgData
  } = useOutletContext();
  const [fanMode, setFanMode] = useState('auto');
  const [fanSpeed, setFanSpeed] = useState(100);
  const [isChangingFan, setIsChangingFan] = useState(false);

  const currentFanRpm = fanData && fanData.length > 0 ? fanData[0].value : 0;
  const spinDuration = fanMode === 'manual' 
    ? `${Math.max(0.1, (105 - fanSpeed) * 0.015)}s` 
    : (currentFanRpm > 0 ? `${Math.max(0.1, (60 / currentFanRpm) * 20)}s` : '1s');

  const [toast, setToast] = useState(null);

  const triggerToast = (msg, isError = false) => {
    setToast({ message: msg, isError });
    setTimeout(() => setToast(null), 4000);
  };

  const handleFanChange = async (mode, speed) => {
    try {
      setIsChangingFan(true);
      setFanMode(mode);
      if (speed !== undefined) setFanSpeed(speed);
      await axios.post('/api/metrics/fan', { mode, speed: speed !== undefined ? speed : fanSpeed });
      triggerToast(`Fan HUD mode updated to ${mode.toUpperCase()}${speed !== undefined ? ` (${speed}%)` : ''}!`);
    } catch (e) {
      console.error(e);
      triggerToast('Error adjusting fan speed. Please try again.', true);
    } finally {
      setIsChangingFan(false);
    }
  };
  const getTemperatureColor = (val, max) => {
    if (val >= max * 0.9) return 'var(--accent-pink)';
    if (val >= max * 0.7) return '#f0b429';
    return 'var(--accent-cyan)';
  };

  const maxTemp = temperatureData && temperatureData.length > 0 
    ? Math.max(...temperatureData.map(t => parseFloat(t.value) || 0))
    : 0;

  const cpuTemps = (temperatureData || []).filter(t => /package|core|cpu|tdie|tctl/i.test(t.label));
  const sysTemps = (temperatureData || []).filter(t => !/package|core|cpu|tdie|tctl/i.test(t.label));
  const shouldSplitCards = cpuTemps.length > 0 && sysTemps.length > 0;

  const maxCpuTemp = cpuTemps.length > 0 ? Math.max(...cpuTemps.map(t => parseFloat(t.value) || 0)) : 0;
  const maxSysTemp = sysTemps.length > 0 ? Math.max(...sysTemps.map(t => parseFloat(t.value) || 0)) : 0;

  const renderThermalList = (sensorList) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', zIndex: 1, overflowY: 'auto', maxHeight: '160px', paddingRight: '4px' }}>
      {sensorList.map((t, idx) => {
        const valNum = parseFloat(t.value) || 0;
        const pct = Math.min(100, Math.max(0, (valNum / 100) * 100));
        const statusClass = valNum >= 80 ? 'critical' : valNum >= 65 ? 'warn' : 'normal';
        const badgeClass = valNum >= 80 ? 'crit' : valNum >= 65 ? 'warn' : 'ok';
        const badgeLabel = valNum >= 80 ? 'CRIT' : valNum >= 65 ? 'WARM' : 'OK';
        const valColor = valNum >= 80 ? 'var(--accent-pink)' : valNum >= 65 ? '#f0b429' : 'var(--accent-cyan)';

        return (
          <div key={`temp-${idx}`} className="sensor-row">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.75rem' }}>
              <span style={{ color: '#fff', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '120px' }} title={t.label}>
                {t.label}
              </span>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span className={`sensor-badge ${badgeClass}`}>{badgeLabel}</span>
                <span style={{ fontSize: '0.9rem', fontWeight: 'bold', color: valColor, fontFamily: 'Share Tech Mono' }}>
                  {valNum.toFixed(1)}°C
                </span>
              </div>
            </div>
            <div className="thermal-bar-bg">
              <div className={`thermal-bar-fill ${statusClass}`} style={{ width: `${pct}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );

  return (
    <main className="main-content">
      {toast && (
        <div style={{
          padding: '10px 16px',
          marginBottom: '15px',
          borderRadius: '4px',
          background: toast.isError ? 'rgba(255, 0, 85, 0.2)' : 'rgba(0, 243, 255, 0.2)',
          border: toast.isError ? '1px solid var(--accent-pink)' : '1px solid var(--accent-cyan)',
          color: toast.isError ? 'var(--accent-pink)' : 'var(--accent-cyan)',
          fontFamily: 'Share Tech Mono',
          fontSize: '0.85rem',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <span>⚡ {toast.message}</span>
          <button onClick={() => setToast(null)} style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', fontWeight: 'bold' }}>✕</button>
        </div>
      )}
      <div className="dashboard-grid">
        {/* Analytics Section */}
        <section className="analytics-section">
          <div className="section-header">
            <h2>Server Overview</h2>
          </div>

          <div className="kpi-cards-grid">
            {/* CPU Card */}
            <div className="kpi-card glass-panel">
              <div className="kpi-header">
                <span className="kpi-title">CPU Usage</span>
                <div className="kpi-stats">
                  <span className="kpi-value">{cpuHistory[cpuHistory.length-1]?.value}%</span>
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

            {/* Load Average Card */}
            <div className="kpi-card glass-panel" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
              <div className="kpi-header">
                <span className="kpi-title">Load Average</span>
                <div className="kpi-stats">
                  <span className="kpi-value" style={{ fontSize: '1.2rem', color: (loadAvgData?.m1 || 0) > 4.0 ? 'var(--accent-pink)' : 'var(--accent-cyan)' }}>
                    {loadAvgData?.m1 !== undefined ? loadAvgData.m1.toFixed(2) : '0.00'}
                  </span>
                  <span className="kpi-sub">1m load</span>
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', margin: '8px 0', textAlign: 'center' }}>
                <div style={{ background: 'rgba(0, 243, 255, 0.05)', border: '1px solid rgba(0, 243, 255, 0.2)', padding: '6px', borderRadius: '4px' }}>
                  <div style={{ fontSize: '0.65rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>1 MIN</div>
                  <div style={{ fontSize: '0.95rem', fontWeight: 'bold', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono' }}>{loadAvgData?.m1 !== undefined ? loadAvgData.m1.toFixed(2) : '0.00'}</div>
                </div>
                <div style={{ background: 'rgba(0, 243, 255, 0.05)', border: '1px solid rgba(0, 243, 255, 0.2)', padding: '6px', borderRadius: '4px' }}>
                  <div style={{ fontSize: '0.65rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>5 MIN</div>
                  <div style={{ fontSize: '0.95rem', fontWeight: 'bold', color: '#f0b429', fontFamily: 'Share Tech Mono' }}>{loadAvgData?.m5 !== undefined ? loadAvgData.m5.toFixed(2) : '0.00'}</div>
                </div>
                <div style={{ background: 'rgba(0, 243, 255, 0.05)', border: '1px solid rgba(0, 243, 255, 0.2)', padding: '6px', borderRadius: '4px' }}>
                  <div style={{ fontSize: '0.65rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>15 MIN</div>
                  <div style={{ fontSize: '0.95rem', fontWeight: 'bold', color: 'var(--accent-green)', fontFamily: 'Share Tech Mono' }}>{loadAvgData?.m15 !== undefined ? loadAvgData.m15.toFixed(2) : '0.00'}</div>
                </div>
              </div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono', display: 'flex', justifyContent: 'space-between' }}>
                <span>Status: {(loadAvgData?.m1 || 0) > 4 ? 'HIGH SATURATION' : 'OPTIMAL'}</span>
                <span>Task Queue</span>
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
                    <Tooltip contentStyle={{backgroundColor: 'var(--glass-bg)', borderColor: 'var(--glass-border)', color: '#fff'}} itemStyle={{color: '#fff'}} />
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
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', marginBottom: '5px', color: '#fff' }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 12H2"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/><line x1="6" y1="16" x2="6.01" y2="16"/><line x1="10" y1="16" x2="14" y2="16"/></svg>
                        {d.mountPoint}
                      </span>
                      <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>{d.usedStr} / {d.totalStr} ({d.percent}%)</span>
                    </div>
                    <div style={{ height: '6px', background: 'rgba(255,255,255,0.1)', borderRadius: '3px', overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${d.percent}%`, background: `linear-gradient(90deg, var(--accent-cyan), var(--accent-magenta))` }} />
                    </div>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 'auto', paddingTop: '15px', display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                <span>Read: <strong>{diskIoData?.readSpeed || '0 B/s'}</strong></span>
                <span>Write: <strong>{diskIoData?.writeSpeed || '0 B/s'}</strong></span>
              </div>
            </div>

            {/* Network Traffic */}
            <div className="kpi-card glass-panel">
              <div className="kpi-header">
                <span className="kpi-title">Network Traffic</span>
                <span className="kpi-sub" style={{color: 'var(--text-secondary)'}}>{networkData.interfaceName || 'N/A'}</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '15px', marginTop: '20px', zIndex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent-cyan)" strokeWidth="2"><path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></svg>
                  <div>
                    <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono' }}>{formatSpeed(networkData.rxSpeed)} <span style={{fontSize: '0.8rem', color: 'var(--text-secondary)'}}>DN</span></div>
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent-magenta)" strokeWidth="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
                  <div>
                    <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: 'var(--accent-magenta)', fontFamily: 'Share Tech Mono' }}>{formatSpeed(networkData.txSpeed)} <span style={{fontSize: '0.8rem', color: 'var(--text-secondary)'}}>UP</span></div>
                  </div>
                </div>
              </div>
              <div style={{ marginTop: 'auto', display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-secondary)', zIndex: 1, paddingTop: '15px' }}>
                <span>Total DL: <strong>{formatBytes(networkData.totalRx)}</strong></span>
                <span>Total UL: <strong>{formatBytes(networkData.totalTx)}</strong></span>
              </div>
            </div>

            {/* Thermal Sensors Section: Split into 2 cards if both CPU & System sensors exist */}
            {shouldSplitCards ? (
              <>
                {/* CPU Thermal Card */}
                <div className="kpi-card glass-panel" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                  <div className="kpi-header" style={{ marginBottom: '10px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span className="kpi-title">CPU THERMAL (°C)</span>
                    <span style={{ 
                      fontSize: '0.68rem', 
                      fontFamily: 'Share Tech Mono', 
                      padding: '2px 7px', 
                      border: `1px solid ${maxCpuTemp >= 80 ? 'var(--accent-pink)' : maxCpuTemp >= 65 ? '#f0b429' : 'var(--accent-cyan)'}`,
                      color: maxCpuTemp >= 80 ? 'var(--accent-pink)' : maxCpuTemp >= 65 ? '#f0b429' : 'var(--accent-cyan)',
                      background: 'rgba(0,0,0,0.3)',
                      letterSpacing: '0.5px'
                    }}>
                      MAX: {maxCpuTemp.toFixed(1)}°C
                    </span>
                  </div>
                  {renderThermalList(cpuTemps)}
                </div>

                {/* System Sensors Card */}
                <div className="kpi-card glass-panel" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                  <div className="kpi-header" style={{ marginBottom: '10px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span className="kpi-title">SYSTEM SENSORS (°C)</span>
                    <span style={{ 
                      fontSize: '0.68rem', 
                      fontFamily: 'Share Tech Mono', 
                      padding: '2px 7px', 
                      border: `1px solid ${maxSysTemp >= 80 ? 'var(--accent-pink)' : maxSysTemp >= 65 ? '#f0b429' : 'var(--accent-cyan)'}`,
                      color: maxSysTemp >= 80 ? 'var(--accent-pink)' : maxSysTemp >= 65 ? '#f0b429' : 'var(--accent-cyan)',
                      background: 'rgba(0,0,0,0.3)',
                      letterSpacing: '0.5px'
                    }}>
                      MAX: {maxSysTemp.toFixed(1)}°C
                    </span>
                  </div>
                  {renderThermalList(sysTemps)}
                </div>
              </>
            ) : (
              /* Single Combined Thermal Card fallback */
              <div className="kpi-card glass-panel" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                <div className="kpi-header" style={{ marginBottom: '10px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span className="kpi-title">THERMAL SENSORS (°C)</span>
                  {maxTemp > 0 && (
                    <span style={{ 
                      fontSize: '0.68rem', 
                      fontFamily: 'Share Tech Mono', 
                      padding: '2px 7px', 
                      border: `1px solid ${maxTemp >= 80 ? 'var(--accent-pink)' : maxTemp >= 65 ? '#f0b429' : 'var(--accent-cyan)'}`,
                      color: maxTemp >= 80 ? 'var(--accent-pink)' : maxTemp >= 65 ? '#f0b429' : 'var(--accent-cyan)',
                      background: 'rgba(0,0,0,0.3)',
                      letterSpacing: '0.5px'
                    }}>
                      MAX: {maxTemp.toFixed(1)}°C
                    </span>
                  )}
                </div>
                {temperatureData.length > 0 ? renderThermalList(temperatureData) : (
                  <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>N/A — no thermal sensors</span>
                )}
              </div>
            )}

            {/* Voltage & Power Rails Card */}
            <div className="kpi-card glass-panel" style={{ overflowY: 'auto', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
              <div className="kpi-header" style={{ marginBottom: '10px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="kpi-title">VOLTAGE & POWER (V)</span>
                <span style={{ fontSize: '0.68rem', fontFamily: 'Share Tech Mono', color: 'var(--accent-green)', letterSpacing: '0.5px' }}>
                  RAILS: {voltageData.length}
                </span>
              </div>

              {voltageData.length > 0 ? (
                voltageData.length <= 2 ? (
                  /* Single / Few Rail Voltmeter HUD Diagnostic View */
                  <div style={{ display: 'flex', flexDirection: 'column', flex: 1, justifyContent: 'space-between', zIndex: 1 }}>
                    {/* Sci-Fi Voltmeter Gauge */}
                    {(() => {
                      const primary = voltageData[0];
                      const valNum = parseFloat(primary.value) || 0;
                      const maxGauge = 15;
                      const pct = Math.min(100, Math.max(10, (valNum / maxGauge) * 100));
                      const dashOffset = 220 - (220 * pct) / 100;
                      const valColor = primary.status === 'crit' ? 'var(--accent-pink)' : primary.status === 'warn' ? '#f0b429' : 'var(--accent-green)';
                      const statusLabel = primary.status === 'crit' ? 'CRITICAL' : primary.status === 'warn' ? 'WARNING' : 'STABLE';

                      return (
                        <>
                          <div className="voltage-hud-container">
                            <div className="voltage-dial-wrapper">
                              <div className="voltage-dial-outer"></div>
                              <svg viewBox="0 0 100 100" width="100%" height="100%" style={{ transform: 'rotate(-90deg)', zIndex: 1 }}>
                                <circle cx="50" cy="50" r="35" fill="none" stroke="rgba(0, 255, 102, 0.12)" strokeWidth="6" />
                                <circle 
                                  cx="50" cy="50" r="35" 
                                  fill="none" 
                                  stroke={valColor} 
                                  strokeWidth="6" 
                                  strokeDasharray="220" 
                                  strokeDashoffset={dashOffset} 
                                  strokeLinecap="round"
                                  style={{ transition: 'stroke-dashoffset 0.8s ease' }}
                                />
                              </svg>
                              <div className="voltage-dial-center">
                                <span style={{ fontSize: '0.5rem', color: 'var(--text-secondary)', letterSpacing: '0.5px', fontFamily: 'Share Tech Mono' }}>
                                  {primary.label}
                                </span>
                                <span style={{ fontSize: '1.05rem', fontWeight: 'bold', fontFamily: 'Share Tech Mono', color: '#ffffff', textShadow: `0 0 8px ${valColor}`, lineHeight: 1.1 }}>
                                  {valNum.toFixed(2)}
                                </span>
                                <span style={{ fontSize: '0.55rem', color: valColor, fontWeight: 'bold', letterSpacing: '1px' }}>
                                  VOLTS
                                </span>
                              </div>
                            </div>
                          </div>

                          {/* Diagnostics Info Grid */}
                          <div className="voltage-stats-grid">
                            <div className="voltage-stat-box">
                              <span style={{ fontSize: '0.6rem', color: 'var(--text-secondary)', letterSpacing: '0.5px' }}>SIGNAL</span>
                              <span style={{ fontSize: '0.78rem', fontWeight: 'bold', fontFamily: 'Share Tech Mono', color: valColor }}>
                                {statusLabel}
                              </span>
                            </div>
                            <div className="voltage-stat-box">
                              <span style={{ fontSize: '0.6rem', color: 'var(--text-secondary)', letterSpacing: '0.5px' }}>STABILITY</span>
                              <span style={{ fontSize: '0.78rem', fontWeight: 'bold', fontFamily: 'Share Tech Mono', color: 'var(--accent-cyan)' }}>
                                99.8% OPT
                              </span>
                            </div>
                          </div>

                          {/* Primary Rail Detail Item */}
                          <div className="sensor-row" style={{ marginTop: '8px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.75rem' }}>
                              <span style={{ color: '#fff', fontWeight: 600 }}>{primary.label}</span>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <span className={`sensor-badge ${primary.status === 'crit' ? 'crit' : primary.status === 'warn' ? 'warn' : 'ok'}`}>
                                  {primary.status === 'crit' ? 'CRIT' : primary.status === 'warn' ? 'WARN' : 'STABLE'}
                                </span>
                                <span style={{ fontSize: '0.85rem', fontWeight: 'bold', color: valColor, fontFamily: 'Share Tech Mono' }}>
                                  {valNum.toFixed(3)} V
                                </span>
                              </div>
                            </div>
                            <div className="thermal-bar-bg">
                              <div style={{ height: '100%', width: '100%', background: `linear-gradient(90deg, rgba(0,255,102,0.15) 0%, ${valColor} 100%)`, borderRadius: '3px' }} />
                            </div>
                          </div>
                        </>
                      );
                    })()}
                  </div>
                ) : (
                  /* Multi-Rail List View */
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', zIndex: 1 }}>
                    {voltageData.map((v, idx) => {
                      const valNum = parseFloat(v.value) || 0;
                      const statusClass = v.status === 'crit' ? 'crit' : v.status === 'warn' ? 'warn' : 'ok';
                      const badgeLabel = v.status === 'crit' ? 'CRIT' : v.status === 'warn' ? 'WARN' : 'STABLE';
                      const valColor = v.status === 'crit' ? 'var(--accent-pink)' : v.status === 'warn' ? '#f0b429' : 'var(--accent-green)';

                      return (
                        <div key={`volt-${idx}`} className="sensor-row">
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.75rem' }}>
                            <span style={{ color: '#fff', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '120px' }} title={v.label}>
                              {v.label}
                            </span>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                              <span className={`sensor-badge ${statusClass}`}>{badgeLabel}</span>
                              <span style={{ fontSize: '0.9rem', fontWeight: 'bold', color: valColor, fontFamily: 'Share Tech Mono' }}>
                                {valNum.toFixed(3)} V
                              </span>
                            </div>
                          </div>
                          <div className="thermal-bar-bg">
                            <div style={{ height: '100%', width: '100%', background: `linear-gradient(90deg, rgba(0,255,102,0.15) 0%, ${valColor} 100%)`, borderRadius: '3px' }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )
              ) : (
                <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>N/A — no voltage sensors</span>
              )}
            </div>

            {/* Fan Control & Override Card (Spans 2 columns) */}
            <div className="kpi-card glass-panel" style={{ gridColumn: 'span 2', display: 'flex', flexDirection: 'column', minWidth: '360px' }}>
              <div className="kpi-header" style={{ marginBottom: '10px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="kpi-title">FAN CONTROL & THERMAL OVERRIDE</span>
                <span style={{ fontSize: '0.7rem', color: 'var(--accent-green)', letterSpacing: '1px', fontFamily: 'Share Tech Mono', background: 'rgba(0, 255, 102, 0.1)', padding: '2px 6px', border: '1px solid var(--accent-green)' }}>
                  SYS_STATUS: ACTIVE
                </span>
              </div>

              <div style={{ display: 'flex', flex: 1, alignItems: 'center', gap: '20px', flexWrap: 'wrap', padding: '5px 0' }}>
                {/* Left Column: Sci-Fi Fan Hologram HUD Widget */}
                <div className="fan-hud-container" style={{ margin: '0 auto', flexShrink: 0 }}>
                  <div className="fan-hud-outer-ring"></div>
                  <div className="fan-hud-inner-ring"></div>
                  <div className="fan-blades-wrapper" style={{ '--spin-duration': spinDuration }}>
                    <svg viewBox="0 0 100 100" width="100%" height="100%">
                      <defs>
                        <linearGradient id="bladeGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                          <stop offset="0%" stopColor="var(--accent-cyan)" stopOpacity="0.95" />
                          <stop offset="100%" stopColor="var(--accent-magenta)" stopOpacity="0.4" />
                        </linearGradient>
                      </defs>
                      <circle cx="50" cy="50" r="28" fill="none" stroke="rgba(0, 243, 255, 0.3)" strokeWidth="1" strokeDasharray="3 3" />
                      {/* 4 Sci-Fi Fan Blades */}
                      <path d="M 50 50 L 44 4 C 60 0, 72 16, 54 50 Z" fill="url(#bladeGrad)" stroke="var(--accent-cyan)" strokeWidth="0.5" />
                      <path d="M 50 50 L 96 44 C 100 60, 84 72, 50 54 Z" fill="url(#bladeGrad)" stroke="var(--accent-cyan)" strokeWidth="0.5" />
                      <path d="M 50 50 L 56 96 C 40 100, 28 84, 46 50 Z" fill="url(#bladeGrad)" stroke="var(--accent-cyan)" strokeWidth="0.5" />
                      <path d="M 50 50 L 4 56 C 0 40, 16 28, 50 46 Z" fill="url(#bladeGrad)" stroke="var(--accent-cyan)" strokeWidth="0.5" />
                    </svg>
                  </div>
                  {/* High-Contrast Sci-Fi Center Core Readout */}
                  <div className="fan-hud-center-core">
                    <span style={{ fontSize: '0.52rem', color: 'var(--accent-cyan)', opacity: 0.85, letterSpacing: '1px', textTransform: 'uppercase', marginBottom: '-2px', fontFamily: 'Share Tech Mono' }}>
                      SYS_FAN
                    </span>
                    <span style={{ fontSize: '1.25rem', fontWeight: 'bold', fontFamily: 'Share Tech Mono', color: '#ffffff', textShadow: '0 0 10px rgba(0, 243, 255, 0.7)', lineHeight: 1.15 }}>
                      {currentFanRpm ? `${currentFanRpm}` : `${fanSpeed}%`}
                    </span>
                    <span style={{ fontSize: '0.62rem', color: 'var(--accent-cyan)', fontWeight: '600', textTransform: 'uppercase', letterSpacing: '1.5px', marginTop: '1px' }}>
                      {currentFanRpm ? 'RPM' : 'SPEED'}
                    </span>
                  </div>
                </div>

                {/* Right Column: Tactical Controls */}
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '15px', minWidth: '180px' }}>
                  {/* Mode Selector */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', letterSpacing: '1px' }}>CONTROL MODE</span>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button 
                        className={`btn-cyan ${fanMode === 'auto' ? 'active' : ''}`}
                        onClick={() => handleFanChange('auto')}
                        disabled={isChangingFan}
                        style={{ fontSize: '0.75rem', padding: '4px 12px' }}
                      >AUTO-SYNC</button>
                      <button 
                        className={`btn-pink ${fanMode === 'manual' ? 'active' : ''}`}
                        onClick={() => handleFanChange('manual')}
                        disabled={isChangingFan}
                        style={{ fontSize: '0.75rem', padding: '4px 12px' }}
                      >OVERRIDE</button>
                    </div>
                  </div>

                  {/* Speed Slider */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', opacity: fanMode === 'manual' ? 1 : 0.3, pointerEvents: fanMode === 'manual' ? 'auto' : 'none', transition: 'opacity 0.3s' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                      <span>MANUAL TARGET</span>
                      <span style={{ fontWeight: 'bold', fontFamily: 'Share Tech Mono', color: 'var(--accent-magenta)' }}>{fanSpeed}%</span>
                    </div>
                    <input 
                      type="range" 
                      min="0" max="100" 
                      value={fanSpeed} 
                      className="sci-fi-slider"
                      onChange={(e) => setFanSpeed(parseInt(e.target.value))}
                      onMouseUp={(e) => handleFanChange('manual', parseInt(e.target.value))}
                      onTouchEnd={(e) => handleFanChange('manual', parseInt(e.target.value))}
                      style={{ '--val': `${fanSpeed}%` }} 
                    />
                  </div>

                  {/* Status Bar */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-secondary)', borderTop: '1px dashed rgba(255,255,255,0.1)', paddingTop: '8px', fontFamily: 'Share Tech Mono' }}>
                    <span>DRIVER: <strong style={{ color: 'var(--accent-cyan)' }}>DELL_SMM</strong></span>
                    <span>SAFEGUARD: <strong style={{ color: 'var(--accent-green)' }}>ACTIVE</strong></span>
                  </div>
                </div>
              </div>
            </div>

            {/* GPU Card (Dynamic) */}
            {gpuData.length > 0 && gpuData.map((gpu, idx) => (
              <div key={`gpu-${idx}`} className="kpi-card glass-panel" style={{ display: 'flex', flexDirection: 'column' }}>
                <div className="kpi-header">
                  <span className="kpi-title" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={gpu.name}>GPU: {gpu.name.replace('NVIDIA ', '')}</span>
                  <div className="kpi-stats">
                    <span className="kpi-value">{gpu.utilPercent}%</span>
                  </div>
                </div>
                <div style={{ marginTop: '15px', display: 'flex', flexDirection: 'column', gap: '10px', zIndex: 1 }}>
                  <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', marginBottom: '5px', color: '#fff' }}>
                      <span>VRAM</span>
                      <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>{(gpu.memUsed/1024).toFixed(1)}G / {(gpu.memTotal/1024).toFixed(1)}G ({gpu.memPercent}%)</span>
                    </div>
                    <div style={{ height: '6px', background: 'rgba(255,255,255,0.1)', borderRadius: '3px', overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${gpu.memPercent}%`, background: `linear-gradient(90deg, #a8ff78, #78ffd6)` }} />
                    </div>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '10px' }}>
                     <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Core Temp</span>
                     <span style={{ fontSize: '1.2rem', fontWeight: 'bold', color: getTemperatureColor(gpu.temp, 85), fontFamily: 'Share Tech Mono' }}>{gpu.temp}°C</span>
                  </div>
                </div>
              </div>
            ))}

          </div>
        </section>

        {/* Right Column */}
        <aside className="right-column">
          {/* Radar Status Gauge */}
          <section className="glass-panel status-gauge">
            <div className="section-header">
              <h3>System Status</h3>
            </div>
            <div className="gauge-circle" style={{ animation: 'pulse 2s infinite' }}>
              <div className="gauge-inner">Online</div>
            </div>
            <div style={{ textAlign: 'center', marginTop: '10px' }}>
              <div style={{ color: 'var(--accent-cyan)', fontWeight: 'bold', fontSize: '0.9rem' }}>Uptime</div>
              <div style={{ color: '#fff', fontSize: '0.85rem', marginTop: '5px' }}>{system ? system.split('load average')[0].trim().replace(/,\s*$/, "") : 'Loading...'}</div>
            </div>
            <div style={{ textAlign: 'center', marginTop: '15px' }}>
              <div style={{ color: 'var(--accent-magenta)', fontWeight: 'bold', fontSize: '0.85rem', marginBottom: '8px' }}>Load Average</div>
              <div style={{ display: 'flex', justifyContent: 'center', gap: '8px' }}>
                <div style={{ background: 'rgba(255,255,255,0.05)', padding: '5px 12px', borderRadius: '4px', textAlign: 'center', border: '1px solid rgba(255,255,255,0.1)' }}>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>1m</div>
                  <div style={{ color: '#fff', fontSize: '1rem', fontFamily: 'Share Tech Mono', marginTop: '2px' }}>{loadAvgData.m1}</div>
                </div>
                <div style={{ background: 'rgba(255,255,255,0.05)', padding: '5px 12px', borderRadius: '4px', textAlign: 'center', border: '1px solid rgba(255,255,255,0.1)' }}>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>5m</div>
                  <div style={{ color: '#fff', fontSize: '1rem', fontFamily: 'Share Tech Mono', marginTop: '2px' }}>{loadAvgData.m5}</div>
                </div>
                <div style={{ background: 'rgba(255,255,255,0.05)', padding: '5px 12px', borderRadius: '4px', textAlign: 'center', border: '1px solid rgba(255,255,255,0.1)' }}>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>15m</div>
                  <div style={{ color: '#fff', fontSize: '1rem', fontFamily: 'Share Tech Mono', marginTop: '2px' }}>{loadAvgData.m15}</div>
                </div>
              </div>
            </div>
          </section>

          {/* Server Info Box */}
          <section className="glass-panel team-members">
            <div className="section-header">
              <h3>Server Info</h3>
            </div>
            <div className="server-details-list">
              <div className="detail-item" style={{display: 'flex', gap: '15px'}}>
                <div className="avatar"><Server size={18} color="var(--accent-cyan)" /></div>
                <div>
                  <div style={{color: '#fff'}}>Hostname</div>
                  <div style={{color: 'var(--accent-cyan)', fontSize: '0.85rem'}}>{sysInfo.hostname}</div>
                </div>
              </div>
              <div className="detail-item" style={{display: 'flex', gap: '15px'}}>
                <div className="avatar"><Activity size={18} color="var(--accent-cyan)" /></div>
                <div>
                  <div style={{color: '#fff'}}>OS</div>
                  <div style={{color: 'var(--text-secondary)', fontSize: '0.85rem'}}>{sysInfo.os}</div>
                </div>
              </div>
              <div className="detail-item" style={{display: 'flex', gap: '15px'}}>
                <div className="avatar"><Zap size={18} color="var(--accent-cyan)" /></div>
                <div>
                  <div style={{color: '#fff'}}>Kernel</div>
                  <div style={{color: 'var(--text-secondary)', fontSize: '0.85rem'}}>{sysInfo.kernel}</div>
                </div>
              </div>
            </div>
          </section>
        </aside>
      </div>
    </main>
  );
}