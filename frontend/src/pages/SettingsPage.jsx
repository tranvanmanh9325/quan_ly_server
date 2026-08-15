import React, { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import axios from 'axios';
import {
  SciFiSettingsIcon, SciFiRefreshIcon, SciFiPulseBadge,
  SciFiConsoleIcon, SciFiCyberLockIcon, SciFiDashboardIcon,
  SciFiTelegramIcon, SciFiInfoIcon, SciFiTerminalPromptIcon,
  SciFiBrowserLaunchIcon, SciFiChronoSpinnerIcon, SciFiCheckCircleIcon, SciFiCloseIcon,
  SciFiFacebookIcon
} from '../components/SciFiIcons';
import { loadSettings, saveSettings, SETTINGS_DEFAULTS } from '../utils/settings';
import { useTranslation } from '../i18n/index.jsx';


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

function formatFbStatus(rawStatus, t) {
  if (!rawStatus || rawStatus === 'Tắt' || rawStatus === 'OFF' || rawStatus === 'Disabled') {
    return t('settings.facebook.statusOff');
  }
  if (rawStatus.includes('Cần nhập Cookies') || rawStatus.includes('Cookies required')) {
    return t('settings.facebook.statusNeedCookies');
  }
  const match = rawStatus.match(/(?:Hoạt động:\s*|Active:\s*)?Đã kiểm tra lúc\s*([\d:\s\/]+)(?:\s*\((?:Đã phản hồi|Replied|Away replies sent:)\s*(\d+)\s*(?:tin nhắn vắng mặt|away replies sent)?\))?/i);
  if (match) {
    const time = match[1].trim();
    const count = match[2];
    if (count) {
      return t('settings.facebook.statusActiveWithReplies', { time, count });
    }
    return t('settings.facebook.statusActive', { time });
  }
  if (rawStatus.startsWith('Lỗi:') || rawStatus.startsWith('Error:')) {
    return t('settings.facebook.statusError') + ': ' + rawStatus.replace(/^(?:Lỗi|Error):\s*/, '');
  }
  return rawStatus;
}

function formatFbTriggerResult(resultStr, t) {
  if (!resultStr) return '';
  if (resultStr.includes('Chức năng Vắng mặt hiện đang TẮT')) {
    return t('settings.facebook.triggerDisabled');
  }
  if (resultStr.includes('Chưa cấu hình Cookies Facebook')) {
    return t('settings.facebook.triggerNoCookies');
  }
  const doneMatch = resultStr.match(/Đã quét xong!\s*Số tin nhắn vắng mặt đã tự động trả lời:\s*(\d+)/i);
  if (doneMatch) {
    return t('settings.facebook.triggerDone', { count: doneMatch[1] });
  }
  const errMatch = resultStr.match(/Lỗi khi quét Messenger:\s*(.*)/i);
  if (errMatch) {
    return t('settings.facebook.triggerError') + ': ' + errMatch[1];
  }
  return resultStr;
}

// ── Main Component ──────────────────────────────────────────────────────────
export default function SettingsPage() {
  const { t } = useTranslation();
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
  // Guard ref: skip auto-save on the very first mount (when API data is loaded)
  const tgMountedRef = useRef(false);
  // ── Facebook state ───────────────────────────────────────────────────────
  const [fbConfig, setFbConfig] = useState({
    enabled: false,
    threshold: 5,
    scanIntervalMinutes: 5,
    cookiesJson: '',
    customMessage: '',
    lastStatus: 'Tắt',
  });
  const [fbSaved, setFbSaved]       = useState(false);
  const [fbTesting, setFbTesting]   = useState(false);
  const [fbTestResult, setFbTestResult] = useState(null);
  const [fbLoading, setFbLoading]   = useState(true);
  const [fbScanModal, setFbScanModal] = useState({ open: false, status: '', message: '' });

  // ── Live VNC Server Browser state ───────────────────────────────────────
  const [vncOpen, setVncOpen]           = useState(false);
  const [vncUrl, setVncUrl]             = useState('');
  const [vncLaunching, setVncLaunching] = useState(false);
  const [vncSaving, setVncSaving]       = useState(false);
  const [vncStatusMsg, setVncStatusMsg] = useState('');
  const [vncReady, setVncReady]         = useState(false);
  const vncPollRef = useRef(null);

  useEffect(() => {
    if (vncOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [vncOpen]);



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
      .finally(() => {
        setTgLoading(false);
        // Allow auto-save to fire AFTER initial data is populated
        tgMountedRef.current = true;
      });
  }, []);

  // Auto-save the 'enabled' toggle immediately when it changes (no Save button needed)
  useEffect(() => {
    if (!tgMountedRef.current) return;
    const payload = {
      enabled:         tgConfig.enabled,
      cpuThreshold:    tgConfig.cpuThreshold,
      ramThreshold:    tgConfig.ramThreshold,
      diskThreshold:   tgConfig.diskThreshold,
      cooldownMinutes: tgConfig.cooldownMinutes,
    };
    axios.post('/api/telegram/config', payload)
      .then(() => {
        setTgSaved(true);
        setTimeout(() => setTgSaved(false), 2000);
      })
      .catch(() => {});
  }, [tgConfig.enabled]); // eslint-disable-line react-hooks/exhaustive-deps

  // Load Facebook config from backend
  useEffect(() => {
    axios.get('/api/facebook/config')
      .then(res => {
        const d = res.data;
        if (d) {
          setFbConfig({
            enabled:             d.enabled             ?? false,
            threshold:           d.threshold           ?? 5,
            scanIntervalMinutes: d.scanIntervalMinutes ?? 5,
            cookiesJson:         d.cookiesJson         || '',
            customMessage:       d.customMessage       || '',
            lastStatus:          d.lastStatus          || 'Tắt',
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
      setFbTestResult(t('settings.facebook.saveConfigError'));
    }
  };

  const handleTriggerFacebook = async () => {
    setFbTesting(true);
    setFbTestResult(null);
    try {
      const res = await axios.post('/api/facebook/trigger');
      const { status, message } = res.data;

      // Immediate result (disabled / missing cookies / already running)
      if (status === 'skipped' || status === 'running') {
        setFbTesting(false);
        setFbScanModal({
          open: true,
          status,
          message: formatFbTriggerResult(message, t),
        });
        return;
      }

      // status === 'started' → poll /scan-status until done
      const poll = setInterval(async () => {
        try {
          const s = await axios.get('/api/facebook/scan-status');
          if (s.data.status === 'done') {
            clearInterval(poll);
            setFbTesting(false);
            setFbScanModal({
              open: true,
              status: 'done',
              message: formatFbTriggerResult(s.data.message, t),
            });
          } else if (s.data.status === 'idle') {
            clearInterval(poll);
            setFbTesting(false);
          }
          // status === 'running' → keep polling
        } catch {
          clearInterval(poll);
          setFbTesting(false);
          setFbScanModal({
            open: true,
            status: 'error',
            message: t('settings.facebook.scanError'),
          });
        }
      }, 2000);
    } catch (e) {
      setFbTesting(false);
      const errMsg = e.response?.data?.message || t('settings.facebook.scanError');
      setFbScanModal({
        open: true,
        status: 'error',
        message: formatFbTriggerResult(errMsg, t),
      });
    }
  };

  const handleLaunchBrowser = async () => {
    if (vncPollRef.current) {
      clearInterval(vncPollRef.current);
      vncPollRef.current = null;
    }

    setVncLaunching(true);
    setVncReady(false);
    setVncOpen(true);
    setVncStatusMsg(t('settings.facebook.initBrowser'));
    try {
      const res = await axios.post('/api/facebook/launch-browser');
      if (res.data.status === 'success') {
        setVncUrl('/vnc-embed.html');
        setVncStatusMsg(t('settings.facebook.waitingVnc'));
        let attempts = 0;
        const MAX_ATTEMPTS = 40;
        vncPollRef.current = setInterval(async () => {
          attempts++;
          try {
            const probe = await axios.get('/api/facebook/vnc-ready');
            if (probe.data.ready === true) {
              clearInterval(vncPollRef.current);
              vncPollRef.current = null;
              setVncStatusMsg('');
              setVncReady(true);
            } else if (attempts >= MAX_ATTEMPTS) {
              clearInterval(vncPollRef.current);
              vncPollRef.current = null;
              setVncStatusMsg(t('settings.facebook.vncTimeout'));
            } else {
              setVncStatusMsg(t('settings.facebook.waitingVncProgress', { n: attempts, max: MAX_ATTEMPTS }));
            }
          } catch {
            if (attempts >= MAX_ATTEMPTS) {
              clearInterval(vncPollRef.current);
              vncPollRef.current = null;
              setVncStatusMsg(t('settings.facebook.backendError'));
            }
          }
        }, 1500);
      } else {
        setVncStatusMsg(res.data.message || t('settings.facebook.browserError'));
      }
    } catch (e) {
      setVncStatusMsg(t('settings.facebook.serverConnError') + (e.response?.data?.message || e.message));
    } finally {
      setVncLaunching(false);
    }
  };

  const handleCloseVnc = async () => {
    if (vncPollRef.current) {
      clearInterval(vncPollRef.current);
      vncPollRef.current = null;
    }
    setVncOpen(false);
    setVncReady(false);
    setVncUrl('');
    setVncStatusMsg('');
    try {
      await axios.post('/api/facebook/close-browser-session');
    } catch {}
  };

  const handleSaveBrowserSession = async () => {
    setVncSaving(true);
    setVncStatusMsg(t('settings.facebook.extractingCookies'));
    try {
      const res = await axios.post('/api/facebook/save-browser-session');
      if (res.data.status === 'success') {
        setVncOpen(false);
        setFbTestResult(res.data.message);
        const cfgRes = await axios.get('/api/facebook/config');
        if (cfgRes.data) {
          setFbConfig({
            enabled:         cfgRes.data.enabled         ?? false,
            threshold:       cfgRes.data.threshold       ?? 5,
            cookiesJson:     cfgRes.data.cookiesJson     || '',
            customMessage:   cfgRes.data.customMessage   || '',
            lastStatus:      cfgRes.data.lastStatus      || 'Tắt',
          });
        }
      } else {
        setVncStatusMsg(res.data.message);
      }
    } catch (e) {
      setVncStatusMsg(t('settings.facebook.sessionSaveError') + (e.response?.data?.message || e.message));
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

      {/* ── Section 5: Telegram Integration ────────────────────────────── */}
      <div style={card}>
        <SectionHeader
          icon={<SciFiTelegramIcon size={18} color="var(--accent-cyan)" />}
          title={t('settings.telegram.title')}
          subtitle={t('settings.telegram.subtitle')}
        />

        {tgLoading ? (
          <div style={{ color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono', fontSize: '0.8rem', opacity: 0.6 }}>
            {t('settings.telegram.loading')}
          </div>
        ) : (
          <>
            <SettingRow label={t('settings.telegram.botToken')} desc={t('settings.telegram.botTokenDesc')}>
              <span style={{ fontFamily: 'Share Tech Mono', fontSize: '0.78rem', letterSpacing: '1px',
                color: tgConfig._configured ? 'var(--accent-green)' : 'var(--accent-pink)',
                textShadow: '0 0 8px currentColor' }}>
                {tgConfig._configured ? t('settings.telegram.configured') : t('settings.telegram.notConfigured')}
              </span>
            </SettingRow>

            <SettingRow label={t('settings.telegram.chatId')} desc={t('settings.telegram.chatIdDesc')}>
              <span style={{ fontFamily: 'Share Tech Mono', fontSize: '0.78rem', letterSpacing: '1px',
                color: tgConfig._configured ? 'var(--accent-green)' : 'var(--accent-pink)',
                textShadow: '0 0 8px currentColor' }}>
                {tgConfig._configured ? t('settings.telegram.configured') : t('settings.telegram.notConfigured')}
              </span>
            </SettingRow>

            <SettingRow label={t('settings.telegram.enableAlerts')} desc={t('settings.telegram.enableAlertsDesc')}>
              <Toggle id="tg-enabled" value={tgConfig.enabled} onChange={v => updateTg('enabled', v)} />
            </SettingRow>

            <SettingRow label={t('settings.telegram.cpuThreshold')} desc={t('settings.telegram.cpuThresholdDesc')}>
              <ThresholdSlider id="tg-cpu" value={tgConfig.cpuThreshold}
                onChange={v => updateTg('cpuThreshold', v)} color="var(--accent-cyan)" />
            </SettingRow>
            <SettingRow label={t('settings.telegram.ramThreshold')} desc={t('settings.telegram.ramThresholdDesc')}>
              <ThresholdSlider id="tg-ram" value={tgConfig.ramThreshold}
                onChange={v => updateTg('ramThreshold', v)} color="var(--accent-purple)" />
            </SettingRow>
            <SettingRow label={t('settings.telegram.diskThreshold')} desc={t('settings.telegram.diskThresholdDesc')}>
              <ThresholdSlider id="tg-disk" value={tgConfig.diskThreshold}
                onChange={v => updateTg('diskThreshold', v)} color="var(--accent-yellow)" />
            </SettingRow>

            {/* Cooldown */}
            <SettingRow label={t('settings.telegram.cooldown')} desc={t('settings.telegram.cooldownDesc')}>
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
                {tgSaved ? t('settings.telegram.saved') : t('settings.telegram.save')}
              </button>

              <button
                onClick={handleTestTelegram}
                disabled={tgTesting}
                style={{
                  background: 'rgba(255,165,0,0.1)', border: '1px solid rgba(255,165,0,0.5)',
                  color: 'rgba(255,165,0,1)', padding: '8px 20px', fontFamily: 'Share Tech Mono',
                  fontSize: '0.78rem', cursor: tgTesting ? 'not-allowed' : 'pointer',
                  letterSpacing: '1px', opacity: tgTesting ? 0.5 : 1,
                  display: 'inline-flex', alignItems: 'center', gap: '6px',
                }}
              >
                {tgTesting ? t('settings.telegram.sending') : <><SciFiTelegramIcon size={14} color="rgba(255,165,0,1)" /> {t('settings.telegram.sendTest')}</>}
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
          title={t('settings.facebook.title')}
          subtitle={t('settings.facebook.subtitle')}
        />

        {fbLoading ? (
          <div style={{ color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono', fontSize: '0.8rem', opacity: 0.6 }}>
            {t('settings.facebook.loading')}
          </div>
        ) : (
          <>
            <SettingRow label={t('settings.facebook.awayMode')} desc={t('settings.facebook.awayModeDesc')}>
              <Toggle id="fb-enabled" value={fbConfig.enabled} onChange={v => updateFb('enabled', v)} />
            </SettingRow>

            <SettingRow label={t('settings.facebook.threshold')} desc={t('settings.facebook.thresholdDesc')}>
              <ThresholdSlider id="fb-threshold" min={1} max={20} unit={` ${t('settings.facebook.thresholdUnit')}`} value={fbConfig.threshold}
                onChange={v => updateFb('threshold', v)} color="var(--accent-purple)" />
            </SettingRow>

            <SettingRow label={t('settings.facebook.scanInterval')} desc={t('settings.facebook.scanIntervalDesc')}>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '8px' }}>
                <ThresholdSlider id="fb-scan-interval" min={1} max={30} unit={` ${t('settings.facebook.minutesUnit')}`} value={fbConfig.scanIntervalMinutes}
                  onChange={v => updateFb('scanIntervalMinutes', v)} color="var(--accent-cyan)" />
                <div style={{ display: 'flex', gap: '4px' }}>
                  {[1, 2, 5, 10, 15, 30].map(m => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => updateFb('scanIntervalMinutes', m)}
                      style={{
                        background: fbConfig.scanIntervalMinutes === m ? 'rgba(0, 242, 254, 0.2)' : 'rgba(0,0,0,0.4)',
                        border: fbConfig.scanIntervalMinutes === m ? '1px solid var(--accent-cyan)' : '1px solid rgba(255,255,255,0.1)',
                        borderRadius: '3px',
                        color: fbConfig.scanIntervalMinutes === m ? 'var(--accent-cyan)' : 'var(--text-secondary)',
                        fontFamily: 'Share Tech Mono',
                        fontSize: '0.72rem',
                        padding: '2px 6px',
                        cursor: 'pointer',
                        transition: 'all 0.2s ease',
                        boxShadow: fbConfig.scanIntervalMinutes === m ? '0 0 8px rgba(0, 242, 254, 0.4)' : 'none',
                      }}
                    >
                      {m}m
                    </button>
                  ))}
                </div>
              </div>
            </SettingRow>

            <SettingRow label={t('settings.facebook.systemStatus')} desc={t('settings.facebook.systemStatusDesc')}>
              <span style={{ fontFamily: 'Share Tech Mono', fontSize: '0.78rem',
                color: fbConfig.enabled ? 'var(--accent-cyan)' : 'var(--text-secondary)' }}>
                {formatFbStatus(fbConfig.lastStatus, t)}
              </span>
            </SettingRow>

            {/* Interactive Server Live Browser Launcher */}
            <div style={{
              margin: '18px 0', padding: '16px 20px',
              background: 'rgba(187,0,255,0.06)', border: '1px dashed rgba(187,0,255,0.4)',
              borderRadius: '4px', display: 'flex', flexDirection: 'column', gap: '12px'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px' }}>
                <div>
                  <div style={{ fontSize: '0.92rem', color: 'var(--accent-purple)', fontWeight: 'bold', letterSpacing: '0.5px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <SciFiBrowserLaunchIcon size={18} color="var(--accent-purple)" /> ĐĂNG NHẬP TRỰC TIẾP TRÊN TRÌNH DUYỆT SERVER
                  </div>
                  <div style={{ fontSize: '0.74rem', color: 'var(--text-secondary)', opacity: 0.8, marginTop: '2px' }}>
                    Mở Chromium GUI trực tiếp trên server qua noVNC để đăng nhập, nhập 2FA và giải mã PIN.
                  </div>
                </div>

                <button
                  onClick={handleLaunchBrowser}
                  disabled={vncLaunching}
                  style={{
                    background: 'linear-gradient(135deg, rgba(187,0,255,0.3) 0%, rgba(0,243,255,0.3) 100%)',
                    border: '1px solid var(--accent-cyan)', color: '#fff',
                    padding: '10px 22px', fontFamily: 'Share Tech Mono', fontSize: '0.82rem',
                    cursor: vncLaunching ? 'not-allowed' : 'pointer', letterSpacing: '1px',
                    boxShadow: '0 0 15px rgba(0,243,255,0.25)', transition: 'all 0.25s ease',
                    display: 'inline-flex', alignItems: 'center', gap: '8px',
                  }}
                >
                  {vncLaunching ? (
                    <><SciFiChronoSpinnerIcon size={16} color="#fff" /> ĐANG KHỞI ĐỘNG CHROMIUM...</>
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
              <div style={{ fontSize: '0.88rem', color: 'var(--text-primary)', marginBottom: '4px' }}>{t('settings.facebook.cookiesLabel')}</div>
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
                {fbSaved ? t('settings.facebook.savedConfig') : t('settings.facebook.saveConfig')}
              </button>

              <button
                onClick={handleTriggerFacebook}
                disabled={fbTesting}
                style={{
                  background: fbTesting ? 'rgba(0,243,255,0.18)' : 'rgba(0,243,255,0.1)',
                  border: `1px solid ${fbTesting ? 'var(--accent-cyan)' : 'rgba(0,243,255,0.5)'}`,
                  color: 'var(--accent-cyan)',
                  padding: '8px 22px', fontFamily: 'Share Tech Mono',
                  fontSize: '0.78rem',
                  cursor: fbTesting ? 'not-allowed' : 'pointer',
                  letterSpacing: '1px',
                  opacity: fbTesting ? 0.85 : 1,
                  display: 'inline-flex', alignItems: 'center', gap: '8px',
                  boxShadow: fbTesting ? '0 0 15px rgba(0,243,255,0.3)' : 'none',
                  transition: 'all 0.25s ease',
                }}
              >
                {fbTesting ? (
                  <>
                    <SciFiChronoSpinnerIcon size={16} color="var(--accent-cyan)" />
                    {t('settings.facebook.scanning')}
                  </>
                ) : (
                  <>
                    <SciFiRefreshIcon size={14} color="var(--accent-cyan)" />
                    {t('settings.facebook.scanNow')}
                  </>
                )}
              </button>
            </div>

            {/* ── Facebook Scan Result Popup Modal ────────────────────────────── */}
            {fbScanModal.open && createPortal(
              <div
                onClick={closeFbScanModal}
                style={{
                  position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                  width: '100vw', height: '100vh', zIndex: 99999,
                  background: 'rgba(5, 7, 13, 0.85)',
                  backdropFilter: 'blur(10px)',
                  WebkitBackdropFilter: 'blur(10px)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  padding: '20px', boxSizing: 'border-box',
                  animation: 'scifiFadeIn 0.2s ease-out',
                }}
              >
                <div
                  onClick={e => e.stopPropagation()}
                  style={{
                    width: '100%', maxWidth: '460px',
                    background: '#090a0f',
                    border: `1px solid ${
                      fbScanModal.status === 'done' || fbScanModal.status === 'success'
                        ? 'var(--accent-green)'
                        : fbScanModal.status === 'error'
                        ? 'var(--accent-pink)'
                        : 'var(--accent-cyan)'
                    }`,
                    borderRadius: '6px',
                    padding: '24px 28px',
                    boxShadow: `0 0 35px ${
                      fbScanModal.status === 'done' || fbScanModal.status === 'success'
                        ? 'rgba(0, 255, 102, 0.3)'
                        : fbScanModal.status === 'error'
                        ? 'rgba(255, 0, 85, 0.3)'
                        : 'rgba(0, 243, 255, 0.3)'
                    }, 0 0 90px rgba(0, 0, 0, 0.95)`,
                    position: 'relative',
                    boxSizing: 'border-box',
                    clipPath: 'polygon(0 0, calc(100% - 14px) 0, 100% 14px, 100% 100%, 14px 100%, 0 calc(100% - 14px))',
                    animation: 'scifiPopIn 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
                  }}
                >
                  {/* Header */}
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      {fbScanModal.status === 'done' || fbScanModal.status === 'success' ? (
                        <SciFiCheckCircleIcon size={22} color="var(--accent-green)" />
                      ) : fbScanModal.status === 'error' ? (
                        <SciFiCloseIcon size={22} color="var(--accent-pink)" />
                      ) : (
                        <SciFiInfoIcon size={22} color="var(--accent-cyan)" />
                      )}
                      <h3 style={{
                        fontFamily: 'Share Tech Mono', fontSize: '1rem', letterSpacing: '2px', margin: 0,
                        color: fbScanModal.status === 'done' || fbScanModal.status === 'success'
                          ? 'var(--accent-green)'
                          : fbScanModal.status === 'error'
                          ? 'var(--accent-pink)'
                          : 'var(--accent-cyan)'
                      }}>
                        {t('settings.facebook.scanResultTitle')}
                      </h3>
                    </div>
                    <button
                      onClick={closeFbScanModal}
                      style={{
                        background: 'none', border: 'none', cursor: 'pointer', padding: '4px',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}
                    >
                      <SciFiCloseIcon size={16} color="var(--text-secondary)" />
                    </button>
                  </div>

                  {/* Glowing Divider */}
                  <div style={{
                    height: '1px',
                    background: `linear-gradient(90deg, ${
                      fbScanModal.status === 'done' || fbScanModal.status === 'success'
                        ? 'var(--accent-green)'
                        : fbScanModal.status === 'error'
                        ? 'var(--accent-pink)'
                        : 'var(--accent-cyan)'
                    } 0%, transparent 100%)`,
                    marginBottom: '18px', opacity: 0.5
                  }} />

                  {/* Content Body */}
                  <div style={{
                    background: 'rgba(0, 0, 0, 0.45)',
                    border: '1px solid rgba(255, 255, 255, 0.08)',
                    padding: '16px 18px',
                    borderRadius: '4px',
                    marginBottom: '20px',
                  }}>
                    <p style={{
                      fontFamily: 'Share Tech Mono', fontSize: '0.85rem', lineHeight: '1.5',
                      color: 'var(--text-primary)', margin: 0, wordBreak: 'break-word',
                    }}>
                      {fbScanModal.message}
                    </p>
                  </div>

                  {/* Action Footer */}
                  <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                    <button
                      onClick={closeFbScanModal}
                      style={{
                        background: fbScanModal.status === 'done' || fbScanModal.status === 'success'
                          ? 'rgba(0, 255, 102, 0.15)'
                          : fbScanModal.status === 'error'
                          ? 'rgba(255, 0, 85, 0.15)'
                          : 'rgba(0, 243, 255, 0.15)',
                        border: `1px solid ${
                          fbScanModal.status === 'done' || fbScanModal.status === 'success'
                            ? 'var(--accent-green)'
                            : fbScanModal.status === 'error'
                            ? 'var(--accent-pink)'
                            : 'var(--accent-cyan)'
                        }`,
                        color: fbScanModal.status === 'done' || fbScanModal.status === 'success'
                          ? 'var(--accent-green)'
                          : fbScanModal.status === 'error'
                          ? 'var(--accent-pink)'
                          : 'var(--accent-cyan)',
                        padding: '8px 24px',
                        fontFamily: 'Share Tech Mono',
                        fontSize: '0.8rem',
                        letterSpacing: '1px',
                        cursor: 'pointer',
                        borderRadius: '3px',
                        transition: 'all 0.2s ease',
                        boxShadow: `0 0 10px ${
                          fbScanModal.status === 'done' || fbScanModal.status === 'success'
                            ? 'rgba(0, 255, 102, 0.3)'
                            : fbScanModal.status === 'error'
                            ? 'rgba(255, 0, 85, 0.3)'
                            : 'rgba(0, 243, 255, 0.3)'
                        }`,
                      }}
                    >
                      {t('settings.facebook.close')}
                    </button>
                  </div>
                </div>
              </div>,
              document.body
            )}

            {/* ── Live VNC Server Chromium Interactive Modal ────────────────── */}
            {vncOpen && createPortal(
              <div style={{
                position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                width: '100vw', height: '100vh', zIndex: 99999,
                background: 'rgba(5, 7, 13, 0.94)', backdropFilter: 'blur(14px)', WebkitBackdropFilter: 'blur(14px)',
                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                padding: '20px', boxSizing: 'border-box'
              }}>
                <div style={{
                  width: '96vw', maxWidth: '1440px', height: '90vh', maxHeight: '920px',
                  background: '#090a0f', border: '1px solid var(--accent-cyan)',
                  borderRadius: '6px', display: 'flex', flexDirection: 'column', overflow: 'hidden',
                  boxShadow: '0 0 35px rgba(0, 243, 255, 0.35), 0 0 90px rgba(0, 0, 0, 0.95)'
                }}>

                  <div style={{
                    padding: '12px 20px', background: 'rgba(0,243,255,0.08)',
                    borderBottom: '1px solid rgba(0,243,255,0.2)',
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    flexShrink: 0
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <SciFiBrowserLaunchIcon size={18} color="var(--accent-cyan)" />
                      <span style={{ color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontSize: '1rem', fontWeight: 'bold', letterSpacing: '1px' }}>
                        SERVER LIVE CHROMIUM (noVNC INTERACTIVE)
                      </span>
                    </div>

                    <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                      <button
                        onClick={handleSaveBrowserSession}
                        disabled={vncSaving}
                        style={{
                          background: 'var(--accent-green)', color: '#000', fontWeight: 'bold',
                          border: 'none', padding: '8px 18px', fontFamily: 'Share Tech Mono',
                          fontSize: '0.82rem', cursor: vncSaving ? 'not-allowed' : 'pointer',
                          borderRadius: '3px', boxShadow: '0 0 12px rgba(0, 255, 157, 0.4)',
                          display: 'inline-flex', alignItems: 'center', gap: '6px',
                          transition: 'all 0.2s'
                        }}
                      >
                        {vncSaving ? (
                          <><SciFiChronoSpinnerIcon size={15} color="#000" /> {t('settings.facebook.savingSession')}</>
                        ) : (
                          <><SciFiCheckCircleIcon size={15} color="#000" /> {t('settings.facebook.saveSession')}</>
                        )}
                      </button>
                      <button
                        onClick={handleCloseVnc}
                        style={{
                          background: 'rgba(255,0,85,0.15)', border: '1px solid var(--accent-pink)',
                          color: 'var(--accent-pink)', padding: '8px 16px', fontFamily: 'Share Tech Mono',
                          fontSize: '0.82rem', cursor: 'pointer', borderRadius: '3px',
                          display: 'inline-flex', alignItems: 'center', gap: '6px',
                          transition: 'all 0.2s'
                        }}
                      >
                        <SciFiCloseIcon size={14} color="var(--accent-pink)" /> {t('settings.facebook.close')}
                      </button>
                    </div>
                  </div>

                  {vncStatusMsg && (
                    <div style={{ padding: '8px 20px', background: 'rgba(0,243,255,0.15)', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontSize: '0.8rem', flexShrink: 0, borderBottom: '1px solid rgba(0,243,255,0.2)' }}>
                      {vncStatusMsg}
                    </div>
                  )}

                  <div style={{ flex: 1, minHeight: 0, width: '100%', position: 'relative', overflow: 'hidden', background: '#000' }}>
                    {vncReady ? (
                      <iframe
                        src={vncUrl || '/vnc-embed.html'}
                        title="Server Live Chromium"
                        style={{ width: '100%', height: '100%', border: 'none', display: 'block', background: '#000' }}
                      />
                    ) : (
                      <div style={{
                        width: '100%', height: '100%', display: 'flex', flexDirection: 'column',
                        alignItems: 'center', justifyContent: 'center', gap: '18px',
                        background: '#0a0b10'
                      }}>
                        <SciFiBrowserLaunchIcon size={48} color="var(--accent-cyan)" />
                        <p style={{ color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontSize: '1rem', textAlign: 'center', opacity: 0.8 }}>
                          {vncLaunching ? t('settings.facebook.launching') : t('settings.facebook.promptLogin')}
                        </p>
                      </div>
                    )}
                  </div>

                </div>
              </div>,
              document.body
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
