import React, { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useSearchParams } from 'react-router-dom';
import axios from 'axios';
import {
  SciFiBotIcon, SciFiFacebookIcon, SciFiZaloIcon, SciFiGmailIcon,
  SciFiTikTokIcon, SciFiYouTubeIcon, SciFiTelegramIcon, SciFiInstagramIcon,
  SciFiWhatsAppIcon, SciFiPulseBadge, SciFiBrowserLaunchIcon,
  SciFiChronoSpinnerIcon, SciFiCheckCircleIcon, SciFiCloseIcon,
  SciFiQuantumIcon, SciFiEnergyBoltIcon, SciFiChevronLeftIcon, SciFiChevronRightIcon,
  SciFiTerminalPromptIcon, SciFiInfoIcon,
  SciFiFlameStreakIcon, SciFiVideoClipIcon, SciFiMessageStreakIcon, SciFiAddFriendIcon,
  SciFiTrashIcon, SciFiRadarScanIcon, SciFiAiChatBubbleIcon, SciFiVerifiedCheckIcon,
  SciFiUsersGroupIcon,
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
  const [searchParams, setSearchParams] = useSearchParams();
  const urlTab = searchParams.get('tab');
  const [activePlatform, setActivePlatform] = useState(urlTab || 'facebook');
  const [isAutoScroll, setIsAutoScroll] = useState(true);
  const [isHovered, setIsHovered] = useState(false);
  const marqueeContainerRef = useRef(null);

  // Sync tab with URL query parameter
  const handleSelectPlatform = (id) => {
    setActivePlatform(id);
    setSearchParams({ tab: id }, { replace: true });
  };

  useEffect(() => {
    if (urlTab && urlTab !== activePlatform) {
      setActivePlatform(urlTab);
    }
  }, [urlTab]);

  // ── Telegram state ────────────────────────────────────────────────────────
  const [tgConfig, setTgConfig] = useState({
    enabled: false,
    cpuThreshold: 80,
    ramThreshold: 85,
    diskThreshold: 90,
    cooldownMinutes: 15,
    _configured: false,
  });
  const [tgSaved, setTgSaved] = useState(false);
  const [tgTesting, setTgTesting] = useState(false);
  const [tgTestResult, setTgTestResult] = useState(null);
  const [tgLoading, setTgLoading] = useState(true);
  const tgSaveTimeoutRef = useRef(null);

  const fetchTgConfig = useCallback(() => {
    setTgLoading(true);
    axios.get('/api/telegram/config')
      .then(res => {
        const d = res.data;
        setTgConfig(prev => ({
          ...prev,
          enabled: d.enabled ?? false,
          cpuThreshold: d.cpuThreshold ?? 80,
          ramThreshold: d.ramThreshold ?? 85,
          diskThreshold: d.diskThreshold ?? 90,
          cooldownMinutes: d.cooldownMinutes ?? 15,
          _configured: d.configured ?? false,
        }));
      })
      .catch(() => {})
      .finally(() => setTgLoading(false));
  }, []);

  useEffect(() => {
    fetchTgConfig();
  }, [fetchTgConfig]);

  // Auto-save Telegram settings on any slider or toggle update (debounced 400ms)
  const updateTg = (field, val) => {
    const next = { ...tgConfig, [field]: val };
    setTgConfig(next);
    setTgSaved(false);

    if (tgSaveTimeoutRef.current) clearTimeout(tgSaveTimeoutRef.current);
    tgSaveTimeoutRef.current = setTimeout(() => {
      const payload = {
        enabled: next.enabled,
        cpuThreshold: next.cpuThreshold,
        ramThreshold: next.ramThreshold,
        diskThreshold: next.diskThreshold,
        cooldownMinutes: next.cooldownMinutes,
      };
      axios.post('/api/telegram/config', payload)
        .then(() => {
          setTgSaved(true);
          setTimeout(() => setTgSaved(false), 2500);
        })
        .catch(() => {});
    }, 400);
  };

  const handleSaveTelegram = async () => {
    try {
      const payload = {
        enabled: tgConfig.enabled,
        cpuThreshold: tgConfig.cpuThreshold,
        ramThreshold: tgConfig.ramThreshold,
        diskThreshold: tgConfig.diskThreshold,
        cooldownMinutes: tgConfig.cooldownMinutes,
      };
      await axios.post('/api/telegram/config', payload);
      setTgSaved(true);
      setTimeout(() => setTgSaved(false), 3000);
    } catch {
      // ignore
    }
  };

  const handleTestTelegram = async () => {
    setTgTesting(true);
    setTgTestResult(null);
    try {
      const res = await axios.post('/api/telegram/test');
      setTgTestResult({
        status: res.data?.status || 'success',
        message: res.data?.message || (t('aiAgents.telegram.testSent') || 'Test alert message sent successfully! Check Telegram.'),
      });
    } catch (e) {
      setTgTestResult({
        status: 'error',
        message: e.response?.data?.message || (t('aiAgents.telegram.testFailed') || 'Failed to send test alert. Check Bot Token & Chat ID.'),
      });
    } finally {
      setTgTesting(false);
    }
  };

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
  const [vncPlatform, setVncPlatform] = useState('facebook'); // 'facebook' | 'tiktok'
  const [vncUrl, setVncUrl] = useState('');
  const [vncStatusMsg, setVncStatusMsg] = useState('');
  const [vncIsLaunching, setVncIsLaunching] = useState(false);
  const [vncIsSaving, setVncIsSaving] = useState(false);
  const heartbeatTimerRef = useRef(null);

  // Keep-alive heartbeat loop while VNC modal is open
  useEffect(() => {
    if (showVncModal) {
      heartbeatTimerRef.current = setInterval(() => {
        const apiPrefix = vncPlatform === 'tiktok' ? '/api/tiktok' : '/api/facebook';
        axios.post(`${apiPrefix}/vnc-heartbeat`).catch(() => {});
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
  }, [showVncModal, vncPlatform]);

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
          axios.post('/api/facebook/config', payload).catch(() => {});
        }, 500);
      }
      return updated;
    });
  };

  // Manual save for cookies JSON
  const handleSaveFacebook = async () => {
    setFbSaving(true);
    try {
      await axios.post('/api/facebook/config', {
        enabled: fbConfig.enabled,
        threshold: fbConfig.threshold,
        cookiesJson: fbConfig.cookiesJson,
        idleTimeoutMinutes: fbConfig.idleTimeoutMinutes,
        autoScanIntervalMinutes: fbConfig.autoScanIntervalMinutes,
        humanActivitySuppressionMinutes: fbConfig.humanActivitySuppressionMinutes,
      });
      setFbSaveSuccess(true);
      setTimeout(() => setFbSaveSuccess(false), 2500);
      fetchFbConfig();
    } catch (e) {
      alert((t('aiAgents.facebook.saveFailed') || 'Save error: ') + (e.response?.data?.message || e.message));
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

  // Launch Server Browser via noVNC (supports facebook & tiktok)
  const handleLaunchVncBrowser = async (platform = 'facebook') => {
    setVncPlatform(platform);
    setVncIsLaunching(true);
    const platformName = platform === 'tiktok' ? 'TikTok' : 'Facebook';
    setVncStatusMsg(t('aiAgents.facebook.initBrowser') || `Initializing ${platformName} Browser on Server...`);
    const apiPrefix = platform === 'tiktok' ? '/api/tiktok' : '/api/facebook';

    try {
      const res = await axios.post(`${apiPrefix}/launch-browser`);
      if (res.data.status === 'success' || res.data.status === 'already_running') {
        setVncStatusMsg(t('aiAgents.facebook.waitingVnc') || 'Waiting for VNC stack...');
        let attempts = 0;
        const MAX_ATTEMPTS = 20;
        const checkReady = setInterval(async () => {
          attempts++;
          try {
            const probe = await axios.get(`${apiPrefix}/vnc-ready`);
            if (probe.data.ready) {
              clearInterval(checkReady);
              setVncUrl(`/vnc-embed.html?t=${Date.now()}`);
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
    const apiPrefix = vncPlatform === 'tiktok' ? '/api/tiktok' : '/api/facebook';
    try {
      await axios.post(`${apiPrefix}/close-browser-session`);
    } catch {}
  };

  const handleSaveBrowserSession = async () => {
    setVncIsSaving(true);
    setVncStatusMsg(t('aiAgents.facebook.extractingCookies') || 'Extracting session cookies...');
    const apiPrefix = vncPlatform === 'tiktok' ? '/api/tiktok' : '/api/facebook';

    try {
      const res = await axios.post(`${apiPrefix}/save-browser-session`);
      if (res.data.status === 'success') {
        setVncStatusMsg(`✓ ${res.data.message}`);
        if (vncPlatform === 'tiktok') {
          fetchTtConfig();
        } else {
          fetchFbConfig();
        }
        setTimeout(() => {
          setShowVncModal(false);
          setVncUrl('');
          setVncStatusMsg('');
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

  // ── TikTok state ──────────────────────────────────────────────────────────
  const [ttConfig, setTtConfig] = useState({
    enabled: false,
    streakEnabled: true,
    streakScheduleHour: 9,
    streakTargets: [],
    streakMessageTemplate: 'Video giữ chuỗi hôm nay nè! Chúc bạn ngày mới vui vẻ nha 🔥✨',
    streakSendType: 'video',
    threshold: 3,
    scanIntervalMinutes: 3,
    idleTimeoutMinutes: 1,
    humanSessionMinutes: 5,
    cooldownMinutes: 60,
    cookiesJson: '',
    customMessage: '',
  });
  const [ttStatus, setTtStatus] = useState({
    enabled: false,
    streakEnabled: true,
    lastCheckAt: null,
    lastStreakRunAt: null,
    recentReplies: [],
    lastStatus: '',
    hasCookies: false,
  });
  const [ttLoading, setTtLoading] = useState(true);
  const [ttSaving, setTtSaving] = useState(false);
  const [ttTesting, setTtTesting] = useState(false);
  const [ttTestResult, setTtTestResult] = useState('');
  const [ttSaveSuccess, setTtSaveSuccess] = useState(false);
  const [ttNewFriendUsername, setTtNewFriendUsername] = useState('');
  const [ttNewFriendNickname, setTtNewFriendNickname] = useState('');
  const [ttInstantSending, setTtInstantSending] = useState('');

  const fetchTtConfig = useCallback(() => {
    setTtLoading(true);
    axios.get('/api/tiktok/config')
      .then(res => {
        const d = res.data;
        const cookies = d.cookiesJson || '';
        setTtConfig({
          enabled: Boolean(d.enabled),
          streakEnabled: Boolean(d.streakEnabled ?? true),
          streakScheduleHour: Number(d.streakScheduleHour ?? 9),
          streakTargets: d.streakTargets || [],
          streakMessageTemplate: d.streakMessageTemplate || 'Video giữ chuỗi hôm nay nè! Chúc bạn ngày mới vui vẻ nha 🔥✨',
          streakSendType: d.streakSendType || 'video',
          threshold: Number(d.threshold ?? 3),
          scanIntervalMinutes: Number(d.scanIntervalMinutes ?? 3),
          idleTimeoutMinutes: Number(d.idleTimeoutMinutes ?? 1),
          humanSessionMinutes: Number(d.humanSessionMinutes ?? 5),
          cooldownMinutes: Number(d.cooldownMinutes ?? 60),
          cookiesJson: cookies,
          customMessage: d.customMessage || '',
        });
        setTtStatus({
          enabled: Boolean(d.enabled),
          streakEnabled: Boolean(d.streakEnabled ?? true),
          lastCheckAt: d.lastCheckAt,
          lastStreakRunAt: d.lastStreakRunAt,
          recentReplies: d.recentReplies || [],
          lastStatus: d.lastStatus || '',
          hasCookies: Boolean(cookies && cookies.length > 20),
        });
      })
      .catch(() => {})
      .finally(() => setTtLoading(false));
  }, []);

  useEffect(() => {
    fetchTtConfig();
  }, [fetchTtConfig]);

  // Debounced auto-save on TikTok slider/toggle updates
  const ttDebounceRef = useRef(null);
  const handleTtConfigChange = (key, value) => {
    setTtConfig(prev => {
      const updated = { ...prev, [key]: value };
      if (key !== 'cookiesJson') {
        if (ttDebounceRef.current) clearTimeout(ttDebounceRef.current);
        ttDebounceRef.current = setTimeout(() => {
          axios.post('/api/tiktok/config', {
            enabled: updated.enabled,
            streakEnabled: updated.streakEnabled,
            streakScheduleHour: updated.streakScheduleHour,
            streakTargets: updated.streakTargets,
            streakMessageTemplate: updated.streakMessageTemplate,
            streakSendType: updated.streakSendType,
            threshold: updated.threshold,
            scanIntervalMinutes: updated.scanIntervalMinutes,
            idleTimeoutMinutes: updated.idleTimeoutMinutes,
            humanSessionMinutes: updated.humanSessionMinutes,
            cooldownMinutes: updated.cooldownMinutes,
            customMessage: updated.customMessage,
          }).catch(() => {});
        }, 500);
      }
      return updated;
    });
  };

  const handleSaveTikTok = async () => {
    setTtSaving(true);
    try {
      await axios.post('/api/tiktok/config', {
        enabled: ttConfig.enabled,
        streakEnabled: ttConfig.streakEnabled,
        streakScheduleHour: ttConfig.streakScheduleHour,
        streakTargets: ttConfig.streakTargets,
        streakMessageTemplate: ttConfig.streakMessageTemplate,
        streakSendType: ttConfig.streakSendType,
        threshold: ttConfig.threshold,
        scanIntervalMinutes: ttConfig.scanIntervalMinutes,
        idleTimeoutMinutes: ttConfig.idleTimeoutMinutes,
        humanSessionMinutes: ttConfig.humanSessionMinutes,
        cooldownMinutes: ttConfig.cooldownMinutes,
        cookiesJson: ttConfig.cookiesJson,
        customMessage: ttConfig.customMessage,
      });
      setTtSaveSuccess(true);
      setTimeout(() => setTtSaveSuccess(false), 2500);
      fetchTtConfig();
    } catch (e) {
      alert((t('aiAgents.tiktok.saveFailed') || 'Save error: ') + (e.response?.data?.message || e.message));
    } finally {
      setTtSaving(false);
    }
  };

  const handleTriggerTikTokScan = async () => {
    setTtTesting(true);
    setTtTestResult(t('aiAgents.tiktok.scanning') || 'Scanning TikTok DMs...');
    try {
      const res = await axios.post('/api/tiktok/trigger-scan');
      setTtTestResult(res.data.message || (t('aiAgents.tiktok.scanSuccess') || 'Scan completed!'));
      fetchTtConfig();
    } catch (e) {
      setTtTestResult(e.response?.data?.message || t('aiAgents.tiktok.scanError') || 'Error during scan.');
    } finally {
      setTtTesting(false);
    }
  };

  const handleTriggerTikTokStreak = async (targetUsername = null) => {
    if (targetUsername) setTtInstantSending(targetUsername);
    else setTtTesting(true);
    try {
      const payload = targetUsername ? { username: targetUsername } : {};
      const res = await axios.post('/api/tiktok/trigger-streak', payload);
      setTtTestResult(res.data.message || 'Streak triggered successfully!');
      fetchTtConfig();
    } catch (e) {
      setTtTestResult(e.response?.data?.message || 'Error triggering streak.');
    } finally {
      setTtInstantSending('');
      setTtTesting(false);
    }
  };

  const handleAddStreakFriend = () => {
    if (!ttNewFriendUsername.trim()) return;
    let uname = ttNewFriendUsername.trim();
    if (!uname.startsWith('@')) uname = `@${uname}`;
    const nickname = ttNewFriendNickname.trim() || uname;

    const exists = ttConfig.streakTargets.some(t => t.username.toLowerCase() === uname.toLowerCase());
    if (exists) {
      alert('Bạn bè này đã có trong danh sách giữ chuỗi!');
      return;
    }

    const updated = [
      ...ttConfig.streakTargets,
      {
        username: uname,
        nickname: nickname,
        streak_days: 0,
        status: 'active',
        last_sent: '',
      }
    ];
    handleTtConfigChange('streakTargets', updated);
    setTtNewFriendUsername('');
    setTtNewFriendNickname('');
  };

  const handleRemoveStreakFriend = (username) => {
    const updated = ttConfig.streakTargets.filter(t => t.username !== username);
    handleTtConfigChange('streakTargets', updated);
  };

  const handleToggleStreakFriend = (username) => {
    const updated = ttConfig.streakTargets.map(t => {
      if (t.username === username) {
        return { ...t, status: t.status === 'active' ? 'paused' : 'active' };
      }
      return t;
    });
    handleTtConfigChange('streakTargets', updated);
  };

  const handleClearTikTokLogs = async () => {
    try {
      await axios.post('/api/tiktok/clear-logs');
      fetchTtConfig();
    } catch (e) {
      console.error('Failed to clear logs:', e);
    }
  };

  // ── Multi-Platform Catalog ────────────────────────────────────────────────
  const platforms = [
    { id: 'facebook', name: t('aiAgents.tabs.facebook') || 'Facebook Messenger', icon: <SciFiFacebookIcon size={18} color="var(--accent-purple)" />, status: t('aiAgents.statusActive') || 'ACTIVE', isLive: true, color: 'var(--accent-purple)' },
    { id: 'tiktok', name: t('aiAgents.tabs.tiktok') || 'TikTok Social & Streaks', icon: <SciFiTikTokIcon size={18} color="#00F2FE" />, status: t('aiAgents.statusActive') || 'ACTIVE', isLive: true, color: '#00F2FE' },
    { id: 'telegram', name: t('aiAgents.tabs.telegram') || 'Telegram Bot & Agent', icon: <SciFiTelegramIcon size={18} color="#229ED9" />, status: t('aiAgents.statusActive') || 'ACTIVE', isLive: true, color: '#229ED9' },
    { id: 'zalo', name: t('aiAgents.tabs.zalo') || 'Zalo AI Agent', icon: <SciFiZaloIcon size={18} color="#0068FF" />, status: t('aiAgents.statusComingSoon') || 'COMING SOON', isLive: false, color: '#0068FF' },
    { id: 'gmail', name: t('aiAgents.tabs.gmail') || 'Gmail AI Assistant', icon: <SciFiGmailIcon size={18} color="#EA4335" />, status: t('aiAgents.statusComingSoon') || 'COMING SOON', isLive: false, color: '#EA4335' },
    { id: 'youtube', name: t('aiAgents.tabs.youtube') || 'YouTube Comment Agent', icon: <SciFiYouTubeIcon size={18} color="#FF0033" />, status: t('aiAgents.statusComingSoon') || 'COMING SOON', isLive: false, color: '#FF0033' },
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
                onClick={() => handleSelectPlatform(p.id)}
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

      {/* ── Tab Content: TIKTOK SOCIAL AUTOMATION & STREAK KEEPER ───────────── */}
      {activePlatform === 'tiktok' && (
        <div style={{
          background: 'rgba(5, 10, 20, 0.85)',
          border: '1px solid rgba(0, 242, 254, 0.35)',
          boxShadow: '0 0 25px rgba(0, 242, 254, 0.15)',
          borderRadius: '4px',
          padding: '24px',
        }}>
          <SectionHeader
            icon={<SciFiTikTokIcon size={22} color="#00F2FE" />}
            title={t('aiAgents.tiktok.title') || "TIKTOK SOCIAL AUTOMATION & STREAK KEEPER"}
            subtitle={t('aiAgents.tiktok.subtitle') || "Auto-reply Direct Messages & daily automated video streak saver for friends"}
            badge={
              <SciFiPulseBadge
                label={ttConfig.streakEnabled || ttConfig.enabled ? (t('aiAgents.tiktok.statusActive') || "STREAK PIPELINE ACTIVE") : (t('aiAgents.tiktok.statusStandby') || "STANDBY")}
                color="#00F2FE"
              />
            }
          />

          {/* TikTok Telemetry 4-Tile Stats Grid */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '12px',
            marginBottom: '24px',
          }}>
            <div style={{ padding: '12px 14px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(0, 242, 254, 0.2)', borderRadius: '3px' }}>
              <div style={{ fontSize: '0.65rem', color: '#00F2FE', fontFamily: 'Share Tech Mono', letterSpacing: '1px' }}>
                {t('aiAgents.tiktok.overviewAutoReply') || 'AUTO-REPLY DMs'}
              </div>
              <div style={{ fontSize: '0.92rem', color: ttConfig.enabled ? 'var(--accent-green)' : 'var(--accent-pink)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', marginTop: '4px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: ttConfig.enabled ? 'var(--accent-green)' : 'var(--accent-pink)', boxShadow: `0 0 8px ${ttConfig.enabled ? 'var(--accent-green)' : 'var(--accent-pink)'}` }} />
                {ttConfig.enabled ? 'ACTIVE (Away Mode)' : 'OFF'}
              </div>
            </div>

            <div style={{ padding: '12px 14px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(0, 242, 254, 0.2)', borderRadius: '3px' }}>
              <div style={{ fontSize: '0.65rem', color: '#00F2FE', fontFamily: 'Share Tech Mono', letterSpacing: '1px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <span>{t('aiAgents.tiktok.overviewStreakKeeper') || 'STREAK KEEPER'}</span>
                <SciFiFlameStreakIcon size={12} color="#FE2C55" />
              </div>
              <div style={{ fontSize: '0.92rem', color: ttConfig.streakEnabled ? 'var(--accent-cyan)' : 'var(--accent-pink)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', marginTop: '4px' }}>
                {ttConfig.streakEnabled ? `${ttConfig.streakTargets?.length || 0} Friends Active` : 'PAUSED'}
              </div>
            </div>

            <div style={{ padding: '12px 14px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(0, 242, 254, 0.2)', borderRadius: '3px' }}>
              <div style={{ fontSize: '0.65rem', color: '#00F2FE', fontFamily: 'Share Tech Mono', letterSpacing: '1px' }}>
                {t('aiAgents.tiktok.overviewDailyDispatch') || 'DAILY DISPATCH'}
              </div>
              <div style={{ fontSize: '0.92rem', color: 'var(--accent-purple)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', marginTop: '4px' }}>
                {String(ttConfig.streakScheduleHour).padStart(2, '0')}:00 (Daily)
              </div>
            </div>

            <div style={{ padding: '12px 14px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(0, 242, 254, 0.2)', borderRadius: '3px' }}>
              <div style={{ fontSize: '0.65rem', color: '#00F2FE', fontFamily: 'Share Tech Mono', letterSpacing: '1px' }}>
                {t('aiAgents.tiktok.overviewSession') || 'TIKTOK SESSION'}
              </div>
              <div style={{ fontSize: '0.92rem', color: ttStatus.hasCookies ? 'var(--accent-green)' : 'var(--accent-pink)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', marginTop: '4px' }}>
                {ttStatus.hasCookies ? 'AUTHENTICATED' : 'NO COOKIES'}
              </div>
            </div>
          </div>

          {ttLoading ? (
            <div style={{ padding: '30px', textAlign: 'center', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
              <SciFiChronoSpinnerIcon size={18} color="#00F2FE" />
              <span>{t('aiAgents.tiktok.loading') || 'Loading TikTok Automation Agent config...'}</span>
            </div>
          ) : (
            <>
              {/* Direct Server Browser Login Banner (noVNC) */}
              <div style={{
                marginBottom: '24px',
                padding: '16px 20px',
                background: 'rgba(0, 242, 254, 0.06)',
                border: '1px solid rgba(0, 242, 254, 0.35)',
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
                    color: '#00F2FE', fontFamily: 'Share Tech Mono',
                    fontSize: '0.88rem', fontWeight: 'bold', letterSpacing: '1px',
                  }}>
                    <SciFiBrowserLaunchIcon size={16} color="#00F2FE" />
                    {t('aiAgents.tiktok.directLoginTitle') || 'DIRECT SERVER BROWSER LOGIN (TIKTOK)'}
                  </div>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.74rem', marginTop: '4px', opacity: 0.8 }}>
                    {t('aiAgents.tiktok.directLoginDesc') || 'Open Chromium GUI on server via noVNC to log in to TikTok, scan QR code, and extract session cookies.'}
                  </div>
                  {vncStatusMsg && vncPlatform === 'tiktok' && (
                    <div style={{ marginTop: '6px', color: '#00F2FE', fontSize: '0.74rem', fontFamily: 'Share Tech Mono', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <SciFiEnergyBoltIcon size={14} color="#00F2FE" />
                      <span>{vncStatusMsg}</span>
                    </div>
                  )}
                </div>

                <button
                  type="button"
                  onClick={() => handleLaunchVncBrowser('tiktok')}
                  disabled={vncIsLaunching}
                  style={{
                    display: 'flex', alignItems: 'center', gap: '8px',
                    padding: '8px 18px',
                    background: 'rgba(0, 242, 254, 0.18)',
                    border: '1px solid #00F2FE',
                    borderRadius: '3px',
                    color: '#fff',
                    fontFamily: 'Share Tech Mono',
                    fontSize: '0.8rem',
                    letterSpacing: '1px',
                    cursor: vncIsLaunching ? 'not-allowed' : 'pointer',
                    opacity: vncIsLaunching ? 0.6 : 1,
                    boxShadow: '0 0 12px rgba(0, 242, 254, 0.25)',
                    transition: 'all 0.2s ease',
                  }}
                >
                  {vncIsLaunching ? <SciFiChronoSpinnerIcon size={16} color="#fff" /> : <SciFiBrowserLaunchIcon size={16} color="#fff" />}
                  {vncIsLaunching ? (t('aiAgents.facebook.launchingBrowser') || 'STARTING...') : (t('aiAgents.tiktok.openBrowserBtn') || 'OPEN TIKTOK BROWSER')}
                </button>
              </div>

              {/* ── SECTION 1: AUTO-REPLY DMs (AWAY MODE) ── */}
              <div style={{
                marginBottom: '24px',
                padding: '18px 20px',
                background: 'rgba(0, 0, 0, 0.3)',
                border: '1px solid rgba(0, 242, 254, 0.25)',
                borderRadius: '4px',
              }}>
                <div style={{
                  display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px',
                  color: '#00F2FE', fontFamily: 'Share Tech Mono', fontSize: '0.86rem', fontWeight: 'bold', letterSpacing: '1px'
                }}>
                  <SciFiBotIcon size={16} color="#00F2FE" />
                  <span>{t('aiAgents.tiktok.sectionDmsTitle') || '1. AUTO-REPLY DIRECT MESSAGES (AWAY MODE)'}</span>
                </div>

                {/* Away Mode Toggle */}
                <SettingRow label={t('aiAgents.tiktok.awayMode') || "Auto-Reply Away Mode"} desc={t('aiAgents.tiktok.awayModeDesc') || "Activate AI Agent to automatically reply to TikTok Direct Messages when you are away"}>
                  <Toggle
                    id="tt-enabled"
                    value={ttConfig.enabled}
                    onChange={v => handleTtConfigChange('enabled', v)}
                  />
                </SettingRow>

                {/* Activation Threshold */}
                <SettingRow label={t('aiAgents.tiktok.threshold') || "Message Activation Threshold"} desc={t('aiAgents.tiktok.thresholdDesc') || "Consecutive unanswered messages before AI auto-replies (Default: 3)"}>
                  <ThresholdSlider
                    id="tt-threshold"
                    min={1}
                    max={15}
                    unit={` ${t('aiAgents.facebook.thresholdUnit') || 'msgs'}`}
                    value={ttConfig.threshold}
                    color="#00F2FE"
                    onChange={v => handleTtConfigChange('threshold', v)}
                  />
                </SettingRow>

                {/* Inactivity Silence Delay */}
                <SettingRow label={t('aiAgents.tiktok.idleTimeout') || "Inactivity Silence Delay"} desc={t('aiAgents.tiktok.idleTimeoutDesc') || "Silence duration without new incoming messages before AI replies (Prevents collision while typing)"}>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '6px' }}>
                    <ThresholdSlider
                      id="tt-idle-timeout"
                      min={1}
                      max={30}
                      unit={` ${t('aiAgents.facebook.minutesUnit') || 'min'}`}
                      value={ttConfig.idleTimeoutMinutes}
                      onChange={v => handleTtConfigChange('idleTimeoutMinutes', v)}
                    />
                    <div style={{ display: 'flex', gap: '4px' }}>
                      {[1, 2, 3, 5, 10].map(m => (
                        <DurationChip
                          key={m}
                          label={`${m}m`}
                          selected={ttConfig.idleTimeoutMinutes === m}
                          onClick={() => handleTtConfigChange('idleTimeoutMinutes', m)}
                        />
                      ))}
                    </div>
                  </div>
                </SettingRow>

                {/* Human Session Suppression */}
                <SettingRow label={t('aiAgents.tiktok.humanSession') || "Active Human Session Duration"} desc={t('aiAgents.tiktok.humanSessionDesc') || "Suppress AI auto-reply if you recently sent a message on TikTok within this window"}>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '6px' }}>
                    <ThresholdSlider
                      id="tt-human-suppression"
                      min={1}
                      max={60}
                      unit={` ${t('aiAgents.facebook.minutesUnit') || 'min'}`}
                      value={ttConfig.humanSessionMinutes}
                      color="var(--accent-purple)"
                      onChange={v => handleTtConfigChange('humanSessionMinutes', v)}
                    />
                    <div style={{ display: 'flex', gap: '4px' }}>
                      {[5, 10, 15, 30].map(m => (
                        <DurationChip
                          key={m}
                          label={`${m}m`}
                          selected={ttConfig.humanSessionMinutes === m}
                          onClick={() => handleTtConfigChange('humanSessionMinutes', m)}
                        />
                      ))}
                    </div>
                  </div>
                </SettingRow>

                {/* Custom Message Template (Optional) */}
                <SettingRow label={t('aiAgents.tiktok.customMsgLabel') || "Custom Away Template (Optional)"} desc={t('aiAgents.tiktok.customMsgDesc') || "Leave blank to use 9Router AI dynamic response, or enter a fixed template"}>
                  <input
                    type="text"
                    value={ttConfig.customMessage}
                    onChange={e => handleTtConfigChange('customMessage', e.target.value)}
                    placeholder="Chào bạn, mình đang bận chút lát rep nha..."
                    style={{
                      width: '320px',
                      background: 'rgba(0,0,0,0.5)',
                      border: '1px solid rgba(0, 242, 254, 0.3)',
                      color: '#fff',
                      padding: '6px 12px',
                      fontFamily: 'Share Tech Mono',
                      fontSize: '0.78rem',
                      borderRadius: '3px',
                      outline: 'none',
                    }}
                  />
                </SettingRow>
              </div>

              {/* ── SECTION 2: DAILY AUTO STREAK KEEPER (🔥 GIỮ CHUỖI TIKTOK) ── */}
              <div style={{
                marginBottom: '24px',
                padding: '18px 20px',
                background: 'rgba(0, 0, 0, 0.3)',
                border: '1px solid rgba(254, 44, 85, 0.35)',
                boxShadow: '0 0 15px rgba(254, 44, 85, 0.08)',
                borderRadius: '4px',
              }}>
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px', flexWrap: 'wrap', gap: '10px'
                }}>
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: '8px',
                    color: '#FE2C55', fontFamily: 'Share Tech Mono', fontSize: '0.86rem', fontWeight: 'bold', letterSpacing: '1px'
                  }}>
                    <SciFiFlameStreakIcon size={18} color="#FE2C55" />
                    <span>{t('aiAgents.tiktok.sectionStreakTitle') || '2. DAILY AUTO STREAK KEEPER (TỰ ĐỘNG GỬI VIDEO GIỮ CHUỖI)'}</span>
                  </div>
                  <SciFiPulseBadge label={ttConfig.streakEnabled ? "STREAKS SAVER ACTIVE" : "STREAKS OFF"} color="#FE2C55" />
                </div>

                {/* Streak Keeper Master Toggle */}
                <SettingRow label={t('aiAgents.tiktok.streakMaster') || "Enable Daily Streak Saver"} desc={t('aiAgents.tiktok.streakMasterDesc') || "Automatically dispatch daily streak videos/messages to friends list so you never lose streaks"}>
                  <Toggle
                    id="tt-streak-enabled"
                    value={ttConfig.streakEnabled}
                    onChange={v => handleTtConfigChange('streakEnabled', v)}
                  />
                </SettingRow>

                {/* Daily Schedule Hour */}
                <SettingRow label={t('aiAgents.tiktok.scheduleHour') || "Daily Schedule Hour"} desc={t('aiAgents.tiktok.scheduleHourDesc') || "Hour of the day to automatically dispatch streak maintenance content"}>
                  <select
                    value={ttConfig.streakScheduleHour}
                    onChange={e => handleTtConfigChange('streakScheduleHour', Number(e.target.value))}
                    style={{
                      background: 'rgba(0,0,0,0.6)',
                      border: '1px solid rgba(254, 44, 85, 0.4)',
                      color: '#FE2C55',
                      padding: '6px 14px',
                      fontSize: '0.8rem',
                      fontFamily: 'Share Tech Mono',
                      cursor: 'pointer',
                      borderRadius: '2px',
                    }}
                  >
                    {[6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23].map(h => (
                      <option key={h} value={h}>{String(h).padStart(2, '0')}:00 (Daily)</option>
                    ))}
                  </select>
                </SettingRow>

                {/* Content Send Type */}
                <SettingRow label={t('aiAgents.tiktok.sendType') || "Streak Dispatch Content"} desc={t('aiAgents.tiktok.sendTypeDesc') || "Format of content sent to friends to maintain the streak flame"}>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      type="button"
                      onClick={() => handleTtConfigChange('streakSendType', 'video')}
                      style={{
                        padding: '5px 12px',
                        background: ttConfig.streakSendType === 'video' ? 'rgba(254, 44, 85, 0.25)' : 'rgba(0,0,0,0.4)',
                        border: ttConfig.streakSendType === 'video' ? '1px solid #FE2C55' : '1px solid rgba(255,255,255,0.1)',
                        color: ttConfig.streakSendType === 'video' ? '#FE2C55' : 'var(--text-secondary)',
                        fontFamily: 'Share Tech Mono',
                        fontSize: '0.74rem',
                        cursor: 'pointer',
                        borderRadius: '2px',
                        display: 'flex', alignItems: 'center', gap: '6px',
                      }}
                    >
                      <SciFiVideoClipIcon size={14} color={ttConfig.streakSendType === 'video' ? '#FE2C55' : 'var(--text-secondary)'} />
                      Video Xu Hướng / Clip Ngắn
                    </button>
                    <button
                      type="button"
                      onClick={() => handleTtConfigChange('streakSendType', 'message')}
                      style={{
                        padding: '5px 12px',
                        background: ttConfig.streakSendType === 'message' ? 'rgba(0, 242, 254, 0.25)' : 'rgba(0,0,0,0.4)',
                        border: ttConfig.streakSendType === 'message' ? '1px solid #00F2FE' : '1px solid rgba(255,255,255,0.1)',
                        color: ttConfig.streakSendType === 'message' ? '#00F2FE' : 'var(--text-secondary)',
                        fontFamily: 'Share Tech Mono',
                        fontSize: '0.74rem',
                        cursor: 'pointer',
                        borderRadius: '2px',
                        display: 'flex', alignItems: 'center', gap: '6px',
                      }}
                    >
                      <SciFiMessageStreakIcon size={14} color={ttConfig.streakSendType === 'message' ? '#00F2FE' : 'var(--text-secondary)'} />
                      Tin Nhắn Giữ Chuỗi (Kèm <SciFiFlameStreakIcon size={12} color={ttConfig.streakSendType === 'message' ? '#00F2FE' : 'var(--text-secondary)'} />)
                    </button>
                  </div>
                </SettingRow>

                {/* Streak Message Template */}
                <SettingRow label={t('aiAgents.tiktok.streakTemplate') || "Streak Message Text"} desc={t('aiAgents.tiktok.streakTemplateDesc') || "Greeting text attached with the daily streak video"}>
                  <input
                    type="text"
                    value={ttConfig.streakMessageTemplate}
                    onChange={e => handleTtConfigChange('streakMessageTemplate', e.target.value)}
                    placeholder="Video giữ chuỗi hôm nay nè! Chúc bạn ngày mới vui vẻ nha 🔥✨"
                    style={{
                      width: '380px',
                      background: 'rgba(0,0,0,0.5)',
                      border: '1px solid rgba(254, 44, 85, 0.3)',
                      color: '#fff',
                      padding: '6px 12px',
                      fontFamily: 'Share Tech Mono',
                      fontSize: '0.78rem',
                      borderRadius: '3px',
                      outline: 'none',
                    }}
                  />
                </SettingRow>

                {/* Friends List & Target Manager */}
                <div style={{ marginTop: '20px', paddingTop: '16px', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                  <div style={{ fontSize: '0.78rem', color: '#FE2C55', fontFamily: 'Share Tech Mono', letterSpacing: '1px', fontWeight: 'bold', marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <SciFiUsersGroupIcon size={14} color="#FE2C55" />
                    <span>DANH SÁCH BẠN BÈ CẦN GIỮ CHUỖI ({ttConfig.streakTargets?.length || 0})</span>
                  </div>

                  {/* Add Friend Row */}
                  <div style={{ display: 'flex', gap: '8px', marginBottom: '14px', flexWrap: 'wrap' }}>
                    <input
                      type="text"
                      value={ttNewFriendUsername}
                      onChange={e => setTtNewFriendUsername(e.target.value)}
                      placeholder="@username"
                      style={{
                        flex: '1', minWidth: '180px',
                        background: 'rgba(0,0,0,0.5)',
                        border: '1px solid rgba(255,255,255,0.15)',
                        color: '#fff',
                        padding: '6px 12px',
                        fontFamily: 'Share Tech Mono',
                        fontSize: '0.76rem',
                        borderRadius: '2px',
                      }}
                    />
                    <input
                      type="text"
                      value={ttNewFriendNickname}
                      onChange={e => setTtNewFriendNickname(e.target.value)}
                      placeholder="Tên gợi nhớ"
                      style={{
                        flex: '1', minWidth: '180px',
                        background: 'rgba(0,0,0,0.5)',
                        border: '1px solid rgba(255,255,255,0.15)',
                        color: '#fff',
                        padding: '6px 12px',
                        fontFamily: 'Share Tech Mono',
                        fontSize: '0.76rem',
                        borderRadius: '2px',
                      }}
                    />
                    <button
                      type="button"
                      onClick={handleAddStreakFriend}
                      style={{
                        padding: '6px 16px',
                        background: 'rgba(254, 44, 85, 0.2)',
                        border: '1px solid #FE2C55',
                        color: '#FE2C55',
                        fontFamily: 'Share Tech Mono',
                        fontSize: '0.76rem',
                        fontWeight: 'bold',
                        cursor: 'pointer',
                        borderRadius: '2px',
                        display: 'flex', alignItems: 'center', gap: '6px',
                      }}
                    >
                      <SciFiAddFriendIcon size={13} color="#FE2C55" />
                      THÊM BẠN BÈ
                    </button>
                  </div>

                  {/* Friends Table */}
                  {ttConfig.streakTargets?.length === 0 ? (
                    <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.76rem', fontFamily: 'Share Tech Mono', background: 'rgba(0,0,0,0.2)', borderRadius: '2px' }}>
                      Chưa có bạn bè nào trong danh sách. Hãy nhập @username ở trên để thêm người nhận video giữ chuỗi hàng ngày.
                    </div>
                  ) : (
                    <div style={{ overflowX: 'auto' }}>
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.76rem', fontFamily: 'Share Tech Mono' }}>
                        <thead>
                          <tr style={{ background: 'rgba(254, 44, 85, 0.08)', color: '#FE2C55', textAlign: 'left' }}>
                            <th style={{ padding: '8px 10px', borderBottom: '1px solid rgba(254, 44, 85, 0.2)' }}>BẠN BÈ</th>
                            <th style={{ padding: '8px 10px', borderBottom: '1px solid rgba(254, 44, 85, 0.2)' }}>CHUỖI (STREAK)</th>
                            <th style={{ padding: '8px 10px', borderBottom: '1px solid rgba(254, 44, 85, 0.2)' }}>GỬI GẦN NHẤT</th>
                            <th style={{ padding: '8px 10px', borderBottom: '1px solid rgba(254, 44, 85, 0.2)' }}>TRẠNG THÁI</th>
                            <th style={{ padding: '8px 10px', borderBottom: '1px solid rgba(254, 44, 85, 0.2)', textAlign: 'right' }}>THAO TÁC</th>
                          </tr>
                        </thead>
                        <tbody>
                          {ttConfig.streakTargets.map((friend, idx) => {
                            const isSendingThis = ttInstantSending === friend.username;
                            return (
                              <tr key={idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', background: idx % 2 === 0 ? 'rgba(0,0,0,0.1)' : 'transparent' }}>
                                <td style={{ padding: '8px 10px' }}>
                                  <div style={{ fontWeight: 'bold', color: '#fff' }}>{friend.nickname || friend.username}</div>
                                  <div style={{ fontSize: '0.68rem', color: '#00F2FE', opacity: 0.8 }}>{friend.username}</div>
                                </td>
                                <td style={{ padding: '8px 10px' }}>
                                  <span style={{ padding: '2px 6px', background: 'rgba(254, 44, 85, 0.15)', border: '1px solid rgba(254, 44, 85, 0.4)', borderRadius: '2px', color: '#FE2C55', fontWeight: 'bold', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                                    <SciFiFlameStreakIcon size={12} color="#FE2C55" />
                                    <span>{friend.streak_days || 0} Ngày</span>
                                  </span>
                                </td>
                                <td style={{ padding: '8px 10px', color: 'var(--text-secondary)' }}>
                                  {friend.last_sent ? friend.last_sent : 'Chưa gửi'}
                                </td>
                                <td style={{ padding: '8px 10px' }}>
                                  <span style={{ color: friend.status === 'active' ? 'var(--accent-green)' : 'var(--text-secondary)' }}>
                                    {friend.status === 'active' ? '● Đang giữ chuỗi' : '○ Tạm dừng'}
                                  </span>
                                </td>
                                <td style={{ padding: '8px 10px', textAlign: 'right' }}>
                                  <div style={{ display: 'inline-flex', gap: '6px' }}>
                                    <button
                                      type="button"
                                      onClick={() => handleTriggerTikTokStreak(friend.username)}
                                      disabled={Boolean(ttInstantSending)}
                                      style={{
                                        padding: '3px 8px',
                                        background: 'rgba(254, 44, 85, 0.15)',
                                        border: '1px solid #FE2C55',
                                        color: '#FE2C55',
                                        fontSize: '0.7rem',
                                        cursor: 'pointer',
                                        borderRadius: '2px',
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: '4px',
                                      }}
                                    >
                                      <SciFiFlameStreakIcon size={11} color="#FE2C55" />
                                      <span>{isSendingThis ? 'ĐANG GỬI...' : 'GỬI NGAY'}</span>
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => handleToggleStreakFriend(friend.username)}
                                      style={{
                                        padding: '3px 8px',
                                        background: 'rgba(255,255,255,0.05)',
                                        border: '1px solid rgba(255,255,255,0.15)',
                                        color: 'var(--text-secondary)',
                                        fontSize: '0.7rem',
                                        cursor: 'pointer',
                                        borderRadius: '2px',
                                      }}
                                    >
                                      {friend.status === 'active' ? 'Tạm dừng' : 'Bật lại'}
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => handleRemoveStreakFriend(friend.username)}
                                      style={{
                                        padding: '3px 8px',
                                        background: 'rgba(255,0,0,0.1)',
                                        border: '1px solid rgba(255,0,0,0.3)',
                                        color: 'var(--accent-pink)',
                                        fontSize: '0.7rem',
                                        cursor: 'pointer',
                                        borderRadius: '2px',
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: '4px',
                                      }}
                                    >
                                      <SciFiTrashIcon size={11} color="var(--accent-pink)" />
                                      <span>Xóa</span>
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
              </div>

              {/* Action Buttons Bar */}
              <div style={{ display: 'flex', gap: '12px', marginTop: '20px', alignItems: 'center', flexWrap: 'wrap' }}>
                <button
                  type="button"
                  onClick={handleSaveTikTok}
                  disabled={ttSaving}
                  style={{
                    background: ttSaveSuccess ? 'rgba(0,255,102,0.15)' : 'rgba(0, 242, 254, 0.18)',
                    border: `1px solid ${ttSaveSuccess ? 'var(--accent-green)' : '#00F2FE'}`,
                    color: ttSaveSuccess ? 'var(--accent-green)' : '#00F2FE',
                    padding: '8px 22px',
                    fontFamily: 'Share Tech Mono',
                    fontSize: '0.82rem',
                    cursor: ttSaving ? 'not-allowed' : 'pointer',
                    letterSpacing: '1px',
                    borderRadius: '3px',
                    transition: 'all 0.2s ease',
                    boxShadow: ttSaveSuccess ? '0 0 10px rgba(0,255,102,0.3)' : '0 0 10px rgba(0, 242, 254, 0.2)',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                  }}
                >
                  {ttSaveSuccess ? <SciFiVerifiedCheckIcon size={13} color="var(--accent-green)" /> : null}
                  <span>{ttSaveSuccess ? (t('settings.telegram.saved') || 'SAVED') : (t('aiAgents.tiktok.saveBtn') || 'SAVE TIKTOK CONFIG')}</span>
                </button>

                <button
                  type="button"
                  onClick={() => handleTriggerTikTokStreak(null)}
                  disabled={ttTesting}
                  style={{
                    background: 'rgba(254, 44, 85, 0.15)',
                    border: '1px solid #FE2C55',
                    color: '#FE2C55',
                    padding: '8px 22px',
                    fontFamily: 'Share Tech Mono',
                    fontSize: '0.82rem',
                    cursor: ttTesting ? 'not-allowed' : 'pointer',
                    letterSpacing: '1px',
                    opacity: ttTesting ? 0.6 : 1,
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '8px',
                    borderRadius: '3px',
                  }}
                >
                  {ttTesting ? <SciFiChronoSpinnerIcon size={14} color="#FE2C55" /> : <SciFiFlameStreakIcon size={14} color="#FE2C55" />}
                  <span>{ttTesting ? 'ĐANG GỬI CHUỖI...' : 'GỬI TẤT CẢ CHUỖI NGAY BÂY GIỜ'}</span>
                </button>

                <button
                  type="button"
                  onClick={handleTriggerTikTokScan}
                  disabled={ttTesting}
                  style={{
                    background: 'rgba(0, 242, 254, 0.1)',
                    border: '1px solid rgba(0, 242, 254, 0.4)',
                    color: '#00F2FE',
                    padding: '8px 20px',
                    fontFamily: 'Share Tech Mono',
                    fontSize: '0.82rem',
                    cursor: ttTesting ? 'not-allowed' : 'pointer',
                    letterSpacing: '1px',
                    borderRadius: '3px',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                  }}
                >
                  <SciFiRadarScanIcon size={14} color="#00F2FE" />
                  <span>QUÉT TIN NHẮN THỦ CÔNG</span>
                </button>

                {ttTestResult && (
                  <span style={{
                    fontSize: '0.78rem',
                    fontFamily: 'Share Tech Mono',
                    color: '#00F2FE',
                    textShadow: '0 0 8px currentColor',
                  }}>
                    {ttTestResult}
                  </span>
                )}
              </div>

              {/* ── SECTION 3: SESSION COOKIES CONFIGURATION ── */}
              <div style={{
                marginTop: '24px',
                padding: '16px 20px',
                background: 'rgba(0, 0, 0, 0.3)',
                border: '1px solid rgba(0, 242, 254, 0.25)',
                borderRadius: '4px',
              }}>
                <div style={{ fontSize: '0.78rem', color: '#00F2FE', fontFamily: 'Share Tech Mono', letterSpacing: '1px', fontWeight: 'bold', marginBottom: '8px' }}>
                  TIKTOK SESSION COOKIES (JSON)
                </div>
                <textarea
                  value={ttConfig.cookiesJson}
                  onChange={e => handleTtConfigChange('cookiesJson', e.target.value)}
                  placeholder='[{"name":"sessionid","value":"..."},{"name":"tt_chain_token","value":"..."}]'
                  rows={4}
                  style={{
                    width: '100%',
                    boxSizing: 'border-box',
                    background: 'rgba(0,0,0,0.5)',
                    border: '1px solid rgba(0, 242, 254, 0.2)',
                    borderRadius: '2px',
                    color: '#fff',
                    fontFamily: 'Share Tech Mono',
                    fontSize: '0.72rem',
                    padding: '8px',
                    resize: 'vertical',
                    outline: 'none',
                  }}
                />
              </div>

              {/* ── SECTION 4: RECENT ACTIVITY & STREAK DISPATCHES FEED ── */}
              <div style={{
                marginTop: '24px',
                padding: '16px 20px',
                background: 'rgba(0, 0, 0, 0.35)',
                border: '1px solid rgba(255, 255, 255, 0.08)',
                borderRadius: '4px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <SciFiTerminalPromptIcon size={16} color="#00F2FE" />
                    <span style={{ fontSize: '0.82rem', fontFamily: 'Share Tech Mono', color: '#00F2FE', letterSpacing: '1px', fontWeight: 'bold' }}>
                      NHẬT KÝ HOẠT ĐỘNG & GỬI CHUỖI GẦN ĐÂY
                    </span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>
                      {ttStatus.recentReplies?.length || 0} sự kiện
                    </span>
                    {ttStatus.recentReplies?.length > 0 && (
                      <button
                        type="button"
                        onClick={handleClearTikTokLogs}
                        style={{
                          padding: '3px 8px',
                          background: 'rgba(255,0,0,0.1)',
                          border: '1px solid rgba(255,0,0,0.3)',
                          color: 'var(--accent-pink)',
                          fontSize: '0.68rem',
                          cursor: 'pointer',
                          borderRadius: '2px',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '4px',
                          fontFamily: 'Share Tech Mono',
                        }}
                      >
                        <SciFiTrashIcon size={11} color="var(--accent-pink)" />
                        <span>XOÁ NHẬT KÝ</span>
                      </button>
                    )}
                  </div>
                </div>

                {ttStatus.recentReplies?.length === 0 ? (
                  <div style={{ textAlign: 'center', padding: '20px', color: 'var(--text-secondary)', fontSize: '0.76rem', fontFamily: 'Share Tech Mono' }}>
                    Chưa có nhật ký gửi tin nhắn hoặc giữ chuỗi nào. Các lượt tự động gửi sẽ được ghi nhận tại đây theo thời gian thực.
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {ttStatus.recentReplies.map((log, idx) => (
                      <div key={idx} style={{
                        padding: '10px 14px',
                        background: 'rgba(255,255,255,0.02)',
                        border: '1px solid rgba(255,255,255,0.05)',
                        borderRadius: '2px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: '12px',
                        fontSize: '0.74rem',
                        fontFamily: 'Share Tech Mono',
                      }}>
                        <div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span style={{
                              padding: '1px 6px',
                              borderRadius: '2px',
                              fontSize: '0.65rem',
                              background: log.targetType?.includes('streak') ? 'rgba(254, 44, 85, 0.2)' : 'rgba(0, 242, 254, 0.2)',
                              color: log.targetType?.includes('streak') ? '#FE2C55' : '#00F2FE',
                              border: log.targetType?.includes('streak') ? '1px solid #FE2C55' : '1px solid #00F2FE',
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '4px',
                            }}>
                              {log.targetType?.includes('streak') ? (
                                <>
                                  <SciFiFlameStreakIcon size={11} color="#FE2C55" />
                                  <span>GIỮ CHUỖI</span>
                                </>
                              ) : (
                                <>
                                  <SciFiAiChatBubbleIcon size={11} color="#00F2FE" />
                                  <span>AUTO-REPLY DM</span>
                                </>
                              )}
                            </span>
                            <span style={{ fontWeight: 'bold', color: '#fff' }}>{log.recipientName}</span>
                            {log.recipientId && <span style={{ color: 'var(--text-secondary)', fontSize: '0.68rem' }}>({log.recipientId})</span>}
                          </div>
                          <div style={{ marginTop: '4px', color: 'var(--text-primary)', opacity: 0.85 }}>
                            {log.replyText}
                          </div>
                        </div>

                        <div style={{ textAlign: 'right', flexShrink: 0, fontSize: '0.68rem', color: 'var(--text-secondary)' }}>
                          <div>{log.createdAt}</div>
                          <div style={{ color: 'var(--accent-green)', marginTop: '2px', display: 'flex', alignItems: 'center', gap: '4px', justifyContent: 'flex-end' }}>
                            <SciFiVerifiedCheckIcon size={11} color="var(--accent-green)" />
                            <span>ĐÃ GỬI</span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
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

      {/* ── Tab Content: TELEGRAM BOT & SYSTEM AGENT ──────────────────────── */}
      {activePlatform === 'telegram' && (
        <div style={{
          background: 'rgba(5, 10, 20, 0.85)',
          border: '1px solid rgba(34, 158, 217, 0.35)',
          boxShadow: '0 0 25px rgba(34, 158, 217, 0.15)',
          borderRadius: '4px',
          padding: '24px',
        }}>
          <SectionHeader
            icon={<SciFiTelegramIcon size={22} color="#229ED9" />}
            title={t('aiAgents.telegram.title') || "TELEGRAM COMMUNITY & SYSTEM AGENT"}
            subtitle={t('aiAgents.telegram.subtitle') || "Real-time AI Assistant, bidirectional server management & intelligent threshold alerts"}
            badge={
              <SciFiPulseBadge
                label={tgConfig.enabled ? (t('aiAgents.telegram.statusAlerts') || "ALERTS ACTIVE") : (tgConfig._configured ? (t('aiAgents.telegram.statusLive') || "BOT ONLINE") : (t('aiAgents.telegram.notConfigured') || "NOT CONFIGURED"))}
                color="#229ED9"
              />
            }
          />

          {/* Telegram Telemetry Stats Grid */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '12px',
            marginBottom: '24px',
          }}>
            <div style={{ padding: '12px 14px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(34, 158, 217, 0.2)', borderRadius: '3px' }}>
              <div style={{ fontSize: '0.65rem', color: '#229ED9', fontFamily: 'Share Tech Mono', letterSpacing: '1px' }}>
                {t('aiAgents.telegram.overviewBotStatus') || 'BOT SERVICE'}
              </div>
              <div style={{ fontSize: '0.92rem', color: tgConfig._configured ? 'var(--accent-green)' : 'var(--accent-pink)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', marginTop: '4px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: tgConfig._configured ? 'var(--accent-green)' : 'var(--accent-pink)', boxShadow: `0 0 8px ${tgConfig._configured ? 'var(--accent-green)' : 'var(--accent-pink)'}` }} />
                {tgConfig._configured ? 'ONLINE (Long-Polling)' : 'NOT CONFIGURED'}
              </div>
            </div>

            <div style={{ padding: '12px 14px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(34, 158, 217, 0.2)', borderRadius: '3px' }}>
              <div style={{ fontSize: '0.65rem', color: '#229ED9', fontFamily: 'Share Tech Mono', letterSpacing: '1px' }}>
                {t('aiAgents.telegram.overviewAuthChat') || 'AUTHORIZED CHAT'}
              </div>
              <div style={{ fontSize: '0.92rem', color: tgConfig._configured ? 'var(--accent-cyan)' : 'var(--accent-pink)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', marginTop: '4px' }}>
                {tgConfig._configured ? (t('settings.telegram.configured') || 'SET (from .env)') : (t('settings.telegram.notConfigured') || 'NOT SET')}
              </div>
            </div>

            <div style={{ padding: '12px 14px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(34, 158, 217, 0.2)', borderRadius: '3px' }}>
              <div style={{ fontSize: '0.65rem', color: '#229ED9', fontFamily: 'Share Tech Mono', letterSpacing: '1px' }}>
                {t('aiAgents.telegram.overviewAiEngine') || 'AI ASSISTANT'}
              </div>
              <div style={{ fontSize: '0.92rem', color: 'var(--accent-purple)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', marginTop: '4px' }}>
                Tiểu Bảo Bảo (9Router)
              </div>
            </div>

            <div style={{ padding: '12px 14px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(34, 158, 217, 0.2)', borderRadius: '3px' }}>
              <div style={{ fontSize: '0.65rem', color: '#229ED9', fontFamily: 'Share Tech Mono', letterSpacing: '1px' }}>
                {t('aiAgents.telegram.overviewAlertEngine') || 'ALERT ENGINE'}
              </div>
              <div style={{ fontSize: '0.92rem', color: tgConfig.enabled ? 'var(--accent-yellow)' : 'var(--text-secondary)', fontFamily: 'Share Tech Mono', fontWeight: 'bold', marginTop: '4px' }}>
                {tgConfig.enabled ? 'ACTIVE (Real-time)' : 'STANDBY'}
              </div>
            </div>
          </div>

          {tgLoading ? (
            <div style={{ padding: '30px', textAlign: 'center', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
              <SciFiChronoSpinnerIcon size={18} color="#229ED9" />
              <span>{t('settings.telegram.loading') || 'Loading Telegram configuration...'}</span>
            </div>
          ) : (
            <>
              {/* Bot Token Env Row */}
              <SettingRow
                label={t('settings.telegram.botToken') || "Bot Token"}
                desc={t('settings.telegram.botTokenDesc') || "Managed via TELEGRAM_BOT_TOKEN in .env — restart container to update"}
              >
                <span style={{
                  fontFamily: 'Share Tech Mono',
                  fontSize: '0.78rem',
                  letterSpacing: '1px',
                  color: tgConfig._configured ? 'var(--accent-green)' : 'var(--accent-pink)',
                  textShadow: '0 0 8px currentColor',
                }}>
                  {tgConfig._configured ? (t('settings.telegram.configured') || '✓ SET (from .env)') : (t('settings.telegram.notConfigured') || '✗ NOT CONFIGURED')}
                </span>
              </SettingRow>

              {/* Chat ID Env Row */}
              <SettingRow
                label={t('settings.telegram.chatId') || "Chat ID"}
                desc={t('settings.telegram.chatIdDesc') || "Managed via TELEGRAM_CHAT_ID in .env — restart container to update"}
              >
                <span style={{
                  fontFamily: 'Share Tech Mono',
                  fontSize: '0.78rem',
                  letterSpacing: '1px',
                  color: tgConfig._configured ? 'var(--accent-green)' : 'var(--accent-pink)',
                  textShadow: '0 0 8px currentColor',
                }}>
                  {tgConfig._configured ? (t('settings.telegram.configured') || '✓ SET (from .env)') : (t('settings.telegram.notConfigured') || '✗ NOT CONFIGURED')}
                </span>
              </SettingRow>

              {/* Enable Alerts Toggle */}
              <SettingRow
                label={t('settings.telegram.enableAlerts') || "Enable Alerts"}
                desc={t('settings.telegram.enableAlertsDesc') || "Bot will send automatic alerts when thresholds are exceeded"}
              >
                <Toggle id="tg-alerts-enabled" value={tgConfig.enabled} onChange={v => updateTg('enabled', v)} />
              </SettingRow>

              {/* CPU Alert Threshold */}
              <SettingRow
                label={t('settings.telegram.cpuThreshold') || "CPU Alert Threshold"}
                desc={t('settings.telegram.cpuThresholdDesc') || "Alert when CPU exceeds this value (Telegram-specific)"}
              >
                <ThresholdSlider
                  id="tg-cpu"
                  value={tgConfig.cpuThreshold}
                  onChange={v => updateTg('cpuThreshold', v)}
                  color="var(--accent-cyan)"
                />
              </SettingRow>

              {/* RAM Alert Threshold */}
              <SettingRow
                label={t('settings.telegram.ramThreshold') || "RAM Alert Threshold"}
                desc={t('settings.telegram.ramThresholdDesc') || "Alert when RAM exceeds this value (Telegram-specific)"}
              >
                <ThresholdSlider
                  id="tg-ram"
                  value={tgConfig.ramThreshold}
                  onChange={v => updateTg('ramThreshold', v)}
                  color="var(--accent-purple)"
                />
              </SettingRow>

              {/* Disk Alert Threshold */}
              <SettingRow
                label={t('settings.telegram.diskThreshold') || "Disk Alert Threshold"}
                desc={t('settings.telegram.diskThresholdDesc') || "Alert when any disk partition exceeds this value"}
              >
                <ThresholdSlider
                  id="tg-disk"
                  value={tgConfig.diskThreshold}
                  onChange={v => updateTg('diskThreshold', v)}
                  color="var(--accent-yellow)"
                />
              </SettingRow>

              {/* Alert Cooldown */}
              <SettingRow
                label={t('settings.telegram.cooldown') || "Alert Cooldown"}
                desc={t('settings.telegram.cooldownDesc') || "Minimum time between two consecutive alerts of the same type"}
              >
                <select
                  value={tgConfig.cooldownMinutes}
                  onChange={e => updateTg('cooldownMinutes', Number(e.target.value))}
                  style={{
                    background: 'rgba(0,0,0,0.6)',
                    border: '1px solid rgba(34, 158, 217, 0.4)',
                    color: '#229ED9',
                    padding: '6px 12px',
                    fontSize: '0.8rem',
                    fontFamily: 'Share Tech Mono',
                    cursor: 'pointer',
                    borderRadius: '2px',
                  }}
                >
                  <option value={5}>5 minutes</option>
                  <option value={15}>15 minutes</option>
                  <option value={30}>30 minutes</option>
                  <option value={60}>60 minutes</option>
                </select>
              </SettingRow>

              {/* Action Buttons Bar */}
              <div style={{ display: 'flex', gap: '12px', marginTop: '24px', alignItems: 'center', flexWrap: 'wrap' }}>
                <button
                  type="button"
                  onClick={handleSaveTelegram}
                  style={{
                    background: tgSaved ? 'rgba(0,255,102,0.15)' : 'rgba(34, 158, 217, 0.15)',
                    border: `1px solid ${tgSaved ? 'var(--accent-green)' : '#229ED9'}`,
                    color: tgSaved ? 'var(--accent-green)' : '#229ED9',
                    padding: '8px 22px',
                    fontFamily: 'Share Tech Mono',
                    fontSize: '0.8rem',
                    cursor: 'pointer',
                    letterSpacing: '1px',
                    borderRadius: '3px',
                    transition: 'all 0.2s ease',
                    boxShadow: tgSaved ? '0 0 10px rgba(0,255,102,0.3)' : '0 0 10px rgba(34, 158, 217, 0.2)',
                  }}
                >
                  {tgSaved ? (t('settings.telegram.saved') || '✓ SAVED') : (t('settings.telegram.save') || 'SAVE TELEGRAM')}
                </button>

                <button
                  type="button"
                  onClick={handleTestTelegram}
                  disabled={tgTesting}
                  style={{
                    background: 'rgba(255,165,0,0.1)',
                    border: '1px solid rgba(255,165,0,0.5)',
                    color: 'rgba(255,165,0,1)',
                    padding: '8px 22px',
                    fontFamily: 'Share Tech Mono',
                    fontSize: '0.8rem',
                    cursor: tgTesting ? 'not-allowed' : 'pointer',
                    letterSpacing: '1px',
                    opacity: tgTesting ? 0.6 : 1,
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '8px',
                    borderRadius: '3px',
                  }}
                >
                  {tgTesting ? (
                    <>
                      <SciFiChronoSpinnerIcon size={14} color="rgba(255,165,0,1)" />
                      <span>{t('settings.telegram.sending') || 'SENDING...'}</span>
                    </>
                  ) : (
                    <>
                      <SciFiTelegramIcon size={14} color="rgba(255,165,0,1)" />
                      <span>{t('settings.telegram.sendTest') || 'SEND TEST ALERT'}</span>
                    </>
                  )}
                </button>

                {tgTestResult && (
                  <span style={{
                    fontSize: '0.78rem',
                    fontFamily: 'Share Tech Mono',
                    color: tgTestResult.status === 'success' ? 'var(--accent-green)' : 'var(--accent-pink)',
                    textShadow: '0 0 8px currentColor',
                  }}>
                    {tgTestResult.status === 'success' ? '✓' : '✗'} {tgTestResult.message}
                  </span>
                )}
              </div>

              {/* Supported Bot Commands & AI Capabilities HUD */}
              <div style={{
                marginTop: '28px',
                padding: '16px 20px',
                background: 'rgba(0, 0, 0, 0.35)',
                border: '1px solid rgba(34, 158, 217, 0.2)',
                borderRadius: '4px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                  <SciFiTerminalPromptIcon size={16} color="#229ED9" />
                  <span style={{ fontSize: '0.82rem', fontFamily: 'Share Tech Mono', color: '#229ED9', letterSpacing: '1px', fontWeight: 'bold' }}>
                    {t('aiAgents.telegram.botCommandsTitle') || 'SUPPORTED BOT COMMANDS & AI CAPABILITIES'}
                  </span>
                </div>

                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                  gap: '10px',
                  fontSize: '0.74rem',
                  fontFamily: 'Share Tech Mono',
                }}>
                  <div style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '2px' }}>
                    <strong style={{ color: 'var(--accent-cyan)' }}>/status</strong> — Comprehensive system & container telemetry
                  </div>
                  <div style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '2px' }}>
                    <strong style={{ color: 'var(--accent-cyan)' }}>/cpu</strong> — Real-time CPU load, cores & top processes
                  </div>
                  <div style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '2px' }}>
                    <strong style={{ color: 'var(--accent-cyan)' }}>/ram</strong> — Memory & Swap utilization breakdown
                  </div>
                  <div style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '2px' }}>
                    <strong style={{ color: 'var(--accent-cyan)' }}>/disk</strong> — Disk partition health & remaining storage
                  </div>
                  <div style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '2px' }}>
                    <strong style={{ color: 'var(--accent-purple)' }}>/fb</strong> — Facebook AI Agent status & recent chat triage
                  </div>
                  <div style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '2px' }}>
                    <strong style={{ color: 'var(--accent-yellow)' }}>/report</strong> — Instant full health audit & metric report
                  </div>
                  <div style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '2px' }}>
                    <strong style={{ color: 'var(--accent-green)' }}>/clean</strong> — Clear temporary system memory cache & logs
                  </div>
                  <div style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '2px' }}>
                    <strong style={{ color: 'var(--text-primary)' }}>/help</strong> — Interactive command cheat-sheet & guide
                  </div>
                </div>

                {/* Natural Language AI Assistant Hint */}
                <div style={{
                  marginTop: '14px',
                  padding: '10px 14px',
                  background: 'rgba(34, 158, 217, 0.08)',
                  border: '1px solid rgba(34, 158, 217, 0.25)',
                  borderRadius: '3px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  fontSize: '0.74rem',
                  color: 'var(--text-primary)',
                }}>
                  <SciFiBotIcon size={16} color="#229ED9" />
                  <span>
                    {t('aiAgents.telegram.naturalLanguageHint') || "💬 You can also chat directly in natural language with AI Agent 'Tiểu Bảo Bảo' on Telegram anytime to check servers, take screenshots, manage Facebook AI, or schedule appointments."}
                  </span>
                </div>
              </div>
            </>
          )}
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
            width: 'min(96vw, calc((96vh - 84px) * (16 / 10)))',
            maxWidth: '1440px',
            height: 'min(94vh, calc(96vw * (10 / 16) + 84px))',
            maxHeight: '96vh',
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
                {vncPlatform === 'tiktok'
                  ? (t('aiAgents.tiktok.vncFooterTip') || '💡 Once logged into TikTok successfully, click [SAVE SESSION & CLOSE] to automatically extract and store session cookies.')
                  : (t('aiAgents.facebook.vncFooterTip') || '💡 Once logged into Facebook successfully, click [SAVE SESSION & CLOSE] to automatically extract and store session cookies.')}
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
