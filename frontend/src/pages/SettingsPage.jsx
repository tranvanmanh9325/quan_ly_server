import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import {
  SciFiSettingsIcon, SciFiRefreshIcon, SciFiPulseBadge,
  SciFiConsoleIcon, SciFiCyberLockIcon, SciFiDashboardIcon,
  SciFiTelegramIcon, SciFiInfoIcon, SciFiTerminalPromptIcon,
  SciFiBrowserLaunchIcon, SciFiChronoSpinnerIcon, SciFiCheckCircleIcon, SciFiCloseIcon
} from '../components/SciFiIcons';
import { loadSettings, saveSettings, SETTINGS_DEFAULTS } from '../utils/settings';

// ── Sub-components ──────────────────────────────────────────────────────────
const SectionHeader = ({ icon, title, subtitle }) => (
  <div style={{ marginBottom: '20px' }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' }}>
      {icon}
      <h2 style={{ fontSize: '1rem', letterSpacing: '3px', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', margin: 0 }}>
        {title}
      </h2>
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

// ── Main Component ──────────────────────────────────────────────────────────
export default function SettingsPage() {
  const [settings, setSettings] = useState(loadSettings);
  const [saved, setSaved] = useState(false);
  const [connStatus, setConnStatus] = useState('checking');
  const [connInfo, setConnInfo] = useState(null);

  // ── Telegram state ──────────────────────────────────────────────────────
  const [tgConfig, setTgConfig] = useState({
    enabled: false,
    cpuThreshold: 80,
    ramThreshold: 85,
    diskThreshold: 90,
    cooldownMinutes: 15,
  });
  const [tgSaved, setTgSaved]     = useState(false);
  const [tgTesting, setTgTesting] = useState(false);
  const [tgTestResult, setTgTestResult] = useState(null); // { status, message }
  const [tgLoading, setTgLoading]   = useState(true);
  // ── Facebook state ───────────────────────────────────────────────────────
  const [fbConfig, setFbConfig] = useState({
    enabled: false,
    threshold: 5,
    cooldownMinutes: 120,
    cookiesJson: '',
    customMessage: '',
    lastStatus: 'Tắt',
  });
  const [fbSaved, setFbSaved]       = useState(false);
  const [fbTesting, setFbTesting]   = useState(false);
  const [fbTestResult, setFbTestResult] = useState(null);
  const [fbLoading, setFbLoading]   = useState(true);

  // ── Live VNC Server Browser state ───────────────────────────────────────
  const [vncOpen, setVncOpen]           = useState(false);
  const [vncUrl, setVncUrl]             = useState('');
  const [vncLaunching, setVncLaunching] = useState(false);
  const [vncSaving, setVncSaving]       = useState(false);
  const [vncStatusMsg, setVncStatusMsg] = useState('');

  // Ping backend to check SSH connection health
  useEffect(() => {
    axios.get('/api/metrics/system')
      .then(res => {
        setConnStatus('ok');
        setConnInfo(res.data?.data || null);
      })
      .catch(() => setConnStatus('error'));
  }, []);

  // Load Telegram config from backend
  useEffect(() => {
    axios.get('/api/telegram/config')
      .then(res => {
        const d = res.data;
        setTgConfig(prev => ({
          ...prev,
          enabled:         d.enabled         ?? false,
          cpuThreshold:    d.cpuThreshold    ?? 80,
          ramThreshold:    d.ramThreshold    ?? 85,
          diskThreshold:   d.diskThreshold   ?? 90,
          cooldownMinutes: d.cooldownMinutes ?? 15,
          _configured:     d.configured      ?? false,
        }));
      })
      .catch(() => {})
      .finally(() => setTgLoading(false));
  }, []);

  // Load Facebook config from backend
  useEffect(() => {
    axios.get('/api/facebook/config')
      .then(res => {
        const d = res.data;
        if (d) {
          setFbConfig({
            enabled:         d.enabled         ?? false,
            threshold:       d.threshold       ?? 5,
            cooldownMinutes: d.cooldownMinutes ?? 120,
            cookiesJson:     d.cookiesJson     || '',
            customMessage:   d.customMessage   || '',
            lastStatus:      d.lastStatus      || 'Tắt',
          });
        }
      })
      .catch(() => {})
      .finally(() => setFbLoading(false));
  }, []);

  const update = useCallback((key, val) => {
    setSettings(prev => ({ ...prev, [key]: val }));
    setSaved(false);
  }, []);

  const updateTg = useCallback((key, val) => {
    setTgConfig(prev => ({ ...prev, [key]: val }));
    setTgSaved(false);
    setTgTestResult(null);
  }, []);

  const updateFb = useCallback((key, val) => {
    setFbConfig(prev => ({ ...prev, [key]: val }));
    setFbSaved(false);
    setFbTestResult(null);
  }, []);

  const handleSaveFacebook = async () => {
    try {
      await axios.post('/api/facebook/config', fbConfig);
      setFbSaved(true);
      setTimeout(() => setFbSaved(false), 2500);
    } catch {
      setFbTestResult('Lỗi khi lưu cấu hình Facebook.');
    }
  };

  const handleTriggerFacebook = async () => {
    setFbTesting(true);
    setFbTestResult(null);
    try {
      const res = await axios.post('/api/facebook/trigger');
      setFbTestResult(res.data?.result || 'Đã kích hoạt quét Messenger!');
    } catch (e) {
      setFbTestResult(e.response?.data?.message || 'Lỗi khi kích hoạt quét.');
    } finally {
      setFbTesting(false);
    }
  };

  const handleLaunchBrowser = async () => {
    setVncLaunching(true);
    setVncStatusMsg('Đang khởi tạo Trình duyệt Facebook trên Server...');
    try {
      const res = await axios.post('/api/facebook/launch-browser');
      if (res.data.status === 'success') {
        setVncUrl(res.data.vncUrl || '/fb-vnc/vnc.html?autoconnect=true');
        setVncOpen(true);
        setVncStatusMsg('');
      } else {
        setVncStatusMsg(res.data.message || 'Lỗi khi mở trình duyệt.');
      }
    } catch (e) {
      setVncStatusMsg('Lỗi kết nối tới Server: ' + (e.response?.data?.message || e.message));
    } finally {
      setVncLaunching(false);
    }
  };

  const handleSaveBrowserSession = async () => {
    setVncSaving(true);
    setVncStatusMsg('Đang trích xuất Session Cookies & Lưu vào Database...');
    try {
      const res = await axios.post('/api/facebook/save-browser-session');
      if (res.data.status === 'success') {
        setVncOpen(false);
        setFbTestResult(res.data.message);
        // Reload facebook config
        const cfgRes = await axios.get('/api/facebook/config');
        if (cfgRes.data) {
          setFbConfig({
            enabled:         cfgRes.data.enabled         ?? false,
            threshold:       cfgRes.data.threshold       ?? 5,
            cooldownMinutes: cfgRes.data.cooldownMinutes ?? 120,
            cookiesJson:     cfgRes.data.cookiesJson     || '',
            customMessage:   cfgRes.data.customMessage   || '',
            lastStatus:      cfgRes.data.lastStatus      || 'Tắt',
          });
        }
      } else {
        setVncStatusMsg(res.data.message);
      }
    } catch (e) {
      setVncStatusMsg('Lỗi lưu phiên: ' + (e.response?.data?.message || e.message));
    } finally {
      setVncSaving(false);
    }
  };

  const handleSaveTelegram = async () => {
    try {
      const payload = {
        enabled:         tgConfig.enabled,
        cpuThreshold:    tgConfig.cpuThreshold,
        ramThreshold:    tgConfig.ramThreshold,
        diskThreshold:   tgConfig.diskThreshold,
        cooldownMinutes: tgConfig.cooldownMinutes,
      };
      await axios.post('/api/telegram/config', payload);
      setTgSaved(true);
      setTimeout(() => setTgSaved(false), 2500);
    } catch {
      setTgTestResult({ status: 'error', message: 'Failed to save config.' });
    }
  };

  const handleTestTelegram = async () => {
    setTgTesting(true);
    setTgTestResult(null);
    try {
      const res = await axios.post('/api/telegram/test');
      setTgTestResult(res.data);
    } catch (e) {
      setTgTestResult({ status: 'error', message: e.response?.data?.message || 'Request failed.' });
    } finally {
      setTgTesting(false);
    }
  };

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
  const connLabel = connStatus === 'ok' ? 'CONNECTED' : connStatus === 'error' ? 'DISCONNECTED' : 'CHECKING...';

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
            RESET
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
            {saved ? '✓ SAVED' : 'SAVE CHANGES'}
          </button>
        </div>
      </div>

      {/* ── Section 1: Connection Status ────────────────────────────────── */}
      <div style={card}>
        <SectionHeader
          icon={<SciFiConsoleIcon size={18} color="var(--accent-cyan)" />}
          title="SSH CONNECTION"
          subtitle="Status of the SSH tunnel to the monitored server"
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
          ⓘ  SSH credentials are configured via environment variables on the server. Edit <code>.env</code> to update.
        </p>
      </div>

      {/* ── Section 2: Polling & Performance ──────────────────────────────── */}
      <div style={card}>
        <SectionHeader
          icon={<SciFiRefreshIcon size={18} color="var(--accent-cyan)" />}
          title="POLLING & PERFORMANCE"
          subtitle="Control how frequently the dashboard fetches data from the server"
        />

        <SettingRow
          label="Auto-Refresh Interval"
          desc="How often metrics are fetched via SSH. Lower = higher server load."
        >
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
          title="ALERT THRESHOLDS"
          subtitle="Set resource usage levels that trigger the CRITICAL ALERT indicator"
        />

        <SettingRow label="CPU Usage Threshold" desc="Alert when CPU usage exceeds this value">
          <ThresholdSlider
            id="cpu-threshold"
            value={settings.cpuThreshold}
            onChange={v => update('cpuThreshold', v)}
            color="var(--accent-cyan)"
          />
        </SettingRow>

        <SettingRow label="RAM Usage Threshold" desc="Alert when RAM usage exceeds this value">
          <ThresholdSlider
            id="ram-threshold"
            value={settings.ramThreshold}
            onChange={v => update('ramThreshold', v)}
            color="var(--accent-purple)"
          />
        </SettingRow>

        <SettingRow label="Disk Usage Threshold" desc="Alert when any disk partition exceeds this value">
          <ThresholdSlider
            id="disk-threshold"
            value={settings.diskThreshold}
            onChange={v => update('diskThreshold', v)}
            color="var(--accent-yellow)"
          />
        </SettingRow>

        {/* Alert preview */}
        <div style={{
          marginTop: '16px',
          padding: '10px 14px',
          background: 'rgba(0,0,0,0.2)',
          border: '1px solid rgba(0, 243, 255, 0.08)',
          fontSize: '0.72rem',
          color: 'var(--text-secondary)',
          fontFamily: 'Share Tech Mono',
          opacity: 0.7,
        }}>
          CRITICAL ALERT fires when: CPU &gt; {settings.cpuThreshold}% OR RAM &gt; {settings.ramThreshold}% OR Disk &gt; {settings.diskThreshold}%
        </div>
      </div>

      {/* ── Section 4: Display & Effects ──────────────────────────────────── */}
      <div style={card}>
        <SectionHeader
          icon={<SciFiDashboardIcon size={18} color="var(--accent-cyan)" />}
          title="DISPLAY & EFFECTS"
          subtitle="Visual and audio effects — toggle to reduce CPU usage on low-end devices"
        />

        <SettingRow label="Sci-Fi Cursor Effect" desc="Custom crosshair cursor with rotating rings">
          <Toggle id="cursor-effect" value={settings.cursorEffect} onChange={v => update('cursorEffect', v)} />
        </SettingRow>

        <SettingRow label="Click Sound Effects" desc="Synthesized laser blip sound on every click">
          <Toggle id="click-sound" value={settings.clickSound} onChange={v => update('clickSound', v)} />
        </SettingRow>

        <SettingRow label="Scanline Overlay" desc="CRT scanline effect on background">
          <Toggle id="scanline" value={settings.scanlineEffect} onChange={v => update('scanlineEffect', v)} />
        </SettingRow>

        <SettingRow label="Tron Grid Background" desc="Animated perspective grid background">
          <Toggle id="grid-bg" value={settings.gridBackground} onChange={v => update('gridBackground', v)} />
        </SettingRow>
      </div>

      {/* ── Section 5: Telegram Integration ────────────────────────────── */}
      <div style={card}>
        <SectionHeader
          icon={<SciFiTelegramIcon size={18} color="var(--accent-cyan)" />}
          title="TELEGRAM INTEGRATION"
          subtitle="Receive real-time server alerts and query status via Telegram Bot"
        />

        {tgLoading ? (
          <div style={{ color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono', fontSize: '0.8rem', opacity: 0.6 }}>
            Loading config...
          </div>
        ) : (
          <>
            {/* Credential status — managed via .env, not editable from UI */}
            <SettingRow
              label="Bot Token"
              desc="Managed via TELEGRAM_BOT_TOKEN in .env — restart container to update"
            >
              <span style={{
                fontFamily: 'Share Tech Mono', fontSize: '0.78rem', letterSpacing: '1px',
                color: tgConfig._configured ? 'var(--accent-green)' : 'var(--accent-pink)',
                textShadow: '0 0 8px currentColor',
              }}>
                {tgConfig._configured ? '✓ SET (from .env)' : '✗ NOT SET'}
              </span>
            </SettingRow>

            <SettingRow
              label="Chat ID"
              desc="Managed via TELEGRAM_CHAT_ID in .env — restart container to update"
            >
              <span style={{
                fontFamily: 'Share Tech Mono', fontSize: '0.78rem', letterSpacing: '1px',
                color: tgConfig._configured ? 'var(--accent-green)' : 'var(--accent-pink)',
                textShadow: '0 0 8px currentColor',
              }}>
                {tgConfig._configured ? '✓ SET (from .env)' : '✗ NOT SET'}
              </span>
            </SettingRow>

            {/* Enable toggle */}
            <SettingRow label="Enable Alerts" desc="Bot will send automatic alerts when thresholds are exceeded">
              <Toggle id="tg-enabled" value={tgConfig.enabled} onChange={v => updateTg('enabled', v)} />
            </SettingRow>

            {/* Thresholds */}
            <SettingRow label="CPU Alert Threshold" desc="Alert when CPU exceeds this value (Telegram-specific)">
              <ThresholdSlider id="tg-cpu" value={tgConfig.cpuThreshold}
                onChange={v => updateTg('cpuThreshold', v)} color="var(--accent-cyan)" />
            </SettingRow>
            <SettingRow label="RAM Alert Threshold" desc="Alert when RAM exceeds this value (Telegram-specific)">
              <ThresholdSlider id="tg-ram" value={tgConfig.ramThreshold}
                onChange={v => updateTg('ramThreshold', v)} color="var(--accent-purple)" />
            </SettingRow>
            <SettingRow label="Disk Alert Threshold" desc="Alert when any disk partition exceeds this value">
              <ThresholdSlider id="tg-disk" value={tgConfig.diskThreshold}
                onChange={v => updateTg('diskThreshold', v)} color="var(--accent-yellow)" />
            </SettingRow>

            {/* Cooldown */}
            <SettingRow label="Alert Cooldown" desc="Minimum time between two consecutive alerts of the same type">
              <select
                value={tgConfig.cooldownMinutes}
                onChange={e => updateTg('cooldownMinutes', Number(e.target.value))}
                style={{
                  background: 'rgba(0,0,0,0.6)', border: '1px solid rgba(0,243,255,0.3)',
                  color: 'var(--accent-cyan)', padding: '5px 10px',
                  fontSize: '0.8rem', fontFamily: 'Share Tech Mono', cursor: 'pointer',
                }}
              >
                <option value={5}>5 minutes</option>
                <option value={15}>15 minutes</option>
                <option value={30}>30 minutes</option>
                <option value={60}>60 minutes</option>
              </select>
            </SettingRow>

            {/* Buttons */}
            <div style={{ display: 'flex', gap: '10px', marginTop: '20px', alignItems: 'center', flexWrap: 'wrap' }}>
              <button
                onClick={handleSaveTelegram}
                style={{
                  background: tgSaved ? 'rgba(0,255,102,0.15)' : 'rgba(0,243,255,0.12)',
                  border: `1px solid ${tgSaved ? 'var(--accent-green)' : 'var(--accent-cyan)'}`,
                  color: tgSaved ? 'var(--accent-green)' : 'var(--accent-cyan)',
                  padding: '8px 20px', fontFamily: 'Share Tech Mono',
                  fontSize: '0.78rem', cursor: 'pointer', letterSpacing: '1px',
                  transition: 'all 0.3s ease',
                }}
              >
                {tgSaved ? '✓ SAVED' : 'SAVE TELEGRAM'}
              </button>

              <button
                onClick={handleTestTelegram}
                disabled={tgTesting}
                style={{
                  background: 'rgba(255,165,0,0.1)',
                  border: '1px solid rgba(255,165,0,0.5)',
                  color: 'rgba(255,165,0,1)',
                  padding: '8px 20px', fontFamily: 'Share Tech Mono',
                  fontSize: '0.78rem', cursor: tgTesting ? 'not-allowed' : 'pointer',
                  letterSpacing: '1px', opacity: tgTesting ? 0.5 : 1,
                  display: 'inline-flex', alignItems: 'center', gap: '6px',
                }}
              >
                {tgTesting ? 'SENDING...' : <><SciFiTelegramIcon size={14} color="rgba(255,165,0,1)" /> SEND TEST</>}
              </button>

              {tgTestResult && (
                <span style={{
                  fontSize: '0.78rem', fontFamily: 'Share Tech Mono',
                  color: tgTestResult.status === 'success' ? 'var(--accent-green)' : 'var(--accent-pink)',
                  textShadow: `0 0 8px currentColor`,
                }}>
                  {tgTestResult.status === 'success' ? '✓' : '✗'} {tgTestResult.message}
                </span>
              )}
            </div>

            {/* Bot commands hint */}
            <div style={{
              marginTop: '16px', padding: '10px 14px',
              background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(0,243,255,0.08)',
              fontSize: '0.72rem', color: 'var(--text-secondary)',
              fontFamily: 'Share Tech Mono', opacity: 0.7,
              display: 'flex', alignItems: 'center', gap: '8px',
            }}>
              <SciFiTerminalPromptIcon size={14} color="var(--accent-cyan)" /> Bot commands: <code>/status</code> · <code>/cpu</code> · <code>/ram</code> · <code>/disk</code> · <code>/help</code>
            </div>
          </>
        )}
      </div>

      {/* ── Section 6: Facebook Messenger Integration ────────────────────── */}
      <div style={card}>
        <SectionHeader
          icon={<SciFiFacebookIcon size={18} color="var(--accent-purple)" />}
          title="FACEBOOK MESSENGER AI AGENT"
          subtitle="Tự động phản hồi tin nhắn vắng mặt khi đối phương nhắn"
        />

        {fbLoading ? (
          <div style={{ color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono', fontSize: '0.8rem', opacity: 0.6 }}>
            Đang tải cấu hình Facebook...
          </div>
        ) : (
          <>
            <SettingRow label="Chế độ Vắng mặt (Away Mode)" desc="AI Agent sẽ dùng Trình duyệt web của Server tự động phản hồi Facebook Messenger">
              <Toggle id="fb-enabled" value={fbConfig.enabled} onChange={v => updateFb('enabled', v)} />
            </SettingRow>

            <SettingRow label="Ngưỡng tin nhắn kích hoạt" desc="Số tin nhắn liên tiếp chưa trả lời để AI tự phản hồi (Mặc định: 5 tin)">
              <ThresholdSlider id="fb-threshold" min={1} max={20} unit=" tin" value={fbConfig.threshold}
                onChange={v => updateFb('threshold', v)} color="var(--accent-purple)" />
            </SettingRow>

            <SettingRow label="Thời gian chờ gửi lại (Cooldown)" desc="Tránh gửi lặp lại cho cùng 1 người dùng trong thời gian vắng mặt">
              <select
                value={fbConfig.cooldownMinutes}
                onChange={e => updateFb('cooldownMinutes', Number(e.target.value))}
                style={{
                  background: 'rgba(0,0,0,0.6)', border: '1px solid rgba(187,0,255,0.3)',
                  color: 'var(--accent-purple)', padding: '5px 10px',
                  fontSize: '0.8rem', fontFamily: 'Share Tech Mono', cursor: 'pointer',
                }}
              >
                <option value={30}>30 phút</option>
                <option value={60}>60 phút</option>
                <option value={120}>120 phút (2 giờ)</option>
                <option value={240}>240 phút (4 giờ)</option>
              </select>
            </SettingRow>

            <SettingRow label="Trạng thái hệ thống" desc="Nhật ký kiểm tra lần cuối từ Trình duyệt Server">
              <span style={{
                fontFamily: 'Share Tech Mono', fontSize: '0.78rem',
                color: fbConfig.enabled ? 'var(--accent-cyan)' : 'var(--text-secondary)',
              }}>
                {fbConfig.lastStatus}
              </span>
            </SettingRow>

            <div style={{
              margin: '18px 0', padding: '16px 20px',
              background: 'rgba(187,0,255,0.06)', border: '1px dashed rgba(187,0,255,0.4)',
              borderRadius: '4px', display: 'flex', flexDirection: 'column', gap: '12px'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px' }}>
                <div>
                  <div style={{ fontSize: '0.92rem', color: 'var(--accent-purple)', fontWeight: 'bold', letterSpacing: '0.5px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <SciFiBrowserLaunchIcon size={18} color="var(--accent-purple)" /> Đăng nhập Facebook Trực tiếp
                  </div>
                  <div style={{ fontSize: '0.74rem', color: 'var(--text-secondary)', opacity: 0.8, marginTop: '2px' }}>
                    Mở màn hình Trình duyệt Chromium trên Server để đăng nhập Facebook/2FA trực quan
                  </div>
                </div>

                <button
                  onClick={handleLaunchBrowser}
                  disabled={vncLaunching}
                  style={{
                    background: 'linear-gradient(135deg, rgba(187,0,255,0.3) 0%, rgba(0,243,255,0.3) 100%)',
                    border: '1px solid var(--accent-cyan)',
                    color: '#fff',
                    padding: '10px 22px',
                    fontFamily: 'Share Tech Mono',
                    fontSize: '0.82rem',
                    cursor: vncLaunching ? 'not-allowed' : 'pointer',
                    letterSpacing: '1px',
                    boxShadow: '0 0 15px rgba(0,243,255,0.25)',
                    transition: 'all 0.25s ease',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '8px',
                  }}
                >
                  {vncLaunching ? (
                    <><SciFiChronoSpinnerIcon size={16} color="#fff" /> ĐANG MỞ...</>
                  ) : (
                    <><SciFiBrowserLaunchIcon size={16} color="#fff" /> MỞ TRÌNH DUYỆT SERVER</>
                  )}
                </button>
              </div>

              {vncStatusMsg && (
                <div style={{ fontSize: '0.78rem', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono' }}>
                  {vncStatusMsg}
                </div>
              )}
            </div>

            <div style={{ marginTop: '14px', marginBottom: '14px' }}>
              <div style={{ fontSize: '0.88rem', color: 'var(--text-primary)', marginBottom: '4px' }}>Facebook Session Cookies (JSON)</div>
              <textarea
                value={fbConfig.cookiesJson}
                onChange={e => updateFb('cookiesJson', e.target.value)}
                placeholder='[{"name": "c_user", "value": "..."}, ...]'
                rows={3}
                style={{
                  width: '100%', background: 'rgba(0,0,0,0.5)', border: '1px solid rgba(187,0,255,0.3)',
                  color: 'var(--text-primary)', fontFamily: 'Share Tech Mono', fontSize: '0.75rem',
                  padding: '8px', boxSizing: 'border-box',
                }}
              />
            </div>

            <div style={{ display: 'flex', gap: '10px', marginTop: '16px', alignItems: 'center', flexWrap: 'wrap' }}>
              <button
                onClick={handleSaveFacebook}
                style={{
                  background: fbSaved ? 'rgba(0,255,102,0.15)' : 'rgba(187,0,255,0.12)',
                  border: `1px solid ${fbSaved ? 'var(--accent-green)' : 'var(--accent-purple)'}`,
                  color: fbSaved ? 'var(--accent-green)' : 'var(--accent-purple)',
                  padding: '8px 20px', fontFamily: 'Share Tech Mono',
                  fontSize: '0.78rem', cursor: 'pointer', letterSpacing: '1px',
                }}
              >
                {fbSaved ? '✓ ĐÃ LƯU' : 'LƯU CẤU HÌNH'}
              </button>

              <button
                onClick={handleTriggerFacebook}
                disabled={fbTesting}
                style={{
                  background: 'rgba(0,243,255,0.1)',
                  border: '1px solid rgba(0,243,255,0.5)',
                  color: 'var(--accent-cyan)',
                  padding: '8px 20px', fontFamily: 'Share Tech Mono',
                  fontSize: '0.78rem', cursor: fbTesting ? 'not-allowed' : 'pointer',
                  letterSpacing: '1px', opacity: fbTesting ? 0.5 : 1,
                }}
              >
                {fbTesting ? 'ĐANG QUÉT...' : 'QUÉT NGAY'}
              </button>

              {fbTestResult && (
                <span style={{ fontSize: '0.78rem', fontFamily: 'Share Tech Mono', color: 'var(--accent-cyan)' }}>
                  {fbTestResult}
                </span>
              )}
            </div>

            {vncOpen && (
              <div style={{
                position: 'fixed', inset: 0, zIndex: 99999,
                background: 'rgba(0,0,0,0.85)', backdropFilter: 'blur(8px)',
                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                padding: '20px'
              }}>
                <div style={{
                  width: '95%', maxWidth: '1280px', height: '88vh',
                  background: 'rgba(9, 10, 15, 0.95)', border: '2px solid var(--accent-cyan)',
                  borderRadius: '4px', display: 'flex', flexDirection: 'column', overflow: 'hidden'
                }}>
                  <div style={{
                    padding: '12px 20px', background: 'rgba(0,243,255,0.12)',
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between'
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <SciFiBrowserLaunchIcon size={18} color="var(--accent-cyan)" />
                      <span style={{ color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontSize: '1rem', fontWeight: 'bold' }}>
                        SERVER LIVE CHROMIUM
                      </span>
                    </div>

                    <div style={{ display: 'flex', gap: '12px' }}>
                      <button
                        onClick={handleSaveBrowserSession}
                        disabled={vncSaving}
                        style={{
                          background: 'var(--accent-green)', color: '#000', fontWeight: 'bold',
                          border: 'none', padding: '8px 18px', fontFamily: 'Share Tech Mono',
                          fontSize: '0.82rem', cursor: vncSaving ? 'not-allowed' : 'pointer',
                          borderRadius: '2px', boxShadow: '0 0 10px var(--accent-green)',
                          display: 'inline-flex', alignItems: 'center', gap: '6px',
                        }}
                      >
                        {vncSaving ? (
                          <><SciFiChronoSpinnerIcon size={15} color="#000" /> ĐANG LƯU SESSION...</>
                        ) : (
                          <><SciFiCheckCircleIcon size={15} color="#000" /> ĐÃ ĐĂNG NHẬP XONG - LƯU PHIÊN & BẬT AI AGENT</>
                        )}
                      </button>
                      <button
                        onClick={() => setVncOpen(false)}
                        style={{
                          background: 'rgba(255,0,85,0.2)', border: '1px solid var(--accent-pink)',
                          color: 'var(--accent-pink)', padding: '8px 14px', fontFamily: 'Share Tech Mono',
                          fontSize: '0.82rem', cursor: 'pointer',
                          display: 'inline-flex', alignItems: 'center', gap: '6px',
                        }}
                      >
                        <SciFiCloseIcon size={14} color="var(--accent-pink)" /> ĐÓNG
                      </button>
                    </div>
                  </div>

                  {vncStatusMsg && (
                    <div style={{ padding: '8px 20px', background: 'rgba(0,243,255,0.15)', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontSize: '0.8rem' }}>
                      {vncStatusMsg}
                    </div>
                  )}

                  {/* noVNC Web Screen */}
                  <iframe
                    src={vncUrl}
                    title="Server Facebook Live Chromium"
                    style={{ width: '100%', height: '100%', border: 'none', background: '#000' }}
                  />
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* ── Section 6: About ──────────────────────────────────────────────── */}
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
