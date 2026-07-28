import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { 
  SciFiContainerIcon, SciFiSearchIcon, SciFiRefreshIcon, 
  SciFiPlayIcon, SciFiStopIcon, SciFiPulseBadge 
} from '../components/SciFiIcons';
import { parseDockerStats } from '../utils/parsers';

export default function ContainersPage() {
  const [containers, setContainers] = useState([]);
  const [dockerStatus, setDockerStatus] = useState('LOADING');
  const [dockerStats, setDockerStats] = useState({});
  const [loading, setLoading] = useState(true);
  
  // Search & Filter
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');

  // Control action feedback toast
  const [actionMessage, setActionMessage] = useState(null);
  const [actionLoading, setActionLoading] = useState({});

  // Container Log Modal
  const [logContainer, setLogContainer] = useState(null); // { id, name }
  const [logContent, setLogContent] = useState('');
  const [logLinesCount, setLogLinesCount] = useState(100);
  const [logSearchQuery, setLogSearchQuery] = useState('');
  const [isLogsLoading, setIsLogsLoading] = useState(false);
  const [copySuccess, setCopySuccess] = useState(false);

  const fetchDockerData = async () => {
    setLoading(true);
    try {
      const [listRes, statsRes] = await Promise.all([
        axios.get('/api/metrics/docker'),
        axios.get('/api/metrics/docker/stats').catch(() => ({ data: { data: '' } }))
      ]);

      if (listRes.data) {
        setDockerStatus(listRes.data.status || 'UNKNOWN');
        setContainers(listRes.data.data || []);
      }

      if (statsRes.data && statsRes.data.data) {
        setDockerStats(parseDockerStats(statsRes.data.data));
      }
    } catch (err) {
      console.error('Failed to fetch Docker containers page data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let isMounted = true;

    const loadData = async () => {
      try {
        const [listRes, statsRes] = await Promise.all([
          axios.get('/api/metrics/docker'),
          axios.get('/api/metrics/docker/stats').catch(() => ({ data: { data: '' } }))
        ]);

        if (!isMounted) return;

        if (listRes.data) {
          setDockerStatus(listRes.data.status || 'UNKNOWN');
          setContainers(listRes.data.data || []);
        }

        if (statsRes.data && statsRes.data.data) {
          setDockerStats(parseDockerStats(statsRes.data.data));
        }
      } catch (err) {
        console.error('Failed to fetch Docker containers page data:', err);
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    loadData();
    const interval = setInterval(loadData, 15000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  const handleContainerAction = async (containerId, action) => {
    setActionLoading(prev => ({ ...prev, [containerId]: true }));
    setActionMessage(null);

    try {
      const res = await axios.post(`/api/metrics/docker/control?containerId=${encodeURIComponent(containerId)}&action=${encodeURIComponent(action)}`);
      if (res.data && res.data.status === 'success') {
        setActionMessage({ type: 'success', text: `Action '${action}' executed successfully on container ${containerId}` });
        fetchDockerData();
      } else {
        setActionMessage({ type: 'error', text: `Failed to ${action} container: ${res.data.message || 'Error'}` });
      }
    } catch (err) {
      setActionMessage({ type: 'error', text: `Error executing container action: ${err.message}` });
    } finally {
      setActionLoading(prev => ({ ...prev, [containerId]: false }));
      setTimeout(() => setActionMessage(null), 5000);
    }
  };

  const fetchContainerLogs = async (containerId, lines = 100) => {
    setIsLogsLoading(true);
    try {
      const res = await axios.get(`/api/metrics/docker/logs?containerId=${encodeURIComponent(containerId)}&lines=${lines}`);
      if (res.data && res.data.data) {
        setLogContent(res.data.data);
      } else {
        setLogContent('No logs returned or container stopped.');
      }
    } catch (err) {
      setLogContent(`Failed to fetch container logs: ${err.message}`);
    } finally {
      setIsLogsLoading(false);
    }
  };

  const openLogViewer = (id, name) => {
    setLogContainer({ id, name });
    fetchContainerLogs(id, logLinesCount);
  };

  // Filtered list
  const filteredContainers = containers.filter(c => {
    const matchesSearch = (c.name || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
                          (c.image || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
                          (c.id || '').toLowerCase().includes(searchQuery.toLowerCase());
    
    if (!matchesSearch) return false;
    const isUp = (c.status || '').toLowerCase().includes('up');
    if (statusFilter === 'RUNNING') return isUp;
    if (statusFilter === 'EXITED') return !isUp;
    return true;
  });

  const totalContainers = containers.length;
  const runningCount = containers.filter(c => (c.status || '').toLowerCase().includes('up')).length;
  const stoppedCount = totalContainers - runningCount;

  const handleCopyLogs = () => {
    if (!logContent) return;
    navigator.clipboard.writeText(logContent);
    setCopySuccess(true);
    setTimeout(() => setCopySuccess(false), 2000);
  };

  return (
    <div style={{ padding: '20px', height: '100%', display: 'flex', flexDirection: 'column', gap: '16px', overflowY: 'auto' }}>
      
      {/* Action Message Toast */}
      {actionMessage && (
        <div style={{
          background: actionMessage.type === 'success' ? 'rgba(0, 255, 157, 0.15)' : 'rgba(255, 0, 85, 0.15)',
          border: actionMessage.type === 'success' ? '1px solid var(--accent-green)' : '1px solid var(--accent-pink)',
          color: actionMessage.type === 'success' ? 'var(--accent-green)' : 'var(--accent-pink)',
          padding: '10px 16px',
          borderRadius: '4px',
          fontFamily: 'Share Tech Mono',
          fontSize: '0.85rem',
          fontWeight: 'bold',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <span>{actionMessage.text}</span>
          <button onClick={() => setActionMessage(null)} style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }}>✕</button>
        </div>
      )}

      {/* Header Bar */}
      <div className="glass-panel" style={{ padding: '16px 20px', display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <SciFiContainerIcon size={28} color="var(--accent-green)" />
          <div>
            <h2 className="title-glow" style={{ margin: 0, fontSize: '1.2rem', letterSpacing: '1px' }}>
              DOCKER CONTAINER MANAGER & STATS
            </h2>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>
              CONTAINERIZED APPLICATION ORCHESTRATION & METRICS
            </span>
          </div>
        </div>

        <button
          onClick={fetchDockerData}
          disabled={loading}
          style={{
            background: 'rgba(0, 255, 157, 0.1)',
            border: '1px solid var(--accent-green)',
            color: 'var(--accent-green)',
            padding: '6px 14px',
            fontFamily: 'Share Tech Mono',
            fontSize: '0.8rem',
            fontWeight: 'bold',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            borderRadius: '3px'
          }}
        >
          <SciFiRefreshIcon size={14} color="var(--accent-green)" />
          <span>REFRESH DOCKER</span>
        </button>
      </div>

      {/* KPI Cards Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
        
        <div className="glass-panel" style={{ padding: '16px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ padding: '10px', borderRadius: '50%', background: 'rgba(0, 243, 255, 0.1)', border: '1px solid var(--accent-cyan)' }}>
            <SciFiContainerIcon size={24} color="var(--accent-cyan)" />
          </div>
          <div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>TOTAL CONTAINERS</div>
            <div style={{ fontSize: '1.6rem', fontWeight: 'bold', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono' }}>{totalContainers}</div>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '16px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ padding: '10px', borderRadius: '50%', background: 'rgba(0, 255, 157, 0.1)', border: '1px solid var(--accent-green)' }}>
            <SciFiPulseBadge size={24} color="var(--accent-green)" />
          </div>
          <div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>RUNNING / ACTIVE</div>
            <div style={{ fontSize: '1.6rem', fontWeight: 'bold', color: 'var(--accent-green)', fontFamily: 'Share Tech Mono' }}>{runningCount}</div>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '16px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ padding: '10px', borderRadius: '50%', background: 'rgba(255, 0, 85, 0.1)', border: '1px solid var(--accent-pink)' }}>
            <SciFiStopIcon size={20} color="var(--accent-pink)" />
          </div>
          <div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>STOPPED / EXITED</div>
            <div style={{ fontSize: '1.6rem', fontWeight: 'bold', color: 'var(--accent-pink)', fontFamily: 'Share Tech Mono' }}>{stoppedCount}</div>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '16px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>DAEMON STATUS</div>
            <div style={{ fontSize: '1.1rem', fontWeight: 'bold', color: dockerStatus === 'RUNNING' ? 'var(--accent-green)' : 'var(--accent-pink)', fontFamily: 'Share Tech Mono', marginTop: '4px' }}>
              {dockerStatus}
            </div>
          </div>
        </div>

      </div>

      {/* Filter & Search Bar */}
      <div className="glass-panel" style={{ padding: '12px 16px', display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
        
        {/* Status Tabs */}
        <div style={{ display: 'flex', gap: '8px' }}>
          {['ALL', 'RUNNING', 'EXITED'].map(st => (
            <button
              key={st}
              onClick={() => setStatusFilter(st)}
              style={{
                background: statusFilter === st ? 'rgba(0, 255, 157, 0.2)' : 'rgba(0,0,0,0.4)',
                border: statusFilter === st ? '1px solid var(--accent-green)' : '1px solid rgba(0, 255, 157, 0.2)',
                color: statusFilter === st ? 'var(--accent-green)' : '#ccc',
                padding: '4px 12px',
                fontSize: '0.75rem',
                fontFamily: 'Share Tech Mono',
                borderRadius: '3px',
                cursor: 'pointer'
              }}
            >
              {st}
            </button>
          ))}
        </div>

        {/* Search Field */}
        <div style={{ position: 'relative', minWidth: '240px' }}>
          <input
            type="text"
            placeholder="Search container by name, ID, image..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            style={{
              width: '100%',
              background: 'rgba(0,0,0,0.4)',
              border: '1px solid rgba(0, 243, 255, 0.25)',
              color: '#fff',
              padding: '6px 10px 6px 30px',
              fontSize: '0.8rem',
              fontFamily: 'Share Tech Mono',
              borderRadius: '3px'
            }}
          />
          <div style={{ position: 'absolute', left: '8px', top: '50%', transform: 'translateY(-50%)' }}>
            <SciFiSearchIcon size={14} color="var(--accent-cyan)" />
          </div>
        </div>

      </div>

      {/* Containers Table */}
      <div className="glass-panel" style={{ flex: 1, padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        
        {dockerStatus === 'NOT_INSTALLED' ? (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--accent-pink)', fontFamily: 'Share Tech Mono' }}>
            ⚠️ DOCKER IS NOT INSTALLED OR DAEMON IS NOT RUNNING ON SSH HOST
          </div>
        ) : loading && containers.length === 0 ? (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--accent-green)', fontFamily: 'Share Tech Mono' }}>
            FETCHING DOCKER CONTAINERS...
          </div>
        ) : filteredContainers.length === 0 ? (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>
            No containers matching filter criteria.
          </div>
        ) : (
          <div style={{ overflowX: 'auto', flex: 1 }}>
            <table className="sci-fi-table" style={{ width: '100%', minWidth: '950px' }}>
              <thead>
                <tr>
                  <th style={{ width: '140px' }}>CONTAINER ID</th>
                  <th style={{ minWidth: '160px' }}>NAME</th>
                  <th style={{ minWidth: '160px' }}>IMAGE</th>
                  <th style={{ minWidth: '160px' }}>STATUS</th>
                  <th style={{ minWidth: '150px' }}>PORTS</th>
                  <th style={{ width: '90px' }}>CPU %</th>
                  <th style={{ width: '130px' }}>MEM USAGE</th>
                  <th style={{ width: '130px' }}>NET I/O</th>
                  <th style={{ width: '160px', textAlign: 'center' }}>ACTIONS</th>
                </tr>
              </thead>
              <tbody>
                {filteredContainers.map((c, idx) => {
                  const isUp = (c.status || '').toLowerCase().includes('up');
                  const stat = dockerStats[c.id] || dockerStats[c.name] || {};
                  const isActLoading = actionLoading[c.id];

                  return (
                    <tr key={idx}>
                      <td style={{ fontFamily: 'Share Tech Mono', color: 'var(--accent-cyan)', fontWeight: 'bold' }}>
                        {c.id}
                      </td>
                      <td style={{ fontWeight: 'bold', color: '#fff' }}>
                        {c.name}
                      </td>
                      <td style={{ fontFamily: 'Share Tech Mono', fontSize: '0.78rem', opacity: 0.85 }}>
                        {c.image}
                      </td>
                      <td>
                        <span style={{
                          padding: '3px 10px',
                          borderRadius: '3px',
                          fontSize: '0.75rem',
                          fontFamily: 'Share Tech Mono',
                          fontWeight: 'bold',
                          whiteSpace: 'nowrap',
                          display: 'inline-block',
                          background: isUp ? 'rgba(0, 255, 157, 0.15)' : 'rgba(255, 0, 85, 0.15)',
                          border: isUp ? '1px solid var(--accent-green)' : '1px solid var(--accent-pink)',
                          color: isUp ? 'var(--accent-green)' : 'var(--accent-pink)'
                        }}>
                          {c.status}
                        </span>
                      </td>
                      <td style={{ fontFamily: 'Share Tech Mono', fontSize: '0.75rem', opacity: 0.75 }}>
                        {c.ports || '—'}
                      </td>
                      <td style={{ fontFamily: 'Share Tech Mono', fontSize: '0.8rem', color: 'var(--accent-yellow)' }}>
                        {stat.cpuPerc || (isUp ? 'Fetch...' : '0.00%')}
                      </td>
                      <td style={{ fontFamily: 'Share Tech Mono', fontSize: '0.8rem', color: 'var(--accent-cyan)' }}>
                        {stat.memUsage || (isUp ? 'Fetch...' : '0B / 0B')}
                      </td>
                      <td style={{ fontFamily: 'Share Tech Mono', fontSize: '0.78rem', opacity: 0.8 }}>
                        {stat.netIO || '0B / 0B'}
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        <div style={{ display: 'flex', gap: '6px', justifyContent: 'center' }}>
                          
                          {/* Start / Stop Button */}
                          {isUp ? (
                            <button
                              onClick={() => handleContainerAction(c.id, 'stop')}
                              disabled={isActLoading}
                              style={{
                                background: 'rgba(255, 0, 85, 0.15)',
                                border: '1px solid var(--accent-pink)',
                                color: 'var(--accent-pink)',
                                padding: '2px 6px',
                                fontSize: '0.7rem',
                                fontFamily: 'Share Tech Mono',
                                cursor: 'pointer',
                                borderRadius: '3px'
                              }}
                              title="Stop Container"
                            >
                              STOP
                            </button>
                          ) : (
                            <button
                              onClick={() => handleContainerAction(c.id, 'start')}
                              disabled={isActLoading}
                              style={{
                                background: 'rgba(0, 255, 157, 0.15)',
                                border: '1px solid var(--accent-green)',
                                color: 'var(--accent-green)',
                                padding: '2px 6px',
                                fontSize: '0.7rem',
                                fontFamily: 'Share Tech Mono',
                                cursor: 'pointer',
                                borderRadius: '3px'
                              }}
                              title="Start Container"
                            >
                              START
                            </button>
                          )}

                          {/* Restart Button */}
                          <button
                            onClick={() => handleContainerAction(c.id, 'restart')}
                            disabled={isActLoading}
                            style={{
                              background: 'rgba(0, 243, 255, 0.15)',
                              border: '1px solid var(--accent-cyan)',
                              color: 'var(--accent-cyan)',
                              padding: '2px 6px',
                              fontSize: '0.7rem',
                              fontFamily: 'Share Tech Mono',
                              cursor: 'pointer',
                              borderRadius: '3px'
                            }}
                            title="Restart Container"
                          >
                            RESTART
                          </button>

                          {/* Logs Button */}
                          <button
                            onClick={() => openLogViewer(c.id, c.name)}
                            style={{
                              background: 'rgba(255, 187, 0, 0.15)',
                              border: '1px solid var(--accent-yellow)',
                              color: 'var(--accent-yellow)',
                              padding: '2px 6px',
                              fontSize: '0.7rem',
                              fontFamily: 'Share Tech Mono',
                              cursor: 'pointer',
                              borderRadius: '3px'
                            }}
                            title="View Container Logs"
                          >
                            LOGS
                          </button>

                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

      </div>

      {/* Container Log Viewer Modal */}
      {logContainer && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.85)',
          backdropFilter: 'blur(8px)',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          zIndex: 99999
        }}>
          <div className="glass-panel" style={{
            width: '880px',
            maxWidth: '94vw',
            height: '600px',
            maxHeight: '92vh',
            display: 'flex',
            flexDirection: 'column',
            border: '1px solid var(--accent-green)',
            padding: 0,
            overflow: 'hidden'
          }}>
            {/* Modal Header */}
            <div style={{
              background: 'rgba(0, 255, 157, 0.1)',
              borderBottom: '1px solid rgba(0, 255, 157, 0.3)',
              padding: '12px 18px',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--accent-green)', fontFamily: 'Share Tech Mono', fontWeight: 'bold' }}>
                <SciFiContainerIcon size={20} color="var(--accent-green)" />
                <span>CONTAINER LOGS: {logContainer.name} ({logContainer.id})</span>
              </div>
              <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                <button
                  onClick={handleCopyLogs}
                  style={{
                    background: copySuccess ? 'rgba(0, 255, 157, 0.2)' : 'rgba(255,255,255,0.08)',
                    border: copySuccess ? '1px solid var(--accent-green)' : '1px solid rgba(255,255,255,0.2)',
                    color: copySuccess ? 'var(--accent-green)' : '#ccc',
                    fontSize: '0.75rem',
                    fontFamily: 'Share Tech Mono',
                    padding: '4px 10px',
                    cursor: 'pointer'
                  }}
                >
                  {copySuccess ? '✓ COPIED' : 'COPY LOGS'}
                </button>
                <button
                  onClick={() => setLogContainer(null)}
                  style={{ background: 'none', border: 'none', color: 'var(--accent-pink)', fontSize: '1.2rem', cursor: 'pointer', fontWeight: 'bold' }}
                >
                  ✕
                </button>
              </div>
            </div>

            {/* Modal Controls Bar */}
            <div style={{
              background: 'rgba(0,0,0,0.4)',
              borderBottom: '1px solid rgba(0, 255, 157, 0.15)',
              padding: '8px 16px',
              display: 'flex',
              gap: '16px',
              alignItems: 'center',
              flexWrap: 'wrap',
              fontSize: '0.8rem',
              fontFamily: 'Share Tech Mono'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span>TAIL LINES:</span>
                <select
                  value={logLinesCount}
                  onChange={e => {
                    const l = parseInt(e.target.value, 10);
                    setLogLinesCount(l);
                    fetchContainerLogs(logContainer.id, l);
                  }}
                  style={{
                    background: '#000',
                    border: '1px solid rgba(0,255,157,0.3)',
                    color: 'var(--accent-green)',
                    padding: '2px 6px',
                    fontSize: '0.75rem',
                    fontFamily: 'Share Tech Mono'
                  }}
                >
                  <option value={50}>50 Lines</option>
                  <option value={100}>100 Lines</option>
                  <option value={200}>200 Lines</option>
                  <option value={500}>500 Lines</option>
                  <option value={1000}>1000 Lines</option>
                </select>
              </div>

              <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span>SEARCH LOG:</span>
                <input
                  type="text"
                  placeholder="Filter logs..."
                  value={logSearchQuery}
                  onChange={e => setLogSearchQuery(e.target.value)}
                  style={{
                    flex: 1,
                    background: '#000',
                    border: '1px solid rgba(0,255,157,0.3)',
                    color: '#fff',
                    padding: '3px 8px',
                    fontSize: '0.78rem',
                    fontFamily: 'Share Tech Mono'
                  }}
                />
              </div>

              <button
                onClick={() => fetchContainerLogs(logContainer.id, logLinesCount)}
                style={{
                  background: 'rgba(0,255,157,0.15)',
                  border: '1px solid var(--accent-green)',
                  color: 'var(--accent-green)',
                  padding: '3px 10px',
                  fontSize: '0.75rem',
                  fontFamily: 'Share Tech Mono',
                  cursor: 'pointer'
                }}
              >
                REFRESH LOGS
              </button>
            </div>

            {/* Log Output Console */}
            <div style={{
              flex: 1,
              background: '#040810',
              padding: '16px',
              overflowY: 'auto',
              fontFamily: 'Share Tech Mono, monospace',
              fontSize: '0.82rem',
              color: 'rgba(255,255,255,0.9)',
              lineHeight: '1.5',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all'
            }}>
              {isLogsLoading ? (
                <div style={{ color: 'var(--accent-green)', textAlign: 'center', padding: '40px' }}>
                  FETCHING CONTAINER LOGS FROM DOCKER DAEMON...
                </div>
              ) : (
                logContent.split('\n').map((line, i) => {
                  if (logSearchQuery && line.toLowerCase().includes(logSearchQuery.toLowerCase())) {
                    return (
                      <div key={i} style={{ background: 'rgba(0, 255, 157, 0.25)', color: '#fff' }}>
                        <span style={{ opacity: 0.4, marginRight: '12px', userSelect: 'none' }}>{i + 1}</span>
                        {line}
                      </div>
                    );
                  }
                  return (
                    <div key={i}>
                      <span style={{ opacity: 0.4, marginRight: '12px', userSelect: 'none', display: 'inline-block', width: '35px', textAlign: 'right' }}>
                        {i + 1}
                      </span>
                      {line}
                    </div>
                  );
                })
              )}
            </div>

          </div>
        </div>
      )}

    </div>
  );
}