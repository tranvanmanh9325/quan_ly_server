import React from 'react';

// ═══════════════════════════════════════════════════════════════
//  CUSTOM SCI-FI / CYBERPUNK SVG ICON LIBRARY
//  All icons are hand-crafted SVG paths — zero external dependencies.
//  Each icon is unique and purpose-built for its section.
// ═══════════════════════════════════════════════════════════════

// 1. OVERVIEW — Multi-layered Holographic HUD Grid with scan diamond
export const SciFiDashboardIcon = ({ size = 20, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    {/* Outer frame with corner cuts */}
    <path d="M2 5L5 2H10V5H2ZM14 2H19L22 5V10H19V2ZM22 14V19L19 22H14V19H22ZM10 22H5L2 19V14H5V22Z"
      fill={color} fillOpacity="0.08" stroke={color} strokeWidth="0.8" />
    {/* Inner cross grid */}
    <line x1="12" y1="2" x2="12" y2="22" stroke={color} strokeWidth="0.5" strokeOpacity="0.4" />
    <line x1="2" y1="12" x2="22" y2="12" stroke={color} strokeWidth="0.5" strokeOpacity="0.4" />
    {/* Center diamond reticle */}
    <path d="M12 7L17 12L12 17L7 12L12 7Z" stroke={color} strokeWidth="1.2" fill={color} fillOpacity="0.1" />
    {/* Corner data blocks */}
    <rect x="3" y="3" width="3" height="3" fill={color} fillOpacity="0.6" />
    <rect x="18" y="3" width="3" height="3" fill={color} fillOpacity="0.3" />
    <rect x="3" y="18" width="3" height="3" fill={color} fillOpacity="0.3" />
    <rect x="18" y="18" width="3" height="3" fill={color} fillOpacity="0.6" />
    {/* Center dot */}
    <circle cx="12" cy="12" r="1.5" fill={color} />
  </svg>
);

// 2. PROCESSES — ECG Pulse with circuit node branches
export const SciFiPulseIcon = ({ size = 20, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    {/* Circuit base lines */}
    <line x1="2" y1="18" x2="4" y2="18" stroke={color} strokeWidth="1" strokeOpacity="0.5" />
    <line x1="20" y1="18" x2="22" y2="18" stroke={color} strokeWidth="1" strokeOpacity="0.5" />
    {/* ECG waveform — sharp medical spike style */}
    <polyline points="2,14 5,14 7,18 8,6 9,18 11,14 13,14 15,10 16,16 17,14 22,14"
      stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    {/* Node branch dots */}
    <circle cx="8" cy="6" r="1.5" fill={color} />
    <circle cx="15" cy="10" r="1" fill={color} fillOpacity="0.7" />
    {/* Bottom circuit traces */}
    <path d="M4 20H8M12 20H16M20 20H22" stroke={color} strokeWidth="0.8" strokeOpacity="0.4" strokeLinecap="round" />
  </svg>
);

// 3. SERVICES — Server blade rack with power LEDs and activity bars
export const SciFiServerRackIcon = ({ size = 20, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    {/* Rack chassis outline with vents */}
    <rect x="2" y="2" width="20" height="6" rx="1" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.06" />
    <rect x="2" y="10" width="20" height="6" rx="1" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.06" />
    <rect x="2" y="18" width="20" height="4" rx="1" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.06" />
    {/* Row 1: status LED + activity bar */}
    <circle cx="5" cy="5" r="1.2" fill={color} />
    <rect x="8" y="4" width="7" height="2" rx="0.5" fill={color} fillOpacity="0.5" />
    <line x1="17" y1="5" x2="20" y2="5" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
    {/* Row 2: status LED + activity bar */}
    <circle cx="5" cy="13" r="1.2" fill={color} fillOpacity="0.5" />
    <rect x="8" y="12" width="4" height="2" rx="0.5" fill={color} fillOpacity="0.35" />
    <line x1="15" y1="13" x2="20" y2="13" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
    {/* Row 3: eject slot indicator */}
    <line x1="5" y1="20" x2="10" y2="20" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="13" y1="20" x2="18" y2="20" stroke={color} strokeWidth="1.2" strokeLinecap="round" strokeOpacity="0.5" />
  </svg>
);

// 4. FILE MANAGER — Data crystal shard with grid-scan overlay
export const SciFiFolderIcon = ({ size = 20, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    {/* Crystal shard body */}
    <path d="M3 8C3 6.9 3.9 6 5 6H9L11 4H19C20.1 4 21 4.9 21 6V18C21 19.1 20.1 20 19 20H5C3.9 20 3 19.1 3 18V8Z"
      stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.07" />
    {/* Internal scan grid lines */}
    <line x1="3" y1="11" x2="21" y2="11" stroke={color} strokeWidth="0.6" strokeOpacity="0.35" strokeDasharray="2 2" />
    <line x1="3" y1="15" x2="21" y2="15" stroke={color} strokeWidth="0.6" strokeOpacity="0.35" strokeDasharray="2 2" />
    <line x1="9" y1="11" x2="9" y2="20" stroke={color} strokeWidth="0.6" strokeOpacity="0.35" strokeDasharray="2 2" />
    <line x1="15" y1="11" x2="15" y2="20" stroke={color} strokeWidth="0.6" strokeOpacity="0.35" strokeDasharray="2 2" />
    {/* Data node corners */}
    <circle cx="9" cy="11" r="1" fill={color} />
    <circle cx="15" cy="15" r="1" fill={color} fillOpacity="0.7" />
  </svg>
);

// 5. DOCKER CONTAINERS — Hexagonal pod cluster with network mesh connections
// Unique design: 3 hexagonal pods interconnected via circuit traces, representing containers in a cluster
export const SciFiContainerIcon = ({ size = 20, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    {/* Center pod — main container */}
    <polygon points="12,3 15.5,5 15.5,9 12,11 8.5,9 8.5,5"
      stroke={color} strokeWidth="1.3" fill={color} fillOpacity="0.15" />
    {/* Center LED dot */}
    <circle cx="12" cy="7" r="1.2" fill={color} />
    {/* Bottom-left pod */}
    <polygon points="5.5,13 8,14.5 8,17.5 5.5,19 3,17.5 3,14.5"
      stroke={color} strokeWidth="1.1" fill={color} fillOpacity="0.08" />
    <circle cx="5.5" cy="16" r="0.8" fill={color} fillOpacity="0.7" />
    {/* Bottom-right pod */}
    <polygon points="18.5,13 21,14.5 21,17.5 18.5,19 16,17.5 16,14.5"
      stroke={color} strokeWidth="1.1" fill={color} fillOpacity="0.08" />
    <circle cx="18.5" cy="16" r="0.8" fill={color} fillOpacity="0.7" />
    {/* Network connection lines — center → bottom-left */}
    <line x1="9" y1="10.5" x2="7" y2="13.5" stroke={color} strokeWidth="1" strokeDasharray="1.5 1.5" strokeLinecap="round" />
    {/* Network connection lines — center → bottom-right */}
    <line x1="15" y1="10.5" x2="17" y2="13.5" stroke={color} strokeWidth="1" strokeDasharray="1.5 1.5" strokeLinecap="round" />
    {/* Bottom connection — bottom-left → bottom-right */}
    <line x1="8" y1="17" x2="16" y2="17" stroke={color} strokeWidth="0.8" strokeDasharray="1.5 1.5" strokeLinecap="round" strokeOpacity="0.6" />
  </svg>
);

// 6. GLOBAL MAP — Orbital scan sphere with meridian rings and target reticle
export const SciFiGlobeIcon = ({ size = 20, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    {/* Main sphere */}
    <circle cx="12" cy="12" r="9" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.05" />
    {/* Longitude arcs */}
    <ellipse cx="12" cy="12" rx="4" ry="9" stroke={color} strokeWidth="0.9" strokeDasharray="2 1.5" />
    {/* Latitude rings */}
    <ellipse cx="12" cy="9" rx="7.7" ry="2.5" stroke={color} strokeWidth="0.8" strokeOpacity="0.6" />
    <ellipse cx="12" cy="15" rx="6.2" ry="2" stroke={color} strokeWidth="0.6" strokeOpacity="0.4" />
    {/* Equator line */}
    <line x1="3" y1="12" x2="21" y2="12" stroke={color} strokeWidth="0.9" />
    {/* Target crosshair at center */}
    <circle cx="12" cy="12" r="2" stroke={color} strokeWidth="1" fill="none" />
    <circle cx="12" cy="12" r="0.8" fill={color} />
    {/* North/south poles */}
    <circle cx="12" cy="3" r="0.8" fill={color} fillOpacity="0.5" />
    <circle cx="12" cy="21" r="0.8" fill={color} fillOpacity="0.5" />
  </svg>
);

// 7. TERMINAL CONSOLE — Cyberpunk CRT terminal with scanline matrix
export const SciFiConsoleIcon = ({ size = 16, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    {/* Monitor bezel with chamfered corners */}
    <path d="M2 4C2 3.4 2.4 3 3 3H21C21.6 3 22 3.4 22 4V17C22 17.6 21.6 18 21 18H13V20H15C15.6 20 16 20.4 16 21H8C8 20.4 8.4 20 9 20H11V18H3C2.4 18 2 17.6 2 17V4Z"
      stroke={color} strokeWidth="1.4" fill="rgba(0,0,0,0.6)" />
    {/* CRT scanlines — subtle horizontal bands */}
    <line x1="4" y1="7" x2="20" y2="7" stroke={color} strokeWidth="0.4" strokeOpacity="0.25" />
    <line x1="4" y1="10" x2="20" y2="10" stroke={color} strokeWidth="0.4" strokeOpacity="0.25" />
    <line x1="4" y1="13" x2="20" y2="13" stroke={color} strokeWidth="0.4" strokeOpacity="0.25" />
    {/* Prompt chevron "> " */}
    <path d="M5 9L9 12L5 15" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    {/* Cursor block */}
    <rect x="11" y="10.5" width="5" height="2.5" rx="0.5" fill={color} fillOpacity="0.7" />
  </svg>
);

// 8. SECURITY & LOGS — DNA Helix Shield with lock core
export const SciFiCyberLockIcon = ({ size = 20, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    {/* Hexagonal shield outline */}
    <path d="M12 2L4 6V13C4 17.4 7.4 21.5 12 23C16.6 21.5 20 17.4 20 13V6L12 2Z"
      stroke={color} strokeWidth="1.4" strokeLinejoin="round" fill={color} fillOpacity="0.06" />
    {/* Inner shield ring */}
    <path d="M12 5.5L6.5 8V13C6.5 16 8.8 18.8 12 20C15.2 18.8 17.5 16 17.5 13V8L12 5.5Z"
      stroke={color} strokeWidth="0.7" strokeDasharray="2 1.5" fill="none" />
    {/* Lock shackle */}
    <path d="M9.5 11V9.5C9.5 7.8 10.6 6.5 12 6.5C13.4 6.5 14.5 7.8 14.5 9.5V11"
      stroke={color} strokeWidth="1.3" strokeLinecap="round" />
    {/* Lock body */}
    <rect x="8.5" y="11" width="7" height="5.5" rx="1" stroke={color} strokeWidth="1.3" fill={color} fillOpacity="0.12" />
    {/* Keyhole */}
    <circle cx="12" cy="13.2" r="1.1" fill={color} />
    <line x1="12" y1="14.3" x2="12" y2="15.8" stroke={color} strokeWidth="1.1" strokeLinecap="round" />
  </svg>
);

// 9. SETTINGS — Quantum circuit gear with inner processor die
export const SciFiSettingsIcon = ({ size = 20, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    {/* Gear teeth — 8-tooth cog built from polygon */}
    <path d="M12 2L13.4 5.2L16.8 4.4L17.1 7.9L20.4 9.1L19 12L20.4 14.9L17.1 16.1L16.8 19.6L13.4 18.8L12 22L10.6 18.8L7.2 19.6L6.9 16.1L3.6 14.9L5 12L3.6 9.1L6.9 7.9L7.2 4.4L10.6 5.2L12 2Z"
      stroke={color} strokeWidth="1.2" fill={color} fillOpacity="0.07" strokeLinejoin="round" />
    {/* Processor die — inner square IC */}
    <rect x="8.5" y="8.5" width="7" height="7" rx="1" stroke={color} strokeWidth="1.1" fill={color} fillOpacity="0.1" />
    {/* IC pin traces */}
    <line x1="10" y1="8.5" x2="10" y2="6.5" stroke={color} strokeWidth="0.9" strokeOpacity="0.5" />
    <line x1="14" y1="8.5" x2="14" y2="6.5" stroke={color} strokeWidth="0.9" strokeOpacity="0.5" />
    <line x1="10" y1="15.5" x2="10" y2="17.5" stroke={color} strokeWidth="0.9" strokeOpacity="0.5" />
    <line x1="14" y1="15.5" x2="14" y2="17.5" stroke={color} strokeWidth="0.9" strokeOpacity="0.5" />
    <line x1="8.5" y1="10" x2="6.5" y2="10" stroke={color} strokeWidth="0.9" strokeOpacity="0.5" />
    <line x1="8.5" y1="14" x2="6.5" y2="14" stroke={color} strokeWidth="0.9" strokeOpacity="0.5" />
    <line x1="15.5" y1="10" x2="17.5" y2="10" stroke={color} strokeWidth="0.9" strokeOpacity="0.5" />
    <line x1="15.5" y1="14" x2="17.5" y2="14" stroke={color} strokeWidth="0.9" strokeOpacity="0.5" />
    {/* Core chip cell */}
    <rect x="10.5" y="10.5" width="3" height="3" fill={color} fillOpacity="0.5" />
  </svg>
);

// 10. NETWORK PORT — Ethernet port with signal waves
export const SciFiPortIcon = ({ size = 20, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    {/* RJ45 jack body */}
    <rect x="5" y="4" width="14" height="12" rx="1.5" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.06" />
    {/* Contact pins inside jack */}
    <line x1="8" y1="8" x2="8" y2="12" stroke={color} strokeWidth="1" strokeLinecap="round" />
    <line x1="10.5" y1="7" x2="10.5" y2="12" stroke={color} strokeWidth="1" strokeLinecap="round" />
    <line x1="13" y1="8" x2="13" y2="12" stroke={color} strokeWidth="1" strokeLinecap="round" />
    <line x1="15.5" y1="7" x2="15.5" y2="12" stroke={color} strokeWidth="1" strokeLinecap="round" />
    {/* Clip latch */}
    <path d="M9 16V19H15V16" stroke={color} strokeWidth="1.1" strokeLinejoin="round" />
    {/* Signal waves emanating from port */}
    <path d="M2 10C2 10 2.5 8 4 8" stroke={color} strokeWidth="1" strokeLinecap="round" strokeOpacity="0.6" />
    <path d="M22 10C22 10 21.5 8 20 8" stroke={color} strokeWidth="1" strokeLinecap="round" strokeOpacity="0.6" />
  </svg>
);

// 11. TERMINAL LOG — Scrolling data feed with typewriter bar
export const SciFiTerminalIcon = ({ size = 20, color = 'var(--accent-green)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    {/* Screen frame */}
    <rect x="3" y="3" width="18" height="15" rx="1.5" stroke={color} strokeWidth="1.4" fill="rgba(0,0,0,0.5)" />
    {/* Text rows at varying widths to simulate code */}
    <line x1="6" y1="7.5" x2="14" y2="7.5" stroke={color} strokeWidth="1.1" strokeLinecap="round" />
    <line x1="6" y1="10.5" x2="17" y2="10.5" stroke={color} strokeWidth="1.1" strokeLinecap="round" strokeOpacity="0.7" />
    <line x1="6" y1="13.5" x2="11" y2="13.5" stroke={color} strokeWidth="1.1" strokeLinecap="round" strokeOpacity="0.5" />
    {/* Blinking cursor */}
    <rect x="12" y="12.5" width="3" height="2" rx="0.3" fill={color} />
    {/* Stand */}
    <path d="M9 18V20H15V18" stroke={color} strokeWidth="1.2" strokeLinejoin="round" />
    <line x1="7" y1="20" x2="17" y2="20" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
  </svg>
);

// 12. SEARCH — Target reticle with diamond crosshair and scan ring
export const SciFiSearchIcon = ({ size = 16, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    {/* Outer scan ring dashed */}
    <circle cx="10.5" cy="10.5" r="8" stroke={color} strokeWidth="1" strokeDasharray="5 2" />
    {/* Inner target ring */}
    <circle cx="10.5" cy="10.5" r="4.5" stroke={color} strokeWidth="1.2" />
    {/* Diamond center crosshair */}
    <path d="M10.5 7.5L13.5 10.5L10.5 13.5L7.5 10.5L10.5 7.5Z" stroke={color} strokeWidth="0.9" fill={color} fillOpacity="0.15" />
    {/* Tick marks at 90° */}
    <line x1="10.5" y1="2" x2="10.5" y2="4" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="19" y1="10.5" x2="17" y2="10.5" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    {/* Search handle */}
    <line x1="17" y1="17" x2="22" y2="22" stroke={color} strokeWidth="2" strokeLinecap="round" />
    <circle cx="10.5" cy="10.5" r="1.2" fill={color} />
  </svg>
);

// 13. KILL / DANGER — Hazard triangle with exclamation bolt
export const SciFiKillIcon = ({ size = 16, color = 'var(--accent-pink)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    {/* Biohazard-style warning triangle */}
    <path d="M12 2L2 21H22L12 2Z" stroke={color} strokeWidth="1.5" fill="rgba(255,0,85,0.08)" strokeLinejoin="round" />
    {/* Inner triangle detail */}
    <path d="M12 8L6.5 18.5H17.5L12 8Z" stroke={color} strokeWidth="0.7" strokeOpacity="0.4" strokeLinejoin="round" fill="none" />
    {/* Lightning bolt in center */}
    <path d="M13 10L10 14H12.5L11 18L14 13.5H11.5L13 10Z" fill={color} stroke={color} strokeWidth="0.5" />
  </svg>
);

// 14. REFRESH / SYNC — Orbital sync arrows with energy pulse
export const SciFiRefreshIcon = ({ size = 16, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    {/* Top arc arrow */}
    <path d="M20 8C18.5 5 15.5 3 12 3C8 3 5 5.5 3.5 9" stroke={color} strokeWidth="1.6" strokeLinecap="round" />
    <polygon points="21,4 20,9 16,8" fill={color} />
    {/* Bottom arc arrow */}
    <path d="M4 16C5.5 19 8.5 21 12 21C16 21 19 18.5 20.5 15" stroke={color} strokeWidth="1.6" strokeLinecap="round" />
    <polygon points="3,20 4,15 8,16" fill={color} />
    {/* Center pulse dot */}
    <circle cx="12" cy="12" r="2" stroke={color} strokeWidth="1" fill={color} fillOpacity="0.2" />
  </svg>
);

// 15. DOWNLOAD — Data stream downlink with beam effect
export const SciFiDownloadIcon = ({ size = 16, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    {/* Downlink beam */}
    <line x1="12" y1="2" x2="12" y2="14" stroke={color} strokeWidth="1.8" strokeLinecap="round" />
    {/* Arrow head */}
    <path d="M7 10L12 16L17 10" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    {/* Receiving tray with corner notches */}
    <path d="M3 19H21M3 19V21H21V19" stroke={color} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
    {/* Side beam decorations */}
    <line x1="7" y1="5" x2="7" y2="8" stroke={color} strokeWidth="0.8" strokeOpacity="0.4" strokeLinecap="round" />
    <line x1="17" y1="5" x2="17" y2="8" stroke={color} strokeWidth="0.8" strokeOpacity="0.4" strokeLinecap="round" />
  </svg>
);

// 16. STATUS BADGE — Pulsing quantum orb
export const SciFiPulseBadge = ({ size = 16, color = 'var(--accent-green)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    {/* Outer glow ring */}
    <circle cx="12" cy="12" r="9" stroke={color} strokeWidth="1" strokeDasharray="4 3" />
    {/* Mid ring */}
    <circle cx="12" cy="12" r="6" stroke={color} strokeWidth="1" strokeOpacity="0.5" />
    {/* Core orb */}
    <circle cx="12" cy="12" r="3.5" fill={color} fillOpacity="0.9" />
    {/* Specular highlight */}
    <circle cx="10.5" cy="10.5" r="1" fill="white" fillOpacity="0.5" />
  </svg>
);

// 17. FILE ICON — Crystal data fragment
export const SciFiFileIcon = ({ size = 20, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M6 2H15L20 7V22H6V2Z" stroke={color} strokeWidth="1.4" fill="rgba(0, 243, 255, 0.05)" strokeLinejoin="round" />
    <path d="M15 2V7H20" stroke={color} strokeWidth="1.4" strokeLinejoin="round" />
    {/* Dog-ear fold detail */}
    <path d="M15 2L13 4.5L15 7" stroke={color} strokeWidth="0.6" strokeOpacity="0.4" />
    <line x1="9" y1="12" x2="17" y2="12" stroke={color} strokeWidth="1.1" strokeLinecap="round" />
    <line x1="9" y1="15" x2="15" y2="15" stroke={color} strokeWidth="1.1" strokeLinecap="round" strokeOpacity="0.7" />
    <line x1="9" y1="18" x2="12" y2="18" stroke={color} strokeWidth="1.1" strokeLinecap="round" strokeOpacity="0.5" />
  </svg>
);

// 18. HOME — Futuristic habitat module with signal tower
export const SciFiHomeIcon = ({ size = 16, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    {/* Roof gable */}
    <path d="M3 10L12 3L21 10" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    {/* Wall body */}
    <rect x="4" y="10" width="16" height="11" rx="0.5" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.06" />
    {/* Door */}
    <rect x="9.5" y="15" width="5" height="6" rx="0.5" stroke={color} strokeWidth="1.1" fill={color} fillOpacity="0.1" />
    {/* Window */}
    <rect x="5" y="11.5" width="4" height="3.5" rx="0.3" stroke={color} strokeWidth="0.9" fill={color} fillOpacity="0.15" />
    <rect x="15" y="11.5" width="4" height="3.5" rx="0.3" stroke={color} strokeWidth="0.9" fill={color} fillOpacity="0.15" />
  </svg>
);

// 19. PLAY — Launch thrust nozzle
export const SciFiPlayIcon = ({ size = 14, color = 'var(--accent-green)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M6 3L20 12L6 21V3Z" fill={color} fillOpacity="0.85" stroke={color} strokeWidth="1.3" strokeLinejoin="round" />
    <line x1="6" y1="9" x2="14" y2="12" stroke="rgba(255,255,255,0.2)" strokeWidth="1" strokeLinecap="round" />
  </svg>
);

// 20. STOP — Emergency halt block with X glyph
export const SciFiStopIcon = ({ size = 14, color = 'var(--accent-pink)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <rect x="4" y="4" width="16" height="16" rx="2" fill={color} fillOpacity="0.15" stroke={color} strokeWidth="1.5" />
    <line x1="9" y1="9" x2="15" y2="15" stroke={color} strokeWidth="1.8" strokeLinecap="round" />
    <line x1="15" y1="9" x2="9" y2="15" stroke={color} strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);

// 21. SHIELD — Hexagonal sci-fi shield for Systemd services
export const SciFiShieldIcon = ({ size = 20, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M12 2L3 6V12C3 17.52 6.84 21.74 12 23C17.16 21.74 21 17.52 21 12V6L12 2Z"
      stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="rgba(0, 243, 255, 0.05)" />
    <path d="M12 6L6 9.5V13.5C6 16.5 8.5 19 12 20C15.5 19 18 16.5 18 13.5V9.5L12 6Z"
      stroke={color} strokeWidth="1" strokeDasharray="2 2" />
    <circle cx="12" cy="12" r="2.5" fill={color} />
    <path d="M12 8V9.5M12 14.5V16M8 12H9.5M14.5 12H16" stroke={color} strokeWidth="1" />
  </svg>
);

// 22. CHRONO TIMER — Sci-fi chrono target icon for Systemd Timers
export const SciFiChronoIcon = ({ size = 20, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <circle cx="12" cy="12" r="9" stroke={color} strokeWidth="1.5" strokeDasharray="6 2" fill="rgba(0, 243, 255, 0.05)" />
    <circle cx="12" cy="12" r="5" stroke={color} strokeWidth="1" />
    <path d="M12 7V12L15.5 14" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
    <path d="M12 1V3M12 21V23M1 12H3M21 12H23" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
    <circle cx="12" cy="12" r="1.5" fill={color} />
  </svg>
);

// 23. QUANTUM CORE — Quantum energy icon
export const SciFiQuantumIcon = ({ size = 20, color = 'var(--accent-magenta)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M13 2L3 14H12L11 22L21 10H12L13 2Z"
      fill="rgba(255, 0, 85, 0.15)" stroke={color} strokeWidth="1.5" strokeLinejoin="round" />
    <circle cx="12" cy="12" r="1.5" fill="#fff" />
    <path d="M7 6L5 4M17 18L19 20M4 17L2 19M20 7L22 5" stroke={color} strokeWidth="1" strokeLinecap="round" />
  </svg>
);

// 24. TELEGRAM — Supersonic Stealth Glider & Orbital Telemetry Drone
export const SciFiTelegramIcon = ({ size = 20, color = '#229ED9', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    {/* Orbital Telemetry Arc */}
    <path d="M4 6C2 8.5 2 13 4.5 17.5" stroke={color} strokeWidth="1" strokeDasharray="2 2" strokeOpacity="0.5" strokeLinecap="round" />
    {/* Hypersonic Stealth Wing Glider */}
    <polygon points="22,2 2,11.5 10.5,14 14,22 17,16 22,2" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.12" strokeLinejoin="round" />
    {/* Ion Laser Central Spline */}
    <line x1="22" y1="2" x2="10.5" y2="14" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
    {/* Ion Core Plasma Spark */}
    <circle cx="22" cy="2" r="1.5" fill={color} />
    <circle cx="10.5" cy="14" r="1" fill={color} />
  </svg>
);

// 25. INFO — Hexagonal info badge
export const SciFiInfoIcon = ({ size = 20, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <polygon points="12,2 21,7 21,17 12,22 3,17 3,7" stroke={color} strokeWidth="1.5" strokeLinejoin="round" fill="rgba(0, 243, 255, 0.06)" />
    <line x1="12" y1="11" x2="12" y2="17" stroke={color} strokeWidth="2" strokeLinecap="round" />
    <circle cx="12" cy="7.5" r="1.2" fill={color} />
  </svg>
);

// 26. TERMINAL PROMPT — CLI prompt chevron
export const SciFiTerminalPromptIcon = ({ size = 16, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M4 17L10 12L4 7" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    <line x1="12" y1="17" x2="20" y2="17" stroke={color} strokeWidth="2" strokeLinecap="round" />
  </svg>
);

// 27. LIGHTNING — Cyberpunk energy bolt
export const SciFiLightningIcon = ({ size = 18, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M13 2L3 14H12L10 22L21 9H12L13 2Z"
      fill="rgba(0, 243, 255, 0.18)" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M11 5L6 13H11.5L9.5 19L17 10.5H11.5L12.5 5Z"
      stroke={color} strokeWidth="0.8" strokeDasharray="2 1" strokeOpacity="0.7" />
    <circle cx="12" cy="11.5" r="1.5" fill="#fff" />
    <path d="M2 2L4 4M20 20L22 22M2 22L4 20M20 2L22 4" stroke={color} strokeWidth="1" strokeOpacity="0.4" />
  </svg>
);

// 28. LOGO ICON — Custom server rack hexagonal logo
export const SciFiLogoIcon = ({ size = 26, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
    {/* Outer hexagon */}
    <polygon points="32,3 58,18 58,46 32,61 6,46 6,18"
      fill="rgba(5,8,16,0.9)" stroke={color} strokeWidth="3.5" strokeLinejoin="round" />
    {/* Inner dashed hexagon */}
    <polygon points="32,10 52,21.5 52,42.5 32,54 12,42.5 12,21.5"
      fill="none" stroke={color} strokeWidth="1" strokeDasharray="4,2" opacity="0.5" />
    {/* Server rack rows */}
    <rect x="16" y="18" width="32" height="6" rx="1.5" fill="none" stroke={color} strokeWidth="2.5" />
    <rect x="16" y="28" width="32" height="6" rx="1.5" fill="none" stroke={color} strokeWidth="2.5" />
    <rect x="16" y="38" width="32" height="6" rx="1.5" fill="none" stroke={color} strokeWidth="2.5" />
    {/* LED indicators */}
    <circle cx="22" cy="21" r="2.5" fill="var(--accent-green)" />
    <circle cx="22" cy="31" r="2.5" fill={color} />
    <circle cx="22" cy="41" r="2.5" fill="var(--accent-green)" />
    {/* Horizontal bar details */}
    <line x1="28" y1="21" x2="40" y2="21" stroke={color} strokeWidth="2" strokeLinecap="round" />
    <line x1="28" y1="31" x2="36" y2="31" stroke={color} strokeWidth="2" strokeLinecap="round" strokeOpacity="0.6" />
    <line x1="28" y1="41" x2="40" y2="41" stroke={color} strokeWidth="2" strokeLinecap="round" />
  </svg>
);

// 29. SORT DESC — Newest first: stacked data bars shrinking downward + downlink arrow
// Represents "newest on top" — taller bar at top, shorter at bottom, arrow pointing down
export const SciFiSortDescIcon = ({ size = 14, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    {/* Stacked horizontal bars — descending width = newest data on top */}
    <line x1="3" y1="5" x2="16" y2="5" stroke={color} strokeWidth="2" strokeLinecap="round" />
    <line x1="3" y1="9" x2="13" y2="9" stroke={color} strokeWidth="2" strokeLinecap="round" strokeOpacity="0.75" />
    <line x1="3" y1="13" x2="10" y2="13" stroke={color} strokeWidth="2" strokeLinecap="round" strokeOpacity="0.5" />
    <line x1="3" y1="17" x2="7" y2="17" stroke={color} strokeWidth="2" strokeLinecap="round" strokeOpacity="0.3" />
    {/* Down arrow on right — data flows downward */}
    <line x1="20" y1="5" x2="20" y2="19" stroke={color} strokeWidth="1.6" strokeLinecap="round" />
    <polyline points="17,15 20,20 23,15" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
  </svg>
);

// 30. SORT ASC — Oldest first: stacked data bars growing upward + uplink arrow
// Represents "oldest on top" — shorter bar at top, taller at bottom, arrow pointing up
export const SciFiSortAscIcon = ({ size = 14, color = 'currentColor' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    {/* Stacked horizontal bars — ascending width = older data on top */}
    <line x1="3" y1="5" x2="7" y2="5" stroke={color} strokeWidth="2" strokeLinecap="round" strokeOpacity="0.3" />
    <line x1="3" y1="9" x2="10" y2="9" stroke={color} strokeWidth="2" strokeLinecap="round" strokeOpacity="0.5" />
    <line x1="3" y1="13" x2="13" y2="13" stroke={color} strokeWidth="2" strokeLinecap="round" strokeOpacity="0.75" />
    <line x1="3" y1="17" x2="16" y2="17" stroke={color} strokeWidth="2" strokeLinecap="round" />
    {/* Up arrow on right — data flows upward */}
    <line x1="20" y1="19" x2="20" y2="5" stroke={color} strokeWidth="1.6" strokeLinecap="round" />
    <polyline points="17,9 20,4 23,9" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
  </svg>
);

// 31. BROWSER LAUNCH — Cyberpunk Holographic Web Portal
export const SciFiBrowserLaunchIcon = ({ size = 18, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    {/* Outer Browser Window Frame */}
    <rect x="2" y="3" width="20" height="18" rx="2" stroke={color} strokeWidth="1.4" fill="rgba(0, 243, 255, 0.08)" />
    <line x1="2" y1="7" x2="22" y2="7" stroke={color} strokeWidth="1.2" />
    {/* Window dots */}
    <circle cx="5" cy="5" r="0.9" fill={color} />
    <circle cx="8" cy="5" r="0.9" fill={color} fillOpacity="0.6" />
    <circle cx="11" cy="5" r="0.9" fill={color} fillOpacity="0.4" />
    {/* Globe Grid Grid Inside Browser */}
    <circle cx="12" cy="14" r="5" stroke={color} strokeWidth="1.2" strokeDasharray="3 1" />
    <ellipse cx="12" cy="14" rx="5" ry="2" stroke={color} strokeWidth="0.9" strokeOpacity="0.6" />
    <line x1="12" y1="9" x2="12" y2="19" stroke={color} strokeWidth="0.9" strokeOpacity="0.6" />
    {/* Corner Quantum Spark */}
    <polygon points="17,10 19,12 17,14 15,12" fill={color} />
  </svg>
);

// 32. CHRONO SPINNER — Quantum Hourglass Reactor
export const SciFiChronoSpinnerIcon = ({ size = 18, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"
    style={{ display: 'inline-block', verticalAlign: 'middle', animation: 'spin 2s linear infinite' }}>
    <style>{`@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }`}</style>
    {/* Rotating Outer Hex Ring */}
    <polygon points="12,2 19,6 19,14 12,18 5,14 5,6" stroke={color} strokeWidth="1.2" strokeDasharray="4 2" fill="none" />
    {/* Hourglass Diamond Core */}
    <polygon points="8,7 16,7 12,12 16,17 8,17 12,12" stroke={color} strokeWidth="1.4" fill="rgba(0, 243, 255, 0.2)" />
    <circle cx="12" cy="12" r="1.5" fill={color} />
  </svg>
);

// 33. CHECK CIRCLE — Cyber Shield Verification Checkmark
export const SciFiCheckCircleIcon = ({ size = 18, color = 'var(--accent-green)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    {/* Shield Octagon */}
    <polygon points="12,2 18,4 21,10 19,17 12,22 5,17 3,10 6,4"
      stroke={color} strokeWidth="1.5" fill="rgba(0, 255, 102, 0.12)" />
    {/* Checkmark */}
    <polyline points="7,12 10.5,15.5 17,8.5" stroke={color} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

// 34. CLOSE ICON — Cyber Bracket Reticle Cancel Cross
export const SciFiCloseIcon = ({ size = 16, color = 'var(--accent-pink)', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    <path d="M3 7V4H7" stroke={color} strokeWidth="1.1" strokeOpacity="0.6" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M17 4H21V7" stroke={color} strokeWidth="1.1" strokeOpacity="0.6" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M21 17V21H17" stroke={color} strokeWidth="1.1" strokeOpacity="0.6" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M7 21H3V17" stroke={color} strokeWidth="1.1" strokeOpacity="0.6" strokeLinecap="round" strokeLinejoin="round" />
    <line x1="7.5" y1="7.5" x2="16.5" y2="16.5" stroke={color} strokeWidth="1.8" strokeLinecap="round" />
    <line x1="16.5" y1="7.5" x2="7.5" y2="16.5" stroke={color} strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);


// 35. FACEBOOK — Cybernetic Shield Node with Laser Data Monogram
export const SciFiFacebookIcon = ({ size = 18, color = 'var(--accent-purple)', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    {/* Chamfered Hex Shield Frame */}
    <polygon points="6,2 18,2 22,6 22,18 18,22 6,22 2,18 2,6" stroke={color} strokeWidth="1.3" fill={color} fillOpacity="0.08" strokeLinejoin="round" />
    {/* Cyber 'f' Monogram with Integrated Data Rails */}
    <path
      d="M16 7.5H13.8C12.8 7.5 12 8.3 12 9.3V11H15.5L15 14H12V21H8.5V14H6.5V11H8.5V9.3C8.5 6.4 10.4 4.5 13.3 4.5H16V7.5Z"
      fill={color}
      fillOpacity="0.9"
    />
    {/* Lateral Data Bus Traces */}
    <line x1="3.5" y1="11" x2="6.5" y2="11" stroke={color} strokeWidth="1" strokeLinecap="round" />
    <line x1="15.5" y1="11" x2="20.5" y2="11" stroke={color} strokeWidth="1" strokeLinecap="round" />
    {/* Optical Sensor Nodes */}
    <circle cx="12" cy="3" r="0.8" fill={color} />
    <circle cx="12" cy="21" r="0.8" fill={color} />
  </svg>
);

// 36. AI BOT / AGENT — Futuristic Cyber AI Core & Visor
export const SciFiBotIcon = ({ size = 20, color = 'var(--accent-cyan)', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    {/* Head chassis */}
    <polygon points="5,6 19,6 21,9 21,19 19,21 5,21 3,19 3,9" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.08" strokeLinejoin="round" />
    {/* Antenna Array */}
    <line x1="12" y1="1.5" x2="12" y2="6" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
    <circle cx="12" cy="1.5" r="1.2" fill={color} />
    {/* Neural Visor Sensor */}
    <polygon points="6,10 18,10 17,14 7,14" stroke={color} strokeWidth="1.2" fill={color} fillOpacity="0.25" strokeLinejoin="round" />
    <circle cx="9" cy="12" r="1" fill={color} />
    <circle cx="15" cy="12" r="1" fill={color} />
    {/* Side Nodes */}
    <line x1="1.5" y1="11" x2="1.5" y2="17" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
    <line x1="22.5" y1="11" x2="22.5" y2="17" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
    {/* Data Bus Mouth */}
    <line x1="8" y1="18" x2="16" y2="18" stroke={color} strokeWidth="1.2" strokeLinecap="round" strokeDasharray="1.5 1.5" />
  </svg>
);

// 37. ZALO — Quantum Communication Node & Z-Matrix Laser Link
export const SciFiZaloIcon = ({ size = 18, color = '#0068FF', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    {/* Octagonal Frame */}
    <polygon points="6,2 18,2 22,6 22,18 18,22 6,22 2,18 2,6" stroke={color} strokeWidth="1.3" fill={color} fillOpacity="0.08" strokeLinejoin="round" />
    {/* Laser Z-Matrix Path */}
    <path d="M7 8H17L8 16H18" stroke={color} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    {/* Synchronization Nodes */}
    <circle cx="7" cy="8" r="1" fill={color} />
    <circle cx="18" cy="16" r="1" fill={color} />
    {/* Telemetry Bracket Ticks */}
    <line x1="12" y1="3" x2="12" y2="4.5" stroke={color} strokeWidth="1" strokeLinecap="round" />
    <line x1="12" y1="19.5" x2="12" y2="21" stroke={color} strokeWidth="1" strokeLinecap="round" />
  </svg>
);

// 38. GMAIL — Quantum Encrypted Data Capsule & Laser Facet Envelope
export const SciFiGmailIcon = ({ size = 18, color = '#EA4335', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    {/* Chamfered Hex Box */}
    <polygon points="5,4 19,4 22,7 22,17 19,20 5,20 2,17 2,7" stroke={color} strokeWidth="1.3" fill={color} fillOpacity="0.08" strokeLinejoin="round" />
    {/* Geometric Laser Folds */}
    <polyline points="2,7 12,14 22,7" stroke={color} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    <line x1="2" y1="17" x2="9.5" y2="12" stroke={color} strokeWidth="1" strokeLinecap="round" strokeOpacity="0.6" />
    <line x1="22" y1="17" x2="14.5" y2="12" stroke={color} strokeWidth="1" strokeLinecap="round" strokeOpacity="0.6" />
    {/* Quantum Key Lock Node */}
    <circle cx="12" cy="14" r="1.2" fill={color} />
  </svg>
);

// 39. TIKTOK — Cyberpunk Quantum Rhythm Emblem
export const SciFiTikTokIcon = ({ size = 18, color = '#00F2FE', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    {/* Octagonal Cyberpunk Frame with Chamfered Corners */}
    <polygon points="6,2 18,2 22,6 22,18 18,22 6,22 2,18 2,6" stroke={color} strokeWidth="1.3" fill={color} fillOpacity="0.08" strokeLinejoin="round" />
    {/* Dual Laser Frequency Stem & Note Head */}
    <path
      d="M14.5 4.5V14C14.5 15.93 12.93 17.5 11 17.5C9.07 17.5 7.5 15.93 7.5 14C7.5 12.07 9.07 10.5 11 10.5C11.6 10.5 12.15 10.65 12.65 10.9V7.5C13.85 8.7 15.4 9.4 17 9.4V6.5C15.6 6.5 14.5 5.4 14.5 4.5Z"
      fill={color}
      fillOpacity="0.9"
    />
    {/* Cyber Equalizer Quantum Waves */}
    <line x1="4.5" y1="12" x2="6" y2="12" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="18" y1="12" x2="19.5" y2="12" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    {/* Corner Precision Ticks */}
    <circle cx="5" cy="5" r="0.8" fill={color} />
    <circle cx="19" cy="5" r="0.8" fill={color} />
    <circle cx="5" cy="19" r="0.8" fill={color} />
    <circle cx="19" cy="19" r="0.8" fill={color} />
  </svg>
);

// 40. YOUTUBE — Holographic Video Matrix Display with Laser Prism Core
export const SciFiYouTubeIcon = ({ size = 18, color = '#FF0033', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    {/* 16:9 Chamfered HUD Display Frame */}
    <polygon points="5,4 19,4 22,7 22,17 19,20 5,20 2,17 2,7" stroke={color} strokeWidth="1.3" fill={color} fillOpacity="0.08" strokeLinejoin="round" />
    {/* Radiant Central Laser Prism */}
    <polygon points="10,8.5 16.5,12 10,15.5" fill={color} fillOpacity="0.95" strokeLinejoin="round" />
    {/* Top / Bottom Sub-pixel Grid Calibration Lines */}
    <line x1="8" y1="2" x2="16" y2="2" stroke={color} strokeWidth="1" strokeLinecap="round" />
    <line x1="8" y1="22" x2="16" y2="22" stroke={color} strokeWidth="1" strokeLinecap="round" />
    {/* Corner Telemetry Points */}
    <circle cx="4" cy="7" r="0.7" fill={color} />
    <circle cx="20" cy="7" r="0.7" fill={color} />
    <circle cx="4" cy="17" r="0.7" fill={color} />
    <circle cx="20" cy="17" r="0.7" fill={color} />
  </svg>
);

// 41. INSTAGRAM — Quantum Optical Sensor & Biometric Iris
export const SciFiInstagramIcon = ({ size = 18, color = '#E1306C', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    {/* Chamfered Octagonal Chassis */}
    <polygon points="6,2 18,2 22,6 22,18 18,22 6,22 2,18 2,6" stroke={color} strokeWidth="1.3" fill={color} fillOpacity="0.08" strokeLinejoin="round" />
    {/* Outer Sensor Reticle */}
    <circle cx="12" cy="12" r="4.5" stroke={color} strokeWidth="1.3" fill={color} fillOpacity="0.15" />
    {/* Core Optical Lens */}
    <circle cx="12" cy="12" r="1.8" fill={color} />
    {/* Laser Flash / Sensor Emitter */}
    <circle cx="17.5" cy="6.5" r="1.2" fill={color} />
    {/* Targeting Crosshair Ticks */}
    <line x1="12" y1="4" x2="12" y2="5.5" stroke={color} strokeWidth="1" strokeLinecap="round" />
    <line x1="12" y1="18.5" x2="12" y2="20" stroke={color} strokeWidth="1" strokeLinecap="round" />
    <line x1="4" y1="12" x2="5.5" y2="12" stroke={color} strokeWidth="1" strokeLinecap="round" />
    <line x1="18.5" y1="12" x2="20" y2="12" stroke={color} strokeWidth="1" strokeLinecap="round" />
  </svg>
);

// 42. WHATSAPP — Tactical Frequency Comms Node & Neural Wave Array
export const SciFiWhatsAppIcon = ({ size = 18, color = '#25D366', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    {/* Cyber Comms Capsule Bubble with Pointer */}
    <path
      d="M12 2C6.5 2 2 6.5 2 12C2 14 2.6 15.9 3.6 17.5L2 22L6.7 20.5C8.3 21.4 10.1 22 12 22C17.5 22 22 17.5 22 12C22 6.5 17.5 2 12 2Z"
      stroke={color}
      strokeWidth="1.3"
      fill={color}
      fillOpacity="0.08"
      strokeLinejoin="round"
    />
    {/* Tactical Handset Receiver Vector */}
    <path
      d="M15.5 14C15 14.8 13.8 15 12.8 14.5C10.8 13.5 9 11.7 8 9.7C7.5 8.7 7.7 7.5 8.5 7L9.8 8.3C10.2 8.7 10.2 9.3 9.8 9.7L9.3 10.2C9.8 11.2 10.8 12.2 11.8 12.7L12.3 12.2C12.7 11.8 13.3 11.8 13.7 12.2L15.5 14Z"
      fill={color}
      fillOpacity="0.9"
    />
    {/* Radio Frequency Arcs */}
    <path d="M14 6C16 7 17 9 17 11" stroke={color} strokeWidth="1" strokeLinecap="round" strokeOpacity="0.7" />
    <path d="M16 4C19 5.5 20.5 8.5 20.5 11.5" stroke={color} strokeWidth="0.8" strokeLinecap="round" strokeOpacity="0.4" />
  </svg>
);

// 43. ENERGY BOLT — Ultra-sleek cyberpunk lightning bolt with neon pulse
export const SciFiEnergyBoltIcon = ({ size = 14, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    {/* Outer Energy Shell */}
    <path
      d="M13.5 1.5L4 12.5H11.5L9.5 22.5L20 10.5H12.5L14 1.5Z"
      fill={color}
      fillOpacity="0.25"
      stroke={color}
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    {/* Core Plasma Segment */}
    <polygon
      points="12.8,4.5 6.8,11.5 11.5,11.5 10.5,18.5 16.8,10.5 12.2,10.5"
      fill={color}
      fillOpacity="0.9"
    />
    {/* Spark Core */}
    <circle cx="11.8" cy="11" r="1.3" fill="#ffffff" />
    {/* Lateral Discharge Particles */}
    <circle cx="3" cy="11" r="0.7" fill={color} fillOpacity="0.6" />
    <circle cx="21" cy="12" r="0.7" fill={color} fillOpacity="0.6" />
  </svg>
);

// 44. CHEVRON LEFT — Cyber HUD Left Navigation Chevron
export const SciFiChevronLeftIcon = ({ size = 14, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M15 18L9 12L15 6" stroke={color} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    <line x1="5" y1="7" x2="5" y2="17" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeOpacity="0.5" />
  </svg>
);

// 45. CHEVRON RIGHT — Cyber HUD Right Navigation Chevron
export const SciFiChevronRightIcon = ({ size = 14, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M9 6L15 12L9 18" stroke={color} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    <line x1="19" y1="7" x2="19" y2="17" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeOpacity="0.5" />
  </svg>
);

// 46. STREAK FLAME — Cyberpunk Plasma Flame with Tri-Core Energy Layers
export const SciFiFlameStreakIcon = ({ size = 18, color = '#FE2C55', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    {/* Outer Plasma Arc Silhouette */}
    <path
      d="M12 2C12 2 7.5 6.5 7.5 11C7.5 13.5 8.8 15 10 16C9.5 14.5 10 13 11 12C11 12 11 14 12.5 15.5C13.5 14.5 14 13.5 14 12C15.5 13.5 16.5 15.2 16.5 11C16.5 6.5 12 2 12 2Z"
      fill={color}
      fillOpacity="0.85"
    />
    {/* Inner White-Hot Plasma Heart */}
    <path
      d="M12 7.5C12 7.5 9.8 10.5 9.8 13C9.8 15 10.8 16.5 12 17C13.2 16.5 14.2 15 14.2 13C14.2 10.5 12 7.5 12 7.5Z"
      fill="#FFF"
      fillOpacity="0.85"
    />
    {/* Sharp Needle Tip Emitter */}
    <polygon points="12,1 11,4 13,4" fill="#FFF" />
    {/* Magnetic Plasma Confinement Base Rails */}
    <line x1="8" y1="19.5" x2="16" y2="19.5" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
    <line x1="10" y1="21.5" x2="14" y2="21.5" stroke={color} strokeWidth="1" strokeLinecap="round" strokeOpacity="0.6" />
    {/* Laser Ion Embers */}
    <circle cx="6.5" cy="14" r="0.8" fill={color} />
    <circle cx="17.5" cy="13" r="0.8" fill={color} />
  </svg>
);

// 47. VIDEO CLIP — Cyberpunk film strip with scan lines and a neon play triangle
// Used for "Video Xu Hướng / Clip Ngắn" button in Streak Dispatch Content selector
export const SciFiVideoClipIcon = ({ size = 14, color = '#FE2C55' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    {/* Main film frame body */}
    <rect x="2" y="4" width="20" height="16" rx="1.5" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.07" />
    {/* Film sprocket holes — left strip */}
    <rect x="3" y="6" width="2.5" height="2.5" rx="0.4" fill={color} fillOpacity="0.6" />
    <rect x="3" y="10.75" width="2.5" height="2.5" rx="0.4" fill={color} fillOpacity="0.6" />
    <rect x="3" y="15.5" width="2.5" height="2.5" rx="0.4" fill={color} fillOpacity="0.6" />
    {/* Film sprocket holes — right strip */}
    <rect x="18.5" y="6" width="2.5" height="2.5" rx="0.4" fill={color} fillOpacity="0.6" />
    <rect x="18.5" y="10.75" width="2.5" height="2.5" rx="0.4" fill={color} fillOpacity="0.6" />
    <rect x="18.5" y="15.5" width="2.5" height="2.5" rx="0.4" fill={color} fillOpacity="0.6" />
    {/* Center divider lines creating frame sections */}
    <line x1="7" y1="4" x2="7" y2="20" stroke={color} strokeWidth="0.8" strokeOpacity="0.35" />
    <line x1="17" y1="4" x2="17" y2="20" stroke={color} strokeWidth="0.8" strokeOpacity="0.35" />
    {/* Play triangle — neon filled, centered in the frame area */}
    <path d="M10 9.5L10 14.5L15 12L10 9.5Z" fill={color} fillOpacity="0.9" />
    {/* Scan line overlay — gives holographic/cyber feel */}
    <line x1="7" y1="12" x2="17" y2="12" stroke={color} strokeWidth="0.5" strokeOpacity="0.25" />
  </svg>
);

// 48. MESSAGE STREAK — Cyber speech bubble with a chain-link connector and pulse dot
// Used for "Tin Nhắn Giữ Chuỗi" button — communicates both messaging and chain/streak concept
export const SciFiMessageStreakIcon = ({ size = 14, color = '#00F2FE' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    {/* Main bubble body with flat bottom-left corner (cyberpunk style) */}
    <path
      d="M3 5C3 3.9 3.9 3 5 3H19C20.1 3 21 3.9 21 5V14C21 15.1 20.1 16 19 16H8L3 20V5Z"
      stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.07" strokeLinejoin="round"
    />
    {/* Message content lines inside bubble */}
    <line x1="6" y1="7.5" x2="18" y2="7.5" stroke={color} strokeWidth="1" strokeOpacity="0.5" strokeLinecap="round" />
    <line x1="6" y1="11" x2="14" y2="11" stroke={color} strokeWidth="1" strokeOpacity="0.5" strokeLinecap="round" />
    {/* Chain link symbol — right side, indicates streak/chain concept */}
    <circle cx="20" cy="19" r="1.5" stroke={color} strokeWidth="1.2" fill="none" strokeOpacity="0.7" />
    <circle cx="17" cy="22" r="1.5" stroke={color} strokeWidth="1.2" fill="none" strokeOpacity="0.5" />
    <line x1="19" y1="20" x2="18" y2="21" stroke={color} strokeWidth="1" strokeOpacity="0.6" />
    {/* Active pulse dot — top-right corner of bubble */}
    <circle cx="18.5" cy="4.5" r="1.5" fill={color} fillOpacity="0.9" />
    <circle cx="18.5" cy="4.5" r="2.8" stroke={color} strokeWidth="0.6" strokeOpacity="0.35" />
  </svg>
);

// 49. ADD FRIEND — Cyberpunk user silhouette with a quantum "+" node extending outward
// Used for "THÊM BẠN BÈ" button in the Streak Friends list manager
export const SciFiAddFriendIcon = ({ size = 13, color = '#FE2C55' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    {/* User head circle */}
    <circle cx="9" cy="7" r="4" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.1" />
    {/* User body / shoulder arc */}
    <path d="M2 21C2 17.1 5.1 14 9 14C11 14 12.8 14.8 14.1 16.1" stroke={color} strokeWidth="1.4" strokeLinecap="round" fill="none" />
    {/* HUD bracket around head — cyber targeting effect */}
    <path d="M6 3.5L5 3L4 3.5" stroke={color} strokeWidth="0.8" strokeOpacity="0.5" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M12 3.5L13 3L14 3.5" stroke={color} strokeWidth="0.8" strokeOpacity="0.5" strokeLinecap="round" strokeLinejoin="round" />
    {/* Plus node — quantum add symbol, positioned top-right */}
    <circle cx="19" cy="17" r="4" stroke={color} strokeWidth="1.2" fill={color} fillOpacity="0.08" />
    <line x1="19" y1="14.5" x2="19" y2="19.5" stroke={color} strokeWidth="1.6" strokeLinecap="round" />
    <line x1="16.5" y1="17" x2="21.5" y2="17" stroke={color} strokeWidth="1.6" strokeLinecap="round" />
    {/* Corner tick marks on the + node circle */}
    <line x1="15.8" y1="14.5" x2="16.5" y2="14.5" stroke={color} strokeWidth="0.8" strokeOpacity="0.5" />
    <line x1="15.8" y1="14.5" x2="15.8" y2="15.2" stroke={color} strokeWidth="0.8" strokeOpacity="0.5" />
  </svg>
);

// 50. SATELLITE SPACECRAFT — Hexagonal bus core, dual solar wings with cell grids, parabolic downlink dish & microwave signal waves
export const SciFiSatelliteIcon = ({ size = 20, color = 'currentColor', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    {/* Left Solar Wing */}
    <rect x="2" y="7.5" width="6" height="5" rx="0.5" stroke={color} strokeWidth="1.2" fill={color} fillOpacity="0.12" />
    <line x1="5" y1="7.5" x2="5" y2="12.5" stroke={color} strokeWidth="0.8" strokeOpacity="0.45" />
    <line x1="2" y1="10" x2="8" y2="10" stroke={color} strokeWidth="0.8" strokeOpacity="0.45" />

    {/* Right Solar Wing */}
    <rect x="16" y="7.5" width="6" height="5" rx="0.5" stroke={color} strokeWidth="1.2" fill={color} fillOpacity="0.12" />
    <line x1="19" y1="7.5" x2="19" y2="12.5" stroke={color} strokeWidth="0.8" strokeOpacity="0.45" />
    <line x1="16" y1="10" x2="22" y2="10" stroke={color} strokeWidth="0.8" strokeOpacity="0.45" />

    {/* Boom Struts connecting wings */}
    <line x1="8" y1="10" x2="9.5" y2="10" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
    <line x1="14.5" y1="10" x2="16" y2="10" stroke={color} strokeWidth="1.4" strokeLinecap="round" />

    {/* Hexagonal Bus Core */}
    <polygon
      points="12,6 14.5,8 14.5,12 12,14 9.5,12 9.5,8"
      stroke={color}
      strokeWidth="1.3"
      fill={color}
      fillOpacity="0.22"
      strokeLinejoin="round"
    />
    <circle cx="12" cy="10" r="1.2" fill={color} />

    {/* Zenith Mast & Beacon */}
    <line x1="12" y1="6" x2="12" y2="2.5" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <circle cx="12" cy="2.5" r="0.9" fill={color} />

    {/* Nadir Parabolic Dish */}
    <path d="M8.5 15.5 C9.5 18 14.5 18 15.5 15.5" stroke={color} strokeWidth="1.4" strokeLinecap="round" fill="none" />
    <line x1="12" y1="14" x2="12" y2="17.2" stroke={color} strokeWidth="1.1" strokeLinecap="round" />
    <circle cx="12" cy="17.2" r="0.6" fill={color} />

    {/* Signal Microwave Waves */}
    <path d="M9.5 19.8 C10.5 21.2 13.5 21.2 14.5 19.8" stroke={color} strokeWidth="1" strokeLinecap="round" strokeOpacity="0.75" />
    <path d="M7.8 22.2 C9.8 24.2 14.2 24.2 16.2 22.2" stroke={color} strokeWidth="0.8" strokeDasharray="1.5 1" strokeLinecap="round" strokeOpacity="0.45" />
  </svg>
);

// 51. 3D ORBIT RINGS — Central Earth globe with dual intersecting elliptical orbital planes & active satellite beacons
export const SciFiOrbitRingIcon = ({ size = 20, color = 'currentColor', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    {/* Inclined Orbit Ellipse 1 (-35deg) */}
    <g transform="rotate(-35 12 12)">
      <ellipse cx="12" cy="12" rx="9.8" ry="3.8" stroke={color} strokeWidth="1.2" strokeDasharray="4 2" fill="none" />
      <circle cx="21.5" cy="12" r="1.5" fill={color} />
      <polygon points="21.5,9.5 22.8,12 21.5,14.5 20.2,12" fill={color} fillOpacity="0.5" />
    </g>

    {/* Inclined Orbit Ellipse 2 (+45deg) */}
    <g transform="rotate(45 12 12)">
      <ellipse cx="12" cy="12" rx="9.5" ry="3.4" stroke={color} strokeWidth="1" strokeOpacity="0.8" fill="none" />
      <circle cx="2.8" cy="12" r="1.4" fill={color} />
      <polygon points="2.8,10 4,12 2.8,14 1.6,12" fill={color} fillOpacity="0.5" />
    </g>

    {/* Central Earth Globe */}
    <circle cx="12" cy="12" r="4.8" stroke={color} strokeWidth="1.3" fill={color} fillOpacity="0.15" />
    <ellipse cx="12" cy="12" rx="4.8" ry="1.8" stroke={color} strokeWidth="0.7" strokeDasharray="1.8 1.2" strokeOpacity="0.6" />
    <ellipse cx="12" cy="12" rx="1.8" ry="4.8" stroke={color} strokeWidth="0.7" strokeDasharray="1.8 1.2" strokeOpacity="0.6" />
    <circle cx="12" cy="12" r="1" fill={color} />
  </svg>
);

// 52. TACTICAL TARGET LOCK / CROSSHAIR — Corner brackets, segmented radar reticle, diamond lock core
export const SciFiTargetLockIcon = ({ size = 20, color = 'currentColor', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    {/* 4 Tactical Corner Brackets */}
    <path d="M3 8V5L5 3H8" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M16 3H19L21 5V8" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M21 16V19L19 21H16" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M8 21H5L3 19V16" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />

    {/* Segmented Radar Reticle */}
    <circle cx="12" cy="12" r="6.2" stroke={color} strokeWidth="1.1" strokeDasharray="3.2 2" fill="none" />

    {/* Diamond Reticle Core */}
    <polygon points="12,9.2 14.8,12 12,14.8 9.2,12" stroke={color} strokeWidth="1.2" fill={color} fillOpacity="0.2" strokeLinejoin="round" />
    <circle cx="12" cy="12" r="1" fill={color} />

    {/* Crosshair Ticks */}
    <line x1="12" y1="2" x2="12" y2="5.2" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
    <line x1="12" y1="18.8" x2="12" y2="22" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
    <line x1="2" y1="12" x2="5.2" y2="12" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
    <line x1="18.8" y1="12" x2="22" y2="12" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
  </svg>
);

// 53. SERVER HQ NODE — Command C2 tower with server chassis, dome sensor and microwave mast
export const SciFiServerNodeIcon = ({ size = 20, color = 'currentColor', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    {/* Base Server Rack Chassis */}
    <rect x="5" y="14" width="14" height="6.5" rx="1" stroke={color} strokeWidth="1.3" fill={color} fillOpacity="0.1" />
    <line x1="8" y1="17.2" x2="16" y2="17.2" stroke={color} strokeWidth="1" strokeLinecap="round" strokeOpacity="0.6" />
    <circle cx="7" cy="17.2" r="0.9" fill={color} />
    <circle cx="17" cy="17.2" r="0.9" fill={color} fillOpacity="0.5" />

    {/* Mid C2 Processing Unit */}
    <rect x="7" y="8" width="10" height="5" rx="0.8" stroke={color} strokeWidth="1.2" fill={color} fillOpacity="0.18" />
    <line x1="9.5" y1="10.5" x2="14.5" y2="10.5" stroke={color} strokeWidth="1" strokeLinecap="round" />

    {/* Command Sensor Dome */}
    <polygon points="12,3.5 15.5,7.5 8.5,7.5" stroke={color} strokeWidth="1.2" fill={color} fillOpacity="0.25" strokeLinejoin="round" />

    {/* Microwave Mast & Waves */}
    <line x1="12" y1="1.5" x2="12" y2="3.5" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
    <circle cx="12" cy="1.5" r="1" fill={color} />
    <path d="M8.5 3 C9.6 1.6 14.4 1.6 15.5 3" stroke={color} strokeWidth="0.9" strokeLinecap="round" strokeOpacity="0.75" />
    <path d="M6.5 1 C8.5 -0.6 15.5 -0.6 17.5 1" stroke={color} strokeWidth="0.7" strokeDasharray="1.5 1" strokeOpacity="0.4" />

    {/* Ground Foundation */}
    <line x1="3" y1="21.5" x2="21" y2="21.5" stroke={color} strokeWidth="1.3" strokeLinecap="round" />
  </svg>
);

// 54. CONNECTED USER NODES — Mesh network topology with central hub and telemetry client endpoints
export const SciFiUserNodesIcon = ({ size = 20, color = 'currentColor', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    {/* Master Hub Node */}
    <polygon
      points="12,8.5 15,10.2 15,13.8 12,15.5 9,13.8 9,10.2"
      stroke={color}
      strokeWidth="1.3"
      fill={color}
      fillOpacity="0.25"
      strokeLinejoin="round"
    />
    <circle cx="12" cy="12" r="1.3" fill={color} />

    {/* 4 Client Nodes */}
    <circle cx="5" cy="6" r="2.2" stroke={color} strokeWidth="1.2" fill={color} fillOpacity="0.12" />
    <circle cx="5" cy="6" r="0.9" fill={color} />

    <circle cx="19" cy="6" r="2.2" stroke={color} strokeWidth="1.2" fill={color} fillOpacity="0.12" />
    <circle cx="19" cy="6" r="0.9" fill={color} />

    <circle cx="4.5" cy="18" r="2.2" stroke={color} strokeWidth="1.2" fill={color} fillOpacity="0.12" />
    <circle cx="4.5" cy="18" r="0.9" fill={color} />

    <circle cx="19.5" cy="18" r="2.2" stroke={color} strokeWidth="1.2" fill={color} fillOpacity="0.12" />
    <circle cx="19.5" cy="18" r="0.9" fill={color} />

    {/* Data Transmission Links */}
    <line x1="9.5" y1="10.5" x2="6.8" y2="7.5" stroke={color} strokeWidth="1.1" strokeDasharray="1.8 1.2" strokeLinecap="round" />
    <line x1="14.5" y1="10.5" x2="17.2" y2="7.5" stroke={color} strokeWidth="1.1" strokeDasharray="1.8 1.2" strokeLinecap="round" />
    <line x1="9.5" y1="13.5" x2="6.3" y2="16.5" stroke={color} strokeWidth="1.1" strokeDasharray="1.8 1.2" strokeLinecap="round" />
    <line x1="14.5" y1="13.5" x2="17.7" y2="16.5" stroke={color} strokeWidth="1.1" strokeDasharray="1.8 1.2" strokeLinecap="round" />
  </svg>
);

// 55. SPEED GAUGE TACHOMETER — HUD 220° arc with needle pointer and multiplier bars
export const SciFiSpeedGaugeIcon = ({ size = 20, color = 'currentColor', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    <path
      d="M4.5 17.5 A 8.5 8.5 0 1 1 19.5 17.5"
      stroke={color}
      strokeWidth="1.5"
      strokeLinecap="round"
      fill="none"
    />
    <path
      d="M6.2 15.8 A 6.5 6.5 0 1 1 17.8 15.8"
      stroke={color}
      strokeWidth="0.9"
      strokeDasharray="2 3"
      strokeOpacity="0.5"
      fill="none"
    />
    <line x1="12" y1="13" x2="17" y2="7.5" stroke={color} strokeWidth="1.8" strokeLinecap="round" />
    <circle cx="12" cy="13" r="2.2" stroke={color} strokeWidth="1.2" fill={color} fillOpacity="0.3" />
    <circle cx="12" cy="13" r="0.9" fill="#ffffff" />
    <rect x="5.5" y="19" width="3.2" height="2" rx="0.5" fill={color} fillOpacity="0.9" />
    <rect x="10.4" y="19" width="3.2" height="2" rx="0.5" fill={color} fillOpacity="0.6" />
    <rect x="15.3" y="19" width="3.2" height="2" rx="0.5" fill={color} fillOpacity="0.3" />
  </svg>
);

// 56. CAMERA RECALIBRATE / RESET — 3D Viewport brackets with 360-degree recalibration loop arrow & coordinate trihedron
export const SciFiCameraResetIcon = ({ size = 20, color = 'currentColor', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    <path d="M4 7V4H7" stroke={color} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" strokeOpacity="0.65" />
    <path d="M17 4H20V7" stroke={color} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" strokeOpacity="0.65" />
    <path d="M20 17V20H17" stroke={color} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" strokeOpacity="0.65" />
    <path d="M7 20H4V17" stroke={color} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" strokeOpacity="0.65" />
    <path
      d="M12 6.5 A 5.5 5.5 0 1 1 6.5 12"
      stroke={color}
      strokeWidth="1.6"
      strokeLinecap="round"
      fill="none"
    />
    <polygon points="12,3.5 12,9.5 7.8,6.5" fill={color} />
    <circle cx="12" cy="12" r="1.3" fill={color} />
  </svg>
);

// 57. CPU MICROPROCESSOR CHIP — Quad-flange silicon die with circuit trace buses & pin 1 indicator
export const SciFiCpuChipIcon = ({ size = 12, color = 'currentColor', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    <rect x="5" y="5" width="14" height="14" rx="2" stroke={color} strokeWidth="1.3" fill={color} fillOpacity="0.1" />
    <rect x="8.5" y="8.5" width="7" height="7" rx="1" stroke={color} strokeWidth="1" fill={color} fillOpacity="0.25" />
    <circle cx="12" cy="12" r="1.2" fill={color} />
    <line x1="8.5" y1="2" x2="8.5" y2="5" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="12" y1="2" x2="12" y2="5" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="15.5" y1="2" x2="15.5" y2="5" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="8.5" y1="19" x2="8.5" y2="22" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="12" y1="19" x2="12" y2="22" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="15.5" y1="19" x2="15.5" y2="22" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="2" y1="8.5" x2="5" y2="8.5" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="2" y1="12" x2="5" y2="12" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="2" y1="15.5" x2="5" y2="15.5" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="19" y1="8.5" x2="22" y2="8.5" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="19" y1="12" x2="22" y2="12" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="19" y1="15.5" x2="22" y2="15.5" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
  </svg>
);

// 58. RAM MEMORY MODULE — DDR5/HBM circuit stick with BGA chips & edge connector bus
export const SciFiRamMemoryIcon = ({ size = 12, color = 'currentColor', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    <rect x="2" y="6" width="20" height="12" rx="1.5" stroke={color} strokeWidth="1.3" fill={color} fillOpacity="0.08" />
    <rect x="4.5" y="8" width="3.5" height="5.5" rx="0.5" stroke={color} strokeWidth="0.9" fill={color} fillOpacity="0.25" />
    <rect x="10.25" y="8" width="3.5" height="5.5" rx="0.5" stroke={color} strokeWidth="0.9" fill={color} fillOpacity="0.25" />
    <rect x="16" y="8" width="3.5" height="5.5" rx="0.5" stroke={color} strokeWidth="0.9" fill={color} fillOpacity="0.25" />
    <line x1="4.5" y1="15.5" x2="4.5" y2="18" stroke={color} strokeWidth="1" strokeLinecap="round" />
    <line x1="7" y1="15.5" x2="7" y2="18" stroke={color} strokeWidth="1" strokeLinecap="round" />
    <line x1="9.5" y1="15.5" x2="9.5" y2="18" stroke={color} strokeWidth="1" strokeLinecap="round" />
    <line x1="12" y1="16.5" x2="12" y2="18" stroke={color} strokeWidth="1" strokeLinecap="round" />
    <line x1="14.5" y1="15.5" x2="14.5" y2="18" stroke={color} strokeWidth="1" strokeLinecap="round" />
    <line x1="17" y1="15.5" x2="17" y2="18" stroke={color} strokeWidth="1" strokeLinecap="round" />
    <line x1="19.5" y1="15.5" x2="19.5" y2="18" stroke={color} strokeWidth="1" strokeLinecap="round" />
  </svg>
);

// 59. NETWORK PORT RJ45 / FIBER — Shielded socket with activity LED & pin connectors
export const SciFiNetworkPortIcon = ({ size = 12, color = 'currentColor', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    <path d="M4 5C4 3.9 4.9 3 6 3H18C19.1 3 20 3.9 20 5V19C20 20.1 19.1 21 18 21H6C4.9 21 4 20.1 4 19V5Z" stroke={color} strokeWidth="1.3" fill={color} fillOpacity="0.08" />
    <path d="M7 8H17V17H14V19H10V17H7V8Z" stroke={color} strokeWidth="1" fill={color} fillOpacity="0.2" />
    <line x1="9" y1="9.5" x2="9" y2="13" stroke={color} strokeWidth="0.9" strokeLinecap="round" />
    <line x1="11" y1="9.5" x2="11" y2="13" stroke={color} strokeWidth="0.9" strokeLinecap="round" />
    <line x1="13" y1="9.5" x2="13" y2="13" stroke={color} strokeWidth="0.9" strokeLinecap="round" />
    <line x1="15" y1="9.5" x2="15" y2="13" stroke={color} strokeWidth="0.9" strokeLinecap="round" />
    <circle cx="6.5" cy="5.5" r="0.9" fill={color} />
    <circle cx="17.5" cy="5.5" r="0.9" fill={color} />
  </svg>
);

// 60. CONTAINER IMAGE LAYERS — 3D Isometric OCI container filesystem layer stack
export const SciFiImageLayerIcon = ({ size = 12, color = 'currentColor', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    <polygon points="12,2 21,6.5 12,11 3,6.5" stroke={color} strokeWidth="1.3" fill={color} fillOpacity="0.35" />
    <path d="M3 11.5L12 16L21 11.5" stroke={color} strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    <path d="M3 16.5L12 21L21 16.5" stroke={color} strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" fill="none" />
  </svg>
);

// 61. HUD EXTERNAL LAUNCH LINK — Tactical target expansion bracket with 45-deg vector arrow
export const SciFiExternalLinkIcon = ({ size = 11, color = 'currentColor', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    <path d="M11 4H5C3.9 4 3 4.9 3 6V19C3 20.1 3.9 21 5 21H18C19.1 21 20 20.1 20 19V13" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    <line x1="12" y1="12" x2="21" y2="3" stroke={color} strokeWidth="1.8" strokeLinecap="round" />
    <polyline points="15,3 21,3 21,9" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

// 62. SCI-FI WARNING ALERT — Cyberpunk caution triangle with segmented exclamation core
export const SciFiWarningIcon = ({ size = 14, color = 'var(--accent-pink)', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    <path d="M12 2L2 20H22L12 2Z" stroke={color} strokeWidth="1.4" strokeLinejoin="round" fill={color} fillOpacity="0.12" />
    <line x1="12" y1="8" x2="12" y2="14" stroke={color} strokeWidth="1.8" strokeLinecap="round" />
    <circle cx="12" cy="17.5" r="1.2" fill={color} />
  </svg>
);

// 63. SCI-FI TRASH / PURGE INCINERATOR — Cyber canister with laser incinerator grid
export const SciFiTrashIcon = ({ size = 13, color = 'currentColor', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    <path d="M3 6H21" stroke={color} strokeWidth="1.6" strokeLinecap="round" />
    <path d="M8 6V4C8 3.4 8.4 3 9 3H15C15.6 3 16 3.4 16 4V6" stroke={color} strokeWidth="1.4" />
    <path d="M5 6L6.5 19.5C6.6 20.3 7.3 21 8.2 21H15.8C16.7 21 17.4 20.3 17.5 19.5L19 6" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.08" />
    <line x1="10" y1="10" x2="10" y2="17" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="14" y1="10" x2="14" y2="17" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
  </svg>
);

// 64. SCI-FI RADAR SCAN — Tactical pulse sweep with target reticle
export const SciFiRadarScanIcon = ({ size = 16, color = 'var(--accent-cyan)', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    <circle cx="12" cy="12" r="9" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.06" />
    <circle cx="12" cy="12" r="5" stroke={color} strokeWidth="0.8" strokeDasharray="2 2" strokeOpacity="0.6" />
    <circle cx="12" cy="12" r="1.5" fill={color} />
    <line x1="12" y1="12" x2="18.5" y2="5.5" stroke={color} strokeWidth="1.6" strokeLinecap="round" />
    <path d="M12 3C16.97 3 21 7.03 21 12" stroke={color} strokeWidth="1.2" strokeOpacity="0.4" />
    <circle cx="16" cy="8" r="1" fill={color} />
  </svg>
);

// 65. SCI-FI AI CHAT BUBBLE — Neural network speech pod with circuit node
export const SciFiAiChatBubbleIcon = ({ size = 15, color = 'var(--accent-cyan)', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    <path d="M21 11.5C21 6.8 16.97 3 12 3C7.03 3 3 6.8 3 11.5C3 14.1 4.2 16.4 6.2 17.9L5 21.5L9.3 19.8C10.2 20 11.1 20 12 20C16.97 20 21 16.2 21 11.5Z" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.08" strokeLinejoin="round" />
    <circle cx="8.5" cy="11.5" r="1.2" fill={color} />
    <circle cx="12" cy="11.5" r="1.2" fill={color} />
    <circle cx="15.5" cy="11.5" r="1.2" fill={color} />
    <line x1="8.5" y1="11.5" x2="15.5" y2="11.5" stroke={color} strokeWidth="0.8" strokeOpacity="0.5" />
  </svg>
);

// 66. SCI-FI VERIFIED CHECK — Hexagonal cyber shield with glowing check vector
export const SciFiVerifiedCheckIcon = ({ size = 13, color = 'var(--accent-green)', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    <polygon points="12,2 20.5,6.5 20.5,17.5 12,22 3.5,17.5 3.5,6.5" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.15" strokeLinejoin="round" />
    <path d="M7.5 12L10.5 15L16.5 9" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

// 67. SCI-FI USERS GROUP — Multi-node mesh squad network for friends manager
export const SciFiUsersGroupIcon = ({ size = 16, color = '#FE2C55', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    <circle cx="9" cy="7" r="3.5" stroke={color} strokeWidth="1.3" fill={color} fillOpacity="0.1" />
    <path d="M2 19C2 15.7 4.7 13 8 13H10C13.3 13 16 15.7 16 19" stroke={color} strokeWidth="1.3" strokeLinecap="round" fill="none" />
    <circle cx="17" cy="8" r="2.5" stroke={color} strokeWidth="1" strokeOpacity="0.7" fill={color} fillOpacity="0.08" />
    <path d="M16 13.5C18.2 14.1 20 15.8 20 18" stroke={color} strokeWidth="1" strokeOpacity="0.7" strokeLinecap="round" fill="none" />
    <line x1="9" y1="13" x2="17" y2="10.5" stroke={color} strokeWidth="0.8" strokeDasharray="1.5 1.5" strokeOpacity="0.4" />
  </svg>
);

// 68. SCI-FI PLAY PULSE — Crystal vector launcher with expanding wave pulses
export const SciFiPlayPulseIcon = ({ size = 14, color = 'var(--accent-cyan)', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    <polygon points="7,4 19,12 7,20" stroke={color} strokeWidth="1.5" fill={color} fillOpacity="0.25" strokeLinejoin="round" />
    <path d="M18 7C20 8.5 21 10.2 21 12C21 13.8 20 15.5 18 17" stroke={color} strokeWidth="1.2" strokeLinecap="round" strokeOpacity="0.6" />
  </svg>
);

// 69. SCI-FI HOLO SILHOUETTE — Cyberpunk avatar placeholder with biometric scan nodes
export const SciFiHoloSilhouette = ({ size = 36, color = 'var(--accent-cyan)', className = '', ...props }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 40 40"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    className={className}
    style={{ display: 'inline-block', verticalAlign: 'middle' }}
    {...props}
  >
    <rect width="40" height="40" rx="3" fill="rgba(0, 243, 255, 0.05)" stroke={color} strokeWidth="1" strokeDasharray="3 2" />
    <circle cx="20" cy="14" r="6" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.15" />
    <path d="M10 32C10 26.5 14.5 23 20 23C25.5 23 30 26.5 30 32" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
    <line x1="6" y1="20" x2="34" y2="20" stroke={color} strokeWidth="0.5" strokeOpacity="0.3" strokeDasharray="2 2" />
    <circle cx="20" cy="14" r="1.5" fill={color} />
  </svg>
);