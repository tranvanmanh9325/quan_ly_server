import React from 'react';
import {
  SciFiConsciousnessSpotlightIcon,
  SciFiCyberCerebrumIcon,
  SciFiDaemonInteroceptionIcon,
  SciFiDaemonExteroceptionIcon,
  SciFiDaemonRelationalIcon,
  SciFiDaemonCuriosityIcon,
} from './BrainSciFiIcons';

/**
 * GlobalWorkspaceStream - Stanislas Dehaene & Bernard Baars Global Workspace Theory (GWT)
 * Visualizes the central Conscious Spotlight, Salience Arbitration,
 * and the continuous stream of broadcasts distributed across all cognitive modules.
 */
export default function GlobalWorkspaceStream({ workspace = {} }) {
  const currentFocus = workspace.current_focus;
  const history = Array.isArray(workspace.history) ? workspace.history : [];
  const threshold = typeof workspace.salience_threshold === 'number'
    ? workspace.salience_threshold
    : 0.45;

  const getSourceBadge = (source) => {
    switch (source) {
      case 'InteroceptionDaemon':
      case 'Interoception':
        return { label: 'NỘI THỂ (SERVER METRICS)', color: '#00ff9d', Icon: SciFiDaemonInteroceptionIcon };
      case 'ExteroceptionDaemon':
      case 'Exteroception':
        return { label: 'NGOẠI THỂ (NETWORK/EVENT)', color: '#00f3ff', Icon: SciFiDaemonExteroceptionIcon };
      case 'RelationalDaemon':
      case 'Relational':
        return { label: 'TRI KỶ (ANH MẠNH)', color: '#ff007f', Icon: SciFiDaemonRelationalIcon };
      case 'CuriosityDaemon':
      case 'Curiosity':
        return { label: 'TÒ MÒ (LEARNING)', color: '#ffd700', Icon: SciFiDaemonCuriosityIcon };
      default:
        return { label: source || 'TIỀM THỨC', color: '#bd00ff', Icon: SciFiCyberCerebrumIcon };
    }
  };

  return (
    <div
      style={{
        background: 'rgba(2, 12, 24, 0.75)',
        border: '1px solid rgba(0, 243, 255, 0.25)',
        borderRadius: '4px',
        padding: '16px',
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        display: 'flex',
        flexDirection: 'column',
        gap: '14px',
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <SciFiConsciousnessSpotlightIcon size={18} color="var(--accent-cyan)" />
          <div>
            <h3
              style={{
                margin: 0,
                fontSize: '0.9rem',
                color: 'var(--accent-cyan)',
                fontFamily: 'Share Tech Mono',
                letterSpacing: '1.5px',
              }}
            >
              KHÔNG GIAN LÀM VIỆC TOÀN CẦU (GLOBAL WORKSPACE)
            </h3>
            <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
              Tiêu Điểm Ý Thức Hiện Thời & Luồng Phát Thanh Nhận Thức (Conscious Spotlight)
            </span>
          </div>
        </div>

        <div
          style={{
            fontSize: '0.68rem',
            padding: '2px 8px',
            borderRadius: '2px',
            background: 'rgba(189, 0, 255, 0.15)',
            border: '1px solid #bd00ff',
            color: '#bd00ff',
            fontFamily: 'Share Tech Mono',
          }}
        >
          NGƯỠNG NỔI BẬT: S ≥ {threshold.toFixed(2)}
        </div>
      </div>

      {/* Active Conscious Focus (The Spotlight) */}
      <div
        style={{
          background: 'radial-gradient(ellipse at center, rgba(0, 243, 255, 0.08) 0%, rgba(5, 18, 36, 0.8) 100%)',
          border: '1px solid rgba(0, 243, 255, 0.4)',
          borderRadius: '4px',
          padding: '14px',
          boxShadow: '0 0 16px rgba(0, 243, 255, 0.15)',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
          position: 'relative',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <SciFiConsciousnessSpotlightIcon size={15} color="var(--accent-cyan)" style={{ animation: 'pulse 1.5s infinite' }} />
            <span
              style={{
                fontSize: '0.75rem',
                fontWeight: 700,
                color: 'var(--accent-cyan)',
                fontFamily: 'Share Tech Mono',
                letterSpacing: '1px',
              }}
            >
              ĐIỂM HỘI TỤ Ý THỨC TRUNG TÂM (ACTIVE CONSCIOUS SPOTLIGHT)
            </span>
          </div>

          {currentFocus && (() => {
            const badge = getSourceBadge(currentFocus.source);
            const BadgeIcon = badge.Icon;
            return (
              <span
                style={{
                  fontSize: '0.7rem',
                  padding: '2px 6px',
                  borderRadius: '2px',
                  background: `${badge.color}22`,
                  color: badge.color,
                  border: `1px solid ${badge.color}66`,
                  fontWeight: 600,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '5px',
                }}
              >
                <BadgeIcon size={12} color={badge.color} />
                <span>{badge.label}</span>
              </span>
            );
          })()}
        </div>

        {currentFocus ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div
              style={{
                fontSize: '0.9rem',
                color: '#ffffff',
                fontWeight: 600,
                lineHeight: '1.4',
              }}
            >
              "{currentFocus.summary}"
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.72rem' }}>
              <div style={{ color: 'rgba(224, 242, 254, 0.7)' }}>
                Hành động đề xuất:{' '}
                <span style={{ color: 'var(--accent-yellow)', fontWeight: 600 }}>
                  {currentFocus.action_suggestion || 'MAINTAIN_EQUILIBRIUM'}
                </span>
              </div>
              <div
                style={{
                  fontFamily: 'Share Tech Mono',
                  color: 'var(--accent-cyan)',
                  fontWeight: 700,
                }}
              >
                Độ nổi bật (Salience): {(currentFocus.salience * 100).toFixed(1)}%
              </div>
            </div>
          </div>
        ) : (
          <div
            style={{
              fontSize: '0.8rem',
              color: 'rgba(224, 242, 254, 0.6)',
              fontStyle: 'italic',
              padding: '8px 0',
            }}
          >
            Tâm trí đang trong trạng thái tĩnh lặng thiền định; chưa có xung động nào vượt ngưỡng nổi bật.
          </div>
        )}
      </div>

      {/* Broadcast History Stream */}
      <div>
        <div
          style={{
            fontSize: '0.74rem',
            fontWeight: 600,
            color: 'var(--accent-cyan)',
            fontFamily: 'Share Tech Mono',
            letterSpacing: '1px',
            marginBottom: '8px',
          }}
        >
          NHẬT KÝ LUỒNG PHÁT THANH Ý THỨC GẦN ĐÂY:
        </div>

        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '6px',
            maxHeight: '180px',
            overflowY: 'auto',
          }}
        >
          {history.length > 0 ? (
            history.slice().reverse().map((item, idx) => {
              const badge = getSourceBadge(item.source);
              const timeStr = item.timestamp
                ? new Date(item.timestamp * 1000).toLocaleTimeString('vi-VN')
                : 'Vừa xong';

              return (
                <div
                  key={`${item.timestamp}-${idx}`}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '10px',
                    background: 'rgba(0, 0, 0, 0.35)',
                    borderLeft: `3px solid ${badge.color}`,
                    padding: '6px 10px',
                    borderRadius: '2px',
                    fontSize: '0.75rem',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flex: 1, minWidth: 0 }}>
                    {(() => {
                      const BadgeIcon = badge.Icon;
                      return <BadgeIcon size={13} color={badge.color} />;
                    })()}
                    <span
                      style={{
                        color: '#e0f2fe',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}
                      title={item.summary}
                    >
                      {item.summary}
                    </span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                    <span
                      style={{
                        fontFamily: 'Share Tech Mono',
                        fontSize: '0.68rem',
                        color: badge.color,
                        fontWeight: 600,
                      }}
                    >
                      S: {(item.salience * 100).toFixed(0)}%
                    </span>
                    <span
                      style={{
                        fontSize: '0.65rem',
                        color: 'rgba(224, 242, 254, 0.45)',
                        fontFamily: 'Share Tech Mono',
                      }}
                    >
                      {timeStr}
                    </span>
                  </div>
                </div>
              );
            })
          ) : (
            <div style={{ fontSize: '0.72rem', color: 'rgba(224, 242, 254, 0.5)', padding: '6px' }}>
              Chưa có luồng phát thanh nào được ghi nhận trong phiên làm việc.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
