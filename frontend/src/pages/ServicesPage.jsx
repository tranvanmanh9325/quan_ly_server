import React, { useState, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import axios from 'axios';
import { 
  SciFiShieldIcon, SciFiContainerIcon, SciFiChronoIcon, SciFiQuantumIcon,
  SciFiTerminalIcon, SciFiRefreshIcon, SciFiStopIcon, SciFiPlayIcon, SciFiChronoSpinnerIcon,
  SciFiEnergyBoltIcon, SciFiCloseIcon, SciFiCpuChipIcon, SciFiRamMemoryIcon,
  SciFiNetworkPortIcon, SciFiImageLayerIcon, SciFiExternalLinkIcon, SciFiWarningIcon
} from '../components/SciFiIcons';
import { parseDockerStats, formatDockerStatus, formatDockerPorts } from '../utils/parsers';
import LogViewer from '../components/LogViewer';

/**
 * Reformat systemd timer date strings returned by the backend.
 *
 * Input variants:
 *   - "Wed 2026-08-12 06:30:00 +07"  -> "Wed 12/08/2026 06:30:00 +07"
 *   - "2026-08-11"                    -> "11/08/2026"
 *   - "N/A" or empty                 -> unchanged
 */
function formatTimerDate(raw) {
  if (!raw || raw === 'N/A') return raw;
  // Optional "Weekday " prefix, then yyyy-MM-dd, then optional time + tz suffix
  const m = raw.match(/^([A-Za-z]{2,3}\s+)?(\d{4})-(\d{2})-(\d{2})(\s+.*)?$/);
  if (!m) return raw;
  const prefix   = m[1] || '';   // e.g. "Wed "
  const yyyy     = m[2];
  const mm       = m[3];
  const dd       = m[4];
  const timePart = m[5] || '';   // e.g. " 06:30:00 +07"
  return `${prefix}${dd}/${mm}/${yyyy}${timePart}`;
}


export default function ServicesPage() {
  const { dockerData } = useOutletContext();
  const [services, setServices] = useState([]);
  const [timers, setTimers] = useState([]);
  const [runtimes, setRuntimes] = useState({});
  const [dockerStats, setDockerStats] = useState({});
  const [loading, setLoading] = useState(true);
  
  // Search & Filter States
  const [serviceSearch, setServiceSearch] = useState('');
  const [serviceFilter, setServiceFilter] = useState('ALL');
  
  const [dockerSearch, setDockerSearch] = useState('');
  const [dockerFilter, setDockerFilter] = useState('ALL');

  // Action status toast
  const [actionMessage, setActionMessage] = useState(null);
  const [actionLoading, setActionLoading] = useState({});

  // Container Log Modal States
  const [logContainer, setLogContainer] = useState(null);
  const [logLinesCount, setLogLinesCount] = useState(100);
  const [logContent, setLogContent] = useState('');
  const [isLogsLoading, setIsLogsLoading] = useState(false);

  const fetchContainerLogs = async (containerId, lines = 100) => {
    setIsLogsLoading(true);
    try {
      const res = await axios.get(`/api/metrics/docker/logs?containerId=${encodeURIComponent(containerId)}&lines=${lines}`);
      if (res.data && res.data.data) {
        setLogContent(res.data.data);
      } else {
        setLogContent('No logs returned or error fetching logs.');
      }
    } catch (e) {
      setLogContent(`Failed to fetch logs: ${e.message}`);
    } finally {
      setIsLogsLoading(false);
    }
  };

  const openContainerLogs = (id, name) => {
    setLogContainer({ id, name });
    fetchContainerLogs(id, logLinesCount);
  };

  const refreshServicesData = async () => {
    try {
      const [svcRes, timerRes, runRes, statsRes] = await Promise.all([
        axios.get('/api/metrics/services'),
        axios.get('/api/metrics/timers'),
        axios.get('/api/metrics/runtimes'),
        axios.get('/api/metrics/docker/stats').catch(() => ({ data: { data: '' } }))
      ]);

      if (svcRes.data && svcRes.data.data) {
        const lines = svcRes.data.data.trim().split('\n');
        const parsed = lines.map(line => {
          const parts = line.split('|');
          return {
            name: parts[0] || 'Unknown',
            status: parts[1] || 'Unknown',
            subStatus: parts[2] || 'Unknown'
          };
        }).filter(s => s.name !== 'Unknown' && s.name !== '' && s.name !== '●');
        setServices(parsed);
      }

      if (timerRes.data && timerRes.data.data) {
        const lines = timerRes.data.data.trim().split('\n');
        const parsedTimers = lines.map(line => {
          const parts = line.split('|');
          return {
            unit: parts[0] || 'N/A',
            next: parts[1] || 'N/A',
            left: parts[2] || 'N/A',
            activates: parts[3] || 'N/A'
          };
        }).filter(t => t.unit !== 'N/A' && t.unit !== '');
        setTimers(parsedTimers);
      }

      if (runRes.data && runRes.data.data) {
        setRuntimes(runRes.data.data);
      }

      if (statsRes && statsRes.data && statsRes.data.data) {
        setDockerStats(parseDockerStats(statsRes.data.data));
      }
    } catch (e) {
      console.error("Error fetching services page data", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let isMounted = true;
    const initialLoad = async () => {
      await refreshServicesData();
    };

    initialLoad();
    const interval = setInterval(() => {
      if (isMounted) refreshServicesData();
    }, 15000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  const triggerToast = (msg, isError = false) => {
    setActionMessage({ text: msg, isError });
    setTimeout(() => setActionMessage(null), 4000);
  };

  const handleServiceControl = async (serviceName, action) => {
    const key = `svc-${serviceName}-${action}`;
    setActionLoading(prev => ({ ...prev, [key]: true }));
    try {
      const res = await axios.post(`/api/metrics/services/control?serviceName=${encodeURIComponent(serviceName)}&action=${action}`);
      if (res.data && res.data.status === 'success') {
        triggerToast(`Systemd [${serviceName}] ${action.toUpperCase()} command executed successfully!`);
        refreshServicesData();
      } else {
        triggerToast(`Failed to ${action} ${serviceName}: ${res.data?.message || 'Error'}`, true);
      }
    } catch (err) {
      triggerToast(`Execution error on ${serviceName}: ${err.message}`, true);
    } finally {
      setActionLoading(prev => ({ ...prev, [key]: false }));
    }
  };

  const handleDockerControl = async (containerId, containerName, action) => {
    const key = `doc-${containerId}-${action}`;
    setActionLoading(prev => ({ ...prev, [key]: true }));
    try {
      const res = await axios.post(`/api/metrics/docker/control?containerId=${encodeURIComponent(containerId)}&action=${action}`);
      if (res.data && res.data.status === 'success') {
        triggerToast(`Docker Container [${containerName}] ${action.toUpperCase()} command executed successfully!`);
      } else {
        triggerToast(`Failed to ${action} container ${containerName}: ${res.data?.message || 'Error'}`, true);
      }
    } catch (err) {
      triggerToast(`Execution error on container ${containerName}: ${err.message}`, true);
    } finally {
      setActionLoading(prev => ({ ...prev, [key]: false }));
    }
  };

  // Filtered Systemd Services
  const filteredServices = services.filter(s => {
    const matchSearch = s.name.toLowerCase().includes(serviceSearch.toLowerCase());
    if (serviceFilter === 'RUNNING') return matchSearch && s.status.toLowerCase() === 'active';
    if (serviceFilter === 'FAILED') return matchSearch && (s.status.toLowerCase() === 'failed' || s.subStatus.toLowerCase() === 'failed');
    return matchSearch;
  });

  const svcRunningCount = services.filter(s => s.status.toLowerCase() === 'active').length;
  const svcFailedCount = services.filter(s => s.status.toLowerCase() === 'failed' || s.subStatus.toLowerCase() === 'failed').length;

  // Filtered Docker Containers
  const containers = dockerData.data || [];
  const filteredContainers = containers.filter(c => {
    const matchSearch = (c.name || '').toLowerCase().includes(dockerSearch.toLowerCase()) ||
                        (c.image || '').toLowerCase().includes(dockerSearch.toLowerCase());
    if (dockerFilter === 'UP') return matchSearch && (c.status || '').startsWith('Up');
    if (dockerFilter === 'EXITED') return matchSearch && !(c.status || '').startsWith('Up');
    return matchSearch;
  });

  const docUpCount = containers.filter(c => (c.status || '').startsWith('Up')).length;
  const docExitedCount = containers.filter(c => !(c.status || '').startsWith('Up')).length;

  return (
    <main className="main-content" style={{ overflowY: 'auto', overflowX: 'hidden', display: 'flex', flexDirection: 'column', gap: '20px', minWidth: 0 }}>
      
      {/* Action Toast Alert */}
      {actionMessage && (        <div style={{
          padding: '10px 16px',
          marginBottom: '20px',
          background: actionMessage.isError ? 'rgba(255, 0, 85, 0.2)' : 'rgba(0, 243, 255, 0.2)',
          border: actionMessage.isError ? '1px solid var(--accent-pink)' : '1px solid var(--accent-cyan)',
          color: actionMessage.isError ? 'var(--accent-pink)' : 'var(--accent-cyan)',
          fontFamily: 'Share Tech Mono',
          fontSize: '0.85rem',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
            <SciFiEnergyBoltIcon size={14} color="currentColor" />
            <span>{actionMessage.text}</span>
          </span>
          <button 
            onClick={() => setActionMessage(null)}
            style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', display: 'inline-flex', alignItems: 'center' }}
            title="Dismiss"
          >
            <SciFiCloseIcon size={12} color="inherit" />
          </button>
        </div>
      )}

      {/* TOP ROW: Systemd Services & Docker Containers */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: '20px', minWidth: 0 }}>
        
        {/* Panel 1: Systemd Services */}
        <section className="glass-panel" style={{ display: 'flex', flexDirection: 'column', height: '380px', minWidth: 0 }}>
          <div className="section-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
            <h2 style={{ margin: 0, fontSize: '1rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <SciFiShieldIcon size={20} color="var(--accent-cyan)" /> System Services (Systemd)
            </h2>
            <div style={{ display: 'flex', gap: '6px' }}>
              <span style={{ fontSize: '0.7rem', fontFamily: 'Share Tech Mono', color: 'var(--accent-cyan)', background: 'rgba(0, 243, 255, 0.08)', padding: '2px 6px', border: '1px solid rgba(0, 243, 255, 0.3)' }}>
                TOTAL: {services.length}
              </span>
              <span style={{ fontSize: '0.7rem', fontFamily: 'Share Tech Mono', color: 'var(--accent-green)', background: 'rgba(0, 255, 157, 0.08)', padding: '2px 6px', border: '1px solid rgba(0, 255, 157, 0.3)' }}>
                ACTIVE: {svcRunningCount}
              </span>
              {svcFailedCount > 0 && (
                <span style={{ fontSize: '0.7rem', fontFamily: 'Share Tech Mono', color: 'var(--accent-pink)', background: 'rgba(255, 0, 85, 0.08)', padding: '2px 6px', border: '1px solid rgba(255, 0, 85, 0.3)' }}>
                  FAILED: {svcFailedCount}
                </span>
              )}
            </div>
          </div>

          <div style={{ display: 'flex', gap: '10px', marginBottom: '10px' }}>
            <input
              type="text"
              placeholder="Search services..."
              value={serviceSearch}
              onChange={e => setServiceSearch(e.target.value)}
              style={{
                flex: 1,
                background: 'rgba(0,0,0,0.4)',
                border: '1px solid rgba(0,243,255,0.2)',
                color: '#fff',
                padding: '4px 8px',
                fontSize: '0.75rem',
                fontFamily: 'Share Tech Mono',
                borderRadius: '3px'
              }}
            />
            <div style={{ display: 'flex', gap: '2px', background: 'rgba(0,0,0,0.4)', padding: '2px', borderRadius: '3px' }}>
              {['ALL', 'RUNNING', 'FAILED'].map(f => (
                <button
                  key={f}
                  onClick={() => setServiceFilter(f)}
                  style={{
                    background: serviceFilter === f ? 'var(--accent-cyan)' : 'transparent',
                    color: serviceFilter === f ? '#000' : 'var(--text-secondary)',
                    border: 'none',
                    padding: '2px 6px',
                    fontSize: '0.65rem',
                    fontFamily: 'Share Tech Mono',
                    cursor: 'pointer',
                    fontWeight: 'bold',
                    borderRadius: '2px'
                  }}
                >
                  {f}
                </button>
              ))}
            </div>
          </div>

          <div style={{ overflow: 'auto', flex: 1, paddingRight: '6px', minWidth: 0 }}>
            {loading ? <div style={{color: 'var(--text-secondary)'}}>Loading services...</div> : (
              <table className="glass-table" style={{width: '100%', fontSize: '0.75rem', tableLayout: 'fixed'}}>
                <thead>
                  <tr>
                    <th style={{ width: '42%' }}>Service Unit</th>
                    <th style={{ width: '20%' }}>Status</th>
                    <th style={{ width: '16%' }}>Sub</th>
                    <th style={{ width: '22%', textAlign: 'right' }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredServices.map((s, i) => {
                    const isRunning = s.status.toLowerCase() === 'active';
                    return (
                      <tr key={i}>
                        <td style={{fontWeight: 'bold', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}} title={s.name}>{s.name}</td>
                        <td style={{color: isRunning ? 'var(--accent-green)' : 'var(--accent-pink)', fontWeight: 'bold', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>
                          {s.status.toUpperCase()}
                        </td>
                        <td style={{color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>{s.subStatus}</td>
                        <td style={{ textAlign: 'right' }}>
                          <div style={{ display: 'flex', gap: '4px', justifyContent: 'flex-end' }}>
                            <button
                              onClick={() => handleServiceControl(s.name, 'restart')}
                              disabled={actionLoading[`svc-${s.name}-restart`]}
                              style={{
                                background: 'rgba(0, 243, 255, 0.1)',
                                border: '1px solid var(--accent-cyan)',
                                color: 'var(--accent-cyan)',
                                padding: '1px 5px',
                                fontSize: '0.6rem',
                                cursor: 'pointer',
                                fontFamily: 'Share Tech Mono'
                              }}
                              title="Restart Service"
                            >
                              {actionLoading[`svc-${s.name}-restart`] ? '...' : 'RESTART'}
                            </button>
                            {isRunning ? (
                              <button
                                onClick={() => handleServiceControl(s.name, 'stop')}
                                disabled={actionLoading[`svc-${s.name}-stop`]}
                                style={{
                                  background: 'rgba(255, 0, 85, 0.1)',
                                  border: '1px solid var(--accent-pink)',
                                  color: 'var(--accent-pink)',
                                  padding: '1px 5px',
                                  fontSize: '0.6rem',
                                  cursor: 'pointer',
                                  fontFamily: 'Share Tech Mono'
                                }}
                                title="Stop Service"
                              >
                                {actionLoading[`svc-${s.name}-stop`] ? '...' : 'STOP'}
                              </button>
                            ) : (
                              <button
                                onClick={() => handleServiceControl(s.name, 'start')}
                                disabled={actionLoading[`svc-${s.name}-start`]}
                                style={{
                                  background: 'rgba(0, 255, 157, 0.1)',
                                  border: '1px solid var(--accent-green)',
                                  color: 'var(--accent-green)',
                                  padding: '1px 5px',
                                  fontSize: '0.6rem',
                                  cursor: 'pointer',
                                  fontFamily: 'Share Tech Mono'
                                }}
                                title="Start Service"
                              >
                                {actionLoading[`svc-${s.name}-start`] ? '...' : 'START'}
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                  {filteredServices.length === 0 && (
                    <tr><td colSpan="4" style={{textAlign: 'center', color: 'var(--text-secondary)'}}>No matching services found.</td></tr>
                  )}
                </tbody>
              </table>
            )}
          </div>
        </section>

        {/* Panel 2: Docker Containers (Sci-Fi Modular Row-Cards HUD) */}
        <section className="glass-panel" style={{ display: 'flex', flexDirection: 'column', height: '380px', minWidth: 0, overflow: 'hidden' }}>
          <div className="section-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <h2 style={{ margin: 0, fontSize: '0.95rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <SciFiContainerIcon size={18} color="var(--accent-green)" /> Docker Containers
            </h2>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ fontSize: '0.68rem', fontFamily: 'Share Tech Mono', color: 'var(--accent-cyan)', background: 'rgba(0, 243, 255, 0.08)', padding: '2px 5px', border: '1px solid rgba(0, 243, 255, 0.3)', borderRadius: '2px' }}>
                TOTAL: {containers.length}
              </span>
              <span style={{ fontSize: '0.68rem', fontFamily: 'Share Tech Mono', color: 'var(--accent-green)', background: 'rgba(0, 255, 157, 0.08)', padding: '2px 5px', border: '1px solid rgba(0, 255, 157, 0.3)', borderRadius: '2px' }}>
                UP: {docUpCount}
              </span>
              {docExitedCount > 0 && (
                <span style={{ fontSize: '0.68rem', fontFamily: 'Share Tech Mono', color: 'var(--accent-pink)', background: 'rgba(255, 0, 85, 0.08)', padding: '2px 5px', border: '1px solid rgba(255, 0, 85, 0.3)', borderRadius: '2px' }}>
                  EXITED: {docExitedCount}
                </span>
              )}
              <a
                href="/containers"
                style={{
                  fontSize: '0.65rem',
                  fontFamily: 'Share Tech Mono',
                  color: 'var(--accent-cyan)',
                  textDecoration: 'none',
                  border: '1px solid rgba(0, 243, 255, 0.4)',
                  padding: '2px 6px',
                  borderRadius: '2px',
                  background: 'rgba(0, 243, 255, 0.1)',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px'
                }}
                title="Open Full Container Management Console (9 Columns & Extended Tools)"
              >
                <span>FULL</span>
                <SciFiExternalLinkIcon size={10} color="var(--accent-cyan)" />
              </a>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
            <input
              type="text"
              placeholder="Search container..."
              value={dockerSearch}
              onChange={e => setDockerSearch(e.target.value)}
              style={{
                flex: 1,
                background: 'rgba(0,0,0,0.4)',
                border: '1px solid rgba(0,243,255,0.2)',
                color: '#fff',
                padding: '3px 8px',
                fontSize: '0.72rem',
                fontFamily: 'Share Tech Mono',
                borderRadius: '3px',
                minWidth: 0
              }}
            />
            <div style={{ display: 'flex', gap: '2px', background: 'rgba(0,0,0,0.4)', padding: '2px', borderRadius: '3px' }}>
              {['ALL', 'UP', 'EXITED'].map(f => (
                <button
                  key={f}
                  onClick={() => setDockerFilter(f)}
                  style={{
                    background: dockerFilter === f ? 'var(--accent-cyan)' : 'transparent',
                    color: dockerFilter === f ? '#000' : 'var(--text-secondary)',
                    border: 'none',
                    padding: '2px 6px',
                    fontSize: '0.65rem',
                    fontFamily: 'Share Tech Mono',
                    cursor: 'pointer',
                    fontWeight: 'bold',
                    borderRadius: '2px'
                  }}
                >
                  {f}
                </button>
              ))}
            </div>
          </div>

          <div style={{ overflowY: 'auto', overflowX: 'hidden', flex: 1, paddingRight: '4px', display: 'flex', flexDirection: 'column', gap: '6px', minWidth: 0 }}>
            {dockerData.status === 'NOT_INSTALLED' ? (
              <div style={{ color: 'var(--text-secondary)', padding: '20px', textAlign: 'center', fontSize: '0.8rem', fontFamily: 'Share Tech Mono' }}>Docker is not installed on this host.</div>
            ) : dockerData.status === 'ERROR' ? (
              <div style={{ color: 'var(--accent-pink)', padding: '20px', textAlign: 'center', fontSize: '0.8rem', fontFamily: 'Share Tech Mono' }}>Error fetching Docker status.</div>
            ) : filteredContainers.length === 0 ? (
              <div style={{ color: 'var(--text-secondary)', padding: '20px', textAlign: 'center', fontSize: '0.8rem', fontFamily: 'Share Tech Mono' }}>No matching containers found.</div>
            ) : (
              filteredContainers.map((c, i) => {
                const isUp = (c.status || '').toLowerCase().startsWith('up');
                const cId = c.id || c.name;
                const stats = dockerStats[c.name] || dockerStats[c.id] || {};
                const { label: statusLabel } = formatDockerStatus(c.status);
                const portDisplay = formatDockerPorts(c.ports);
                const cpuVal = stats.cpu || (isUp ? '0.0%' : '—');
                const memVal = stats.mem ? stats.mem.split('/')[0].trim() : (isUp ? '—' : '—');

                return (
                  <div
                    key={i}
                    style={{
                      background: 'rgba(10, 15, 26, 0.7)',
                      border: `1px solid ${isUp ? 'rgba(0, 243, 255, 0.18)' : 'rgba(255, 0, 85, 0.2)'}`,
                      borderLeft: `3px solid ${isUp ? 'var(--accent-green)' : 'var(--accent-pink)'}`,
                      padding: '6px 8px',
                      borderRadius: '3px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '4px',
                      transition: 'background 0.2s',
                    }}
                  >
                    {/* Top Row: LED + Name + Uptime Pill | Action Buttons */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', minWidth: 0, gap: '6px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', minWidth: 0, flex: 1 }}>
                        <span
                          style={{
                            width: '6px',
                            height: '6px',
                            borderRadius: '50%',
                            background: isUp ? 'var(--accent-green)' : 'var(--accent-pink)',
                            boxShadow: isUp ? '0 0 6px var(--accent-green)' : '0 0 6px var(--accent-pink)',
                            flexShrink: 0
                          }}
                        />
                        <span
                          style={{
                            fontFamily: 'Share Tech Mono',
                            fontSize: '0.8rem',
                            fontWeight: 'bold',
                            color: '#fff',
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis'
                          }}
                          title={c.name}
                        >
                          {c.name}
                        </span>
                        <span
                          style={{
                            fontFamily: 'Share Tech Mono',
                            fontSize: '0.62rem',
                            padding: '1px 4px',
                            borderRadius: '2px',
                            whiteSpace: 'nowrap',
                            flexShrink: 0,
                            color: isUp ? 'var(--accent-green)' : 'var(--accent-pink)',
                            background: isUp ? 'rgba(0, 255, 102, 0.1)' : 'rgba(255, 0, 85, 0.1)',
                            border: `1px solid ${isUp ? 'rgba(0, 255, 102, 0.25)' : 'rgba(255, 0, 85, 0.25)'}`
                          }}
                          title={c.status}
                        >
                          {statusLabel}
                        </span>
                      </div>

                      {/* Action Buttons Group */}
                      <div style={{ display: 'flex', gap: '3px', flexShrink: 0 }}>
                        <button
                          onClick={() => openContainerLogs(cId, c.name)}
                          style={{
                            background: 'rgba(255, 187, 0, 0.12)',
                            border: '1px solid rgba(255, 187, 0, 0.4)',
                            color: 'var(--accent-yellow)',
                            padding: '2px 5px',
                            fontSize: '0.62rem',
                            fontFamily: 'Share Tech Mono',
                            cursor: 'pointer',
                            borderRadius: '2px',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '2px'
                          }}
                          title="View Container Logs"
                        >
                          <SciFiTerminalIcon size={10} color="var(--accent-yellow)" />
                          <span>LOGS</span>
                        </button>

                        <button
                          onClick={() => handleDockerControl(cId, c.name, 'restart')}
                          disabled={actionLoading[`doc-${cId}-restart`]}
                          style={{
                            background: 'rgba(0, 243, 255, 0.12)',
                            border: '1px solid rgba(0, 243, 255, 0.4)',
                            color: 'var(--accent-cyan)',
                            padding: '2px 5px',
                            fontSize: '0.62rem',
                            fontFamily: 'Share Tech Mono',
                            cursor: 'pointer',
                            borderRadius: '2px',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '2px'
                          }}
                          title="Restart Container"
                        >
                          {actionLoading[`doc-${cId}-restart`] ? (
                            <SciFiChronoSpinnerIcon size={10} color="var(--accent-cyan)" />
                          ) : (
                            <SciFiRefreshIcon size={10} color="var(--accent-cyan)" />
                          )}
                          <span>RST</span>
                        </button>

                        {isUp ? (
                          <button
                            onClick={() => handleDockerControl(cId, c.name, 'stop')}
                            disabled={actionLoading[`doc-${cId}-stop`]}
                            style={{
                              background: 'rgba(255, 0, 85, 0.12)',
                              border: '1px solid rgba(255, 0, 85, 0.4)',
                              color: 'var(--accent-pink)',
                              padding: '2px 5px',
                              fontSize: '0.62rem',
                              fontFamily: 'Share Tech Mono',
                              cursor: 'pointer',
                              borderRadius: '2px',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '2px'
                            }}
                            title="Stop Container"
                          >
                            {actionLoading[`doc-${cId}-stop`] ? (
                              <SciFiChronoSpinnerIcon size={10} color="var(--accent-pink)" />
                            ) : (
                              <SciFiStopIcon size={9} color="var(--accent-pink)" />
                            )}
                            <span>STOP</span>
                          </button>
                        ) : (
                          <button
                            onClick={() => handleDockerControl(cId, c.name, 'start')}
                            disabled={actionLoading[`doc-${cId}-start`]}
                            style={{
                              background: 'rgba(0, 255, 157, 0.12)',
                              border: '1px solid rgba(0, 255, 157, 0.4)',
                              color: 'var(--accent-green)',
                              padding: '2px 5px',
                              fontSize: '0.62rem',
                              fontFamily: 'Share Tech Mono',
                              cursor: 'pointer',
                              borderRadius: '2px',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '2px'
                            }}
                            title="Start Container"
                          >
                            {actionLoading[`doc-${cId}-start`] ? (
                              <SciFiChronoSpinnerIcon size={10} color="var(--accent-green)" />
                            ) : (
                              <SciFiPlayIcon size={9} color="var(--accent-green)" />
                            )}
                            <span>START</span>
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Bottom Row: Image Tag + Port Chip | CPU + RAM Metrics */}
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        fontFamily: 'Share Tech Mono',
                        fontSize: '0.65rem',
                        borderTop: '1px dashed rgba(255, 255, 255, 0.08)',
                        paddingTop: '3px',
                        minWidth: 0
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', minWidth: 0, flex: 1, overflow: 'hidden' }}>
                        <span
                          style={{
                            color: 'rgba(224, 242, 254, 0.65)',
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '4px'
                          }}
                          title={c.image}
                        >
                          <SciFiImageLayerIcon size={11} color="rgba(224, 242, 254, 0.65)" />
                          <span>{c.image}</span>
                        </span>
                        {portDisplay && (
                          <span
                            style={{
                              color: 'var(--accent-cyan)',
                              background: 'rgba(0, 243, 255, 0.08)',
                              padding: '1px 4px',
                              borderRadius: '2px',
                              whiteSpace: 'nowrap',
                              flexShrink: 0,
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '3px'
                            }}
                            title={c.ports}
                          >
                            <SciFiNetworkPortIcon size={10} color="var(--accent-cyan)" />
                            <span>{portDisplay}</span>
                          </span>
                        )}
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
                        <span
                          style={{
                            color: 'var(--accent-yellow)',
                            fontWeight: 'bold',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '3px'
                          }}
                          title={`CPU: ${cpuVal}`}
                        >
                          <SciFiCpuChipIcon size={10} color="var(--accent-yellow)" />
                          <span>{cpuVal}</span>
                        </span>
                        <span style={{ color: 'rgba(255, 255, 255, 0.2)' }}>/</span>
                        <span
                          style={{
                            color: 'var(--accent-cyan)',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '3px'
                          }}
                          title={`Memory: ${stats.mem || memVal}`}
                        >
                          <SciFiRamMemoryIcon size={10} color="var(--accent-cyan)" />
                          <span>{memVal}</span>
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </section>

      </div>

      {/* BOTTOM ROW: Systemd Timers & Host Runtimes */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: '20px', minWidth: 0 }}>
        
        {/* Panel 3: Systemd Timers & Scheduled Jobs */}
        <section className="glass-panel" style={{ display: 'flex', flexDirection: 'column', height: '340px', minWidth: 0 }}>
          <div className="section-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
            <h2 style={{ margin: 0, fontSize: '1rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <SciFiChronoIcon size={20} color="var(--accent-cyan)" /> Systemd Timers & Scheduled Jobs
            </h2>
            <span style={{ fontSize: '0.7rem', fontFamily: 'Share Tech Mono', color: 'var(--accent-cyan)', background: 'rgba(0, 243, 255, 0.08)', padding: '2px 6px', border: '1px solid rgba(0, 243, 255, 0.3)' }}>
              SCHEDULED: {timers.length}
            </span>
          </div>

          <div style={{ overflow: 'auto', flex: 1, paddingRight: '6px', minWidth: 0 }}>
            <table className="glass-table" style={{ width: '100%', fontSize: '0.75rem', tableLayout: 'fixed' }}>
              <thead>
                <tr>
                  <th style={{ width: '32%' }}>Timer Unit</th>
                  <th style={{ width: '28%' }}>Next Execution</th>
                  <th style={{ width: '16%' }}>Countdown / Left</th>
                  <th style={{ width: '24%' }}>Activates Target</th>
                </tr>
              </thead>
              <tbody>
                {timers.map((t, i) => (
                  <tr key={i}>
                    <td style={{ fontWeight: 'bold', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={t.unit}>{t.unit}</td>
                    <td style={{ fontFamily: 'Share Tech Mono', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={formatTimerDate(t.next)}>{formatTimerDate(t.next)}</td>
                    <td>
                      <span style={{
                        background: 'rgba(0, 255, 157, 0.1)',
                        border: '1px solid var(--accent-green)',
                        color: 'var(--accent-green)',
                        padding: '1px 6px',
                        fontSize: '0.65rem',
                        fontFamily: 'Share Tech Mono',
                        borderRadius: '2px',
                        whiteSpace: 'nowrap'
                      }}>
                        {t.left}
                      </span>
                    </td>
                    <td style={{ color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={formatTimerDate(t.activates)}>{formatTimerDate(t.activates)}</td>
                  </tr>
                ))}
                {timers.length === 0 && (
                  <tr><td colSpan="4" style={{ textAlign: 'center', color: 'var(--text-secondary)' }}>No scheduled timers active.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        {/* Panel 4: Host Runtimes & Daemons */}
        <section className="glass-panel" style={{ display: 'flex', flexDirection: 'column', height: '340px', minWidth: 0 }}>
          <div className="section-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
            <h2 style={{ margin: 0, fontSize: '1rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <SciFiQuantumIcon size={20} color="var(--accent-pink)" /> Host Runtimes & Application Servers
            </h2>
            <span style={{ fontSize: '0.7rem', fontFamily: 'Share Tech Mono', color: 'var(--accent-green)', background: 'rgba(0, 255, 157, 0.08)', padding: '2px 6px', border: '1px solid rgba(0, 255, 157, 0.3)' }}>
              ECOSYSTEM READY
            </span>
          </div>

          <div style={{ overflow: 'auto', flex: 1, paddingRight: '6px', minWidth: 0 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '10px', minWidth: 0 }}>
              {Object.entries(runtimes).map(([name, val], idx) => {
                const lowerVal = (val || '').toLowerCase();
                const isInstalled = val
                  && !lowerVal.includes('not installed')
                  && !lowerVal.includes('not found')
                  && !lowerVal.includes('command not found')
                  && !lowerVal.includes('no such file')
                  && !lowerVal.includes('inactive')
                  && !lowerVal.includes('error');
                const isService = ['Nginx', 'PostgreSQL', 'Redis', 'UFW Firewall'].includes(name);
                return (
                  <div key={idx} style={{
                    background: 'rgba(0,0,0,0.3)',
                    border: isInstalled ? '1px solid rgba(0, 243, 255, 0.3)' : '1px solid rgba(255, 255, 255, 0.1)',
                    borderRadius: '4px',
                    padding: '10px 12px',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'space-between',
                    gap: '6px',
                    minWidth: 0,
                    overflow: 'hidden'
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', minWidth: 0 }}>
                      <span style={{ fontWeight: 'bold', fontSize: '0.8rem', color: isInstalled ? 'var(--accent-cyan)' : 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {name}
                      </span>
                      <span style={{
                        fontSize: '0.65rem',
                        fontFamily: 'Share Tech Mono',
                        padding: '1px 6px',
                        borderRadius: '2px',
                        background: isInstalled ? 'rgba(0, 255, 157, 0.15)' : 'rgba(255, 255, 255, 0.08)',
                        color: isInstalled ? 'var(--accent-green)' : 'var(--text-secondary)',
                        border: isInstalled ? '1px solid var(--accent-green)' : '1px solid rgba(255, 255, 255, 0.2)',
                        flexShrink: 0
                      }}>
                        {isInstalled ? (isService ? 'ACTIVE' : 'INSTALLED') : 'INACTIVE'}
                      </span>
                    </div>
                    <div style={{
                      fontSize: '0.72rem',
                      fontFamily: 'Share Tech Mono',
                      color: isInstalled ? '#fff' : 'var(--text-secondary)',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis'
                    }} title={val}>
                      {val}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </section>

      </div>

      {/* Sci-Fi Container Log Viewer Modal */}
      {logContainer && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.85)',
          backdropFilter: 'blur(8px)',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          zIndex: 9999,
          padding: '20px'
        }}>
          <div style={{
            background: 'var(--glass-bg)',
            border: '1px solid var(--accent-cyan)',
            borderRadius: '8px',
            width: '900px',
            maxWidth: '95vw',
            maxHeight: '85vh',
            display: 'flex',
            flexDirection: 'column',
            boxShadow: '0 0 30px rgba(0, 243, 255, 0.2)',
            overflow: 'hidden'
          }}>
            {/* Header */}
            <div style={{
              padding: '12px 18px',
              borderBottom: '1px solid rgba(0, 243, 255, 0.2)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              background: 'rgba(0, 243, 255, 0.05)'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <SciFiContainerIcon size={20} color="var(--accent-cyan)" />
                <span style={{ fontFamily: 'Share Tech Mono', color: 'var(--accent-cyan)', fontWeight: 'bold', fontSize: '1.05rem' }}>
                  CONTAINER LOGS: {logContainer.name} ({logContainer.id.substring(0, 12)})
                </span>
              </div>
              <button
                onClick={() => setLogContainer(null)}
                style={{ background: 'none', border: 'none', color: '#fff', fontSize: '1.2rem', cursor: 'pointer', fontWeight: 'bold' }}
              >
                ✕
              </button>
            </div>

            {/* Controls Bar */}
            <div style={{
              padding: '10px 18px',
              display: 'flex',
              gap: '12px',
              alignItems: 'center',
              borderBottom: '1px solid rgba(255, 255, 255, 0.1)',
              background: 'rgba(0, 0, 0, 0.4)'
            }}>

              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.75rem', fontFamily: 'Share Tech Mono', color: 'var(--text-secondary)' }}>
                <span>Lines:</span>
                {[50, 100, 200, 500].map(count => (
                  <button
                    key={count}
                    onClick={() => { setLogLinesCount(count); fetchContainerLogs(logContainer.id, count); }}
                    style={{
                      background: logLinesCount === count ? 'var(--accent-cyan)' : 'transparent',
                      color: logLinesCount === count ? '#000' : 'var(--accent-cyan)',
                      border: '1px solid rgba(0,243,255,0.3)',
                      padding: '2px 8px',
                      fontSize: '0.7rem',
                      fontFamily: 'Share Tech Mono',
                      cursor: 'pointer',
                      borderRadius: '2px'
                    }}
                  >
                    {count}
                  </button>
                ))}
              </div>

              <button
                onClick={() => fetchContainerLogs(logContainer.id, logLinesCount)}
                disabled={isLogsLoading}
                style={{
                  background: 'rgba(0, 243, 255, 0.15)',
                  border: '1px solid var(--accent-cyan)',
                  color: 'var(--accent-cyan)',
                  padding: '4px 12px',
                  fontSize: '0.75rem',
                  fontFamily: 'Share Tech Mono',
                  cursor: 'pointer',
                  borderRadius: '3px'
                }}
              >
                {isLogsLoading ? 'LOADING...' : 'REFRESH'}
              </button>
            </div>

            {/* Log Display Box — search + sort are managed inside LogViewer */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, maxHeight: '60vh' }}>
              <LogViewer
                logContent={logContent}
                isLoading={isLogsLoading}
                background="#040914"
              />
            </div>
          </div>
        </div>
      )}

    </main>
  );
}