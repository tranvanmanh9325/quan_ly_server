import React, { useState, useEffect } from 'react';
import { useOutletContext } from 'react-router-dom';
import axios from 'axios';
import { SciFiPortIcon, SciFiCyberLockIcon, SciFiTerminalIcon, SciFiSearchIcon, SciFiDownloadIcon } from '../components/SciFiIcons';
import { formatLogLineTimestamp } from '../utils/parsers';

const WELL_KNOWN_PORTS = {
  '22': 'sshd (SSH)',
  '53': 'systemd-resolved (DNS)',
  '80': 'nginx / httpd (HTTP)',
  '443': 'nginx / httpd (HTTPS)',
  '3306': 'mysqld (MySQL)',
  '5432': 'postgres (PostgreSQL)',
  '6379': 'redis-server (Redis)',
  '27017': 'mongod (MongoDB)',
  '8080': 'java / Spring Boot',
  '5173': 'vite / Node.js (Dev)',
  '20242': 'quan_ly_server (Frontend)',
  '20243': 'quan_ly_server (Backend)',
};

function formatProcess(proc, localAddr) {
  const portMatch = localAddr ? localAddr.match(/:(\d+)$/) : null;
  const port = portMatch ? portMatch[1] : null;

  if (proc && proc.trim() !== '' && !proc.includes('Restricted') && proc !== 'N/A') {
    // Extract process name + PID from ss output: users:(("nginx",pid=1234,fd=6))
    const match = proc.match(/users:\(\("([^"]+)",pid=(\d+)/);
    if (match) {
      return (
        <span style={{ color: 'var(--accent-cyan)', fontWeight: 'bold', fontFamily: 'Share Tech Mono' }}>
          {match[1]} <span style={{ color: 'var(--text-secondary)', fontWeight: 'normal', fontSize: '0.75rem' }}>(PID {match[2]})</span>
        </span>
      );
    }
    // Fallback: render raw string if regex doesn't match (e.g. non-standard format)
    return <span style={{ color: 'var(--accent-cyan)', fontWeight: 'bold' }}>{proc}</span>;
  }

  if (port && WELL_KNOWN_PORTS[port]) {
    return (
      <span style={{ color: '#f0b429', fontStyle: 'italic', fontSize: '0.8rem' }}>
        {WELL_KNOWN_PORTS[port]}
      </span>
    );
  }

  return <span style={{ color: 'var(--text-secondary)', fontStyle: 'italic', fontSize: '0.75rem' }}>System Service</span>;
}


function renderFormattedLogLine(line, index) {
  const formattedLine = formatLogLineTimestamp(line);
  const upper = line.toUpperCase();
  let color = 'rgba(255, 255, 255, 0.75)';
  let bg = 'transparent';

  if (upper.includes('ERROR') || upper.includes('DENIED') || upper.includes('FAILED') || upper.includes('FATAL') || upper.includes('CRITICAL')) {
    color = 'var(--accent-pink)';
    bg = 'rgba(255, 0, 85, 0.08)';
  } else if (upper.includes('WARN') || upper.includes('WARNING')) {
    color = '#f0b429';
    bg = 'rgba(240, 180, 41, 0.05)';
  } else if (upper.includes('INFO') || upper.includes('SUCCESS') || upper.includes('ACTIVATED') || upper.includes('STARTED')) {
    color = 'var(--accent-green)';
  }

  return (
    <div key={index} style={{
      color,
      background: bg,
      padding: '2px 6px',
      borderLeft: bg !== 'transparent' ? `2px solid ${color}` : 'none',
      marginBottom: '2px',
      wordBreak: 'break-all'
    }}>
      {formattedLine}
    </div>
  );
}

export default function SecurityPage() {
  const { systemLogs, connections } = useOutletContext();
  const [ports, setPorts] = useState([]);
  const [loading, setLoading] = useState(true);
  
  // Log Search & Filter
  const [logSearch, setLogSearch] = useState('');
  const [logLevelFilter, setLogLevelFilter] = useState('ALL');

  // Port Search & Filter
  const [portSearch, setPortSearch] = useState('');
  const [portProtoFilter, setPortProtoFilter] = useState('ALL');

  useEffect(() => {
    let isMounted = true;
    const loadPorts = async () => {
      try {
        const res = await axios.get('/api/metrics/ports');
        if (res.data && res.data.data && isMounted) {
          const lines = res.data.data.trim().split('\n');
          const parsed = lines.map(line => {
            const parts = line.split('|');
            return {
              proto: parts[0] || '',
              localAddr: parts[1] || '',
              process: parts[2] || ''
            };
          }).filter(p => p.proto !== '');
          setPorts(parsed);
        }
      } catch (e) {
        console.error("Error fetching ports", e);
      } finally {
        if (isMounted) setLoading(false);
      }
    };
    
    loadPorts();
    const interval = setInterval(loadPorts, 15000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  const tcpCount = ports.filter(p => p.proto.toLowerCase().includes('tcp')).length;
  const udpCount = ports.filter(p => p.proto.toLowerCase().includes('udp')).length;

  const filteredPorts = ports.filter(p => {
    const matchSearch = p.localAddr.toLowerCase().includes(portSearch.toLowerCase()) ||
                        p.process.toLowerCase().includes(portSearch.toLowerCase());
    if (portProtoFilter === 'TCP') return matchSearch && p.proto.toLowerCase().includes('tcp');
    if (portProtoFilter === 'UDP') return matchSearch && p.proto.toLowerCase().includes('udp');
    return matchSearch;
  });

  // Filter System Logs (newest entries first at the top)
  const logLines = systemLogs ? systemLogs.split('\n').reverse() : [];
  const filteredLogLines = logLines.filter(line => {
    if (!line.trim()) return false;
    const matchSearch = line.toLowerCase().includes(logSearch.toLowerCase());
    const upper = line.toUpperCase();
    if (logLevelFilter === 'ERRORS') return matchSearch && (upper.includes('ERROR') || upper.includes('DENIED') || upper.includes('FAILED') || upper.includes('FATAL') || upper.includes('CRITICAL'));
    if (logLevelFilter === 'WARNS') return matchSearch && (upper.includes('WARN') || upper.includes('WARNING'));
    if (logLevelFilter === 'INFO') return matchSearch && (upper.includes('INFO') || upper.includes('SUCCESS') || upper.includes('ACTIVATED'));
    return matchSearch;
  });

  const exportSystemLogs = () => {
    if (!systemLogs) return;
    const blob = new Blob([systemLogs], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `system_logs_${new Date().toISOString().slice(0, 10)}.log`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <main className="main-content" style={{ overflowY: 'auto' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
        
        {/* Listening Ports Panel */}
        <section className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', maxHeight: '420px' }}>
          <div className="section-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
            <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <SciFiPortIcon size={20} color="var(--accent-cyan)" /> Listening Ports
            </h2>
            <span style={{ fontSize: '0.7rem', fontFamily: 'Share Tech Mono', color: 'var(--accent-cyan)', background: 'rgba(0, 243, 255, 0.08)', padding: '3px 8px', border: '1px solid rgba(0, 243, 255, 0.3)', borderRadius: '2px' }}>
              TOTAL: {ports.length} ({tcpCount} TCP, {udpCount} UDP)
            </span>
          </div>

          {/* Port Search & Filter Controls */}
          <div style={{ display: 'flex', gap: '10px', marginBottom: '10px' }}>
            <input
              type="text"
              placeholder="Filter port or process..."
              value={portSearch}
              onChange={e => setPortSearch(e.target.value)}
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
              {['ALL', 'TCP', 'UDP'].map(f => (
                <button
                  key={f}
                  onClick={() => setPortProtoFilter(f)}
                  style={{
                    background: portProtoFilter === f ? 'var(--accent-cyan)' : 'transparent',
                    color: portProtoFilter === f ? '#000' : 'var(--text-secondary)',
                    border: 'none',
                    padding: '2px 8px',
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

          <div style={{ overflowY: 'auto', flex: 1, paddingRight: '6px' }}>
            {loading ? <div style={{color: 'var(--text-secondary)'}}>Loading ports...</div> : (
              <table className="glass-table" style={{width: '100%', fontSize: '0.82rem'}}>
                <thead>
                  <tr>
                    <th>Protocol</th>
                    <th>Local Address</th>
                    <th>Process ID/Name</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredPorts.map((p, i) => (
                    <tr key={i}>
                      <td style={{color: p.proto.toLowerCase().includes('udp') ? '#f0b429' : 'var(--accent-cyan)', fontWeight: 'bold', fontFamily: 'Share Tech Mono'}}>
                        {p.proto.toUpperCase()}
                      </td>
                      <td style={{fontFamily: 'Share Tech Mono'}}>{p.localAddr}</td>
                      <td>{formatProcess(p.process, p.localAddr)}</td>
                    </tr>
                  ))}
                  {filteredPorts.length === 0 && (
                    <tr><td colSpan="3" style={{textAlign: 'center', color: 'var(--text-secondary)'}}>No matching listening ports found.</td></tr>
                  )}
                </tbody>
              </table>
            )}
          </div>
        </section>

        {/* Active User Sessions Panel */}
        <section className="glass-panel" style={{ padding: '20px', display: 'flex', flexDirection: 'column', maxHeight: '420px' }}>
          <div className="section-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <SciFiCyberLockIcon size={20} color="var(--accent-green)" /> Active SSH Sessions
            </h2>
            <span style={{ fontSize: '0.7rem', fontFamily: 'Share Tech Mono', color: 'var(--accent-green)', background: 'rgba(0, 255, 157, 0.08)', padding: '3px 8px', border: '1px solid rgba(0, 255, 157, 0.3)', borderRadius: '2px' }}>
              SESSIONS: {connections.length}
            </span>
          </div>
          <div style={{ overflowY: 'auto', flex: 1, paddingRight: '6px' }}>
            <table className="glass-table" style={{width: '100%', fontSize: '0.82rem'}}>
              <thead>
                <tr>
                  <th>User</th>
                  <th>Terminal</th>
                  <th>IP Address</th>
                  <th>Login Time</th>
                </tr>
              </thead>
              <tbody>
                {connections.map((c, i) => (
                  <tr key={i}>
                    <td style={{color: 'var(--accent-cyan)', fontWeight: 'bold', fontFamily: 'Share Tech Mono'}}>{c.user}</td>
                    <td style={{fontFamily: 'Share Tech Mono'}}>{c.terminal}</td>
                    <td style={{color: 'var(--accent-pink)', fontFamily: 'Share Tech Mono'}}>{c.ip}</td>
                    <td style={{color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono'}}>{c.loginTime}</td>
                  </tr>
                ))}
                {connections.length === 0 && (
                  <tr><td colSpan="4" style={{textAlign: 'center', color: 'var(--text-secondary)'}}>No active SSH sessions.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
        
        {/* System Logs Panel */}
        <section className="glass-panel" style={{ padding: '20px', gridColumn: '1 / -1', display: 'flex', flexDirection: 'column', maxHeight: '480px' }}>
          <div className="section-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <SciFiTerminalIcon size={20} color="var(--accent-green)" /> System Logs (Tail 50)
            </h2>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <span style={{ fontSize: '0.7rem', fontFamily: 'Share Tech Mono', color: 'var(--accent-cyan)', background: 'rgba(0, 243, 255, 0.08)', padding: '3px 8px', border: '1px solid rgba(0, 243, 255, 0.3)', borderRadius: '2px' }}>
                LINES: {filteredLogLines.length}
              </span>
              <button
                onClick={exportSystemLogs}
                style={{
                  background: 'rgba(0, 255, 157, 0.1)',
                  border: '1px solid var(--accent-green)',
                  color: 'var(--accent-green)',
                  padding: '3px 10px',
                  fontSize: '0.7rem',
                  fontFamily: 'Share Tech Mono',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  borderRadius: '2px'
                }}
                title="Export logs to file"
              >
                <SciFiDownloadIcon size={12} color="var(--accent-green)" /> EXPORT LOGS
              </button>
            </div>
          </div>

          {/* Log Controls */}
          <div style={{ display: 'flex', gap: '10px', marginBottom: '12px' }}>
            <div style={{ position: 'relative', flex: 1 }}>
              <div style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)' }}>
                <SciFiSearchIcon size={16} color="var(--accent-cyan)" />
              </div>
              <input
                type="text"
                placeholder="Search system logs..."
                value={logSearch}
                onChange={e => setLogSearch(e.target.value)}
                style={{
                  width: '100%',
                  padding: '6px 10px 6px 34px',
                  background: 'rgba(0,0,0,0.4)',
                  border: '1px solid rgba(0,243,255,0.2)',
                  color: '#fff',
                  fontSize: '0.8rem',
                  fontFamily: 'Share Tech Mono',
                  borderRadius: '3px'
                }}
              />
            </div>
            <div style={{ display: 'flex', gap: '2px', background: 'rgba(0,0,0,0.4)', padding: '2px', borderRadius: '3px' }}>
              {[
                { id: 'ALL', label: 'ALL' },
                { id: 'ERRORS', label: 'ERRORS / DENIED' },
                { id: 'WARNS', label: 'WARNINGS' },
                { id: 'INFO', label: 'INFO' }
              ].map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setLogLevelFilter(tab.id)}
                  style={{
                    background: logLevelFilter === tab.id ? 'var(--accent-cyan)' : 'transparent',
                    color: logLevelFilter === tab.id ? '#000' : 'var(--text-secondary)',
                    border: 'none',
                    padding: '4px 10px',
                    fontSize: '0.7rem',
                    fontFamily: 'Share Tech Mono',
                    cursor: 'pointer',
                    fontWeight: 'bold',
                    borderRadius: '2px'
                  }}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>

          <div className="terminal-logs" style={{ flex: 1, overflowY: 'auto', background: 'rgba(0,0,0,0.6)', padding: '12px', border: '1px solid rgba(0,243,255,0.15)', fontSize: '0.78rem', fontFamily: 'Share Tech Mono' }}>
            {filteredLogLines.length > 0 ? (
              filteredLogLines.map((line, idx) => renderFormattedLogLine(line, idx))
            ) : (
              <div style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: '20px' }}>No log entries matching search filter.</div>
            )}
          </div>
        </section>

        {/* Web Terminal Console Panel */}
        <WebTerminalPanel />

      </div>
    </main>
  );
}

function WebTerminalPanel() {
  const [command, setCommand] = useState('');
  const [terminalOutput, setTerminalOutput] = useState('root@miniserver:~# Type a Linux command and press Enter...');
  const [history, setHistory] = useState([]);
  const [historyIdx, setHistoryIdx] = useState(-1);
  const [executing, setExecuting] = useState(false);

  const handleExecute = async (cmdToRun) => {
    const cmdStr = cmdToRun || command;
    if (!cmdStr.trim()) return;

    setExecuting(true);
    const newHistory = [cmdStr, ...history.filter(h => h !== cmdStr)];
    setHistory(newHistory);
    setHistoryIdx(-1);

    try {
      const res = await axios.post(`/api/metrics/execute-command?command=${encodeURIComponent(cmdStr)}`);
      const outputStr = res.data?.output || res.data?.message || 'No output returned.';
      setTerminalOutput(`root@miniserver:~# ${cmdStr}\n${outputStr}`);
    } catch (err) {
      setTerminalOutput(`root@miniserver:~# ${cmdStr}\nERROR: ${err.message}`);
    } finally {
      setExecuting(false);
      if (!cmdToRun) setCommand('');
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      handleExecute();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (history.length > 0) {
        const nextIdx = Math.min(historyIdx + 1, history.length - 1);
        setHistoryIdx(nextIdx);
        setCommand(history[nextIdx] || '');
      }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (historyIdx > 0) {
        const prevIdx = historyIdx - 1;
        setHistoryIdx(prevIdx);
        setCommand(history[prevIdx] || '');
      } else if (historyIdx === 0) {
        setHistoryIdx(-1);
        setCommand('');
      }
    }
  };

  const copyOutput = () => {
    navigator.clipboard.writeText(terminalOutput);
  };

  return (
    <section className="glass-panel" style={{ padding: '20px', gridColumn: '1 / -1', display: 'flex', flexDirection: 'column', height: '350px' }}>
      <div className="section-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
        <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
          <SciFiTerminalIcon size={20} color="var(--accent-cyan)" /> Interactive Web Terminal Console (&gt;_)
        </h2>
        <div style={{ display: 'flex', gap: '6px' }}>
          <button
            onClick={copyOutput}
            style={{
              background: 'rgba(0, 243, 255, 0.1)',
              border: '1px solid var(--accent-cyan)',
              color: 'var(--accent-cyan)',
              padding: '2px 8px',
              fontSize: '0.7rem',
              fontFamily: 'Share Tech Mono',
              cursor: 'pointer',
              borderRadius: '2px'
            }}
          >
            COPY OUTPUT
          </button>
          <button
            onClick={() => setTerminalOutput('root@miniserver:~# ')}
            style={{
              background: 'rgba(255, 0, 85, 0.1)',
              border: '1px solid var(--accent-pink)',
              color: 'var(--accent-pink)',
              padding: '2px 8px',
              fontSize: '0.7rem',
              fontFamily: 'Share Tech Mono',
              cursor: 'pointer',
              borderRadius: '2px'
            }}
          >
            CLEAR CONSOLE
          </button>
        </div>
      </div>

      {/* Quick Command Chips */}
      <div style={{ display: 'flex', gap: '6px', marginBottom: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>Quick Commands:</span>
        {['uname -a', 'free -h', 'df -h', 'uptime', 'docker ps', 'ss -tulpn', 'whoami'].map(quickCmd => (
          <button
            key={quickCmd}
            onClick={() => { setCommand(quickCmd); handleExecute(quickCmd); }}
            style={{
              background: 'rgba(0, 243, 255, 0.08)',
              border: '1px solid rgba(0, 243, 255, 0.25)',
              color: 'var(--accent-cyan)',
              padding: '2px 7px',
              fontSize: '0.68rem',
              fontFamily: 'Share Tech Mono',
              cursor: 'pointer',
              borderRadius: '2px'
            }}
          >
            {quickCmd}
          </button>
        ))}
      </div>

      {/* Console Output Screen */}
      <div style={{
        flex: 1,
        background: '#030712',
        border: '1px solid rgba(0, 243, 255, 0.2)',
        borderRadius: '4px',
        padding: '10px 14px',
        fontFamily: 'Consolas, Monaco, "Courier New", monospace',
        fontSize: '0.82rem',
        color: 'var(--accent-cyan)',
        overflowY: 'auto',
        whiteSpace: 'pre-wrap',
        marginBottom: '10px'
      }}>
        {executing ? '⚡ Executing command via SSH tunnel...' : terminalOutput}
      </div>

      {/* Console Input Row */}
      <div style={{ display: 'flex', gap: '8px' }}>
        <div style={{
          background: 'rgba(0, 243, 255, 0.1)',
          border: '1px solid var(--accent-cyan)',
          color: 'var(--accent-cyan)',
          padding: '6px 10px',
          fontFamily: 'Share Tech Mono',
          fontSize: '0.8rem',
          fontWeight: 'bold',
          borderRadius: '3px'
        }}>
          root@miniserver:~#
        </div>
        <input
          type="text"
          placeholder="Type command and press Enter (Use ↑/↓ keys for history)..."
          value={command}
          onChange={e => setCommand(e.target.value)}
          onKeyDown={handleKeyDown}
          style={{
            flex: 1,
            background: 'rgba(0,0,0,0.6)',
            border: '1px solid rgba(0,243,255,0.3)',
            color: '#fff',
            padding: '6px 12px',
            fontFamily: 'Share Tech Mono',
            fontSize: '0.82rem',
            borderRadius: '3px'
          }}
        />
        <button
          onClick={() => handleExecute()}
          disabled={executing}
          style={{
            background: 'var(--accent-cyan)',
            color: '#000',
            border: 'none',
            padding: '6px 16px',
            fontWeight: 'bold',
            fontFamily: 'Share Tech Mono',
            cursor: 'pointer',
            borderRadius: '3px'
          }}
        >
          {executing ? '...' : 'RUN'}
        </button>
      </div>
    </section>
  );
}