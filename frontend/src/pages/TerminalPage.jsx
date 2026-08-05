import React, { useState, useEffect, useRef } from 'react';
import { useOutletContext } from 'react-router-dom';
import axios from 'axios';
import { SciFiConsoleIcon, SciFiDownloadIcon, SciFiRefreshIcon, SciFiLightningIcon } from '../components/SciFiIcons';

export default function TerminalPage() {
  const context = useOutletContext();
  const sysInfo = context?.sysInfo || {};

  const [commandInput, setCommandInput] = useState('');
  const [executing, setExecuting] = useState(false);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const [cmdHistoryList, setCmdHistoryList] = useState([]); // List of string commands for up/down arrow navigation
  
  const [terminalOutputHistory, setTerminalOutputHistory] = useState([
    {
      cmd: 'system-init',
      output: `====================================================================
CYBERPUNK SERVER SSH WEB TERMINAL CONSOLE INITIALIZED
Connected to Node: ${sysInfo.hostname || 'remote-host'} (${sysInfo.os || 'Linux'})
Type commands or click Quick Macro chips to execute diagnostic operations.
====================================================================`,
      status: 'success',
      timestamp: new Date().toLocaleTimeString()
    }
  ]);

  const terminalEndRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [terminalOutputHistory]);

  const runCommand = async (cmdToRun) => {
    const cmd = (cmdToRun || commandInput).trim();
    if (!cmd || executing) return;

    setCommandInput('');
    setExecuting(true);
    setHistoryIndex(-1);

    // Save to cmd history list if not duplicate of last
    setCmdHistoryList(prev => {
      if (prev[prev.length - 1] !== cmd) {
        return [...prev, cmd];
      }
      return prev;
    });

    try {
      const res = await axios.post(`/api/metrics/execute-command?command=${encodeURIComponent(cmd)}`);
      const data = res.data || {};
      const outputText = data.output || data.message || 'Command executed with no output.';
      
      setTerminalOutputHistory(prev => [
        ...prev,
        {
          cmd,
          output: outputText,
          status: data.status === 'success' ? 'success' : 'error',
          timestamp: new Date().toLocaleTimeString()
        }
      ]);
    } catch (err) {
      setTerminalOutputHistory(prev => [
        ...prev,
        {
          cmd,
          output: `Execution error: ${err.message}`,
          status: 'error',
          timestamp: new Date().toLocaleTimeString()
        }
      ]);
    } finally {
      setExecuting(false);
      if (inputRef.current) inputRef.current.focus();
    }
  };

  const handleSubmit = (e) => {
    if (e) e.preventDefault();
    runCommand(commandInput);
  };

  const handleKeyDown = (e) => {
    if (cmdHistoryList.length === 0) return;

    if (e.key === 'ArrowUp') {
      e.preventDefault();
      const nextIdx = historyIndex === -1 ? cmdHistoryList.length - 1 : Math.max(0, historyIndex - 1);
      setHistoryIndex(nextIdx);
      setCommandInput(cmdHistoryList[nextIdx] || '');
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (historyIndex >= 0) {
        const nextIdx = historyIndex + 1;
        if (nextIdx >= cmdHistoryList.length) {
          setHistoryIndex(-1);
          setCommandInput('');
        } else {
          setHistoryIndex(nextIdx);
          setCommandInput(cmdHistoryList[nextIdx] || '');
        }
      }
    }
  };

  const handleExportConsole = () => {
    const text = terminalOutputHistory.map(item => `[${item.timestamp}] root@server:~# ${item.cmd}\n${item.output}\n`).join('\n----------------------------------------\n');
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `ssh-terminal-log-${Date.now()}.txt`;
    link.click();
    URL.revokeObjectURL(url);
  };

  // Quick Command Macro Categories
  const macroGroups = [
    {
      group: 'SYSTEM & KERNEL',
      macros: [
        { label: 'uname -a', cmd: 'uname -a' },
        { label: 'uptime', cmd: 'uptime' },
        { label: 'whoami', cmd: 'whoami' },
        { label: 'hostnamectl', cmd: 'hostnamectl' },
        { label: 'syslog tail', cmd: 'tail -n 20 /var/log/syslog 2>/dev/null || dmesg | tail -n 20' }
      ]
    },
    {
      group: 'DISK & RAM',
      macros: [
        { label: 'df -h', cmd: 'df -h -x tmpfs -x devtmpfs' },
        { label: 'free -h', cmd: 'free -h' },
        { label: 'lsblk', cmd: 'lsblk' },
        { label: 'top cpu', cmd: 'ps aux --sort=-%cpu | head -n 10' },
        { label: 'top ram', cmd: 'ps aux --sort=-%mem | head -n 10' }
      ]
    },
    {
      group: 'NETWORK & PORTS',
      macros: [
        { label: 'ss -tulpn', cmd: 'ss -tulpn' },
        { label: 'ip addr', cmd: 'ip a' },
        { label: 'who logins', cmd: 'who' },
        { label: 'ping google', cmd: 'ping -c 3 google.com' }
      ]
    },
    {
      group: 'SERVICES & DOCKER',
      macros: [
        { label: 'docker ps', cmd: 'docker ps -a' },
        { label: 'docker stats', cmd: 'docker stats --no-stream' },
        { label: 'systemctl failed', cmd: 'systemctl --failed' },
        { label: 'timers', cmd: 'systemctl list-timers' }
      ]
    }
  ];

  return (
    <div style={{ padding: '20px', height: '100%', display: 'flex', flexDirection: 'column', gap: '16px', overflow: 'hidden' }}>
      
      {/* Header Bar */}
      <div className="glass-panel" style={{ padding: '14px 20px', display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <SciFiConsoleIcon size={26} color="var(--accent-cyan)" />
          <div>
            <h2 className="title-glow" style={{ margin: 0, fontSize: '1.2rem', letterSpacing: '1px' }}>
              INTERACTIVE SSH WEB TERMINAL CONSOLE
            </h2>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>
              DIRECT ROOT SHELL DIAGNOSTICS & EXECUTION ENGINE
            </span>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <button
            onClick={handleExportConsole}
            style={{
              background: 'rgba(0, 243, 255, 0.1)',
              border: '1px solid var(--accent-cyan)',
              color: 'var(--accent-cyan)',
              padding: '6px 12px',
              fontFamily: 'Share Tech Mono',
              fontSize: '0.78rem',
              fontWeight: 'bold',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              borderRadius: '3px'
            }}
          >
            <SciFiDownloadIcon size={14} color="var(--accent-cyan)" />
            <span>EXPORT TRANSCRIPT</span>
          </button>

          <button
            onClick={() => setTerminalOutputHistory([])}
            style={{
              background: 'rgba(255, 0, 85, 0.1)',
              border: '1px solid var(--accent-pink)',
              color: 'var(--accent-pink)',
              padding: '6px 12px',
              fontFamily: 'Share Tech Mono',
              fontSize: '0.78rem',
              fontWeight: 'bold',
              cursor: 'pointer',
              borderRadius: '3px'
            }}
          >
            CLEAR CONSOLE
          </button>
        </div>
      </div>

      {/* Quick Command Macro Bar */}
      <div className="glass-panel" style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div style={{ fontSize: '0.75rem', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <SciFiLightningIcon size={18} color="var(--accent-cyan)" />
          <span>QUICK COMMAND MACRO CHIPS (1-CLICK EXECUTE):</span>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
          {macroGroups.map((grp, gIdx) => (
            <div key={gIdx} style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
              <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono', opacity: 0.8 }}>
                [{grp.group}]:
              </span>
              {grp.macros.map((m, mIdx) => (
                <button
                  key={mIdx}
                  onClick={() => runCommand(m.cmd)}
                  disabled={executing}
                  style={{
                    background: 'rgba(0, 0, 0, 0.5)',
                    border: '1px solid rgba(0, 243, 255, 0.25)',
                    color: '#fff',
                    padding: '3px 8px',
                    fontSize: '0.72rem',
                    fontFamily: 'Share Tech Mono',
                    cursor: 'pointer',
                    borderRadius: '3px',
                    transition: 'all 0.15s'
                  }}
                  onMouseEnter={e => e.target.style.borderColor = 'var(--accent-cyan)'}
                  onMouseLeave={e => e.target.style.borderColor = 'rgba(0, 243, 255, 0.25)'}
                >
                  {m.label}
                </button>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Main Terminal Screen */}
      <div className="glass-panel" style={{ flex: 1, padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column', border: '1px solid var(--accent-cyan)' }}>
        
        {/* Terminal Header Info Bar */}
        <div style={{
          background: 'rgba(0, 243, 255, 0.08)',
          borderBottom: '1px solid rgba(0, 243, 255, 0.2)',
          padding: '8px 16px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          fontSize: '0.8rem',
          fontFamily: 'Share Tech Mono'
        }}>
          <div style={{ color: 'var(--accent-cyan)', fontWeight: 'bold' }}>
            SSH CONSOLE — root@{sysInfo.hostname || 'server'}:~#
          </div>
          <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
            Use ↑ / ↓ arrow keys for command history
          </div>
        </div>

        {/* Console Buffer Window */}
        <div style={{
          flex: 1,
          background: '#040810',
          padding: '16px',
          overflowY: 'auto',
          fontFamily: 'Share Tech Mono, monospace',
          fontSize: '0.85rem',
          lineHeight: '1.5'
        }}>
          {terminalOutputHistory.map((item, idx) => (
            <div key={idx} style={{ marginBottom: '16px' }}>
              <div style={{ display: 'flex', gap: '8px', color: 'var(--accent-cyan)', fontWeight: 'bold' }}>
                <span style={{ color: 'var(--accent-green)' }}>root@{sysInfo.hostname || 'server'}:~#</span>
                <span>{item.cmd}</span>
                <span style={{ color: 'var(--text-secondary)', fontSize: '0.72rem', marginLeft: 'auto' }}>{item.timestamp}</span>
              </div>
              <pre style={{
                margin: '4px 0 0 0',
                color: item.status === 'error' ? 'var(--accent-pink)' : 'rgba(255, 255, 255, 0.88)',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
                fontFamily: 'inherit'
              }}>
                {item.output}
              </pre>
            </div>
          ))}
          <div ref={terminalEndRef} />
        </div>

        {/* Input Bar */}
        <form onSubmit={handleSubmit} style={{
          background: 'rgba(0, 0, 0, 0.6)',
          borderTop: '1px solid rgba(0, 243, 255, 0.25)',
          padding: '10px 16px',
          display: 'flex',
          gap: '10px',
          alignItems: 'center'
        }}>
          <span style={{ color: 'var(--accent-green)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', fontSize: '0.9rem' }}>
            root@{sysInfo.hostname || 'server'}:~#
          </span>
          <input
            ref={inputRef}
            type="text"
            placeholder="Type SSH command (e.g., uname -a, df -h, free -m, docker ps)..."
            value={commandInput}
            onChange={e => setCommandInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={executing}
            style={{
              flex: 1,
              background: 'rgba(0, 0, 0, 0.5)',
              border: '1px solid rgba(0, 243, 255, 0.35)',
              color: '#fff',
              padding: '8px 12px',
              fontFamily: 'Share Tech Mono',
              fontSize: '0.9rem',
              borderRadius: '3px'
            }}
            autoFocus
          />
          <button
            type="submit"
            disabled={executing || !commandInput.trim()}
            style={{
              background: 'rgba(0, 243, 255, 0.2)',
              border: '1px solid var(--accent-cyan)',
              color: 'var(--accent-cyan)',
              padding: '8px 20px',
              fontFamily: 'Share Tech Mono',
              fontSize: '0.85rem',
              fontWeight: 'bold',
              cursor: executing || !commandInput.trim() ? 'not-allowed' : 'pointer',
              borderRadius: '3px'
            }}
          >
            {executing ? 'RUNNING...' : 'EXECUTE'}
          </button>
        </form>

      </div>

    </div>
  );
}
