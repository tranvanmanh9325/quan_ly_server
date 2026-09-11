import React from 'react';
import { createPortal } from 'react-dom';
import {
  SciFiBrowserLaunchIcon,
  SciFiChronoSpinnerIcon,
  SciFiCheckCircleIcon,
  SciFiCloseIcon,
} from '../SciFiIcons';
import { useTranslation } from '../../i18n/index.jsx';

export default function AiAgentVncModal({
  isOpen,
  platform,
  vncUrl,
  vncStatusMsg,
  isSaving,
  onClose,
  onSaveSession,
}) {
  const { t } = useTranslation();
  if (!isOpen) return null;

  return createPortal(
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
              onClick={onSaveSession}
              disabled={isSaving}
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
                cursor: isSaving ? 'not-allowed' : 'pointer',
                boxShadow: '0 0 10px rgba(0, 255, 102, 0.25)',
              }}
            >
              {isSaving ? <SciFiChronoSpinnerIcon size={14} color="var(--accent-green)" /> : <SciFiCheckCircleIcon size={14} color="var(--accent-green)" />}
              {isSaving ? (t('aiAgents.facebook.vncSavingCookies') || 'SAVING COOKIES...') : (t('aiAgents.facebook.vncSaveSessionBtn') || 'SAVE SESSION & CLOSE')}
            </button>

            <button
              type="button"
              onClick={onClose}
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
            {platform === 'tiktok'
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
  );
}
