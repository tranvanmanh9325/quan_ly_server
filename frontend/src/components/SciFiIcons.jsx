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
export const SciFiContainerIcon = ({ size = 20, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M12 2L2 7V17L12 22L22 17V7L12 2Z" stroke={color} strokeWidth="1.5" strokeLinejoin="round" fill={color} fillOpacity="0.08" />
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

// 17. Custom Sci-Fi Folder Icon for File Manager
export const SciFiFolderIcon = ({ size = 20, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M3 6C3 4.89543 3.89543 4 5 4H9.58579C10.1162 4 10.625 4.21071 11 4.58579L12.4142 6H19C20.1046 6 21 6.89543 21 8V18C21 19.1046 20.1046 20 19 20H5C3.89543 20 3 19.1046 3 18V6Z" stroke={color} strokeWidth="1.6" fill={color} fillOpacity="0.15" />
    <path d="M7 11H17M7 14H13" stroke={color} strokeWidth="1.4" strokeLinecap="round" strokeDasharray="2 2" />
  </svg>
);

// 18. Custom Sci-Fi File Icon for File Manager
export const SciFiFileIcon = ({ size = 20, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M14 2H6C4.89543 2 4 2.89543 4 4V20C4 21.1046 4.89543 22 6 22H18C19.1046 22 20 21.1046 20 20V8L14 2Z" stroke={color} strokeWidth="1.5" fill="rgba(0, 243, 255, 0.05)" />
    <path d="M14 2V8H20" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
    <line x1="8" y1="12" x2="16" y2="12" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="8" y1="15" x2="14" y2="15" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="8" y1="18" x2="11" y2="18" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
  </svg>
);

// 19. Custom Sci-Fi Home Icon
export const SciFiHomeIcon = ({ size = 16, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M3 9.5L12 3L21 9.5V20C21 20.5523 20.5523 21 20 21H15V14H9V21H4C3.44772 21 3 20.5523 3 20V9.5Z" stroke={color} strokeWidth="1.5" strokeLinejoin="round" fill="rgba(0, 243, 255, 0.05)" />
  </svg>
);

// 20. Custom Sci-Fi Play Icon
export const SciFiPlayIcon = ({ size = 14, color = 'var(--accent-green)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <polygon points="5,3 19,12 5,21" fill={color} stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
  </svg>
);

// 21. Custom Sci-Fi Stop Icon
export const SciFiStopIcon = ({ size = 14, color = 'var(--accent-pink)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <rect x="5" y="5" width="14" height="14" rx="2" fill={color} stroke={color} strokeWidth="1.5" />
  </svg>
);

// 22. Custom Sci-Fi Globe Icon for Global Map
export const SciFiGlobeIcon = ({ size = 20, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <circle cx="12" cy="12" r="9" stroke={color} strokeWidth="1.5" fill="rgba(0, 243, 255, 0.05)" />
    <ellipse cx="12" cy="12" rx="9" ry="3.5" stroke={color} strokeWidth="1" strokeDasharray="3 1" />
    <ellipse cx="12" cy="12" rx="3.5" ry="9" stroke={color} strokeWidth="1" strokeDasharray="3 1" />
    <line x1="3" y1="12" x2="21" y2="12" stroke={color} strokeWidth="1.2" />
    <line x1="12" y1="3" x2="12" y2="21" stroke={color} strokeWidth="1.2" />
    <circle cx="12" cy="12" r="2" fill={color} />
  </svg>
);

// 16. Sci-Fi Settings / Gear Icon — circuit cog with inner ring
export const SciFiSettingsIcon = ({ size = 20, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M12 15.5C13.933 15.5 15.5 13.933 15.5 12C15.5 10.067 13.933 8.5 12 8.5C10.067 8.5 8.5 10.067 8.5 12C8.5 13.933 10.067 15.5 12 15.5Z" stroke={color} strokeWidth="1.5" fill={color} fillOpacity="0.12" />
    <path d="M19.4 15C19.2669 15.3016 19.2272 15.6362 19.286 15.9606C19.3448 16.285 19.4995 16.5843 19.73 16.82L19.79 16.88C19.976 17.0657 20.1235 17.2863 20.2241 17.5291C20.3248 17.7719 20.3766 18.0322 20.3766 18.295C20.3766 18.5578 20.3248 18.8181 20.2241 19.0609C20.1235 19.3037 19.976 19.5243 19.79 19.71C19.6043 19.896 19.3837 20.0435 19.1409 20.1441C18.8981 20.2448 18.6378 20.2966 18.375 20.2966C18.1122 20.2966 17.8519 20.2448 17.6091 20.1441C17.3663 20.0435 17.1457 19.896 16.96 19.71L16.9 19.65C16.6643 19.4195 16.365 19.2648 16.0406 19.206C15.7162 19.1472 15.3816 19.1869 15.08 19.32C14.7842 19.4468 14.532 19.6572 14.3543 19.9255C14.1766 20.1938 14.0813 20.5082 14.08 20.83V21C14.08 21.5304 13.8693 22.0391 13.4942 22.4142C13.1191 22.7893 12.6104 23 12.08 23C11.5496 23 11.0409 22.7893 10.6658 22.4142C10.2907 22.0391 10.08 21.5304 10.08 21V20.91C10.0723 20.579 9.96512 20.258 9.77251 19.9887C9.5799 19.7194 9.31074 19.5143 9 19.4C8.69838 19.2669 8.36381 19.2272 8.03941 19.286C7.71502 19.3448 7.41568 19.4995 7.18 19.73L7.12 19.79C6.93425 19.976 6.71368 20.1235 6.47088 20.2241C6.22808 20.3248 5.96783 20.3766 5.705 20.3766C5.44217 20.3766 5.18192 20.3248 4.93912 20.2241C4.69632 20.1235 4.47575 19.976 4.29 19.79C4.10405 19.6043 3.95653 19.3837 3.85588 19.1409C3.75523 18.8981 3.70343 18.6378 3.70343 18.375C3.70343 18.1122 3.75523 17.8519 3.85588 17.6091C3.95653 17.3663 4.10405 17.1457 4.29 16.96L4.35 16.9C4.58054 16.6643 4.73519 16.365 4.794 16.0406C4.85282 15.7162 4.81312 15.3816 4.68 15.08C4.55324 14.7842 4.34276 14.532 4.07447 14.3543C3.80618 14.1766 3.49179 14.0813 3.17 14.08H3C2.46957 14.08 1.96086 13.8693 1.58579 13.4942C1.21071 13.1191 1 12.6104 1 12.08C1 11.5496 1.21071 11.0409 1.58579 10.6658C1.96086 10.2907 2.46957 10.08 3 10.08H3.09C3.42099 10.0723 3.742 9.96512 4.0113 9.77251C4.28059 9.5799 4.48572 9.31074 4.6 9C4.73312 8.69838 4.77282 8.36381 4.714 8.03941C4.65519 7.71502 4.50054 7.41568 4.27 7.18L4.21 7.12C4.02405 6.93425 3.87653 6.71368 3.77588 6.47088C3.67523 6.22808 3.62343 5.96783 3.62343 5.705C3.62343 5.44217 3.67523 5.18192 3.77588 4.93912C3.87653 4.69632 4.02405 4.47575 4.21 4.29C4.39575 4.10405 4.61632 3.95653 4.85912 3.85588C5.10192 3.75523 5.36217 3.70343 5.625 3.70343C5.88783 3.70343 6.14808 3.75523 6.39088 3.85588C6.63368 3.95653 6.85425 4.10405 7.04 4.29L7.1 4.35C7.33568 4.58054 7.63502 4.73519 7.95941 4.794C8.28381 4.85282 8.61838 4.81312 8.92 4.68H9C9.29577 4.55324 9.54802 4.34276 9.72569 4.07447C9.90337 3.80618 9.99872 3.49179 10 3.17V3C10 2.46957 10.2107 1.96086 10.5858 1.58579C10.9609 1.21071 11.4696 1 12 1C12.5304 1 13.0391 1.21071 13.4142 1.58579C13.7893 1.96086 14 2.46957 14 3V3.09C14.0013 3.41179 14.0966 3.72618 14.2743 3.99447C14.452 4.26276 14.7042 4.47324 15 4.6C15.3016 4.73312 15.6362 4.77282 15.9606 4.714C16.285 4.65519 16.5843 4.50054 16.82 4.27L16.88 4.21C17.0657 4.02405 17.2863 3.87653 17.5291 3.77588C17.7719 3.67523 18.0322 3.62343 18.295 3.62343C18.5578 3.62343 18.8181 3.67523 19.0609 3.77588C19.3037 3.87653 19.5243 4.02405 19.71 4.21C19.896 4.39575 20.0435 4.61632 20.1441 4.85912C20.2448 5.10192 20.2966 5.36217 20.2966 5.625C20.2966 5.88783 20.2448 6.14808 20.1441 6.39088C20.0435 6.63368 19.896 6.85425 19.71 7.04L19.65 7.1C19.4195 7.33568 19.2648 7.63502 19.206 7.95941C19.1472 8.28381 19.1869 8.61838 19.32 8.92V9C19.4468 9.29577 19.6572 9.54802 19.9255 9.72569C20.1938 9.90337 20.5082 9.99872 20.83 10H21C21.5304 10 22.0391 10.2107 22.4142 10.5858C22.7893 10.9609 23 11.4696 23 12C23 12.5304 22.7893 13.0391 22.4142 13.4142C22.0391 13.7893 21.5304 14 21 14H20.91C20.5882 14.0013 20.2738 14.0966 20.0055 14.2743C19.7372 14.452 19.5268 14.7042 19.4 15Z" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill={color} fillOpacity="0.05" />
  </svg>
);

// 23. Custom Sci-Fi Telegram Telemetry Transmitter Icon
export const SciFiTelegramIcon = ({ size = 20, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M22 2L11 13" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M22 2L15 22L11 13L2 9L22 2Z" stroke={color} strokeWidth="1.6" strokeLinejoin="round" fill="rgba(0, 243, 255, 0.08)" />
    <circle cx="22" cy="2" r="1.5" fill={color} />
    <path d="M6 16L3 19M18 8L21 5" stroke={color} strokeWidth="1" strokeDasharray="2 2" />
  </svg>
);

// 24. Custom Sci-Fi Info Badge Icon for About Section
export const SciFiInfoIcon = ({ size = 20, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <polygon points="12,2 21,7 21,17 12,22 3,17 3,7" stroke={color} strokeWidth="1.5" strokeLinejoin="round" fill="rgba(0, 243, 255, 0.06)" />
    <line x1="12" y1="11" x2="12" y2="17" stroke={color} strokeWidth="2" strokeLinecap="round" />
    <circle cx="12" cy="7.5" r="1.2" fill={color} />
  </svg>
);

// 25. Custom Sci-Fi Terminal Prompt Icon for Bot Commands
export const SciFiTerminalPromptIcon = ({ size = 16, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M4 17L10 12L4 7" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    <line x1="12" y1="17" x2="20" y2="17" stroke={color} strokeWidth="2" strokeLinecap="round" />
  </svg>
);

