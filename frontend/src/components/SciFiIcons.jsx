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

// 24. TELEGRAM — Sci-fi signal transmitter icon
export const SciFiTelegramIcon = ({ size = 20, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <path d="M22 2L11 13" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M22 2L15 22L11 13L2 9L22 2Z" stroke={color} strokeWidth="1.6" strokeLinejoin="round" fill="rgba(0, 243, 255, 0.08)" />
    <circle cx="22" cy="2" r="1.5" fill={color} />
    <path d="M6 16L3 19M18 8L21 5" stroke={color} strokeWidth="1" strokeDasharray="2 2" />
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
export const SciFiCloseIcon = ({ size = 18, color = 'var(--accent-pink)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    {/* Corner Bracket Frame */}
    <path d="M4 8V4H8M16 4H20V8M20 16V20H16M8 20H4V16" stroke={color} strokeWidth="1" strokeOpacity="0.6" />
    {/* Cross Lines */}
    <line x1="7" y1="7" x2="17" y2="17" stroke={color} strokeWidth="1.8" strokeLinecap="round" />
    <line x1="17" y1="7" x2="7" y2="17" stroke={color} strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);

// 35. FACEBOOK — Cyberpunk Facebook emblem with reticle ring
export const SciFiFacebookIcon = ({ size = 18, color = 'var(--accent-purple)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    {/* Outer Rounded Hex Box */}
    <rect x="2" y="2" width="20" height="20" rx="5" stroke={color} strokeWidth="1.5" fill="rgba(187, 0, 255, 0.1)" />
    {/* Stylized Cyber 'f' path */}
    <path d="M16 8H13.5C12.7 8 12 8.7 12 9.5V11.5H16L15.5 15.5H12V22H8V15.5H6V11.5H8V9.5C8 7 9.8 5 12.3 5H16V8Z"
      fill={color} fillOpacity="0.85" />
    {/* Corner Reticle Sparks */}
    <circle cx="4" cy="4" r="0.8" fill={color} />
    <circle cx="20" cy="20" r="0.8" fill={color} />
  </svg>
);

// 36. AI BOT / AGENT — Futuristic Cyber AI Core & Visor
export const SciFiBotIcon = ({ size = 20, color = 'var(--accent-cyan)' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    {/* Head chassis */}
    <rect x="3" y="6" width="18" height="14" rx="3" stroke={color} strokeWidth="1.5" fill="rgba(0, 243, 255, 0.08)" />
    {/* Antenna */}
    <line x1="12" y1="2" x2="12" y2="6" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
    <circle cx="12" cy="2" r="1.5" fill={color} />
    {/* Visor / Eye display */}
    <rect x="6" y="10" width="12" height="4" rx="1.5" stroke={color} strokeWidth="1.2" fill={color} fillOpacity="0.2" />
    <circle cx="8.5" cy="12" r="1" fill={color} />
    <circle cx="15.5" cy="12" r="1" fill={color} />
    {/* Side ears / connectors */}
    <rect x="1" y="10" width="2" height="6" rx="0.5" fill={color} fillOpacity="0.6" />
    <rect x="21" y="10" width="2" height="6" rx="0.5" fill={color} fillOpacity="0.6" />
    {/* Mouth / Data port */}
    <line x1="9" y1="17" x2="15" y2="17" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
  </svg>
);

// 37. ZALO — Cyber messaging bubble
export const SciFiZaloIcon = ({ size = 18, color = '#0068FF' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <rect x="2" y="2" width="20" height="20" rx="5" stroke={color} strokeWidth="1.5" fill="rgba(0, 104, 255, 0.12)" />
    <path d="M6 8H18L8 16H18" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

// 38. GMAIL — Cyber envelope with laser folds
export const SciFiGmailIcon = ({ size = 18, color = '#EA4335' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <rect x="3" y="4" width="18" height="16" rx="2" stroke={color} strokeWidth="1.5" fill="rgba(234, 67, 53, 0.1)" />
    <polyline points="3,6 12,13 21,6" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

// 39. TIKTOK — Cyber musical rhythm note
export const SciFiTikTokIcon = ({ size = 18, color = '#00F2FE' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <rect x="2" y="2" width="20" height="20" rx="5" stroke={color} strokeWidth="1.5" fill="rgba(0, 242, 254, 0.08)" />
    <path d="M14 4V14.5C14 16.43 12.43 18 10.5 18C8.57 18 7 16.43 7 14.5C7 12.57 8.57 11 10.5 11C11.03 11 11.53 11.12 11.97 11.33V7.5C13.2 8.64 14.8 9.35 16.57 9.35V6.5C15.15 6.5 14 5.38 14 4Z" fill={color} />
  </svg>
);

// 40. YOUTUBE — Cyber video screen with play reticle
export const SciFiYouTubeIcon = ({ size = 18, color = '#FF0033' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <rect x="2" y="4" width="20" height="16" rx="4" stroke={color} strokeWidth="1.5" fill="rgba(255, 0, 51, 0.1)" />
    <polygon points="10,8.5 16,12 10,15.5" fill={color} />
  </svg>
);

// 41. INSTAGRAM — Cyber camera reticle
export const SciFiInstagramIcon = ({ size = 18, color = '#E1306C' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <rect x="2" y="2" width="20" height="20" rx="5" stroke={color} strokeWidth="1.5" fill="rgba(225, 48, 108, 0.1)" />
    <circle cx="12" cy="12" r="4" stroke={color} strokeWidth="1.5" />
    <circle cx="17" cy="7" r="1.2" fill={color} />
  </svg>
);

// 42. WHATSAPP — Cyber chat node
export const SciFiWhatsAppIcon = ({ size = 18, color = '#25D366' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    <rect x="2" y="2" width="20" height="20" rx="5" stroke={color} strokeWidth="1.5" fill="rgba(37, 211, 102, 0.1)" />
    <path d="M16.5 14.5C16 15.2 14.5 15.5 13.5 15C11.5 14 9.5 12 8.5 10C8 9 8.3 7.5 9 7L10.5 8.5L9.5 10C10.2 11.5 11.5 12.8 13 13.5L14.5 12.5L16.5 14.5Z" fill={color} />
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

// 46. STREAK FLAME — Cyberpunk plasma flame with inner core layers and energy tendrils
// Designed for TikTok "Daily Streak" feature — evokes burning energy, persistence, chain reaction
export const SciFiFlameStreakIcon = ({ size = 18, color = '#FE2C55' }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ display: 'inline-block', verticalAlign: 'middle' }}>
    {/* Outer flame silhouette — asymmetric for organic feel */}
    <path
      d="M12 2C12 2 8 6.5 8 10.5C8 11.8 8.4 13 9.2 13.9C9.1 13.3 9.1 12.5 9.5 11.9C10.3 10.7 11 10 11 10C11 10 10.8 13 12.5 14.5C13 14 13.4 13.2 13.4 12.4C14.2 13.4 14.5 14.8 14.2 16C15.3 15.1 16 13.6 16 12C16 9 14 7 14 7C14 9 13 10 13 10C13 10 16 7 12 2Z"
      fill={color} fillOpacity="0.9"
    />
    {/* Inner hot core — brighter, smaller flame */}
    <path
      d="M12 8C12 8 10.5 10.5 10.5 12.5C10.5 13.8 11.1 14.9 12 15.5C12.9 14.9 13.5 13.8 13.5 12.5C13.5 10.5 12 8 12 8Z"
      fill={color} fillOpacity="0.4"
    />
    {/* Flame tip — sharp peak */}
    <path d="M12 2L11.2 4.5L12 6L12.8 4.5L12 2Z" fill={color} fillOpacity="0.6" />
    {/* Base glow embers — small sparks at bottom */}
    <circle cx="10" cy="17" r="0.8" fill={color} fillOpacity="0.7" />
    <circle cx="14" cy="17" r="0.6" fill={color} fillOpacity="0.5" />
    <circle cx="12" cy="18" r="1" fill={color} fillOpacity="0.8" />
    {/* Energy tendril left */}
    <path d="M9.5 11C9 10.2 8.5 9 8.8 7.5" stroke={color} strokeWidth="0.7" strokeOpacity="0.4" strokeLinecap="round" />
    {/* Energy tendril right */}
    <path d="M14.5 9C15 8 15.2 6.8 14.8 5.5" stroke={color} strokeWidth="0.7" strokeOpacity="0.3" strokeLinecap="round" />
    {/* Bottom base line — grounding the flame */}
    <line x1="9" y1="19" x2="15" y2="19" stroke={color} strokeWidth="1.2" strokeLinecap="round" strokeOpacity="0.5" />
    <line x1="10.5" y1="20.5" x2="13.5" y2="20.5" stroke={color} strokeWidth="0.8" strokeLinecap="round" strokeOpacity="0.3" />
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