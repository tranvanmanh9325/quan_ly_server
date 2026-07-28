import React, { useState, useEffect, useRef } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { 
  SciFiDashboardIcon, SciFiPulseIcon, SciFiServerRackIcon, 
  SciFiCyberLockIcon, SciFiPulseBadge, SciFiRefreshIcon, SciFiConsoleIcon,
  SciFiFolderIcon, SciFiContainerIcon, SciFiGlobeIcon, SciFiSettingsIcon
} from './SciFiIcons';
import '../App.css';
import '../index.css';
import { removeToken, getUsername } from '../utils/auth';

export default function Layout({ isAlerting, context }) {
  const navigate = useNavigate();
  const [clock, setClock] = useState('');
  const username = getUsername();

  const handleLogout = () => {
    removeToken();
    navigate('/login', { replace: true });
  };

  const [logoutHovered, setLogoutHovered] = useState(false);

  // Terminal Modal state
  const [showTerminal, setShowTerminal] = useState(false);
  const [commandInput, setCommandInput] = useState('');
  const [executing, setExecuting] = useState(false);
  const [terminalHistory, setTerminalHistory] = useState([
    {
      cmd: 'system-init',
      output: 'Cyberpunk Server Terminal Console Initialized.\nType commands like "uname -a", "df -h", "free -m", "docker ps", "uptime" to execute.',
      status: 'success',
      timestamp: new Date().toLocaleTimeString()
    }
  ]);
  const terminalEndRef = useRef(null);

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setClock(now.toLocaleTimeString('en-US', { hour12: false }));
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (showTerminal && terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [terminalHistory, showTerminal]);

  const sysInfo = context?.sysInfo || {};
  const refreshSpeed = context?.refreshSpeed || '10s';
  const setRefreshSpeed = context?.setRefreshSpeed || (() => {});

  const handleRunCommand = async (e) => {
    if (e) e.preventDefault();
    if (!commandInput.trim() || executing) return;

    const cmd = commandInput.trim();
    setCommandInput('');
    setExecuting(true);

    try {
      const res = await axios.post(`/api/metrics/execute-command?command=${encodeURIComponent(cmd)}`);
      const data = res.data || {};
      const outputText = data.output || data.message || 'Command executed with no output.';
      setTerminalHistory(prev => [
        ...prev,
        {
          cmd,
          output: outputText,
          status: data.status === 'success' ? 'success' : 'error',
          timestamp: new Date().toLocaleTimeString()
        }
      ]);
    } catch (err) {
      setTerminalHistory(prev => [
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
    }
  };

  return (
    <div className={`app-layout ${isAlerting ? 'critical-alert' : ''}`}>
      
      {/* Sci-Fi Web Command Terminal Console Modal */}
      {showTerminal && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0, 0, 0, 0.8)',
          backdropFilter: 'blur(8px)',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          zIndex: 99999
        }}>
          <div className="glass-panel" style={{
            width: '820px',
            maxWidth: '92vw',
            height: '540px',
            maxHeight: '90vh',
            display: 'flex',
            flexDirection: 'column',
            border: '1px solid var(--accent-cyan)',
            boxShadow: '0 0 35px rgba(0, 243, 255, 0.25)',
            padding: 0,
            overflow: 'hidden'
          }}>
            {/* Modal Header */}
            <div style={{
              background: 'rgba(0, 243, 255, 0.1)',
              borderBottom: '1px solid rgba(0, 243, 255, 0.3)',
              padding: '10px 16px',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', fontSize: '0.9rem' }}>
                <SciFiConsoleIcon size={18} color="var(--accent-cyan)" />
                <span>TERMINAL CONSOLE — root@{sysInfo.hostname || 'server'}:~#</span>
              </div>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <button
                  onClick={() => setTerminalHistory([])}
                  style={{
                    background: 'rgba(255, 255, 255, 0.08)',
                    border: '1px solid rgba(255, 255, 255, 0.2)',
                    color: '#ccc',
                    fontSize: '0.7rem',
                    fontFamily: 'Share Tech Mono',
                    padding: '2px 8px',
                    cursor: 'pointer'
                  }}
                >
                  CLEAR
                </button>
                <button
                  onClick={() => setShowTerminal(false)}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: 'var(--accent-pink)',
                    fontSize: '1.2rem',
                    cursor: 'pointer',
                    fontWeight: 'bold'
                  }}
                >
                  ✕
                </button>
              </div>
            </div>

            {/* Terminal Body */}
            <div style={{
              flex: 1,
              background: '#040810',
              padding: '14px',
              overflowY: 'auto',
              fontFamily: 'Share Tech Mono, monospace',
              fontSize: '0.82rem',
              lineHeight: '1.5'
            }}>
              {terminalHistory.map((item, idx) => (
                <div key={idx} style={{ marginBottom: '14px' }}>
                  <div style={{ display: 'flex', gap: '8px', color: 'var(--accent-cyan)', fontWeight: 'bold' }}>
                    <span style={{ color: 'var(--accent-green)' }}>root@{sysInfo.hostname || 'server'}:~#</span>
                    <span>{item.cmd}</span>
                    <span style={{ color: 'var(--text-secondary)', fontSize: '0.7rem', marginLeft: 'auto' }}>{item.timestamp}</span>
                  </div>
                  <pre style={{
                    margin: '4px 0 0 0',
                    color: item.status === 'error' ? 'var(--accent-pink)' : 'rgba(255, 255, 255, 0.85)',
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

            {/* Terminal Input Bar */}
            <form onSubmit={handleRunCommand} style={{
              background: 'rgba(0, 0, 0, 0.6)',
              borderTop: '1px solid rgba(0, 243, 255, 0.2)',
              padding: '10px 14px',
              display: 'flex',
              gap: '10px',
              alignItems: 'center'
            }}>
              <span style={{ color: 'var(--accent-green)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', fontSize: '0.85rem' }}>
                root@{sysInfo.hostname || 'server'}:~#
              </span>
              <input
                type="text"
                placeholder="Type command (e.g. uname -a, df -h, free -m, docker ps)..."
                value={commandInput}
                onChange={e => setCommandInput(e.target.value)}
                disabled={executing}
                style={{
                  flex: 1,
                  background: 'rgba(0, 0, 0, 0.4)',
                  border: '1px solid rgba(0, 243, 255, 0.3)',
                  color: '#fff',
                  padding: '6px 10px',
                  fontFamily: 'Share Tech Mono',
                  fontSize: '0.85rem',
                  borderRadius: '3px'
                }}
                autoFocus
              />
              <button
                type="submit"
                disabled={executing || !commandInput.trim()}
                style={{
                  background: 'rgba(0, 243, 255, 0.15)',
                  border: '1px solid var(--accent-cyan)',
                  color: 'var(--accent-cyan)',
                  padding: '6px 16px',
                  fontFamily: 'Share Tech Mono',
                  fontSize: '0.8rem',
                  fontWeight: 'bold',
                  cursor: 'pointer'
                }}
              >
                {executing ? 'RUNNING...' : 'RUN'}
              </button>
            </form>
          </div>
        </div>
      )}

      {/* Sci-Fi Sidebar */}
      <aside className="sci-fi-sidebar">
        <div className="sidebar-logo" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            width: '38px',
            height: '38px',
            minWidth: '38px',
            borderRadius: '6px',
            background: 'rgba(0, 243, 255, 0.08)',
            border: '1px solid var(--accent-cyan)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 0 12px rgba(0, 243, 255, 0.25)'
          }}>
            <svg width="26" height="26" viewBox="0 0 64 64" fill="none">
              <polygon points="32,4 58,19 58,45 32,60 6,45 6,19" fill="rgba(5,8,16,0.9)" stroke="var(--accent-cyan)" strokeWidth="3.5" strokeLinejoin="round" />
              <polygon points="32,10 52,21.5 52,42.5 32,54 12,42.5 12,21.5" fill="none" stroke="var(--accent-cyan)" strokeWidth="1" strokeDasharray="4,2" opacity="0.5" />
              <path d="M20 21 H44 M20 28 H44 M20 35 H44 M20 42 H44" stroke="var(--accent-cyan)" strokeWidth="3" strokeLinecap="round" />
              <circle cx="26" cy="21" r="2.5" fill="var(--accent-green)" />
              <circle cx="38" cy="28" r="2.5" fill="var(--accent-cyan)" />
              <circle cx="26" cy="35" r="2.5" fill="var(--accent-green)" />
              <circle cx="38" cy="42" r="2.5" fill="var(--accent-cyan)" />
            </svg>
          </div>
          <div>
            <h1 className="title-glow" style={{ fontSize: '1.2rem', letterSpacing: '2px', margin: 0, lineHeight: 1.15 }}>
              SERVER<br/>DASHBOARD
            </h1>
          </div>
        </div>

        <nav className="sidebar-nav">
          <NavLink to="/" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`} end>
            <SciFiDashboardIcon size={20} />
            <span>Overview</span>
          </NavLink>

          <NavLink to="/processes" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <SciFiPulseIcon size={20} />
            <span>Processes</span>
          </NavLink>

          <NavLink to="/services" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <SciFiServerRackIcon size={20} />
            <span>Services</span>
          </NavLink>

          <NavLink to="/files" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <SciFiFolderIcon size={20} />
            <span>File Manager</span>
          </NavLink>

          <NavLink to="/containers" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <SciFiContainerIcon size={20} />
            <span>Docker Containers</span>
          </NavLink>

          <NavLink to="/map" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <SciFiGlobeIcon size={20} />
            <span>Global Map</span>
          </NavLink>

          <NavLink to="/terminal" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <SciFiConsoleIcon size={20} />
            <span>Terminal Console</span>
          </NavLink>

          <NavLink to="/security" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <SciFiCyberLockIcon size={20} />
            <span>Security & Logs</span>
          </NavLink>

          <NavLink to="/settings" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <SciFiSettingsIcon size={20} />
            <span>Settings</span>
          </NavLink>
        </nav>
      </aside>

      {/* Main Container Area with Top Header Bar */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        
        {/* Sci-Fi Top Operational Header Bar */}
        <header style={{
          height: '48px',
          background: 'rgba(5, 10, 20, 0.75)',
          backdropFilter: 'blur(8px)',
          borderBottom: isAlerting ? '1px solid var(--accent-pink)' : '1px solid rgba(0, 243, 255, 0.2)',
          boxShadow: isAlerting ? '0 0 15px rgba(255,0,85,0.4)' : '0 2px 10px rgba(0,0,0,0.5)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '0 24px',
          zIndex: 10,
          fontSize: '0.8rem',
          fontFamily: 'Share Tech Mono'
        }}>
          
          {/* Left: System Status & Host Node */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '3px 10px',
              borderRadius: '3px',
              background: isAlerting ? 'rgba(255, 0, 85, 0.15)' : 'rgba(0, 255, 157, 0.1)',
              border: isAlerting ? '1px solid var(--accent-pink)' : '1px solid var(--accent-green)',
              color: isAlerting ? 'var(--accent-pink)' : 'var(--accent-green)',
              fontWeight: 'bold'
            }}>
              <SciFiPulseBadge size={14} color={isAlerting ? 'var(--accent-pink)' : 'var(--accent-green)'} />
              <span>{isAlerting ? 'CRITICAL ALERT' : 'SYSTEM STATUS: ONLINE'}</span>
            </div>

            <div style={{ color: 'var(--text-secondary)' }}>
              NODE: <span style={{ color: 'var(--accent-cyan)' }}>{sysInfo.hostname || 'localhost'}</span>
              {sysInfo.os && <span style={{ marginLeft: '8px', opacity: 0.7 }}>({sysInfo.os})</span>}
            </div>
          </div>

          {/* Right: Terminal Console Button, Auto-Refresh Selector, Live Clock */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            
            {/* Terminal Console Trigger Button */}
            <button
              onClick={() => setShowTerminal(true)}
              style={{
                background: 'rgba(0, 243, 255, 0.1)',
                border: '1px solid var(--accent-cyan)',
                color: 'var(--accent-cyan)',
                padding: '4px 10px',
                fontSize: '0.75rem',
                fontFamily: 'Share Tech Mono',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                borderRadius: '3px'
              }}
              title="Open Web SSH Terminal Console"
            >
              <SciFiConsoleIcon size={14} color="var(--accent-cyan)" />
              <span>TERMINAL CONSOLE</span>
            </button>

            {/* Refresh Speed Dropdown */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--accent-cyan)' }}>
              <SciFiRefreshIcon size={14} color="var(--accent-cyan)" />
              <span>AUTO-REFRESH:</span>
              <select
                value={refreshSpeed}
                onChange={e => setRefreshSpeed(e.target.value)}
                style={{
                  background: 'rgba(0,0,0,0.6)',
                  border: '1px solid rgba(0, 243, 255, 0.3)',
                  color: 'var(--accent-cyan)',
                  padding: '2px 6px',
                  fontSize: '0.75rem',
                  fontFamily: 'Share Tech Mono',
                  borderRadius: '3px',
                  cursor: 'pointer'
                }}
              >
                <option value="5s">5s (FAST)</option>
                <option value="10s">10s (NORMAL)</option>
                <option value="15s">15s (SLOW)</option>
                <option value="30s">30s (ECO)</option>
                <option value="PAUSE">PAUSED</option>
              </select>
            </div>

            <div style={{ color: 'var(--text-secondary)', borderLeft: '1px solid rgba(255,255,255,0.1)', paddingLeft: '16px' }}>
              TIME: <span style={{ color: '#fff', fontWeight: 'bold' }}>{clock}</span>
            </div>

            {/* Logout */}
            <button
              id="header-logout-btn"
              onClick={handleLogout}
              title={`Logged in as ${username || 'unknown'} — click to logout`}
              onMouseEnter={() => setLogoutHovered(true)}
              onMouseLeave={() => setLogoutHovered(false)}
              style={{
                background: logoutHovered ? 'rgba(255,0,85,0.15)' : 'transparent',
                border: '1px solid rgba(255,0,85,0.4)',
                color: logoutHovered ? 'var(--accent-pink)' : 'rgba(255,0,85,0.7)',
                padding: '4px 10px',
                fontSize: '0.7rem',
                fontFamily: 'Share Tech Mono',
                letterSpacing: '1px',
                cursor: 'pointer',
                borderRadius: '3px',
                transition: 'all 0.2s',
              }}
            >
              LOGOUT
            </button>
          </div>

        </header>

        {/* Page Content */}
        <div className="page-content" style={{ flex: 1, overflow: 'hidden' }}>
          <Outlet context={{ ...context, refreshSpeed }} />
        </div>
      </div>
    </div>
  );
}