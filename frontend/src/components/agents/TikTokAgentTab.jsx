import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import {
  SciFiBotIcon, SciFiPulseBadge, SciFiBrowserLaunchIcon,
  SciFiChronoSpinnerIcon, SciFiCheckCircleIcon, SciFiCloseIcon,
  SciFiEnergyBoltIcon, SciFiFlameStreakIcon, SciFiVideoClipIcon,
  SciFiMessageStreakIcon, SciFiAddFriendIcon, SciFiTrashIcon,
  SciFiRadarScanIcon, SciFiAiChatBubbleIcon, SciFiVerifiedCheckIcon,
  SciFiUsersGroupIcon, SciFiSearchIcon, SciFiPlayPulseIcon,
  SciFiHoloSilhouette,
} from '../SciFiIcons';
import {
  SectionHeader, SettingRow, Toggle, ThresholdSlider, DurationChip
} from './AgentUiControls';
import { useTranslation } from '../../i18n/index.jsx';

export default function TikTokAgentTab({
  onLaunchVnc,
  vncIsLaunching = false,
  vncStatusMsg = '',
  refreshTrigger = 0,
}) {
  const { t } = useTranslation();
  const handleLaunchVncBrowser = onLaunchVnc || (() => {});
  const vncPlatform = 'tiktok';

  // ── TikTok state ──────────────────────────────────────────────────────────
  const [ttConfig, setTtConfig] = useState({
    enabled: false,
    streakEnabled: true,
    streakScheduleHour: 9,
    streakTargets: [],
    streakMessageTemplate: 'Video giữ chuỗi hôm nay nè! Chúc bạn ngày mới vui vẻ nha',
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
  const [ttFriendsScanning, setTtFriendsScanning] = useState(false);
  const [ttFriendsScanMsg, setTtFriendsScanMsg] = useState('');
  const [ttFriendSearch, setTtFriendSearch] = useState('');
  const [ttFriendFilter, setTtFriendFilter] = useState('all'); // 'all' | 'active' | 'paused'
  const [ttShowManualAdd, setTtShowManualAdd] = useState(false);

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
          streakMessageTemplate: d.streakMessageTemplate || 'Video giữ chuỗi hôm nay nè! Chúc bạn ngày mới vui vẻ nha',
          streakSendType: d.streakSendType || 'video',
          threshold: Number(d.threshold ?? 3),
          scanIntervalMinutes: Number(d.scanIntervalMinutes ?? 3),
          idleTimeoutMinutes: Number(d.idleTimeoutMinutes ?? 1),
          humanSessionMinutes: Number(d.humanSessionMinutes ?? 5),
          cooldownMinutes: Number(d.cooldownMinutes ?? 60),
          cookiesJson: cookies,
          customMessage: d.customMessage || '',
          lastFriendsScannedAt: d.lastFriendsScannedAt || d.last_friends_scanned_at || null,
        });
        setTtStatus({
          enabled: Boolean(d.enabled),
          streakEnabled: Boolean(d.streakEnabled ?? true),
          lastCheckAt: d.lastCheckAt,
          lastStreakRunAt: d.lastStreakRunAt,
          recentReplies: d.recentReplies || [],
          lastStatus: d.lastStatus || '',
          hasCookies: Boolean(cookies && cookies.length > 20),
          lastFriendsScannedAt: d.lastFriendsScannedAt || d.last_friends_scanned_at || null,
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

  const handleScanTikTokFriends = async () => {
    setTtFriendsScanning(true);
    setTtFriendsScanMsg('Đang kích hoạt Radar quét danh sách bạn bè TikTok...');
    try {
      const res = await axios.post('/api/tiktok/scan-friends');
      if (res.data?.targets) {
        setTtConfig(prev => ({
          ...prev,
          streakTargets: res.data.targets,
        }));
      }
      setTtFriendsScanMsg(res.data?.message || 'Đã quét xong danh sách bạn bè TikTok!');
      fetchTtConfig();
    } catch (e) {
      setTtFriendsScanMsg(e.response?.data?.message || 'Lỗi khi quét bạn bè. Hãy kiểm tra trạng thái đăng nhập TikTok.');
    } finally {
      setTtFriendsScanning(false);
      setTimeout(() => setTtFriendsScanMsg(''), 5000);
    }
  };

  const handleBatchToggleFriends = async (action) => {
    try {
      const res = await axios.post('/api/tiktok/batch-toggle-friends', { action });
      if (res.data?.targets) {
        setTtConfig(prev => ({
          ...prev,
          streakTargets: res.data.targets,
        }));
      }
      fetchTtConfig();
    } catch (e) {
      console.error('Failed to batch toggle friends:', e);
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


  useEffect(() => {
    if (refreshTrigger) {
      fetchTtConfig();
    }
  }, [refreshTrigger, fetchTtConfig]);

  return (
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

              {/* ── SECTION 2: DAILY AUTO STREAK KEEPER (GIỮ CHUỖI TIKTOK) ── */}
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
                      Tin Nhắn Giữ Chuỗi
                    </button>
                  </div>
                </SettingRow>

                {/* Streak Message Template */}
                <SettingRow label={t('aiAgents.tiktok.streakTemplate') || "Streak Message Text"} desc={t('aiAgents.tiktok.streakTemplateDesc') || "Greeting text attached with the daily streak video"}>
                  <input
                    type="text"
                    value={ttConfig.streakMessageTemplate}
                    onChange={e => handleTtConfigChange('streakMessageTemplate', e.target.value)}
                    placeholder="Video giữ chuỗi hôm nay nè! Chúc bạn ngày mới vui vẻ nha"
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

                {/* ── SMART FRIEND SCANNER & TACTICAL CONTROL BAR ── */}
                <div style={{
                  marginTop: '20px',
                  paddingTop: '16px',
                  borderTop: '1px solid rgba(255,255,255,0.06)'
                }}>
                  {/* Top Bar: Title, Last Scanned At, Scan Button & Manual Drawer Toggle */}
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    flexWrap: 'wrap',
                    gap: '12px',
                    marginBottom: '16px'
                  }}>
                    <div>
                      <div style={{
                        fontSize: '0.82rem',
                        color: '#FE2C55',
                        fontFamily: 'Share Tech Mono',
                        letterSpacing: '1.2px',
                        fontWeight: 'bold',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px'
                      }}>
                        <SciFiUsersGroupIcon size={16} color="#FE2C55" />
                        <span>QUẢN LÝ BẠN BÈ GIỮ CHUỖI TIKTOK</span>
                        <span style={{ fontSize: '0.74rem', color: 'var(--accent-cyan)', opacity: 0.85 }}>
                          ({(ttConfig.streakTargets || []).length} BẠN BÈ)
                        </span>
                      </div>
                      <div style={{
                        fontSize: '0.7rem',
                        color: 'var(--text-secondary)',
                        opacity: 0.7,
                        marginTop: '3px',
                        fontFamily: 'Share Tech Mono'
                      }}>
                        {ttStatus.lastFriendsScannedAt || ttConfig.lastFriendsScannedAt
                          ? `Lần quét radar gần nhất: ${ttStatus.lastFriendsScannedAt || ttConfig.lastFriendsScannedAt}`
                          : 'Chưa thực hiện quét bạn bè tự động từ TikTok Messages'}
                      </div>
                    </div>

                    {/* Scan and Manual Add Controls */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                      <button
                        type="button"
                        onClick={handleScanTikTokFriends}
                        disabled={ttFriendsScanning}
                        style={{
                          padding: '7px 16px',
                          background: ttFriendsScanning
                            ? 'rgba(0, 243, 255, 0.2)'
                            : 'linear-gradient(135deg, rgba(254, 44, 85, 0.25) 0%, rgba(0, 243, 255, 0.15) 100%)',
                          border: ttFriendsScanning ? '1px solid var(--accent-cyan)' : '1px solid #FE2C55',
                          color: ttFriendsScanning ? 'var(--accent-cyan)' : '#fff',
                          fontFamily: 'Share Tech Mono',
                          fontSize: '0.76rem',
                          fontWeight: 'bold',
                          letterSpacing: '1px',
                          cursor: ttFriendsScanning ? 'not-allowed' : 'pointer',
                          borderRadius: '2px',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '8px',
                          boxShadow: ttFriendsScanning
                            ? '0 0 15px rgba(0, 243, 255, 0.4)'
                            : '0 0 12px rgba(254, 44, 85, 0.25)',
                          transition: 'all 0.2s ease',
                        }}
                      >
                        {ttFriendsScanning ? (
                          <>
                            <SciFiChronoSpinnerIcon size={14} color="var(--accent-cyan)" />
                            <span>ĐANG QUÉT RADAR TIKTOK...</span>
                          </>
                        ) : (
                          <>
                            <SciFiRadarScanIcon size={15} color="#FE2C55" />
                            <span>QUÉT DANH SÁCH BẠN BÈ</span>
                          </>
                        )}
                      </button>

                      <button
                        type="button"
                        onClick={() => setTtShowManualAdd(!ttShowManualAdd)}
                        style={{
                          padding: '7px 12px',
                          background: ttShowManualAdd ? 'rgba(0, 243, 255, 0.2)' : 'rgba(255, 255, 255, 0.05)',
                          border: ttShowManualAdd ? '1px solid var(--accent-cyan)' : '1px solid rgba(255, 255, 255, 0.2)',
                          color: ttShowManualAdd ? 'var(--accent-cyan)' : 'var(--text-secondary)',
                          fontFamily: 'Share Tech Mono',
                          fontSize: '0.74rem',
                          cursor: 'pointer',
                          borderRadius: '2px',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '5px',
                        }}
                      >
                        <SciFiAddFriendIcon size={13} color="currentColor" />
                        <span>{ttShowManualAdd ? 'ĐÓNG NHẬP TAY' : 'NHẬP THỦ CÔNG'}</span>
                      </button>
                    </div>
                  </div>

                  {/* Scan Result Toast */}
                  {ttFriendsScanMsg && (
                    <div style={{
                      marginBottom: '14px',
                      padding: '8px 14px',
                      background: 'rgba(0, 243, 255, 0.1)',
                      border: '1px solid var(--accent-cyan)',
                      color: 'var(--accent-cyan)',
                      fontFamily: 'Share Tech Mono',
                      fontSize: '0.76rem',
                      borderRadius: '2px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                    }}>
                      <SciFiCheckCircleIcon size={14} color="var(--accent-cyan)" />
                      <span>{ttFriendsScanMsg}</span>
                    </div>
                  )}

                  {/* 3-Tile Telemetry Badges */}
                  {(() => {
                    const allTargets = ttConfig.streakTargets || [];
                    const total = allTargets.length;
                    const active = allTargets.filter(f => f.status === 'active').length;
                    const paused = total - active;

                    return (
                      <div style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
                        gap: '10px',
                        marginBottom: '16px',
                      }}>
                        <div style={{
                          padding: '10px 14px',
                          background: 'rgba(0, 0, 0, 0.4)',
                          border: '1px solid rgba(255, 255, 255, 0.1)',
                          borderRadius: '3px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                        }}>
                          <div>
                            <div style={{ fontSize: '0.66rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>TỔNG BẠN BÈ</div>
                            <div style={{ fontSize: '1.1rem', fontWeight: 'bold', color: '#fff', fontFamily: 'Share Tech Mono' }}>{total}</div>
                          </div>
                          <SciFiUsersGroupIcon size={20} color="var(--accent-cyan)" />
                        </div>

                        <div style={{
                          padding: '10px 14px',
                          background: 'rgba(254, 44, 85, 0.08)',
                          border: '1px solid rgba(254, 44, 85, 0.3)',
                          borderRadius: '3px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                        }}>
                          <div>
                            <div style={{ fontSize: '0.66rem', color: '#FE2C55', fontFamily: 'Share Tech Mono' }}>ĐANG GIỮ CHUỖI</div>
                            <div style={{ fontSize: '1.1rem', fontWeight: 'bold', color: '#FE2C55', fontFamily: 'Share Tech Mono' }}>{active}</div>
                          </div>
                          <SciFiFlameStreakIcon size={20} color="#FE2C55" />
                        </div>

                        <div style={{
                          padding: '10px 14px',
                          background: 'rgba(0, 0, 0, 0.4)',
                          border: '1px solid rgba(255, 255, 255, 0.1)',
                          borderRadius: '3px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                        }}>
                          <div>
                            <div style={{ fontSize: '0.66rem', color: 'rgba(255,255,255,0.5)', fontFamily: 'Share Tech Mono' }}>TẠM DỪNG</div>
                            <div style={{ fontSize: '1.1rem', fontWeight: 'bold', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>{paused}</div>
                          </div>
                          <SciFiInfoIcon size={20} color="rgba(255,255,255,0.4)" />
                        </div>
                      </div>
                    );
                  })()}

                  {/* Toolbar: Search + Filter Chips + Batch Actions */}
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    flexWrap: 'wrap',
                    gap: '10px',
                    marginBottom: '16px',
                    padding: '10px 14px',
                    background: 'rgba(0, 0, 0, 0.35)',
                    border: '1px solid rgba(255, 255, 255, 0.08)',
                    borderRadius: '3px',
                  }}>
                    {/* Search Input */}
                    <div style={{ position: 'relative', flex: '1', minWidth: '200px' }}>
                      <span style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)', opacity: 0.6 }}>
                        <SciFiSearchIcon size={13} color="var(--accent-cyan)" />
                      </span>
                      <input
                        type="text"
                        value={ttFriendSearch}
                        onChange={e => setTtFriendSearch(e.target.value)}
                        placeholder="Tìm theo nickname hoặc @username..."
                        style={{
                          width: '100%',
                          padding: '6px 12px 6px 30px',
                          background: 'rgba(0, 0, 0, 0.6)',
                          border: '1px solid rgba(0, 243, 255, 0.25)',
                          color: '#fff',
                          fontFamily: 'Share Tech Mono',
                          fontSize: '0.76rem',
                          borderRadius: '2px',
                          outline: 'none',
                        }}
                      />
                    </div>

                    {/* Filter Tabs */}
                    {(() => {
                      const allTargets = ttConfig.streakTargets || [];
                      const total = allTargets.length;
                      const active = allTargets.filter(f => f.status === 'active').length;
                      const paused = total - active;

                      return (
                        <div style={{ display: 'flex', gap: '6px' }}>
                          {[
                            { id: 'all', label: `TẤT CẢ (${total})` },
                            { id: 'active', label: `BẬT (${active})` },
                            { id: 'paused', label: `DỪNG (${paused})` },
                          ].map(tab => (
                            <button
                              key={tab.id}
                              type="button"
                              onClick={() => setTtFriendFilter(tab.id)}
                              style={{
                                padding: '4px 10px',
                                fontSize: '0.7rem',
                                fontFamily: 'Share Tech Mono',
                                borderRadius: '2px',
                                cursor: 'pointer',
                                border: ttFriendFilter === tab.id ? '1px solid var(--accent-cyan)' : '1px solid rgba(255,255,255,0.1)',
                                background: ttFriendFilter === tab.id ? 'rgba(0, 243, 255, 0.15)' : 'rgba(0,0,0,0.4)',
                                color: ttFriendFilter === tab.id ? 'var(--accent-cyan)' : 'var(--text-secondary)',
                                transition: 'all 0.15s ease',
                              }}
                            >
                              {tab.label}
                            </button>
                          ))}
                        </div>
                      );
                    })()}

                    {/* Batch Actions */}
                    <div style={{ display: 'flex', gap: '6px' }}>
                      <button
                        type="button"
                        onClick={() => handleBatchToggleFriends('enable_all')}
                        style={{
                          padding: '4px 10px',
                          fontSize: '0.68rem',
                          fontFamily: 'Share Tech Mono',
                          fontWeight: 'bold',
                          borderRadius: '2px',
                          cursor: 'pointer',
                          border: '1px solid var(--accent-green)',
                          background: 'rgba(0, 255, 102, 0.1)',
                          color: 'var(--accent-green)',
                        }}
                      >
                        ✓ BẬT TẤT CẢ
                      </button>
                      <button
                        type="button"
                        onClick={() => handleBatchToggleFriends('disable_all')}
                        style={{
                          padding: '4px 10px',
                          fontSize: '0.68rem',
                          fontFamily: 'Share Tech Mono',
                          borderRadius: '2px',
                          cursor: 'pointer',
                          border: '1px solid rgba(255, 255, 255, 0.2)',
                          background: 'rgba(255, 255, 255, 0.05)',
                          color: 'var(--text-secondary)',
                        }}
                      >
                        ✕ TẮT TẤT CẢ
                      </button>
                    </div>
                  </div>

                  {/* Collapsible Manual Add Drawer */}
                  {ttShowManualAdd && (
                    <div style={{
                      marginBottom: '16px',
                      padding: '14px 16px',
                      background: 'rgba(0, 243, 255, 0.04)',
                      border: '1px solid rgba(0, 243, 255, 0.3)',
                      borderRadius: '3px',
                      display: 'flex',
                      gap: '10px',
                      flexWrap: 'wrap',
                      alignItems: 'center',
                    }}>
                      <input
                        type="text"
                        value={ttNewFriendUsername}
                        onChange={e => setTtNewFriendUsername(e.target.value)}
                        placeholder="@username TikTok"
                        style={{
                          flex: '1', minWidth: '160px',
                          background: 'rgba(0,0,0,0.6)',
                          border: '1px solid rgba(255,255,255,0.2)',
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
                        placeholder="Tên gợi nhớ (Ví dụ: Thảo My)"
                        style={{
                          flex: '1', minWidth: '160px',
                          background: 'rgba(0,0,0,0.6)',
                          border: '1px solid rgba(255,255,255,0.2)',
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
                          background: 'rgba(0, 243, 255, 0.2)',
                          border: '1px solid var(--accent-cyan)',
                          color: 'var(--accent-cyan)',
                          fontFamily: 'Share Tech Mono',
                          fontSize: '0.76rem',
                          fontWeight: 'bold',
                          cursor: 'pointer',
                          borderRadius: '2px',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                        }}
                      >
                        <SciFiAddFriendIcon size={12} color="var(--accent-cyan)" />
                        <span>XÁC NHẬN THÊM</span>
                      </button>
                    </div>
                  )}

                  {/* Friends Matrix Cards Grid */}
                  {(() => {
                    const allTargets = ttConfig.streakTargets || [];
                    const q = ttFriendSearch.toLowerCase().trim();
                    const filtered = allTargets.filter(f => {
                      const matchSearch = !q ||
                        (f.username && f.username.toLowerCase().includes(q)) ||
                        (f.nickname && f.nickname.toLowerCase().includes(q));
                      const matchStatus =
                        ttFriendFilter === 'all' ||
                        (ttFriendFilter === 'active' && f.status === 'active') ||
                        (ttFriendFilter === 'paused' && f.status !== 'active');
                      return matchSearch && matchStatus;
                    });

                    if (filtered.length === 0) {
                      return (
                        <div style={{
                          padding: '35px 20px',
                          textAlign: 'center',
                          background: 'rgba(0, 0, 0, 0.25)',
                          border: '1px dashed rgba(255, 255, 255, 0.1)',
                          borderRadius: '3px',
                          color: 'var(--text-secondary)',
                          fontFamily: 'Share Tech Mono',
                          fontSize: '0.78rem',
                        }}>
                          {q ? (
                            <div>Không tìm thấy bạn bè nào khớp với từ khóa "{q}"</div>
                          ) : (
                            <div>
                              Chưa có bạn bè nào trong danh sách. Hãy nhấn nút <b>"QUÉT DANH SÁCH BẠN BÈ"</b> ở trên để hệ thống tự động tìm kiếm từ TikTok Messages.
                            </div>
                          )}
                        </div>
                      );
                    }

                    return (
                      <div style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fill, minmax(310px, 1fr))',
                        gap: '12px',
                      }}>
                        {filtered.map((friend) => {
                          const isSending = ttInstantSending === friend.username;
                          const isActive = friend.status === 'active';

                          return (
                            <div
                              key={friend.username}
                              style={{
                                padding: '14px',
                                background: isActive
                                  ? 'linear-gradient(135deg, rgba(254, 44, 85, 0.07) 0%, rgba(10, 12, 18, 0.85) 100%)'
                                  : 'rgba(0, 0, 0, 0.4)',
                                border: isActive
                                  ? '1px solid rgba(254, 44, 85, 0.35)'
                                  : '1px solid rgba(255, 255, 255, 0.08)',
                                borderRadius: '4px',
                                boxShadow: isActive ? '0 0 15px rgba(254, 44, 85, 0.06)' : 'none',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '10px',
                                position: 'relative',
                                transition: 'all 0.2s ease',
                              }}
                            >
                              {/* Card Top: Avatar + Nickname + @username + Status Switch */}
                              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', overflow: 'hidden' }}>
                                  {friend.avatar_url ? (
                                    <img
                                      src={friend.avatar_url}
                                      alt={friend.nickname || friend.username}
                                      style={{
                                        width: '38px',
                                        height: '38px',
                                        borderRadius: '3px',
                                        border: isActive ? '1px solid #FE2C55' : '1px solid rgba(255,255,255,0.2)',
                                        objectFit: 'cover',
                                        flexShrink: 0,
                                      }}
                                      onError={e => {
                                        e.target.style.display = 'none';
                                      }}
                                    />
                                  ) : (
                                    <SciFiHoloSilhouette size={38} color={isActive ? '#FE2C55' : 'var(--accent-cyan)'} />
                                  )}

                                  <div style={{ overflow: 'hidden' }}>
                                    <div style={{
                                      fontSize: '0.84rem',
                                      fontWeight: 'bold',
                                      color: '#fff',
                                      fontFamily: 'Share Tech Mono',
                                      lineHeight: '1.2',
                                      whiteSpace: 'nowrap',
                                      overflow: 'hidden',
                                      textOverflow: 'ellipsis',
                                    }}>
                                      {friend.nickname || friend.username}
                                    </div>
                                    <div style={{
                                      fontSize: '0.7rem',
                                      color: 'var(--accent-cyan)',
                                      opacity: 0.85,
                                      fontFamily: 'Share Tech Mono',
                                      marginTop: '2px',
                                      whiteSpace: 'nowrap',
                                      overflow: 'hidden',
                                      textOverflow: 'ellipsis',
                                    }}>
                                      {friend.username}
                                    </div>
                                  </div>
                                </div>

                                {/* Custom Toggle Switch */}
                                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', flexShrink: 0 }}>
                                  <input
                                    type="checkbox"
                                    checked={isActive}
                                    onChange={() => handleToggleStreakFriend(friend.username)}
                                    style={{ display: 'none' }}
                                  />
                                  <div style={{
                                    width: '36px',
                                    height: '18px',
                                    background: isActive ? 'rgba(254, 44, 85, 0.3)' : 'rgba(255,255,255,0.08)',
                                    border: isActive ? '1px solid #FE2C55' : '1px solid rgba(255,255,255,0.2)',
                                    borderRadius: '2px',
                                    position: 'relative',
                                    transition: 'all 0.2s ease',
                                  }}>
                                    <div style={{
                                      width: '12px',
                                      height: '12px',
                                      background: isActive ? '#FE2C55' : 'rgba(255,255,255,0.4)',
                                      borderRadius: '1px',
                                      position: 'absolute',
                                      top: '2px',
                                      left: isActive ? '20px' : '2px',
                                      transition: 'all 0.2s ease',
                                    }} />
                                  </div>
                                </label>
                              </div>

                              {/* Card Middle: Streak Flame Badge & Last Sent Telemetry */}
                              <div style={{
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                padding: '6px 10px',
                                background: 'rgba(0, 0, 0, 0.3)',
                                border: '1px solid rgba(255, 255, 255, 0.05)',
                                borderRadius: '2px',
                                fontSize: '0.72rem',
                                fontFamily: 'Share Tech Mono',
                              }}>
                                <div style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: '4px',
                                  color: '#FE2C55',
                                  fontWeight: 'bold',
                                }}>
                                  <SciFiFlameStreakIcon size={12} color="#FE2C55" />
                                  <span>{friend.streak_days || 0} NGÀY CHUỖI</span>
                                </div>

                                <div style={{ color: 'var(--text-secondary)', opacity: 0.8 }}>
                                  {friend.last_sent ? `Đã gửi: ${friend.last_sent}` : 'Chưa gửi'}
                                </div>
                              </div>

                              {/* Card Bottom: Instant Dispatch Button & Delete Action */}
                              <div style={{ display: 'flex', gap: '6px', marginTop: '2px' }}>
                                <button
                                  type="button"
                                  onClick={() => handleTriggerTikTokStreak(friend.username)}
                                  disabled={Boolean(ttInstantSending)}
                                  style={{
                                    flex: '1',
                                    padding: '6px 10px',
                                    background: isSending ? 'rgba(0, 243, 255, 0.2)' : 'rgba(254, 44, 85, 0.15)',
                                    border: isSending ? '1px solid var(--accent-cyan)' : '1px solid #FE2C55',
                                    color: isSending ? 'var(--accent-cyan)' : '#FE2C55',
                                    fontFamily: 'Share Tech Mono',
                                    fontSize: '0.72rem',
                                    fontWeight: 'bold',
                                    cursor: Boolean(ttInstantSending) ? 'not-allowed' : 'pointer',
                                    borderRadius: '2px',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    gap: '6px',
                                    transition: 'all 0.15s ease',
                                  }}
                                >
                                  {isSending ? (
                                    <>
                                      <SciFiChronoSpinnerIcon size={12} color="var(--accent-cyan)" />
                                      <span>ĐANG GỬI CLIP...</span>
                                    </>
                                  ) : (
                                    <>
                                      <SciFiPlayPulseIcon size={12} color="#FE2C55" />
                                      <span>BẮN VIDEO NGAY</span>
                                    </>
                                  )}
                                </button>

                                <button
                                  type="button"
                                  title="Xóa bạn bè khỏi danh sách"
                                  onClick={() => handleRemoveStreakFriend(friend.username)}
                                  style={{
                                    padding: '6px 10px',
                                    background: 'rgba(255, 255, 255, 0.04)',
                                    border: '1px solid rgba(255, 255, 255, 0.15)',
                                    color: 'var(--text-secondary)',
                                    cursor: 'pointer',
                                    borderRadius: '2px',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                  }}
                                >
                                  <SciFiTrashIcon size={13} color="currentColor" />
                                </button>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    );
                  })()}
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
  );
}
