import React from 'react';

/**
 * RussellCircumplexRadar - 2D Cartesian Affect Space Visualization
 * Plots Valence [-1..1] vs Arousal [0..1] with Cyberpunk holographic aesthetics.
 */
export default function RussellCircumplexRadar({ affect = {} }) {
  const valence = typeof affect.valence === 'number' ? affect.valence : 0.25;
  const arousal = typeof affect.arousal === 'number' ? affect.arousal : 0.65;
  const quadrant = affect.quadrant || 'Q1';
  const emotionalTitle = affect.emotional_title || 'Hào hứng & Tò mò';
  const styleHint = affect.style_hint || 'Sôi nổi, chủ động đề xuất giải pháp mới, chia sẻ hào hứng';

  // Coordinate mapping for 300x300 canvas
  // X: valence [-1..1] -> [30..270] (center 150)
  // Y: arousal [0..1] -> [270..30] (0 is bottom 270, 1 is top 30)
  const cx = 150 + valence * 120;
  const cy = 270 - arousal * 240;

  // Determine quadrant color theme
  const getQuadTheme = (q) => {
    switch (q) {
      case 'Q1': return { color: '#00ff9d', name: 'Q1: HÀO HỨNG & SÁNG TẠO' };
      case 'Q2': return { color: '#ff3366', name: 'Q2: CĂNG THẲNG & CẢNH GIÁC' };
      case 'Q3': return { color: '#bd00ff', name: 'Q3: TRẦM TƯ & MỆT MỎI' };
      case 'Q4': return { color: '#00f3ff', name: 'Q4: BÌNH YÊN & THƯ GIÃN' };
      default:   return { color: '#00f3ff', name: 'TRUNG TÍNH' };
    }
  };

  const currentTheme = getQuadTheme(quadrant);

  return (
    <div style={{
      background: 'rgba(2, 12, 24, 0.75)',
      border: '1px solid rgba(0, 243, 255, 0.25)',
      borderRadius: '4px',
      padding: '16px',
      boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
      display: 'flex',
      flexDirection: 'column',
      gap: '14px',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '1rem' }}>🎭</span>
          <div>
            <h3 style={{
              margin: 0,
              fontSize: '0.9rem',
              color: 'var(--accent-cyan)',
              fontFamily: 'Share Tech Mono',
              letterSpacing: '1.5px',
            }}>
              KHÔNG GIAN CẢM XÚC RUSSELL CIRCUMPLEX
            </h3>
            <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
              2D Affect Plane (Valence × Arousal)
            </span>
          </div>
        </div>

        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          padding: '3px 10px',
          background: 'rgba(0, 243, 255, 0.08)',
          border: `1px solid ${currentTheme.color}`,
          borderRadius: '3px',
          fontFamily: 'Share Tech Mono',
          fontSize: '0.75rem',
          color: currentTheme.color,
          fontWeight: 'bold',
        }}>
          <span>{currentTheme.name}</span>
        </div>
      </div>

      {/* SVG 2D Radar Grid */}
      <div style={{ display: 'flex', justifyContent: 'center', position: 'relative' }}>
        <svg width="300" height="300" viewBox="0 0 300 300" style={{ overflow: 'visible' }}>
          {/* Background Quadrants Subtle Tints */}
          <rect x="150" y="30" width="120" height="120" fill="#00ff9d" fillOpacity="0.03" />
          <rect x="30" y="30" width="120" height="120" fill="#ff3366" fillOpacity="0.03" />
          <rect x="30" y="150" width="120" height="120" fill="#bd00ff" fillOpacity="0.03" />
          <rect x="150" y="150" width="120" height="120" fill="#00f3ff" fillOpacity="0.03" />

          {/* Outer Circle Frame */}
          <rect x="30" y="30" width="240" height="240" rx="3" stroke="rgba(0, 243, 255, 0.2)" strokeWidth="1" fill="none" />

          {/* Concentric Range Rings */}
          <circle cx="150" cy="150" r="120" stroke="rgba(0, 243, 255, 0.15)" strokeWidth="1" strokeDasharray="3 3" fill="none" />
          <circle cx="150" cy="150" r="80" stroke="rgba(0, 243, 255, 0.15)" strokeWidth="0.8" strokeDasharray="2 2" fill="none" />
          <circle cx="150" cy="150" r="40" stroke="rgba(0, 243, 255, 0.15)" strokeWidth="0.8" strokeDasharray="2 2" fill="none" />

          {/* Coordinate Axes */}
          <line x1="30" y1="150" x2="270" y2="150" stroke="rgba(0, 243, 255, 0.5)" strokeWidth="1.2" />
          <line x1="150" y1="30" x2="150" y2="270" stroke="rgba(0, 243, 255, 0.5)" strokeWidth="1.2" />

          {/* Axis Labels */}
          <text x="275" y="154" fill="var(--accent-cyan)" fontSize="9" fontFamily="Share Tech Mono" textAnchor="start">+VALENCE</text>
          <text x="25" y="154" fill="#ff3366" fontSize="9" fontFamily="Share Tech Mono" textAnchor="end">-VALENCE</text>
          <text x="150" y="22" fill="#ffb800" fontSize="9" fontFamily="Share Tech Mono" textAnchor="middle">+AROUSAL (CAO)</text>
          <text x="150" y="285" fill="var(--text-secondary)" fontSize="9" fontFamily="Share Tech Mono" textAnchor="middle">-AROUSAL (TRẦM)</text>

          {/* Quadrant corner labels */}
          <text x="260" y="44" fill="rgba(0, 255, 157, 0.5)" fontSize="8" fontFamily="Share Tech Mono" textAnchor="end">Q1: HÀO HỨNG</text>
          <text x="40" y="44" fill="rgba(255, 51, 102, 0.5)" fontSize="8" fontFamily="Share Tech Mono" textAnchor="start">Q2: CẢNH GIÁC</text>
          <text x="40" y="260" fill="rgba(189, 0, 255, 0.5)" fontSize="8" fontFamily="Share Tech Mono" textAnchor="start">Q3: MỆT MỎI</text>
          <text x="260" y="260" fill="rgba(0, 243, 255, 0.5)" fontSize="8" fontFamily="Share Tech Mono" textAnchor="end">Q4: THƯ THÁI</text>

          {/* Crosshair indicator at current mood */}
          <line x1={cx} y1="30" x2={cx} y2="270" stroke={currentTheme.color} strokeWidth="0.8" strokeDasharray="3 3" strokeOpacity="0.4" />
          <line x1="30" y1={cy} x2="270" y2={cy} stroke={currentTheme.color} strokeWidth="0.8" strokeDasharray="3 3" strokeOpacity="0.4" />

          {/* Pulsing Ripple Rings */}
          <circle cx={cx} cy={cy} r="14" stroke={currentTheme.color} strokeWidth="1" strokeOpacity="0.5" fill="none">
            <animate attributeName="r" values="8;20;8" dur="2.4s" repeatCount="indefinite" />
            <animate attributeName="stroke-opacity" values="0.8;0;0.8" dur="2.4s" repeatCount="indefinite" />
          </circle>

          {/* Center Glowing Mood Puck */}
          <circle cx={cx} cy={cy} r="6" fill={currentTheme.color} />
          <circle cx={cx} cy={cy} r="2" fill="#fff" />
        </svg>
      </div>

      {/* Mood Telemetry Summary Box */}
      <div style={{
        background: 'rgba(0, 0, 0, 0.45)',
        border: '1px solid rgba(0, 243, 255, 0.15)',
        borderRadius: '3px',
        padding: '10px 14px',
        display: 'flex',
        flexDirection: 'column',
        gap: '6px',
        fontFamily: 'Share Tech Mono',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: '0.8rem', color: '#fff', fontWeight: 'bold' }}>
            TÂM TRẠNG: <span style={{ color: currentTheme.color }}>{emotionalTitle}</span>
          </span>
          <div style={{ display: 'flex', gap: '12px', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
            <span>V = <b style={{ color: valence >= 0 ? '#00ff9d' : '#ff3366' }}>{valence >= 0 ? `+${valence}` : valence}</b></span>
            <span>A = <b style={{ color: '#ffb800' }}>{arousal}</b></span>
          </div>
        </div>

        <div style={{
          fontSize: '0.72rem',
          color: 'rgba(255, 255, 255, 0.75)',
          lineHeight: '1.4',
          borderLeft: `2px solid ${currentTheme.color}`,
          paddingLeft: '8px',
          marginTop: '2px',
        }}>
          <span style={{ color: 'var(--accent-cyan)' }}>Gợi ý phong thái: </span>
          {styleHint}
        </div>
      </div>
    </div>
  );
}
