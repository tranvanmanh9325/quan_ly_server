import React, { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import axios from 'axios';
import {
  SciFiBotIcon, SciFiFacebookIcon, SciFiZaloIcon, SciFiGmailIcon,
  SciFiTikTokIcon, SciFiYouTubeIcon, SciFiTelegramIcon, SciFiInstagramIcon,
  SciFiWhatsAppIcon, SciFiPulseBadge, SciFiBrowserLaunchIcon,
  SciFiChronoSpinnerIcon, SciFiCheckCircleIcon, SciFiCloseIcon,
  SciFiQuantumIcon, SciFiEnergyBoltIcon, SciFiChevronLeftIcon, SciFiChevronRightIcon
} from '../components/SciFiIcons';
import { useTranslation } from '../i18n/index.jsx';

// ── Sci-Fi Sub-components ───────────────────────────────────────────────────
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
    padding: '14px 0',
    borderBottom: '1px solid rgba(0, 243, 255, 0.06)',
  }}>
    <div style={{ flex: 1 }}>
      <div style={{ fontSize: '0.88rem', color: 'var(--text-primary)', letterSpacing: '0.5px' }}>{label}</div>
      {desc && <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', opacity: 0.6, marginTop: '3px' }}>{desc}</div>}
    </div>
    <div style={{ marginLeft: '20px', flexShrink: 0 }}>{children}</div>
  </div>
);

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

const ThresholdSlider = ({ value, onChange, id, unit = '%', min = 1, max = 100, color = 'var(--accent-cyan)' }) => (
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
      fontSize: '0.8rem',
      fontFamily: 'Share Tech Mono',
      color: color,
      minWidth: '55px',
      textAlign: 'right',
    }}>
      {value}{unit}
    </span>
  </div>
);

// Preset duration button chip
const DurationChip = ({ label, selected, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    style={{
      padding: '2px 7px',
      fontSize: '0.68rem',
      fontFamily: 'Share Tech Mono',
      border: selected ? '1px solid var(--accent-cyan)' : '1px solid rgba(0,243,255,0.2)',
      background: selected ? 'rgba(0,243,255,0.18)' : 'rgba(0,0,0,0.3)',
      color: selected ? 'var(--accent-cyan)' : 'var(--text-secondary)',
      cursor: 'pointer',
      borderRadius: '2px',
      transition: 'all 0.15s ease',
      boxShadow: selected ? '0 0 6px rgba(0,243,255,0.3)' : 'none',
    }}
  >
    {label}
  </button>
);

export default function AiAgentsPage() {
  const { t } = useTranslation();
  const [activePlatform, setActivePlatform] = useState('facebook');
  const [isAutoScroll, setIsAutoScroll] = useState(true);
  const [isHovered, setIsHovered] = useState(false);
  const marqueeContainerRef = useRef(null);

  // ── Facebook state ────────────────────────────────────────────────────────
  const [fbConfig, setFbConfig] = useState({
    enabled: false,
    threshold: 5,
    cookiesJson: '',
    idleTimeoutMinutes: 1,
    autoScanIntervalMinutes: 1,
    humanActivitySuppressionMinutes: 5,
  });
  const [fbStatus, setFbStatus] = useState({
    enabled: false,
    lastScannedAt: null,
    recentReplies: [],
    lastStatus: '',
    hasCookies: false,
  });
  const [fbLoading, setFbLoading] = useState(true);
  const [fbSaving, setFbSaving] = useState(false);
  const [fbTesting, setFbTesting] = useState(false);
  const [fbTestResult, setFbTestResult] = useState('');
  const [fbSaveSuccess, setFbSaveSuccess] = useState(false);

  // ── noVNC Modal state ─────────────────────────────────────────────────────
  const [showVncModal, setShowVncModal] = useState(false);
  const [vncUrl, setVncUrl] = useState('');
  const [vncStatusMsg, setVncStatusMsg] = useState('');
  const [vncIsLaunching, setVncIsLaunching] = useState(false);
  const [vncIsSaving, setVncIsSaving] = useState(false);
  const heartbeatTimerRef = useRef(null);

  // Keep-alive heartbeat loop while VNC modal is open
  useEffect(() => {
    if (showVncModal) {
      heartbeatTimerRef.current = setInterval(() => {
        axios.post('/api/facebook/vnc-heartbeat').catch(() => {});
      }, 15000);
    } else {
      if (heartbeatTimerRef.current) {
        clearInterval(heartbeatTimerRef.current);
        heartbeatTimerRef.current = null;
      }
    }
    return () => {
      if (heartbeatTimerRef.current) {
        clearInterval(heartbeatTimerRef.current);
      }
    };
  }, [showVncModal]);

  // Format Facebook system status text with full multi-language support
  const formatFbStatus = (rawStatus, lastScannedAt, recentReplies) => {
    if (!rawStatus || rawStatus === 'Tắt' || rawStatus === 'OFF' || rawStatus === 'Disabled') {
      return t('settings.facebook.statusOff') || 'Disabled';
    }
    if (rawStatus === 'need_cookies' || rawStatus.includes('Cần nhập Cookies') || rawStatus.includes('Cookies required')) {
      return t('settings.facebook.statusNeedCookies') || 'Facebook Cookies required';
    }
    if (rawStatus.includes('Đã lưu phiên từ Server Chromium') || rawStatus.includes('Session saved from Server Chromium')) {
      return t('aiAgents.facebook.savedSessionStatus') || 'Session saved from Server Chromium';
    }
    const time = lastScannedAt
      ? new Date(lastScannedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      : '---';
    if (rawStatus.startsWith('active') || rawStatus.startsWith('Hoạt động')) {
      const count = recentReplies ? recentReplies.length : 0;
      if (count > 0) return t('settings.facebook.statusActiveWithReplies', { time, count });
      return t('settings.facebook.statusActive', { time });
    }
    if (rawStatus.startsWith('error') || rawStatus.startsWith('Lỗi')) {
      return (t('settings.facebook.statusError') || 'Error') + ': ' + rawStatus.replace(/^(?:Lỗi|Error):\s*/, '');
    }
    return rawStatus;
  };

  // Load Facebook config from backend
  const fetchFbConfig = useCallback(() => {
    setFbLoading(true);
    axios.get('/api/facebook/config')
      .then(res => {
        const d = res.data;
        setFbConfig({
          enabled: Boolean(d.enabled),
          threshold: Number(d.threshold ?? 5),
          cookiesJson: d.cookiesJson || '',
          idleTimeoutMinutes: Number(d.idleTimeoutMinutes ?? 1),
          autoScanIntervalMinutes: Number(d.autoScanIntervalMinutes ?? 1),
          humanActivitySuppressionMinutes: Number(d.humanActivitySuppressionMinutes ?? 5),
        });
        setFbStatus({
          enabled: Boolean(d.enabled),
          lastScannedAt: d.lastScannedAt,
          recentReplies: d.recentReplies || [],
          lastStatus: d.lastStatus || '',
          hasCookies: Boolean(d.hasCookies),
        });
      })
      .catch(() => {})
      .finally(() => setFbLoading(false));
  }, []);

  useEffect(() => {
    fetchFbConfig();
  }, [fetchFbConfig]);

  // Debounced auto-save on slider/toggle updates
  const fbDebounceRef = useRef(null);
  const handleFbConfigChange = (key, value) => {
    setFbConfig(prev => {
      const updated = { ...prev, [key]: value };
      if (key !== 'cookiesJson') {
        if (fbDebounceRef.current) clearTimeout(fbDebounceRef.current);
        fbDebounceRef.current = setTimeout(() => {
          const payload = {
            enabled: updated.enabled,
            threshold: updated.threshold,
            idleTimeoutMinutes: updated.idleTimeoutMinutes,
            autoScanIntervalMinutes: updated.autoScanIntervalMinutes,
            humanActivitySuppressionMinutes: updated.humanActivitySuppressionMinutes,
          };
          axios.post('/api/facebook/config', payload)
            .then(() => {
              setFbSaveSuccess(true);
              setTimeout(() => setFbSaveSuccess(false), 2000);
            })
            .catch(() => {});
        }, 400);
      }
      return updated;
    });
  };

  // Manual save for cookies JSON
  const handleSaveFacebook = async () => {
    setFbSaving(true);
    setFbTestResult('');
    try {
      await axios.post('/api/facebook/config', fbConfig);
      setFbSaveSuccess(true);
      setTimeout(() => setFbSaveSuccess(false), 3000);
    } catch {
      setFbTestResult(t('aiAgents.facebook.saveConfigError') || 'Error saving Facebook config.');
    } finally {
      setFbSaving(false);
    }
  };

  // Manual Trigger Scan Now
  const handleTriggerFacebook = async () => {
    setFbTesting(true);
    setFbTestResult(t('aiAgents.facebook.scanning') || 'Scanning Messenger...');
    try {
      await axios.post('/api/facebook/trigger');
      let attempts = 0;
      const pollInterval = setInterval(async () => {
        attempts++;
        try {
          const s = await axios.get('/api/facebook/scan-status');
          const d = s.data;
          if (d.status === 'idle') {
            clearInterval(pollInterval);
            setFbTesting(false);
            setFbTestResult(d.message || t('aiAgents.facebook.scanSuccess') || 'Scan complete!');
            fetchFbConfig();
          } else if (d.status === 'error') {
            clearInterval(pollInterval);
            setFbTesting(false);
            setFbTestResult(t('aiAgents.facebook.scanError') || 'Error during scan.');
            fetchFbConfig();
          }
        } catch {
          if (attempts > 15) {
            clearInterval(pollInterval);
            setFbTesting(false);
          }
        }
      }, 2000);
    } catch (e) {
      setFbTesting(false);
      setFbTestResult(e.response?.data?.message || t('aiAgents.facebook.scanError') || 'Error during scan.');
    }
  };

  // Launch Server Browser via noVNC
  const handleLaunchVncBrowser = async () => {
    setVncIsLaunching(true);
    setVncStatusMsg(t('aiAgents.facebook.initBrowser') || 'Initializing Facebook Browser on Server...');
    try {
      const res = await axios.post('/api/facebook/launch-browser');
      if (res.data.status === 'success' || res.data.status === 'already_running') {
        setVncStatusMsg(t('aiAgents.facebook.waitingVnc') || 'Waiting for VNC stack...');
        let attempts = 0;
        const MAX_ATTEMPTS = 20;
        const checkReady = setInterval(async () => {
          attempts++;
          try {
            const probe = await axios.get('/api/facebook/vnc-ready');
            if (probe.data.ready) {
              clearInterval(checkReady);
              setVncUrl(probe.data.vnc_url || '/fb-vnc/vnc_lite.html?autoconnect=true&resize=scale');
              setShowVncModal(true);
              setVncIsLaunching(false);
              setVncStatusMsg('');
            } else if (attempts >= MAX_ATTEMPTS) {
              clearInterval(checkReady);
              setVncIsLaunching(false);
              setVncStatusMsg(t('aiAgents.facebook.vncTimeout') || 'VNC startup timed out.');
            }
          } catch {
            if (attempts >= MAX_ATTEMPTS) {
              clearInterval(checkReady);
              setVncIsLaunching(false);
            }
          }
        }, 1000);
      } else {
        setVncIsLaunching(false);
        setVncStatusMsg(res.data.message || t('aiAgents.facebook.browserError') || 'Browser launch error.');
      }
    } catch (e) {
      setVncIsLaunching(false);
      setVncStatusMsg((t('aiAgents.facebook.serverConnError') || 'Server connection error: ') + (e.response?.data?.message || e.message));
    }
  };

  const handleCloseVncModal = async () => {
    setShowVncModal(false);
    setVncUrl('');
    try {
      await axios.post('/api/facebook/close-browser-session');
    } catch {}
  };

  const handleSaveBrowserSession = async () => {
    setVncIsSaving(true);
    setVncStatusMsg(t('aiAgents.facebook.extractingCookies') || 'Extracting session cookies...');
    try {
      const res = await axios.post('/api/facebook/save-browser-session');
      if (res.data.status === 'success') {
        setVncStatusMsg(`✓ ${res.data.message}`);
        const cfgRes = await axios.get('/api/facebook/config');
        if (cfgRes.data?.cookiesJson) {
          setFbConfig(prev => ({ ...prev, cookiesJson: cfgRes.data.cookiesJson }));
          setFbStatus(prev => ({ ...prev, hasCookies: true }));
        }
        setTimeout(() => {
          setShowVncModal(false);
          setVncUrl('');
          setVncStatusMsg('');
          fetchFbConfig();
        }, 1200);
      } else {
        setVncStatusMsg(`⚠️ ${res.data.message}`);
      }
    } catch (e) {
      setVncStatusMsg((t('aiAgents.facebook.sessionSaveError') || 'Session save error: ') + (e.response?.data?.message || e.message));
    } finally {
      setVncIsSaving(false);
    }
  };

  // ── Multi-Platform Catalog ────────────────────────────────────────────────
  const platforms = [
    { id: 'facebook', name: t('aiAgents.tabs.facebook') || 'Facebook Messenger', icon: <SciFiFacebookIcon size={18} color="var(--accent-purple)" />, status: t('aiAgents.statusActive') || 'ACTIVE', isLive: true, color: 'var(--accent-purple)' },
    { id: 'zalo', name: t('aiAgents.tabs.zalo') || 'Zalo AI Agent', icon: <SciFiZaloIcon size={18} color="#0068FF" />, status: t('aiAgents.statusComingSoon') || 'COMING SOON', isLive: false, color: '#0068FF' },
    { id: 'gmail', name: t('aiAgents.tabs.gmail') || 'Gmail AI Assistant', icon: <SciFiGmailIcon size={18} color="#EA4335" />, status: t('aiAgents.statusComingSoon') || 'COMING SOON', isLive: false, color: '#EA4335' },
    { id: 'tiktok', name: t('aiAgents.tabs.tiktok') || 'TikTok Social Agent', icon: <SciFiTikTokIcon size={18} color="#00F2FE" />, status: t('aiAgents.statusComingSoon') || 'COMING SOON', isLive: false, color: '#00F2FE' },
    { id: 'youtube', name: t('aiAgents.tabs.youtube') || 'YouTube Comment Agent', icon: <SciFiYouTubeIcon size={18} color="#FF0033" />, status: t('aiAgents.statusComingSoon') || 'COMING SOON', isLive: false, color: '#FF0033' },
    { id: 'telegram', name: t('aiAgents.tabs.telegram') || 'Telegram Community Bot', icon: <SciFiTelegramIcon size={18} color="#229ED9" />, status: t('aiAgents.statusComingSoon') || 'COMING SOON', isLive: false, color: '#229ED9' },
    { id: 'instagram', name: t('aiAgents.tabs.instagram') || 'Instagram Direct Agent', icon: <SciFiInstagramIcon size={18} color="#E1306C" />, status: t('aiAgents.statusComingSoon') || 'COMING SOON', isLive: false, color: '#E1306C' },
    { id: 'whatsapp', name: t('aiAgents.tabs.whatsapp') || 'WhatsApp Business AI', icon: <SciFiWhatsAppIcon size={18} color="#25D366" />, status: t('aiAgents.statusComingSoon') || 'COMING SOON', isLive: false, color: '#25D366' },
  ];

  // Manual scroll buttons for marquee ribbon
  const handleScrollBy = (offset) => {
    if (marqueeContainerRef.current) {
      marqueeContainerRef.current.scrollBy({ left: offset, behavior: 'smooth' });
    }
  };

  return (
    <div style={{ padding: '24px 28px', overflowY: 'auto', height: '100%', boxSizing: 'border-box' }}>
      <div style={{ maxWidth: '1280px', margin: '0 auto', paddingBottom: '60px' }}>
      
      {/* ── Page Header ───────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <SciFiBotIcon size={28} color="var(--accent-cyan)" />
            <h1 className="title-glow" style={{ fontSize: '1.4rem', letterSpacing: '3px', margin: 0 }}>
              {t('aiAgents.pageTitle') || 'MULTI-PLATFORM AI AGENTS'}
            </h1>
          </div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', margin: '6px 0 0 40px', opacity: 0.75 }}>
            {t('aiAgents.pageSubtitle') || 'Autonomous multi-channel automation: Auto-reply, appointment scheduling, and AI community engagement'}
          </p>
        </div>

        {/* Global AI Engine Badge */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: '10px',
          background: 'rgba(0, 243, 255, 0.06)',
          border: '1px solid rgba(0, 243, 255, 0.3)',
          padding: '6px 14px', borderRadius: '4px',
          boxShadow: '0 0 12px rgba(0, 243, 255, 0.15)'
        }}>
          <SciFiQuantumIcon size={16} color="var(--accent-cyan)" />
          <span style={{ fontSize: '0.75rem', fontFamily: 'Share Tech Mono', color: 'var(--accent-cyan)' }}>
            {t('aiAgents.engineBadge') || 'ENGINE: 9ROUTER (GROQ LPU + OPENROUTER)'}
          </span>
        </div>
      </div>

      {/* ── Platform Tabs Subheader Bar (Controls & Marquee Indicator) ─────── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: '10px', padding: '0 4px', fontSize: '0.72rem',
        fontFamily: 'Share Tech Mono', color: 'var(--text-secondary)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ color: 'var(--accent-cyan)', letterSpacing: '1px', fontWeight: 'bold' }}>
            CHANNEL SELECTOR
          </span>
          <span style={{ opacity: 0.4 }}>|</span>
          <button
            type="button"
            onClick={() => setIsAutoScroll(prev => !prev)}
            style={{
              background: isAutoScroll ? 'rgba(0, 243, 255, 0.12)' : 'rgba(255, 255, 255, 0.05)',
              border: isAutoScroll ? '1px solid var(--accent-cyan)' : '1px solid rgba(255, 255, 255, 0.15)',
              color: isAutoScroll ? 'var(--accent-cyan)' : 'var(--text-secondary)',
              padding: '2px 8px',
              borderRadius: '3px',
              fontSize: '0.68rem',
              fontFamily: 'Share Tech Mono',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '5px',
              transition: 'all 0.2s ease',
            }}
          >
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '5px' }}>
              <SciFiEnergyBoltIcon size={13} color={isAutoScroll ? 'var(--accent-cyan)' : 'var(--text-secondary)'} />
              <span>{t('aiAgents.autoScroll') || 'AUTO-SCROLL'}: <strong>{isAutoScroll ? 'ON' : 'OFF'}</strong></span>
            </span>
            {isAutoScroll && isHovered && (
              <span style={{ color: 'var(--accent-pink)', fontSize: '0.62rem', marginLeft: '4px' }}>
                ({t('aiAgents.autoScrollPaused') || 'HOVER PAUSED'})
              </span>
            )}
          </button>
        </div>

        {/* Left / Right Quick Scroll Buttons */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <button
            type="button"
            onClick={() => handleScrollBy(-220)}
            title="Scroll Left"
            style={{
              background: 'rgba(5, 10, 20, 0.8)',
              border: '1px solid rgba(0, 243, 255, 0.25)',
              color: 'var(--accent-cyan)',
              width: '26px', height: '24px',
              borderRadius: '3px',
              cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: '0 0 6px rgba(0, 243, 255, 0.15)',
              transition: 'all 0.15s ease',
            }}
          >
            <SciFiChevronLeftIcon size={13} color="var(--accent-cyan)" />
          </button>
          <button
            type="button"
            onClick={() => handleScrollBy(220)}
            title="Scroll Right"
            style={{
              background: 'rgba(5, 10, 20, 0.8)',
              border: '1px solid rgba(0, 243, 255, 0.25)',
              color: 'var(--accent-cyan)',
              width: '26px', height: '24px',
              borderRadius: '3px',
              cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: '0 0 6px rgba(0, 243, 255, 0.15)',
              transition: 'all 0.15s ease',
            }}
          >
            <SciFiChevronRightIcon size={13} color="var(--accent-cyan)" />
          </button>
        </div>
      </div>

      {/* ── Auto-scrolling Horizontal Marquee Ribbon ───────────────────────── */}
      <div
        ref={marqueeContainerRef}
        className="scifi-marquee-container"
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        style={{
          marginBottom: '24px',
          borderBottom: '1px solid rgba(0, 243, 255, 0.18)',
          overflowX: isAutoScroll ? 'hidden' : 'auto',
        }}
      >
        <div
          className={`scifi-marquee-track ${isAutoScroll ? 'animating' : ''}`}
          style={{
            animationPlayState: isHovered ? 'paused' : 'running',
          }}
        >
          {/* Double array for seamless infinite looping to the left */}
          {(isAutoScroll ? [...platforms, ...platforms] : platforms).map((p, idx) => {
            const isSelected = activePlatform === p.id;
            return (
              <button
                key={`${p.id}-${idx}`}
                type="button"
                onClick={() => setActivePlatform(p.id)}
                style={{
                  display: 'flex', alignItems: 'center', gap: '10px',
                  padding: '10px 18px',
                  background: isSelected ? 'rgba(0, 243, 255, 0.15)' : 'rgba(5, 10, 20, 0.75)',
                  border: isSelected ? '1px solid var(--accent-cyan)' : '1px solid rgba(255, 255, 255, 0.08)',
                  borderBottom: isSelected ? '2px solid var(--accent-cyan)' : '1px solid rgba(255, 255, 255, 0.08)',
                  color: isSelected ? '#fff' : 'var(--text-secondary)',
                  fontFamily: 'Share Tech Mono',
                  fontSize: '0.82rem',
                  cursor: 'pointer',
                  borderRadius: '4px 4px 0 0',
                  transition: 'all 0.2s ease',
                  boxShadow: isSelected ? '0 0 16px rgba(0, 243, 255, 0.25)' : 'none',
                  whiteSpace: 'nowrap',
                  flexShrink: 0,
                }}
              >
                {p.icon}
                <span style={{ fontWeight: isSelected ? 'bold' : 'normal', color: isSelected ? '#fff' : 'var(--text-primary)' }}>
                  {p.name}
                </span>
                <span style={{
                  fontSize: '0.62rem',
                  padding: '1px 6px',
                  borderRadius: '3px',
                  background: p.isLive ? 'rgba(0, 255, 102, 0.2)' : 'rgba(255, 255, 255, 0.08)',
                  color: p.isLive ? 'var(--accent-green)' : 'var(--text-secondary)',
                  border: p.isLive ? '1px solid var(--accent-green)' : '1px solid rgba(255, 255, 255, 0.15)',
                  letterSpacing: '0.5px',
                }}>
                  {p.status}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Tab Content: FACEBOOK MESSENGER ────────────────────────────────── */}
      {activePlatform === 'facebook' && (
        <div style={{
          background: 'rgba(5, 10, 20, 0.85)',
          border: '1px solid rgba(187, 0, 255, 0.3)',
          boxShadow: '0 0 20px rgba(187, 0, 255, 0.12)',
          borderRadius: '4px',
          padding: '24px',
        }}>
          <SectionHeader
            icon={<SciFiFacebookIcon size={20} color="var(--accent-purple)" />}
            title={t('aiAgents.facebook.title') || "FACEBOOK MESSENGER AI AGENT"}
            subtitle={t('aiAgents.facebook.subtitle') || "Auto-reply to Facebook Messenger messages when away via Server Chromium"}
            badge={
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <SciFiPulseBadge
                  label={fbStatus.enabled ? (t('aiAgents.statusActive') || 'ACTIVE') : 'STANDBY'}
                  color={fbStatus.enabled ? 'var(--accent-green)' : 'var(--text-secondary)'}
                />
                {fbSaveSuccess && (
                  <span style={{ color: 'var(--accent-green)', fontSize: '0.72rem', fontFamily: 'Share Tech Mono' }}>
                    ✓ {t('aiAgents.facebook.savedConfig') || 'Saved config'}
                  </span>
                )}
              </div>
            }
          />

          {fbLoading ? (
            <div style={{ padding: '30px', textAlign: 'center', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
              <SciFiEnergyBoltIcon size={16} color="var(--accent-cyan)" />
              <span>{t('aiAgents.facebook.loading') || 'Loading Facebook AI Agent config...'}</span>
            </div>
          ) : (
            <>
              {/* Away Mode Toggle */}
              <SettingRow label={t('aiAgents.facebook.awayMode') || "Away Mode"} desc={t('aiAgents.facebook.awayModeDesc') || "Activate AI Agent to automatically scan and reply to messages on Server browser"}>
                <Toggle
                  id="fb-enabled"
                  value={fbConfig.enabled}
                  onChange={v => handleFbConfigChange('enabled', v)}
                />
              </SettingRow>

              {/* Message Activation Threshold */}
              <SettingRow label={t('aiAgents.facebook.threshold') || "Message Activation Threshold"} desc={t('aiAgents.facebook.thresholdDesc') || "Consecutive unanswered messages before AI auto-replies (Default: 5)"}>
                <ThresholdSlider
                  id="fb-threshold"
                  min={1}
                  max={20}
                  unit={` ${t('aiAgents.facebook.thresholdUnit') || 'msgs'}`}
                  value={fbConfig.threshold}
                  color="var(--accent-purple)"
                  onChange={v => handleFbConfigChange('threshold', v)}
                />
              </SettingRow>

              {/* Inactivity Silence Delay */}
              <SettingRow label={t('aiAgents.facebook.idleTimeout') || "Inactivity Silence Delay"} desc={t('aiAgents.facebook.idleTimeoutDesc') || "Silence duration without new incoming messages before AI replies (Prevents collision while typing)"}>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '6px' }}>
                  <ThresholdSlider
                    id="fb-idle-timeout"
                    min={1}
                    max={30}
                    unit={` ${t('aiAgents.facebook.minutesUnit') || 'min'}`}
                    value={fbConfig.idleTimeoutMinutes}
                    onChange={v => handleFbConfigChange('idleTimeoutMinutes', v)}
                  />
                  <div style={{ display: 'flex', gap: '4px' }}>
                    {[1, 2, 3, 5, 10, 15].map(m => (
                      <DurationChip
                        key={m}
                        label={`${m}m`}
                        selected={fbConfig.idleTimeoutMinutes === m}
                        onClick={() => handleFbConfigChange('idleTimeoutMinutes', m)}
                      />
                    ))}
                  </div>
                </div>
              </SettingRow>

              {/* Active Human Session Duration */}
              <SettingRow label={t('aiAgents.facebook.humanSession') || "Active Human Session Duration"} desc={t('aiAgents.facebook.humanSessionDesc') || "Suppress AI auto-reply if you recently sent a message on Facebook within this window"}>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '6px' }}>
                  <ThresholdSlider
                    id="fb-human-suppression"
                    min={1}
                    max={60}
                    unit={` ${t('aiAgents.facebook.minutesUnit') || 'min'}`}
                    value={fbConfig.humanActivitySuppressionMinutes}
                    color="var(--accent-purple)"
                    onChange={v => handleFbConfigChange('humanActivitySuppressionMinutes', v)}
                  />
                  <div style={{ display: 'flex', gap: '4px' }}>
                    {[5, 10, 15, 30, 60].map(m => (
                      <DurationChip
                        key={m}
                        label={`${m}m`}
                        selected={fbConfig.humanActivitySuppressionMinutes === m}
                        onClick={() => handleFbConfigChange('humanActivitySuppressionMinutes', m)}
                      />
                    ))}
                  </div>
                </div>
              </SettingRow>

              {/* Auto Scan Interval */}
              <SettingRow label={t('aiAgents.facebook.scanInterval') || "Auto Scan Interval"} desc={t('aiAgents.facebook.scanIntervalDesc') || "How frequently the Server browser checks Messenger inbox"}>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '6px' }}>
                  <ThresholdSlider
                    id="fb-scan-interval"
                    min={1}
                    max={30}
                    unit={` ${t('aiAgents.facebook.minutesUnit') || 'min'}`}
                    value={fbConfig.autoScanIntervalMinutes}
                    onChange={v => handleFbConfigChange('autoScanIntervalMinutes', v)}
                  />
                  <div style={{ display: 'flex', gap: '4px' }}>
                    {[1, 2, 5, 10, 15, 30].map(m => (
                      <DurationChip
                        key={m}
                        label={`${m}m`}
                        selected={fbConfig.autoScanIntervalMinutes === m}
                        onClick={() => handleFbConfigChange('autoScanIntervalMinutes', m)}
                      />
                    ))}
                  </div>
                </div>
              </SettingRow>

              {/* System Status Display */}
              <SettingRow label={t('aiAgents.facebook.systemStatus') || "Operational Status"} desc={t('aiAgents.facebook.systemStatusDesc') || "Last check log from Server Browser"}>
                <span style={{
                  fontSize: '0.78rem',
                  fontFamily: 'Share Tech Mono',
                  color: fbStatus.lastStatus?.startsWith('error') || fbStatus.lastStatus?.startsWith('Lỗi') ? 'var(--accent-pink)' : 'var(--accent-cyan)'
                }}>
                  {formatFbStatus(fbStatus.lastStatus, fbStatus.lastScannedAt, fbStatus.recentReplies)}
                </span>
              </SettingRow>

              {/* Direct Server Browser Login Banner (noVNC) */}
              <div style={{
                marginTop: '20px',
                padding: '16px 20px',
                background: 'rgba(187, 0, 255, 0.06)',
                border: '1px solid rgba(187, 0, 255, 0.35)',
                borderRadius: '4px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '16px',
                flexWrap: 'wrap',
              }}>
                <div>
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: '8px',
                    color: 'var(--accent-purple)', fontFamily: 'Share Tech Mono',
                    fontSize: '0.88rem', fontWeight: 'bold', letterSpacing: '1px',
                  }}>
                    <SciFiBrowserLaunchIcon size={16} color="var(--accent-purple)" />
                    {t('aiAgents.facebook.directLoginTitle') || 'DIRECT SERVER BROWSER LOGIN'}
                  </div>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.74rem', marginTop: '4px', opacity: 0.8 }}>
                    {t('aiAgents.facebook.directLoginDesc') || 'Open Chromium GUI on server via noVNC to log in, enter 2FA, and unlock E2EE PIN.'}
                  </div>
                  {vncStatusMsg && (
                    <div style={{ marginTop: '6px', color: 'var(--accent-cyan)', fontSize: '0.74rem', fontFamily: 'Share Tech Mono', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <SciFiEnergyBoltIcon size={14} color="var(--accent-cyan)" />
                      <span>{vncStatusMsg}</span>
                    </div>
                  )}
                </div>

                <button
                  type="button"
                  onClick={handleLaunchVncBrowser}
                  disabled={vncIsLaunching}
                  style={{
                    display: 'flex', alignItems: 'center', gap: '8px',
                    padding: '8px 18px',
                    background: 'rgba(187, 0, 255, 0.2)',
                    border: '1px solid var(--accent-purple)',
                    borderRadius: '3px',
                    color: '#fff',
                    fontFamily: 'Share Tech Mono',
                    fontSize: '0.8rem',
                    letterSpacing: '1px',
                    cursor: vncIsLaunching ? 'not-allowed' : 'pointer',
                    opacity: vncIsLaunching ? 0.6 : 1,
                    boxShadow: '0 0 12px rgba(187, 0, 255, 0.3)',
                    transition: 'all 0.2s ease',
                  }}
                >
                  {vncIsLaunching ? <SciFiChronoSpinnerIcon size={16} color="#fff" /> : <SciFiBrowserLaunchIcon size={16} color="#fff" />}
                  {vncIsLaunching ? (t('aiAgents.facebook.launchingBrowser') || 'STARTING...') : (t('aiAgents.facebook.openBrowserBtn') || 'OPEN SERVER BROWSER')}
                </button>
              </div>

              {/* Cookies JSON Textarea */}
              <div style={{ marginTop: '20px' }}>
                <label style={{
                  display: 'block',
                  fontSize: '0.82rem',
                  color: 'var(--text-primary)',
                  marginBottom: '8px',
                  fontFamily: 'Share Tech Mono',
                  letterSpacing: '0.5px'
                }}>
                  {t('aiAgents.facebook.cookiesLabel') || 'Facebook Session Cookies (JSON)'}
                </label>
                <textarea
                  value={fbConfig.cookiesJson}
                  onChange={e => handleFbConfigChange('cookiesJson', e.target.value)}
                  placeholder='[{"name":"c_user","value":"..."},{"name":"xs","value":"..."}]'
                  rows={4}
                  style={{
                    width: '100%',
                    boxSizing: 'border-box',
                    background: 'rgba(0,0,0,0.5)',
                    border: '1px solid rgba(0,243,255,0.2)',
                    borderRadius: '3px',
                    color: '#fff',
                    fontFamily: 'Share Tech Mono',
                    fontSize: '0.75rem',
                    padding: '10px',
                    resize: 'vertical',
                    outline: 'none',
                  }}
                />
              </div>

              {/* Action Buttons */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginTop: '16px' }}>
                <button
                  type="button"
                  onClick={handleSaveFacebook}
                  disabled={fbSaving}
                  style={{
                    padding: '8px 20px',
                    background: 'rgba(0,243,255,0.15)',
                    border: '1px solid var(--accent-cyan)',
                    color: 'var(--accent-cyan)',
                    fontFamily: 'Share Tech Mono',
                    fontSize: '0.8rem',
                    cursor: fbSaving ? 'not-allowed' : 'pointer',
                    borderRadius: '2px',
                    letterSpacing: '1px',
                    fontWeight: 'bold',
                  }}
                >
                  {fbSaving ? (t('aiAgents.facebook.savingConfig') || 'SAVING...') : (t('aiAgents.facebook.saveConfigBtn') || 'SAVE CONFIG')}
                </button>

                <button
                  type="button"
                  onClick={handleTriggerFacebook}
                  disabled={fbTesting}
                  style={{
                    padding: '8px 20px',
                    background: 'rgba(187, 0, 255, 0.15)',
                    border: '1px solid var(--accent-purple)',
                    color: 'var(--accent-purple)',
                    fontFamily: 'Share Tech Mono',
                    fontSize: '0.8rem',
                    cursor: fbTesting ? 'not-allowed' : 'pointer',
                    borderRadius: '2px',
                    letterSpacing: '1px',
                    fontWeight: 'bold',
                  }}
                >
                  {fbTesting ? (t('aiAgents.facebook.scanning') || 'SCANNING...') : (t('aiAgents.facebook.scanNowBtn') || 'SCAN NOW')}
                </button>

                {fbTestResult && (
                  <span style={{
                    fontSize: '0.78rem',
                    fontFamily: 'Share Tech Mono',
                    color: fbTestResult.includes('Lỗi') || fbTestResult.includes('Error') ? 'var(--accent-pink)' : 'var(--accent-green)',
                  }}>
                    {fbTestResult}
                  </span>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {/* ── Tab Content: ZALO AI AGENT ─────────────────────────────────────── */}
      {activePlatform === 'zalo' && (
        <div style={{
          background: 'rgba(5, 10, 20, 0.85)',
          border: '1px solid rgba(0, 104, 255, 0.3)',
          boxShadow: '0 0 20px rgba(0, 104, 255, 0.12)',
          borderRadius: '4px',
          padding: '24px',
        }}>
          <SectionHeader
            icon={<SciFiZaloIcon size={20} color="#0068FF" />}
            title={t('aiAgents.zalo.title') || "ZALO AI AGENT (OFFICIAL ACCOUNT & PERSONAL)"}
            subtitle={t('aiAgents.zalo.subtitle') || "Auto-reply to Zalo OA messages, customer care, and calendar sync"}
            badge={<SciFiPulseBadge label={t('aiAgents.statusInDevelopment') || "IN DEVELOPMENT"} color="#0068FF" />}
          />

          <div style={{ padding: '30px 20px', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <div style={{ width: '50px', height: '50px', margin: '0 auto 16px', borderRadius: '50%', background: 'rgba(0, 104, 255, 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid #0068FF' }}>
              <SciFiZaloIcon size={28} color="#0068FF" />
            </div>
            <h3 style={{ color: '#fff', fontFamily: 'Share Tech Mono', letterSpacing: '2px', marginBottom: '8px' }}>
              {t('aiAgents.zalo.cardTitle') || 'ZALO AI AGENT INTEGRATION GATEWAY'}
            </h3>
            <p style={{ maxWidth: '600px', margin: '0 auto 20px', fontSize: '0.82rem', lineHeight: '1.6' }}>
              {t('aiAgents.zalo.desc') || 'The Zalo module is under development to support Zalo Official Account (Zalo OA API) and Zalo Web Session. Enables AI Agent to handle customer inquiries, capture leads, and schedule appointments automatically.'}
            </p>
            <div style={{ display: 'inline-flex', gap: '8px', padding: '6px 14px', background: 'rgba(0, 104, 255, 0.08)', border: '1px solid rgba(0, 104, 255, 0.3)', borderRadius: '3px', fontSize: '0.75rem', fontFamily: 'Share Tech Mono', color: '#0068FF' }}>
              {t('aiAgents.zalo.statusBadge') || 'STATUS: ARCHITECTURE DESIGNED ➔ BACKEND PIPELINE READY'}
            </div>
          </div>
        </div>
      )}

      {/* ── Tab Content: GMAIL AI ASSISTANT ─────────────────────────────────── */}
      {activePlatform === 'gmail' && (
        <div style={{
          background: 'rgba(5, 10, 20, 0.85)',
          border: '1px solid rgba(234, 67, 53, 0.3)',
          boxShadow: '0 0 20px rgba(234, 67, 53, 0.12)',
          borderRadius: '4px',
          padding: '24px',
        }}>
          <SectionHeader
            icon={<SciFiGmailIcon size={20} color="#EA4335" />}
            title={t('aiAgents.gmail.title') || "GMAIL AI ASSISTANT & SMART INBOX"}
            subtitle={t('aiAgents.gmail.subtitle') || "Smart email triage, meeting detection, and AI draft generation"}
            badge={<SciFiPulseBadge label={t('aiAgents.statusInDevelopment') || "IN DEVELOPMENT"} color="#EA4335" />}
          />

          <div style={{ padding: '30px 20px', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <div style={{ width: '50px', height: '50px', margin: '0 auto 16px', borderRadius: '50%', background: 'rgba(234, 67, 53, 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid #EA4335' }}>
              <SciFiGmailIcon size={28} color="#EA4335" />
            </div>
            <h3 style={{ color: '#fff', fontFamily: 'Share Tech Mono', letterSpacing: '2px', marginBottom: '8px' }}>
              {t('aiAgents.gmail.cardTitle') || 'GMAIL AI ASSISTANT GATEWAY'}
            </h3>
            <p style={{ maxWidth: '600px', margin: '0 auto 20px', fontSize: '0.82rem', lineHeight: '1.6' }}>
              {t('aiAgents.gmail.desc') || 'Google OAuth2 & Gmail IMAP/API integration: AI Agent automatically scans new emails, extracts concise summaries to Telegram, and drafts professional reply templates.'}
            </p>
            <div style={{ display: 'inline-flex', gap: '8px', padding: '6px 14px', background: 'rgba(234, 67, 53, 0.08)', border: '1px solid rgba(234, 67, 53, 0.3)', borderRadius: '3px', fontSize: '0.75rem', fontFamily: 'Share Tech Mono', color: '#EA4335' }}>
              {t('aiAgents.gmail.statusBadge') || 'STATUS: OAUTH2 HOOKS PREPARED'}
            </div>
          </div>
        </div>
      )}

      {/* ── Tab Content: TIKTOK SOCIAL AGENT ─────────────────────────────────── */}
      {activePlatform === 'tiktok' && (
        <div style={{
          background: 'rgba(5, 10, 20, 0.85)',
          border: '1px solid rgba(0, 242, 254, 0.3)',
          boxShadow: '0 0 20px rgba(0, 242, 254, 0.12)',
          borderRadius: '4px',
          padding: '24px',
        }}>
          <SectionHeader
            icon={<SciFiTikTokIcon size={20} color="#00F2FE" />}
            title={t('aiAgents.tiktok.title') || "TIKTOK SOCIAL AUTOMATION AGENT"}
            subtitle={t('aiAgents.tiktok.subtitle') || "Auto-reply to video comments, Direct Messages, and engagement analytics"}
            badge={<SciFiPulseBadge label={t('aiAgents.statusInDevelopment') || "IN DEVELOPMENT"} color="#00F2FE" />}
          />

          <div style={{ padding: '30px 20px', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <div style={{ width: '50px', height: '50px', margin: '0 auto 16px', borderRadius: '50%', background: 'rgba(0, 242, 254, 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid #00F2FE' }}>
              <SciFiTikTokIcon size={28} color="#00F2FE" />
            </div>
            <h3 style={{ color: '#fff', fontFamily: 'Share Tech Mono', letterSpacing: '2px', marginBottom: '8px' }}>
              {t('aiAgents.tiktok.cardTitle') || 'TIKTOK SOCIAL AGENT GATEWAY'}
            </h3>
            <p style={{ maxWidth: '600px', margin: '0 auto 20px', fontSize: '0.82rem', lineHeight: '1.6' }}>
              {t('aiAgents.tiktok.desc') || 'TikTok channel automation: Intelligently reply to viewers\' comments using AI scenarios, capture customer questions, and auto-respond to incoming DMs.'}
            </p>
            <div style={{ display: 'inline-flex', gap: '8px', padding: '6px 14px', background: 'rgba(0, 242, 254, 0.08)', border: '1px solid rgba(0, 242, 254, 0.3)', borderRadius: '3px', fontSize: '0.75rem', fontFamily: 'Share Tech Mono', color: '#00F2FE' }}>
              {t('aiAgents.tiktok.statusBadge') || 'STATUS: WEB AUTOMATION HOOK READY'}
            </div>
          </div>
        </div>
      )}

      {/* ── Tab Content: YOUTUBE COMMUNITY AGENT ─────────────────────────────── */}
      {activePlatform === 'youtube' && (
        <div style={{
          background: 'rgba(5, 10, 20, 0.85)',
          border: '1px solid rgba(255, 0, 51, 0.3)',
          boxShadow: '0 0 20px rgba(255, 0, 51, 0.12)',
          borderRadius: '4px',
          padding: '24px',
        }}>
          <SectionHeader
            icon={<SciFiYouTubeIcon size={20} color="#FF0033" />}
            title={t('aiAgents.youtube.title') || "YOUTUBE COMMUNITY & COMMENT AGENT"}
            subtitle={t('aiAgents.youtube.subtitle') || "Video comments management, spam filtering, and community care"}
            badge={<SciFiPulseBadge label={t('aiAgents.statusInDevelopment') || "IN DEVELOPMENT"} color="#FF0033" />}
          />

          <div style={{ padding: '30px 20px', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <div style={{ width: '50px', height: '50px', margin: '0 auto 16px', borderRadius: '50%', background: 'rgba(255, 0, 51, 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid #FF0033' }}>
              <SciFiYouTubeIcon size={28} color="#FF0033" />
            </div>
            <h3 style={{ color: '#fff', fontFamily: 'Share Tech Mono', letterSpacing: '2px', marginBottom: '8px' }}>
              {t('aiAgents.youtube.cardTitle') || 'YOUTUBE COMMUNITY AGENT GATEWAY'}
            </h3>
            <p style={{ maxWidth: '600px', margin: '0 auto 20px', fontSize: '0.82rem', lineHeight: '1.6' }}>
              {t('aiAgents.youtube.desc') || 'YouTube Data API v3 integration: Detect new comments across channel videos, answer viewers\' questions, filter toxic spam, and send analytics reports to Telegram.'}
            </p>
            <div style={{ display: 'inline-flex', gap: '8px', padding: '6px 14px', background: 'rgba(255, 0, 51, 0.08)', border: '1px solid rgba(255, 0, 51, 0.3)', borderRadius: '3px', fontSize: '0.75rem', fontFamily: 'Share Tech Mono', color: '#FF0033' }}>
              {t('aiAgents.youtube.statusBadge') || 'STATUS: API PIPELINE READY'}
            </div>
          </div>
        </div>
      )}

      {/* ── Tab Content: TELEGRAM COMMUNITY BOT ──────────────────────────────── */}
      {activePlatform === 'telegram' && (
        <div style={{
          background: 'rgba(5, 10, 20, 0.85)',
          border: '1px solid rgba(34, 158, 217, 0.3)',
          boxShadow: '0 0 20px rgba(34, 158, 217, 0.12)',
          borderRadius: '4px',
          padding: '24px',
        }}>
          <SectionHeader
            icon={<SciFiTelegramIcon size={20} color="#229ED9" />}
            title={t('aiAgents.telegram.title') || "TELEGRAM COMMUNITY & CHANNEL AGENT"}
            subtitle={t('aiAgents.telegram.subtitle') || "Automated group administration, keyword responses, and channel broadcasting"}
            badge={<SciFiPulseBadge label={t('aiAgents.statusInDevelopment') || "IN DEVELOPMENT"} color="#229ED9" />}
          />

          <div style={{ padding: '30px 20px', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <div style={{ width: '50px', height: '50px', margin: '0 auto 16px', borderRadius: '50%', background: 'rgba(34, 158, 217, 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid #229ED9' }}>
              <SciFiTelegramIcon size={28} color="#229ED9" />
            </div>
            <h3 style={{ color: '#fff', fontFamily: 'Share Tech Mono', letterSpacing: '2px', marginBottom: '8px' }}>
              {t('aiAgents.telegram.cardTitle') || 'TELEGRAM COMMUNITY GATEWAY'}
            </h3>
            <p style={{ maxWidth: '600px', margin: '0 auto 20px', fontSize: '0.82rem', lineHeight: '1.6' }}>
              {t('aiAgents.telegram.desc') || 'Telegram Bot API & MTProto automation: AI Agent auto-moderates group discussions, answers members\' queries in real-time, and schedules announcements.'}
            </p>
            <div style={{ display: 'inline-flex', gap: '8px', padding: '6px 14px', background: 'rgba(34, 158, 217, 0.08)', border: '1px solid rgba(34, 158, 217, 0.3)', borderRadius: '3px', fontSize: '0.75rem', fontFamily: 'Share Tech Mono', color: '#229ED9' }}>
              {t('aiAgents.telegram.statusBadge') || 'STATUS: BOT PIPELINE CONNECTED'}
            </div>
          </div>
        </div>
      )}

      {/* ── Tab Content: INSTAGRAM DIRECT AGENT ──────────────────────────────── */}
      {activePlatform === 'instagram' && (
        <div style={{
          background: 'rgba(5, 10, 20, 0.85)',
          border: '1px solid rgba(225, 48, 108, 0.3)',
          boxShadow: '0 0 20px rgba(225, 48, 108, 0.12)',
          borderRadius: '4px',
          padding: '24px',
        }}>
          <SectionHeader
            icon={<SciFiInstagramIcon size={20} color="#E1306C" />}
            title={t('aiAgents.instagram.title') || "INSTAGRAM DIRECT & STORY AGENT"}
            subtitle={t('aiAgents.instagram.subtitle') || "Auto-reply to Direct Messages, story mentions, and comment engagement"}
            badge={<SciFiPulseBadge label={t('aiAgents.statusInDevelopment') || "IN DEVELOPMENT"} color="#E1306C" />}
          />

          <div style={{ padding: '30px 20px', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <div style={{ width: '50px', height: '50px', margin: '0 auto 16px', borderRadius: '50%', background: 'rgba(225, 48, 108, 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid #E1306C' }}>
              <SciFiInstagramIcon size={28} color="#E1306C" />
            </div>
            <h3 style={{ color: '#fff', fontFamily: 'Share Tech Mono', letterSpacing: '2px', marginBottom: '8px' }}>
              {t('aiAgents.instagram.cardTitle') || 'INSTAGRAM AUTOMATION GATEWAY'}
            </h3>
            <p style={{ maxWidth: '600px', margin: '0 auto 20px', fontSize: '0.82rem', lineHeight: '1.6' }}>
              {t('aiAgents.instagram.desc') || 'Meta Graph API integration: Automated DM triage, lead generation from story reactions, and intelligent interaction with reel comments.'}
            </p>
            <div style={{ display: 'inline-flex', gap: '8px', padding: '6px 14px', background: 'rgba(225, 48, 108, 0.08)', border: '1px solid rgba(225, 48, 108, 0.3)', borderRadius: '3px', fontSize: '0.75rem', fontFamily: 'Share Tech Mono', color: '#E1306C' }}>
              {t('aiAgents.instagram.statusBadge') || 'STATUS: GRAPH API HOOK PREPARED'}
            </div>
          </div>
        </div>
      )}

      {/* ── Tab Content: WHATSAPP BUSINESS AI ─────────────────────────────────── */}
      {activePlatform === 'whatsapp' && (
        <div style={{
          background: 'rgba(5, 10, 20, 0.85)',
          border: '1px solid rgba(37, 211, 102, 0.3)',
          boxShadow: '0 0 20px rgba(37, 211, 102, 0.12)',
          borderRadius: '4px',
          padding: '24px',
        }}>
          <SectionHeader
            icon={<SciFiWhatsAppIcon size={20} color="#25D366" />}
            title={t('aiAgents.whatsapp.title') || "WHATSAPP BUSINESS AI ASSISTANT"}
            subtitle={t('aiAgents.whatsapp.subtitle') || "Official WhatsApp Business Cloud API automated 24/7 customer support"}
            badge={<SciFiPulseBadge label={t('aiAgents.statusInDevelopment') || "IN DEVELOPMENT"} color="#25D366" />}
          />

          <div style={{ padding: '30px 20px', textAlign: 'center', color: 'var(--text-secondary)' }}>
            <div style={{ width: '50px', height: '50px', margin: '0 auto 16px', borderRadius: '50%', background: 'rgba(37, 211, 102, 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid #25D366' }}>
              <SciFiWhatsAppIcon size={28} color="#25D366" />
            </div>
            <h3 style={{ color: '#fff', fontFamily: 'Share Tech Mono', letterSpacing: '2px', marginBottom: '8px' }}>
              {t('aiAgents.whatsapp.cardTitle') || 'WHATSAPP BUSINESS GATEWAY'}
            </h3>
            <p style={{ maxWidth: '600px', margin: '0 auto 20px', fontSize: '0.82rem', lineHeight: '1.6' }}>
              {t('aiAgents.whatsapp.desc') || 'WhatsApp Business Cloud API: AI Agent handles orders, provides instant customer support, and sends real-time order notifications.'}
            </p>
            <div style={{ display: 'inline-flex', gap: '8px', padding: '6px 14px', background: 'rgba(37, 211, 102, 0.08)', border: '1px solid rgba(37, 211, 102, 0.3)', borderRadius: '3px', fontSize: '0.75rem', fontFamily: 'Share Tech Mono', color: '#25D366' }}>
              {t('aiAgents.whatsapp.statusBadge') || 'STATUS: CLOUD API READY'}
            </div>
          </div>
        </div>
      )}

      {/* ── noVNC Interactive Fullscreen Modal Portal ──────────────────────── */}
      {showVncModal && createPortal(
        <div style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0, 0, 0, 0.88)',
          backdropFilter: 'blur(10px)',
          zIndex: 99999,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '16px',
          boxSizing: 'border-box',
          animation: 'fadeIn 0.2s ease-out',
        }}>
          <div style={{
            width: '100%',
            maxWidth: '1280px',
            height: '92vh',
            background: '#0a0d14',
            border: '1px solid var(--accent-purple)',
            borderRadius: '6px',
            boxShadow: '0 0 35px rgba(187, 0, 255, 0.35)',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
          }}>
            {/* Modal Header Bar */}
            <div style={{
              padding: '12px 20px',
              background: 'rgba(187, 0, 255, 0.12)',
              borderBottom: '1px solid rgba(187, 0, 255, 0.3)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <SciFiBrowserLaunchIcon size={18} color="var(--accent-purple)" />
                <span style={{
                  color: '#fff',
                  fontFamily: 'Share Tech Mono',
                  fontSize: '0.9rem',
                  letterSpacing: '1.5px',
                  fontWeight: 'bold',
                }}>
                  {t('aiAgents.facebook.vncModalTitle') || 'SERVER CHROMIUM BROWSER CONSOLE (noVNC)'}
                </span>
                <span style={{
                  fontSize: '0.7rem',
                  padding: '2px 8px',
                  borderRadius: '2px',
                  background: 'rgba(0, 255, 102, 0.15)',
                  color: 'var(--accent-green)',
                  border: '1px solid var(--accent-green)',
                  fontFamily: 'Share Tech Mono',
                }}>
                  {t('aiAgents.facebook.vncLiveBadge') || '● LIVE'}
                </span>
              </div>

              {/* Header Action Buttons */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <button
                  type="button"
                  onClick={handleSaveBrowserSession}
                  disabled={vncIsSaving}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '6px 14px',
                    background: 'rgba(0, 255, 102, 0.2)',
                    border: '1px solid var(--accent-green)',
                    borderRadius: '3px',
                    color: 'var(--accent-green)',
                    fontFamily: 'Share Tech Mono',
                    fontSize: '0.78rem',
                    letterSpacing: '1px',
                    fontWeight: 'bold',
                    cursor: vncIsSaving ? 'not-allowed' : 'pointer',
                    boxShadow: '0 0 10px rgba(0, 255, 102, 0.25)',
                  }}
                >
                  {vncIsSaving ? <SciFiChronoSpinnerIcon size={14} color="var(--accent-green)" /> : <SciFiCheckCircleIcon size={14} color="var(--accent-green)" />}
                  {vncIsSaving ? (t('aiAgents.facebook.vncSavingCookies') || 'SAVING COOKIES...') : (t('aiAgents.facebook.vncSaveSessionBtn') || 'SAVE SESSION & CLOSE')}
                </button>

                <button
                  type="button"
                  onClick={handleCloseVncModal}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: '32px',
                    height: '32px',
                    background: 'rgba(255, 0, 85, 0.15)',
                    border: '1px solid var(--accent-pink)',
                    borderRadius: '3px',
                    color: 'var(--accent-pink)',
                    cursor: 'pointer',
                  }}
                  title="Close without saving"
                >
                  <SciFiCloseIcon size={16} color="var(--accent-pink)" />
                </button>
              </div>
            </div>

            {/* noVNC Iframe */}
            <div style={{ flex: 1, position: 'relative', background: '#000' }}>
              {vncUrl && (
                <iframe
                  src={vncUrl}
                  title="Server Browser noVNC"
                  style={{
                    width: '100%',
                    height: '100%',
                    border: 'none',
                    display: 'block',
                  }}
                  allow="clipboard-read; clipboard-write; fullscreen"
                />
              )}
            </div>

            {/* Modal Footer Bar */}
            <div style={{
              padding: '8px 16px',
              background: 'rgba(5, 10, 20, 0.95)',
              borderTop: '1px solid rgba(187, 0, 255, 0.2)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              fontSize: '0.72rem',
              color: 'var(--text-secondary)',
              fontFamily: 'Share Tech Mono',
            }}>
              <span>
                {t('aiAgents.facebook.vncFooterTip') || '💡 Once logged into Facebook successfully, click [SAVE SESSION & CLOSE] to automatically extract and store session cookies.'}
              </span>
              {vncStatusMsg && (
                <span style={{ color: 'var(--accent-cyan)' }}>
                  {vncStatusMsg}
                </span>
              )}
            </div>
          </div>
        </div>,
        document.body
      )}

      </div>
    </div>
  );
}
