import React from 'react';

// 1. Custom Sci-Fi Hexagonal Shield Icon for Systemd Services
export const SciFiShieldIcon = ({ size = 20, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M12 2L3 6V12C3 17.52 6.84 21.74 12 23C17.16 21.74 21 17.52 21 12V6L12 2Z" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="rgba(0, 243, 255, 0.05)" />
    <path d="M12 6L6 9.5V13.5C6 16.5 8.5 19 12 20C15.5 19 18 16.5 18 13.5V9.5L12 6Z" stroke={color} strokeWidth="1" strokeDasharray="2 2" />
    <circle cx="12" cy="12" r="2.5" fill={color} />
    <path d="M12 8V9.5M12 14.5V16M8 12H9.5M14.5 12H16" stroke={color} strokeWidth="1" />
  </svg>
);

// 2. Custom Sci-Fi Data Container Icon for Docker
export const SciFiContainerIcon = ({ size = 20, color = 'var(--accent-green)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M12 2L2 7V17L12 22L22 17V7L12 2Z" stroke={color} strokeWidth="1.5" strokeLinejoin="round" fill="rgba(0, 255, 157, 0.05)" />
    <path d="M2 7L12 12L22 7" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
    <path d="M12 12V22" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
    <path d="M7 4.5L17 9.5M7 14.5L17 19.5" stroke={color} strokeWidth="1" strokeOpacity="0.6" strokeDasharray="2 2" />
    <circle cx="12" cy="7" r="1.5" fill={color} />
    <circle cx="7" cy="14.5" r="1" fill={color} />
    <circle cx="17" cy="14.5" r="1" fill={color} />
  </svg>
);

// 3. Custom Sci-Fi Chrono Target Icon for Systemd Timers
export const SciFiChronoIcon = ({ size = 20, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <circle cx="12" cy="12" r="9" stroke={color} strokeWidth="1.5" strokeDasharray="6 2" fill="rgba(0, 243, 255, 0.05)" />
    <circle cx="12" cy="12" r="5" stroke={color} strokeWidth="1" />
    <path d="M12 7V12L15.5 14" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
    <path d="M12 1V3M12 21V23M1 12H3M21 12H23" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
    <circle cx="12" cy="12" r="1.5" fill={color} />
  </svg>
);

// 4. Custom Sci-Fi Quantum Core Icon for Host Runtimes
export const SciFiQuantumIcon = ({ size = 20, color = 'var(--accent-magenta)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M13 2L3 14H12L11 22L21 10H12L13 2Z" fill="rgba(255, 0, 85, 0.15)" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
    <circle cx="12" cy="12" r="1.5" fill="#fff" />
    <path d="M7 6L5 4M17 18L19 20M4 17L2 19M20 7L22 5" stroke={color} strokeWidth="1" strokeLinecap="round" />
  </svg>
);

// 5. Custom Sci-Fi Hologram Grid Icon for Sidebar Overview
export const SciFiDashboardIcon = ({ size = 20, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="3" y="3" width="8" height="8" rx="1" stroke={color} strokeWidth="1.5" fill="rgba(0,243,255,0.05)" />
    <rect x="13" y="3" width="8" height="5" rx="1" stroke={color} strokeWidth="1.5" fill="rgba(0,243,255,0.05)" />
    <rect x="13" y="10" width="8" height="11" rx="1" stroke={color} strokeWidth="1.5" fill="rgba(0,243,255,0.05)" />
    <rect x="3" y="13" width="8" height="8" rx="1" stroke={color} strokeWidth="1.5" fill="rgba(0,243,255,0.05)" />
    <circle cx="7" cy="7" r="1.5" fill={color} />
    <circle cx="17" cy="15.5" r="1.5" fill={color} />
  </svg>
);

// 6. Custom Sci-Fi ECG Waveform Icon for Sidebar Processes
export const SciFiPulseIcon = ({ size = 20, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M2 12H6L9 3L13 21L16 10L18 14H22" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    <circle cx="9" cy="3" r="1.5" fill={color} />
    <circle cx="13" cy="21" r="1.5" fill={color} />
  </svg>
);

// 7. Custom Sci-Fi Server Blade Rack Icon for Sidebar Services
export const SciFiServerRackIcon = ({ size = 20, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="3" y="3" width="18" height="5" rx="1" stroke={color} strokeWidth="1.5" />
    <rect x="3" y="10" width="18" height="5" rx="1" stroke={color} strokeWidth="1.5" />
    <rect x="3" y="17" width="18" height="4" rx="1" stroke={color} strokeWidth="1.5" />
    <circle cx="6" cy="5.5" r="1" fill={color} />
    <circle cx="9" cy="5.5" r="1" fill={color} />
    <circle cx="6" cy="12.5" r="1" fill={color} />
    <circle cx="9" cy="12.5" r="1" fill={color} />
    <circle cx="6" cy="19" r="1" fill={color} />
    <line x1="15" y1="5.5" x2="18" y2="5.5" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
    <line x1="15" y1="12.5" x2="18" y2="12.5" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
    <line x1="15" y1="19" x2="18" y2="19" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

// 8. Custom Sci-Fi Cyber Shield Lock Icon for Sidebar Security
export const SciFiCyberLockIcon = ({ size = 20, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M12 2L4 5V11C4 16.5 7.5 20.5 12 22C16.5 20.5 20 16.5 20 11V5L12 2Z" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
    <rect x="9" y="10" width="6" height="5" rx="1" stroke={color} strokeWidth="1.2" />
    <path d="M10 10V8C10 6.9 10.9 6 12 6C13.1 6 14 6.9 14 8V10" stroke={color} strokeWidth="1.2" />
    <circle cx="12" cy="12.5" r="1" fill={color} />
  </svg>
);

// 9. Custom Sci-Fi Network Port Icon
export const SciFiPortIcon = ({ size = 20, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <rect x="4" y="4" width="16" height="16" rx="2" stroke={color} strokeWidth="1.5" fill="rgba(0,243,255,0.05)" />
    <path d="M9 9H15M9 12H15M9 15H13" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
    <circle cx="17" cy="15" r="1" fill={color} />
  </svg>
);

// 10. Custom Sci-Fi Terminal Log Icon
export const SciFiTerminalIcon = ({ size = 20, color = 'var(--accent-green)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <rect x="3" y="4" width="18" height="16" rx="2" stroke={color} strokeWidth="1.5" fill="rgba(0,0,0,0.4)" />
    <path d="M7 9L10 12L7 15" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    <line x1="12" y1="15" x2="16" y2="15" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);

// 11. Custom Sci-Fi Target Search Reticle Icon
export const SciFiSearchIcon = ({ size = 16, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <circle cx="11" cy="11" r="7" stroke={color} strokeWidth="1.5" strokeDasharray="10 2" />
    <line x1="16" y1="16" x2="22" y2="22" stroke={color} strokeWidth="2" strokeLinecap="round" />
    <circle cx="11" cy="11" r="2" fill={color} />
  </svg>
);

// 12. Custom Sci-Fi Process Kill / Danger Icon
export const SciFiKillIcon = ({ size = 16, color = 'var(--accent-pink)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <polygon points="12,2 22,22 2,22" stroke={color} strokeWidth="1.5" fill="rgba(255,0,85,0.1)" strokeLinejoin="round" />
    <line x1="12" y1="9" x2="12" y2="15" stroke={color} strokeWidth="2" strokeLinecap="round" />
    <circle cx="12" cy="18" r="1" fill={color} />
  </svg>
);

// 13. Custom Sci-Fi Refresh Sync Icon
export const SciFiRefreshIcon = ({ size = 16, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M21.5 2V6H17.5M2.5 22V18H6.5" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M21.05 11A9 9 0 005.64 5.64L2.5 6M2.95 13A9 9 0 0018.36 18.36L21.5 18" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

// 14. Custom Sci-Fi Download / Export Icon
export const SciFiDownloadIcon = ({ size = 16, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M12 3V15M12 15L7 10M12 15L17 10" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M3 17V19C3 20.1 3.9 21 5 21H19C20.1 21 21 20.1 21 19V17" stroke={color} strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);

// 15. Custom Sci-Fi System Health Pulse Badge
export const SciFiPulseBadge = ({ size = 16, color = 'var(--accent-green)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <circle cx="12" cy="12" r="8" stroke={color} strokeWidth="1.5" fill="rgba(0, 255, 157, 0.1)" />
    <circle cx="12" cy="12" r="3" fill={color} />
  </svg>
);

// 16. Custom Sci-Fi Web Command Console Terminal Icon
export const SciFiConsoleIcon = ({ size = 16, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <rect x="2" y="3" width="20" height="18" rx="3" stroke={color} strokeWidth="1.5" fill="rgba(0,0,0,0.5)" />
    <path d="M6 9L10 12L6 15" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    <line x1="12" y1="15" x2="17" y2="15" stroke={color} strokeWidth="2" strokeLinecap="round" />
  </svg>
);