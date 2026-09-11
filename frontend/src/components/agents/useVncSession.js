import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { useTranslation } from '../../i18n/index.jsx';

export function useVncSession({ onSessionSaved } = {}) {
  const { t } = useTranslation();
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

  // Disconnect VNC session immediately if user closes tab, refreshes, or navigates away
  useEffect(() => {
    const handleBeforeUnload = () => {
      if (showVncModal) {
        const apiPrefix = vncPlatform === 'tiktok' ? '/api/tiktok' : '/api/facebook';
        try {
          navigator.sendBeacon(`${apiPrefix}/close-browser-session`);
        } catch {
          // Ignore beacon delivery errors during page unload
        }
      }
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    window.addEventListener('pagehide', handleBeforeUnload);
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
      window.removeEventListener('pagehide', handleBeforeUnload);
      if (showVncModal) {
        const apiPrefix = vncPlatform === 'tiktok' ? '/api/tiktok' : '/api/facebook';
        try {
          navigator.sendBeacon(`${apiPrefix}/close-browser-session`);
        } catch {
          // Ignore beacon delivery errors during unmount
        }
      }
    };
  }, [showVncModal, vncPlatform]);

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
              setVncUrl(`/vnc-embed.html?platform=${platform}&t=${Date.now()}`);
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
    } catch {
      // Best-effort session closure on backend
    }
  };

  const handleSaveBrowserSession = async () => {
    setVncIsSaving(true);
    setVncStatusMsg(t('aiAgents.facebook.extractingCookies') || 'Extracting session cookies...');
    const apiPrefix = vncPlatform === 'tiktok' ? '/api/tiktok' : '/api/facebook';

    try {
      const res = await axios.post(`${apiPrefix}/save-browser-session`);
      if (res.data.status === 'success') {
        setVncStatusMsg(`✓ ${res.data.message}`);
        if (onSessionSaved) {
          onSessionSaved(vncPlatform);
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

  return {
    showVncModal,
    vncPlatform,
    vncUrl,
    vncStatusMsg,
    vncIsLaunching,
    vncIsSaving,
    launchVnc: handleLaunchVncBrowser,
    closeVnc: handleCloseVncModal,
    saveSession: handleSaveBrowserSession,
  };
}
