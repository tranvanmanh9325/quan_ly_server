import React, { useState, useEffect, useRef } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { 
  SciFiDashboardIcon, SciFiPulseIcon, SciFiServerRackIcon, 
  SciFiCyberLockIcon, SciFiPulseBadge, SciFiRefreshIcon, SciFiConsoleIcon,
  SciFiFolderIcon, SciFiContainerIcon, SciFiGlobeIcon, SciFiSettingsIcon,
  SciFiLogoIcon, SciFiBotIcon
} from './SciFiIcons';
import '../App.css';
import '../index.css';
import { removeToken, getUsername } from '../utils/auth';
import { useTranslation, SUPPORTED_LANGS } from '../i18n/index.jsx';

// Compact language switcher for the header bar
function LanguageSwitcher() {
  const { lang, setLang } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const current = SUPPORTED_LANGS.find(l => l.code === lang) || SUPPORTED_LANGS[0];

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen(o => !o)}
        title="Switch language"
        style={{
          display: 'flex', alignItems: 'center', gap: '5px',
          background: open ? 'rgba(0,243,255,0.15)' : 'rgba(0,0,0,0.4)',
          border: `1px solid ${open ? 'var(--accent-cyan)' : 'rgba(0,243,255,0.3)'}`,
          color: 'var(--accent-cyan)', padding: '3px 9px',
          fontSize: '0.72rem', fontFamily: 'Share Tech Mono',
          cursor: 'pointer', borderRadius: '3px',
          transition: 'all 0.2s', outline: 'none',
          boxShadow: open ? '0 0 8px rgba(0,243,255,0.3)' : 'none',
        }}
      >
        <span style={{ fontSize: '0.95rem' }}>{current.flag}</span>
        <span>{current.label}</span>
        <svg width="8" height="5" viewBox="0 0 8 5" fill="none"
          style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s', flexShrink: 0 }}>
          <path d="M1 1L4 4L7 1" stroke="var(--accent-cyan)" strokeWidth="1.2" strokeLinecap="round"/>
        </svg>
      </button>

      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 4px)', right: 0,
          background: 'rgba(5, 10, 20, 0.98)',
          border: '1px solid var(--accent-cyan)',
          borderRadius: '3px', minWidth: '140px',
          boxShadow: '0 8px 32px rgba(0,0,0,0.7), 0 0 16px rgba(0,243,255,0.2)',
          zIndex: 99999, overflow: 'hidden',
          animation: 'langDropIn 0.15s ease',
        }}>
          {SUPPORTED_LANGS.map(l => (
            <div
              key={l.code}
              onClick={() => { setLang(l.code); setOpen(false); }}
              style={{
                display: 'flex', alignItems: 'center', gap: '8px',
                padding: '8px 12px', cursor: 'pointer',
                fontFamily: 'Share Tech Mono', fontSize: '0.78rem',
                color: l.code === lang ? 'var(--accent-cyan)' : 'rgba(255,255,255,0.75)',
                background: l.code === lang ? 'rgba(0,243,255,0.1)' : 'transparent',
                borderLeft: l.code === lang ? '2px solid var(--accent-cyan)' : '2px solid transparent',
                transition: 'all 0.12s',
              }}
              onMouseEnter={e => { if (l.code !== lang) e.currentTarget.style.background = 'rgba(0,243,255,0.06)'; }}
              onMouseLeave={e => { if (l.code !== lang) e.currentTarget.style.background = 'transparent'; }}
            >
              <span style={{ fontSize: '1rem' }}>{l.flag}</span>
              <span>{l.name}</span>
            </div>
          ))}
        </div>
      )}
      <style>{`
        @keyframes langDropIn {
          from { opacity: 0; transform: translateY(-5px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}

export default function Layout({ isAlerting, context }) {
  const navigate = useNavigate();
  const { t } = useTranslation();
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
          zIndex: 10000
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
            width: '42px',
            height: '42px',
            minWidth: '42px',
            borderRadius: '8px',
            background: 'rgba(0, 243, 255, 0.06)',
            border: '1px solid var(--accent-cyan)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 0 16px rgba(0, 243, 255, 0.3), inset 0 0 8px rgba(0, 243, 255, 0.05)'
          }}>
            <SciFiLogoIcon size={30} color="var(--accent-cyan)" />
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
            <span>{t('nav.overview')}</span>
          </NavLink>

          <NavLink to="/processes" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <SciFiPulseIcon size={20} />
            <span>{t('nav.processes')}</span>
          </NavLink>

          <NavLink to="/services" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <SciFiServerRackIcon size={20} />
            <span>{t('nav.services')}</span>
          </NavLink>

          <NavLink to="/files" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <SciFiFolderIcon size={20} />
            <span>{t('nav.fileManager')}</span>
          </NavLink>

          <NavLink to="/containers" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <SciFiContainerIcon size={20} />
            <span>{t('nav.dockerContainers')}</span>
          </NavLink>

          <NavLink to="/map" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <SciFiGlobeIcon size={20} />
            <span>{t('nav.globalMap')}</span>
          </NavLink>

          <NavLink to="/terminal" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <SciFiConsoleIcon size={20} />
            <span>{t('nav.terminal')}</span>
          </NavLink>

          <NavLink to="/security" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <SciFiCyberLockIcon size={20} />
            <span>{t('nav.security')}</span>
          </NavLink>

          <NavLink to="/ai-agents" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <SciFiBotIcon size={20} />
            <span>{t('nav.aiAgents') || 'AI Agents'}</span>
          </NavLink>

          <NavLink to="/settings" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <SciFiSettingsIcon size={20} />
            <span>{t('nav.settings')}</span>
          </NavLink>
        </nav>
      </aside>

      {/* Main Container Area with Top Header Bar */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
        
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
              <span>{isAlerting ? t('header.criticalAlert') : t('header.systemOnline')}</span>
            </div>

            <div style={{ color: 'var(--text-secondary)' }}>
              {t('header.node')}: <span style={{ color: 'var(--accent-cyan)' }}>{sysInfo.hostname || 'localhost'}</span>
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
              <span>{t('header.terminalConsole')}</span>
            </button>

            {/* Refresh Speed Dropdown */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--accent-cyan)' }}>
              <SciFiRefreshIcon size={14} color="var(--accent-cyan)" />
              <span>{t('header.autoRefresh')}:</span>
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
              {t('header.time')}: <span style={{ color: '#fff', fontWeight: 'bold' }}>{clock}</span>
            </div>

            {/* Language Switcher */}
            <LanguageSwitcher />

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
              {t('header.logout')}
            </button>
          </div>

        </header>

        {/* Page Content */}
        <div className="page-content" style={{ flex: 1, overflow: 'hidden', minWidth: 0 }}>
          <Outlet context={{ ...context, refreshSpeed }} />
        </div>
      </div>
    </div>
  );
}