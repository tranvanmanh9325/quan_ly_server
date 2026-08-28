import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import {
  SciFiSettingsIcon, SciFiRefreshIcon, SciFiPulseBadge,
  SciFiConsoleIcon, SciFiCyberLockIcon, SciFiDashboardIcon,
  SciFiInfoIcon, SciFiTerminalPromptIcon,
  SciFiQuantumIcon
} from '../components/SciFiIcons';
import { loadSettings, saveSettings, SETTINGS_DEFAULTS } from '../utils/settings';
import { useTranslation } from '../i18n/index.jsx';


// ── Sub-components ──────────────────────────────────────────────────────────
const SectionHeader = ({ icon, title, subtitle, badge }) => (
  <div style={{ marginBottom: '20px' }}>
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        {icon}
        <h2 style={{ fontSize: '1rem', letterSpacing: '3px', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', margin: 0 }}>
          {title}
        </h2>
      </div>
      {badge && <div>{badge}</div>}
    </div>
    {subtitle && (
      <p style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', marginLeft: '30px', opacity: 0.7 }}>
        {subtitle}
      </p>
    )}
    <div style={{ height: '1px', background: 'linear-gradient(90deg, var(--accent-cyan) 0%, transparent 70%)', marginTop: '10px', opacity: 0.4 }} />
  </div>
);

const SettingRow = ({ label, desc, children }) => (
  <div style={{
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '12px 0',
    borderBottom: '1px solid rgba(0, 243, 255, 0.06)',
  }}>
    <div style={{ flex: 1 }}>
      <div style={{ fontSize: '0.88rem', color: 'var(--text-primary)', letterSpacing: '0.5px' }}>{label}</div>
      {desc && <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', opacity: 0.6, marginTop: '2px' }}>{desc}</div>}
    </div>
    <div style={{ marginLeft: '20px', flexShrink: 0 }}>{children}</div>
  </div>
);

// Sci-fi toggle switch
const Toggle = ({ value, onChange, id }) => (
  <label htmlFor={id} style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
    <div style={{ position: 'relative', width: '44px', height: '22px' }}>
      <input
        id={id}
        type="checkbox"
        checked={value}
        onChange={e => onChange(e.target.checked)}
        style={{ opacity: 0, width: 0, height: 0, position: 'absolute' }}
      />
      <div style={{
        position: 'absolute', inset: 0,
        background: value ? 'rgba(0, 243, 255, 0.25)' : 'rgba(255,255,255,0.06)',
        border: value ? '1px solid var(--accent-cyan)' : '1px solid rgba(255,255,255,0.15)',
        borderRadius: '2px',
        transition: 'all 0.25s ease',
        boxShadow: value ? '0 0 8px rgba(0,243,255,0.4)' : 'none',
      }} />
      <div style={{
        position: 'absolute',
        top: '3px',
        left: value ? '24px' : '3px',
        width: '14px', height: '14px',
        background: value ? 'var(--accent-cyan)' : 'rgba(255,255,255,0.3)',
        borderRadius: '1px',
        transition: 'all 0.25s ease',
        boxShadow: value ? '0 0 6px var(--accent-cyan)' : 'none',
      }} />
    </div>
    <span style={{ fontSize: '0.75rem', color: value ? 'var(--accent-cyan)' : 'var(--text-secondary)', fontFamily: 'Share Tech Mono', minWidth: '32px' }}>
      {value ? 'ON' : 'OFF'}
    </span>
  </label>
);

// Threshold slider with current value readout
const ThresholdSlider = ({ value, onChange, id, unit = '%', min = 50, max = 100, color = 'var(--accent-cyan)' }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
    <input
      id={id}
      type="range"
      min={min}
      max={max}
      value={value}
      onChange={e => onChange(Number(e.target.value))}
      style={{
        width: '140px',
        accentColor: color,
        cursor: 'pointer',
      }}
    />
    <span style={{
      fontFamily: 'Share Tech Mono', fontSize: '0.85rem',
      color: value >= 90 ? 'var(--accent-pink)' : value >= 80 ? 'var(--accent-yellow)' : 'var(--accent-green)',
      minWidth: '42px',
      textAlign: 'right',
      textShadow: `0 0 8px currentColor`,
    }}>
      {value}{unit}
    </span>
  </div>
);

// Sci-fi styled custom dropdown — replaces native <select> for consistent theming
const SciFiSelect = ({ value, onChange, options, color = 'var(--accent-purple)' }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const selected = options.find(o => o.value === value) || options[0];

  // Close on outside click
  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <div ref={ref} style={{ position: 'relative', userSelect: 'none' }}>
      {/* Trigger button */}
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display: 'flex', alignItems: 'center', gap: '10px',
          background: open ? 'rgba(187,0,255,0.15)' : 'rgba(0,0,0,0.55)',
          border: `1px solid ${open ? color : 'rgba(187,0,255,0.35)'}`,
          borderRadius: '3px',
          padding: '6px 12px',
          cursor: 'pointer',
          fontFamily: 'Share Tech Mono',
          fontSize: '0.82rem',
          color,
          minWidth: '170px',
          justifyContent: 'space-between',
          transition: 'all 0.2s ease',
          boxShadow: open ? `0 0 10px ${color}55` : 'none',
          outline: 'none',
        }}
      >
        <span>{selected.label}</span>
        {/* Animated chevron */}
        <svg
          width="10" height="6" viewBox="0 0 10 6" fill="none"
          style={{ transition: 'transform 0.2s ease', transform: open ? 'rotate(180deg)' : 'rotate(0deg)', flexShrink: 0 }}
        >
          <path d="M1 1L5 5L9 1" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {/* Dropdown list */}
      {open && (
        <div style={{
          position: 'absolute',
          top: 'calc(100% + 4px)',
          left: 0,
          right: 0,
          background: 'rgba(8, 4, 20, 0.97)',
          border: `1px solid ${color}`,
          borderRadius: '3px',
          boxShadow: `0 8px 32px rgba(0,0,0,0.7), 0 0 16px ${color}44`,
          zIndex: 9999,
          overflow: 'hidden',
          animation: 'scifiDropIn 0.15s ease',
        }}>
          {options.map(opt => {
            const isSelected = opt.value === value;
            return (
              <div
                key={opt.value}
                onClick={() => { onChange(opt.value); setOpen(false); }}
                style={{
                  display: 'flex', alignItems: 'center', gap: '8px',
                  padding: '9px 12px',
                  fontFamily: 'Share Tech Mono',
                  fontSize: '0.82rem',
                  color: isSelected ? color : 'var(--text-primary)',
                  background: isSelected ? `${color}22` : 'transparent',
                  borderLeft: isSelected ? `2px solid ${color}` : '2px solid transparent',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                }}
                onMouseEnter={e => {
                  if (!isSelected) {
                    e.currentTarget.style.background = 'rgba(187,0,255,0.1)';
                    e.currentTarget.style.color = color;
                  }
                }}
                onMouseLeave={e => {
                  if (!isSelected) {
                    e.currentTarget.style.background = 'transparent';
                    e.currentTarget.style.color = 'var(--text-primary)';
                  }
                }}
              >
                {/* Active indicator dot */}
                <div style={{
                  width: '5px', height: '5px', borderRadius: '50%', flexShrink: 0,
                  background: isSelected ? color : 'transparent',
                  boxShadow: isSelected ? `0 0 6px ${color}` : 'none',
                  transition: 'all 0.15s',
                }} />
                {opt.label}
              </div>
            );
          })}
        </div>
      )}

      {/* Keyframe for dropdown animation */}
      <style>{`
        @keyframes scifiDropIn {
          from { opacity: 0; transform: translateY(-6px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
};

// ── Main Component ──────────────────────────────────────────────────────────
export default function SettingsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [settings, setSettings] = useState(loadSettings);
  const [saved, setSaved] = useState(false);
  const [connStatus, setConnStatus] = useState('checking');
  const [connInfo, setConnInfo] = useState(null);

  // ── 9Router AI Gateway Telemetry state ──────────────────────────────────
  const [routerStatus, setRouterStatus]   = useState(null);
  const [routerLoading, setRouterLoading] = useState(true);

  const fetchRouterStatus = useCallback(() => {
    axios.get('/api/ai/router/status')
      .then(res => setRouterStatus(res.data))
      .catch(() => {})
      .finally(() => setRouterLoading(false));
  }, []);

  useEffect(() => {
    fetchRouterStatus();
    const timer = setInterval(fetchRouterStatus, 20000);
    return () => clearInterval(timer);
  }, [fetchRouterStatus]);

  // Ping backend to check SSH connection health
  useEffect(() => {
    axios.get('/api/metrics/system')
      .then(res => {
        setConnStatus('ok');
        setConnInfo(res.data?.data || null);
      })
      .catch(() => setConnStatus('error'));
  }, []);

  const update = useCallback((key, val) => {
    setSettings(prev => ({ ...prev, [key]: val }));
    setSaved(false);
  }, []);

  const handleSave = () => {
    saveSettings(settings);
    // Apply effects immediately via CSS custom props / class toggling
    document.documentElement.style.setProperty(
      '--scanline-opacity', settings.scanlineEffect ? '1' : '0'
    );
    document.body.classList.toggle('no-grid', !settings.gridBackground);
    // Dispatch custom event so SpaceInteractionLayer can react
    window.dispatchEvent(new CustomEvent('srvdash:settings', { detail: settings }));
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  const handleReset = () => {
    setSettings({ ...SETTINGS_DEFAULTS });
    setSaved(false);
  };

  // Card wrapper style
  const card = {
    background: 'rgba(9, 10, 15, 0.6)',
    border: '1px solid rgba(0, 243, 255, 0.15)',
    padding: '24px 28px',
    marginBottom: '20px',
    position: 'relative',
    backdropFilter: 'blur(6px)',
    clipPath: 'polygon(0 0, calc(100% - 16px) 0, 100% 16px, 100% 100%, 16px 100%, 0 calc(100% - 16px))',
  };

  const connColor = connStatus === 'ok' ? 'var(--accent-green)' : connStatus === 'error' ? 'var(--accent-pink)' : 'var(--accent-yellow)';
  const connLabel = connStatus === 'ok' ? t('settings.ssh.connected') : connStatus === 'error' ? t('settings.ssh.disconnected') : t('settings.ssh.checking');

  return (
    <div style={{ padding: '24px 28px', overflowY: 'auto', height: '100%', boxSizing: 'border-box' }}>
      <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
      {/* Page Header */}
      <div style={{ marginBottom: '28px', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '6px' }}>
            <SciFiSettingsIcon size={24} color="var(--accent-cyan)" />
            <h1 className="title-glow" style={{ fontSize: '1.4rem', letterSpacing: '4px', margin: 0 }}>
              SYSTEM SETTINGS
            </h1>
          </div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', fontFamily: 'Share Tech Mono', opacity: 0.7, marginLeft: '36px' }}>
            CONFIGURATION — PREFERENCES — THRESHOLDS
          </p>
        </div>

        {/* Save button */}
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <button
            onClick={handleReset}
            style={{
              background: 'rgba(255,0,85,0.08)',
              border: '1px solid rgba(255,0,85,0.4)',
              color: 'var(--accent-pink)',
              padding: '8px 18px',
              fontFamily: 'Share Tech Mono',
              fontSize: '0.78rem',
              cursor: 'pointer',
              letterSpacing: '1px',
            }}
          >
            {t('settings.reset')}
          </button>
          <button
            onClick={handleSave}
            style={{
              background: saved ? 'rgba(0,255,102,0.15)' : 'rgba(0,243,255,0.12)',
              border: `1px solid ${saved ? 'var(--accent-green)' : 'var(--accent-cyan)'}`,
              color: saved ? 'var(--accent-green)' : 'var(--accent-cyan)',
              padding: '8px 24px',
              fontFamily: 'Share Tech Mono',
              fontSize: '0.78rem',
              cursor: 'pointer',
              letterSpacing: '1px',
              boxShadow: saved ? '0 0 12px rgba(0,255,102,0.3)' : '0 0 8px rgba(0,243,255,0.2)',
              transition: 'all 0.3s ease',
            }}
          >
            {saved ? t('settings.saved') : t('settings.save')}
          </button>
        </div>
      </div>

      {/* ── Section 1: Connection Status ────────────────────────────────── */}
      <div style={card}>
        <SectionHeader
          icon={<SciFiConsoleIcon size={18} color="var(--accent-cyan)" />}
          title={t('settings.ssh.title')}
          subtitle={t('settings.ssh.subtitle')}
        />

        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginBottom: '16px' }}>
          <SciFiPulseBadge size={16} color={connColor} />
          <span style={{ fontFamily: 'Share Tech Mono', fontSize: '0.85rem', color: connColor, textShadow: `0 0 8px ${connColor}` }}>
            {connLabel}
          </span>
          {connStatus === 'ok' && connInfo && (
            <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', opacity: 0.7 }}>
              — {connInfo.hostname || 'remote-server'}
            </span>
          )}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
          {[
            { label: 'SSH HOST', value: import.meta.env.VITE_SSH_HOST || '(from .env)', masked: false },
            { label: 'SSH USER', value: import.meta.env.VITE_SSH_USER || '(from .env)', masked: false },
            { label: 'SSH PORT', value: '22', masked: false },
            { label: 'SSH PASSWORD', value: '••••••••', masked: true },
          ].map(item => (
            <div key={item.label} style={{
              background: 'rgba(0,0,0,0.3)',
              border: '1px solid rgba(0, 243, 255, 0.1)',
              padding: '10px 14px',
            }}>
              <div style={{ fontSize: '0.65rem', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', letterSpacing: '2px', marginBottom: '4px', opacity: 0.7 }}>
                {item.label}
              </div>
              <div style={{ fontSize: '0.85rem', color: item.masked ? 'var(--text-secondary)' : 'var(--text-primary)', fontFamily: 'Share Tech Mono' }}>
                {item.value}
              </div>
            </div>
          ))}
        </div>
        <p style={{ marginTop: '12px', fontSize: '0.7rem', color: 'var(--text-secondary)', opacity: 0.5, fontFamily: 'Share Tech Mono' }}>
          {t('settings.ssh.note')}
        </p>
      </div>

      {/* ── Section 2: Polling & Performance ──────────────────────────────── */}
      <div style={card}>
        <SectionHeader
          icon={<SciFiRefreshIcon size={18} color="var(--accent-cyan)" />}
          title={t('settings.polling.title')}
          subtitle={t('settings.polling.subtitle')}
        />

        <SettingRow label={t('settings.polling.label')} desc={t('settings.polling.desc')}>
          <select
            value={settings.refreshSpeed}
            onChange={e => update('refreshSpeed', e.target.value)}
            style={{
              background: 'rgba(0,0,0,0.6)',
              border: '1px solid rgba(0, 243, 255, 0.3)',
              color: 'var(--accent-cyan)',
              padding: '5px 10px',
              fontSize: '0.8rem',
              fontFamily: 'Share Tech Mono',
              cursor: 'pointer',
              minWidth: '140px',
            }}
          >
            <option value="5s">5s — FAST</option>
            <option value="10s">10s — NORMAL</option>
            <option value="15s">15s — SLOW</option>
            <option value="30s">30s — ECO</option>
            <option value="PAUSE">PAUSED</option>
          </select>
        </SettingRow>
      </div>

      {/* ── Section 3: Alert Thresholds ────────────────────────────────────── */}
      <div style={card}>
        <SectionHeader
          icon={<SciFiCyberLockIcon size={18} color="var(--accent-cyan)" />}
          title={t('settings.alerts.title')}
          subtitle={t('settings.alerts.subtitle')}
        />

        <SettingRow label={t('settings.alerts.cpu')} desc={t('settings.alerts.cpuDesc')}>
          <ThresholdSlider id="cpu-threshold" value={settings.cpuThreshold}
            onChange={v => update('cpuThreshold', v)} color="var(--accent-cyan)" />
        </SettingRow>

        <SettingRow label={t('settings.alerts.ram')} desc={t('settings.alerts.ramDesc')}>
          <ThresholdSlider id="ram-threshold" value={settings.ramThreshold}
            onChange={v => update('ramThreshold', v)} color="var(--accent-purple)" />
        </SettingRow>

        <SettingRow label={t('settings.alerts.disk')} desc={t('settings.alerts.diskDesc')}>
          <ThresholdSlider id="disk-threshold" value={settings.diskThreshold}
            onChange={v => update('diskThreshold', v)} color="var(--accent-yellow)" />
        </SettingRow>

        {/* Alert preview */}
        <div style={{
          marginTop: '16px', padding: '10px 14px',
          background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(0, 243, 255, 0.08)',
          fontSize: '0.72rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono', opacity: 0.7,
        }}>
          {t('settings.alerts.preview', { cpu: settings.cpuThreshold, ram: settings.ramThreshold, disk: settings.diskThreshold })}
        </div>
      </div>

      {/* ── Section 4: Display & Effects ──────────────────────────────────── */}
      <div style={card}>
        <SectionHeader
          icon={<SciFiDashboardIcon size={18} color="var(--accent-cyan)" />}
          title={t('settings.display.title')}
          subtitle={t('settings.display.subtitle')}
        />

        <SettingRow label={t('settings.display.cursor')} desc={t('settings.display.cursorDesc')}>
          <Toggle id="cursor-effect" value={settings.cursorEffect} onChange={v => update('cursorEffect', v)} />
        </SettingRow>

        <SettingRow label={t('settings.display.sound')} desc={t('settings.display.soundDesc')}>
          <Toggle id="click-sound" value={settings.clickSound} onChange={v => update('clickSound', v)} />
        </SettingRow>

        <SettingRow label={t('settings.display.scanline')} desc={t('settings.display.scanlineDesc')}>
          <Toggle id="scanline" value={settings.scanlineEffect} onChange={v => update('scanlineEffect', v)} />
        </SettingRow>

        <SettingRow label={t('settings.display.grid')} desc={t('settings.display.gridDesc')}>
          <Toggle id="grid-bg" value={settings.gridBackground} onChange={v => update('gridBackground', v)} />
        </SettingRow>
      </div>


      {/* ── Section 6: 9Router AI Gateway Telemetry ────────────────────────── */}
      <div style={card}>
        <SectionHeader
          icon={<SciFiQuantumIcon size={18} color="var(--accent-magenta)" />}
          title="9ROUTER AI GATEWAY & MULTI-PROVIDER POOL"
          subtitle="Smart Tiered Routing · Multi-Key Load Balancer · RTK Token Killer · Auto-Fallback"
        />

        {routerLoading ? (
          <div style={{ color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono', fontSize: '0.8rem', opacity: 0.6 }}>
            Loading 9Router status...
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            {/* Quick Metrics Bar */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '10px' }}>
              <div style={{ padding: '10px 14px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(0,243,255,0.1)' }}>
                <div style={{ fontSize: '0.65rem', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', letterSpacing: '1px' }}>
                  ROUTER STATUS
                </div>
                <div style={{ fontSize: '0.95rem', color: 'var(--accent-green)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '6px', marginTop: '3px' }}>
                  <SciFiPulseBadge size={12} color="var(--accent-green)" /> {routerStatus?.status?.toUpperCase() || 'ONLINE'}
                </div>
              </div>

              <div style={{ padding: '10px 14px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(0,243,255,0.1)' }}>
                <div style={{ fontSize: '0.65rem', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', letterSpacing: '1px' }}>
                  TOTAL ROUTED
                </div>
                <div style={{ fontSize: '0.95rem', color: 'var(--text-primary)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', marginTop: '3px' }}>
                  {routerStatus?.total_routed ?? 0} requests
                </div>
              </div>

              <div style={{ padding: '10px 14px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(0,243,255,0.1)' }}>
                <div style={{ fontSize: '0.65rem', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', letterSpacing: '1px' }}>
                  RTK TOKENS SAVED
                </div>
                <div style={{ fontSize: '0.95rem', color: 'var(--accent-yellow)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', marginTop: '3px' }}>
                  ≈{(routerStatus?.rtk?.estimated_tokens_saved ?? 0).toLocaleString()} tok ({(routerStatus?.rtk?.total_compressions ?? 0).toLocaleString()} runs)
                </div>
              </div>

              <div style={{ padding: '10px 14px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(0,243,255,0.1)' }}>
                <div style={{ fontSize: '0.65rem', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', letterSpacing: '1px' }}>
                  AUTO-FAILOVERS
                </div>
                <div style={{ fontSize: '0.95rem', color: (routerStatus?.total_failovers || 0) > 0 ? 'var(--accent-pink)' : 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', marginTop: '3px' }}>
                  {routerStatus?.total_failovers ?? 0}
                </div>
              </div>
            </div>

            {/* Providers & Keys List */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '6px' }}>
              {(routerStatus?.providers || []).map((prov) => (
                <div key={prov.name} style={{
                  padding: '12px 16px',
                  background: 'rgba(0,0,0,0.25)',
                  border: `1px solid ${prov.tier === 1 ? 'rgba(0,243,255,0.2)' : 'rgba(255,0,255,0.2)'}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap', gap: '8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{
                        padding: '2px 8px',
                        background: prov.tier === 1 ? 'rgba(0,243,255,0.15)' : 'rgba(255,0,255,0.15)',
                        border: `1px solid ${prov.tier === 1 ? 'var(--accent-cyan)' : 'var(--accent-magenta)'}`,
                        color: prov.tier === 1 ? 'var(--accent-cyan)' : 'var(--accent-magenta)',
                        fontSize: '0.68rem',
                        fontFamily: 'Share Tech Mono',
                      }}>
                        TIER {prov.tier}: {prov.name.toUpperCase()}
                      </span>
                      <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>
                        Model: <code style={{ color: 'var(--accent-cyan)' }}>{prov.model}</code>
                      </span>
                    </div>

                    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>
                      Active Keys: <strong style={{ color: 'var(--accent-green)' }}>{prov.active_keys}</strong> / {prov.total_keys} · Success: {prov.successful_requests}/{prov.total_requests}
                    </div>
                  </div>

                  {/* Key pills */}
                  <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                    {(prov.keys || []).map((k) => (
                      <div key={k.key_id} style={{
                        padding: '4px 8px',
                        background: k.available ? 'rgba(0,255,102,0.08)' : 'rgba(255,0,85,0.12)',
                        border: `1px solid ${k.available ? 'rgba(0,255,102,0.3)' : 'rgba(255,0,85,0.4)'}`,
                        fontSize: '0.68rem',
                        fontFamily: 'Share Tech Mono',
                        color: k.available ? 'var(--accent-green)' : 'var(--accent-pink)',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '5px',
                      }}>
                        <span>Key #{k.key_id} ({k.masked})</span>
                        {k.available ? (
                          <span style={{ opacity: 0.7 }}>· {k.usage_count} req</span>
                        ) : (
                          <span style={{ color: 'var(--accent-pink)', fontWeight: 'bold' }}>
                            [429 Cooldown {k.cooldown_remaining_sec}s]
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            {/* OpenAI API Gateway Connection Endpoint */}
            <div style={{
              marginTop: '4px', padding: '10px 14px',
              background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(0,243,255,0.08)',
              fontSize: '0.72rem', color: 'var(--text-secondary)',
              fontFamily: 'Share Tech Mono', opacity: 0.8,
              display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px'
            }}>
              <div>
                <SciFiTerminalPromptIcon size={14} color="var(--accent-cyan)" /> OpenAI Gateway: <code>POST /v1/chat/completions</code> (Port 8084)
              </div>
              <button
                onClick={fetchRouterStatus}
                style={{
                  background: 'rgba(0,243,255,0.1)', border: '1px solid rgba(0,243,255,0.3)',
                  color: 'var(--accent-cyan)', padding: '3px 10px', fontSize: '0.7rem',
                  cursor: 'pointer', fontFamily: 'Share Tech Mono'
                }}
              >
                Refresh Telemetry
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ── Section 8: About ──────────────────────────────────────────────── */}
      <div style={card}>
        <SectionHeader
          icon={<SciFiInfoIcon size={18} color="var(--accent-cyan)" />}
          title="ABOUT"
          subtitle="System information and stack details"
        />

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
          {[
            { label: 'APPLICATION', value: 'Server Dashboard' },
            { label: 'VERSION', value: '2.0.0' },
            { label: 'FRONTEND', value: 'React 19 + Vite 8' },
            { label: 'BACKEND', value: 'Spring Boot 4 / Java 21 (Microservices)' },
            { label: 'DATABASE', value: 'PostgreSQL 17' },
            { label: 'RUNTIME', value: 'Docker Compose' },
          ].map(item => (
            <div key={item.label} style={{
              display: 'flex',
              flexDirection: 'column',
              padding: '10px 14px',
              background: 'rgba(0,0,0,0.2)',
              border: '1px solid rgba(0, 243, 255, 0.06)',
            }}>
              <span style={{ fontSize: '0.65rem', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', letterSpacing: '2px', opacity: 0.6, marginBottom: '3px' }}>
                {item.label}
              </span>
              <span style={{ fontSize: '0.85rem', color: 'var(--text-primary)', fontFamily: 'Share Tech Mono' }}>
                {item.value}
              </span>
            </div>
          ))}
        </div>

        <div style={{ marginTop: '16px', textAlign: 'center' }}>
          <a
            href="https://github.com/tranvanmanh9325/quan_ly_server"
            target="_blank"
            rel="noopener noreferrer"
            style={{
              color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontSize: '0.75rem',
              textDecoration: 'none', letterSpacing: '1px', opacity: 0.7,
            }}
          >
            ⎋ VIEW SOURCE ON GITHUB
          </a>
        </div>
      </div>
      </div>
    </div>
  );
}
