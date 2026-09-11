import React from 'react';

// ── Sci-Fi Sub-components ───────────────────────────────────────────────────
export const SectionHeader = ({ icon, title, subtitle, badge }) => (
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

export const SettingRow = ({ label, desc, children }) => (
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

export const Toggle = ({ value, onChange, id }) => (
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

export const ThresholdSlider = ({ value, onChange, id, unit = '%', min = 1, max = 100, color = 'var(--accent-cyan)' }) => (
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
export const DurationChip = ({ label, selected, onClick }) => (
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
