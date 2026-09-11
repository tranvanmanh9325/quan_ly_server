import React from 'react';

/**
 * BrainSciFiIcons.jsx - Bespoke Custom-Designed Cyberpunk SVG Icons
 * Handcrafted exclusively for Tiểu Bảo Bảo's Neuromorphic Brain Core Dashboard.
 * 100% pure SVG with zero external icon/font dependencies.
 */

// 1. CYBER CEREBRUM — Dual-hemisphere cybernetic brain with circuit gyri & corpus callosum bridge
export const SciFiCyberCerebrumIcon = ({ size = 20, color = 'currentColor', className = '', ...props }) => (
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
    {/* Left Hemisphere Gyri */}
    <path
      d="M12 4.2C9.2 2.8 5.8 3.4 4.2 5.6C2.2 8.2 2.6 11.8 3.8 14C2.6 15.8 3 18.4 4.8 20C6.5 21.4 9.2 21 12 19.5"
      stroke={color}
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M5.5 9C7.2 9.5 8.8 8.4 9.8 6.8M5 14.5C6.8 15 8.2 13.8 9.6 12.2M6 18C7.5 17.5 8.6 18.5 10.2 17"
      stroke={color}
      strokeWidth="1.1"
      strokeLinecap="round"
      strokeOpacity="0.75"
    />

    {/* Right Hemisphere Gyri */}
    <path
      d="M12 4.2C14.8 2.8 18.2 3.4 19.8 5.6C21.8 8.2 21.4 11.8 20.2 14C21.4 15.8 21 18.4 19.2 20C17.5 21.4 14.8 21 12 19.5"
      stroke={color}
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M18.5 9C16.8 9.5 15.2 8.4 14.2 6.8M19 14.5C17.2 15 15.8 13.8 14.4 12.2M18 18C16.5 17.5 15.4 18.5 13.8 17"
      stroke={color}
      strokeWidth="1.1"
      strokeLinecap="round"
      strokeOpacity="0.75"
    />

    {/* Central Corpus Callosum Bus */}
    <line x1="12" y1="4.5" x2="12" y2="19.5" stroke={color} strokeWidth="1.3" strokeDasharray="1.5 1.5" />
    <circle cx="12" cy="12" r="2.2" stroke={color} strokeWidth="1.2" fill={color} fillOpacity="0.3" />
    <circle cx="12" cy="12" r="0.8" fill="#ffffff" />
  </svg>
);

// 2. CIRCUMPLEX RADAR — 2D Cartesian Affect Space with concentric circles and mood vector
export const SciFiCircumplexRadarIcon = ({ size = 20, color = 'currentColor', className = '', ...props }) => (
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
    <circle cx="12" cy="12" r="9" stroke={color} strokeWidth="1.2" strokeOpacity="0.4" />
    <circle cx="12" cy="12" r="5" stroke={color} strokeWidth="0.8" strokeDasharray="2 2" strokeOpacity="0.5" />
    <line x1="12" y1="2" x2="12" y2="22" stroke={color} strokeWidth="1.2" strokeOpacity="0.7" />
    <line x1="2" y1="12" x2="22" y2="12" stroke={color} strokeWidth="1.2" strokeOpacity="0.7" />
    {/* Mood Vector Puck in Q1 */}
    <circle cx="16" cy="8" r="2.2" stroke={color} strokeWidth="1.2" fill={color} fillOpacity="0.4" />
    <circle cx="16" cy="8" r="0.9" fill="#ffffff" />
    <line x1="12" y1="12" x2="16" y2="8" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
  </svg>
);

// 3. NEURO MOLECULAR — Biomorphic hexagon with neurotransmitter bonding rings & receptor nodes
export const SciFiNeuroMolecularIcon = ({ size = 20, color = 'currentColor', className = '', ...props }) => (
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
    {/* Central Hexagon Ring */}
    <polygon points="12,3 19,7 19,15 12,19 5,15 5,7" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.1" />
    <circle cx="12" cy="3" r="1.5" fill={color} />
    <circle cx="19" cy="7" r="1.5" fill={color} />
    <circle cx="19" cy="15" r="1.5" fill={color} />
    <circle cx="12" cy="19" r="1.5" fill={color} />
    <circle cx="5" cy="15" r="1.5" fill={color} />
    <circle cx="5" cy="7" r="1.5" fill={color} />
    {/* Internal Receptor Bonds */}
    <line x1="12" y1="3" x2="12" y2="19" stroke={color} strokeWidth="0.9" strokeDasharray="2 2" strokeOpacity="0.6" />
    <circle cx="12" cy="11" r="2.2" stroke={color} strokeWidth="1.1" fill={color} fillOpacity="0.35" />
    <line x1="19" y1="7" x2="22" y2="5" stroke={color} strokeWidth="1.3" strokeLinecap="round" />
    <circle cx="22" cy="5" r="1" fill="#ffffff" />
    <line x1="5" y1="15" x2="2" y2="17" stroke={color} strokeWidth="1.3" strokeLinecap="round" />
    <circle cx="2" cy="17" r="1" fill="#ffffff" />
  </svg>
);

// 4. FREE ENERGY SPIRAL — Variational FEP energy funnel with prediction delta arrow
export const SciFiFreeEnergySpiralIcon = ({ size = 20, color = 'currentColor', className = '', ...props }) => (
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
    {/* Energy Vortex Arc */}
    <path
      d="M12 2C6.48 2 2 6.48 2 12C2 17.52 6.48 22 12 22C16.5 22 20.2 19 21.5 15"
      stroke={color}
      strokeWidth="1.4"
      strokeLinecap="round"
    />
    <path
      d="M12 6C8.69 6 6 8.69 6 12C6 15.31 8.69 18 12 18C14.5 18 16.6 16.5 17.5 14"
      stroke={color}
      strokeWidth="1.2"
      strokeOpacity="0.75"
      strokeLinecap="round"
    />
    <circle cx="12" cy="12" r="2.2" fill={color} />
    {/* Variational Delta Lightning Arrow */}
    <polygon points="17,3 13,10 16,10 14,16 21,9 18,9" fill={color} />
  </svg>
);

// 5. CONSCIOUSNESS SPOTLIGHT — Optical emitter with radiant broadcast wave
export const SciFiConsciousnessSpotlightIcon = ({ size = 20, color = 'currentColor', className = '', ...props }) => (
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
    <polygon points="4,7 10,4 10,14 4,11" stroke={color} strokeWidth="1.3" fill={color} fillOpacity="0.2" />
    <path d="M10 5L20 2L20 16L10 13" stroke={color} strokeWidth="1.2" strokeOpacity="0.6" fill={color} fillOpacity="0.08" />
    <line x1="12" y1="9" x2="19" y2="9" stroke={color} strokeWidth="1" strokeDasharray="1.5 1.5" />
    <circle cx="4" cy="9" r="1.5" fill={color} />
    <circle cx="20" cy="9" r="2" stroke={color} strokeWidth="1.2" fill="#ffffff" />
    <path d="M19 19C17 21 14 22 10 22" stroke={color} strokeWidth="1.2" strokeLinecap="round" strokeDasharray="2 2" />
  </svg>
);

// 6. VIRTUAL CORTEX LATTICE — 3D Hyper-dimensional memory cube with 10k-bit grid
export const SciFiVirtualCortexLatticeIcon = ({ size = 20, color = 'currentColor', className = '', ...props }) => (
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
    <polygon points="12,2 21,7 12,12 3,7" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.25" />
    <polygon points="3,7 12,12 12,22 3,17" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.12" />
    <polygon points="12,12 21,7 21,17 12,22" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.18" />
    <circle cx="12" cy="7" r="1.2" fill={color} />
    <circle cx="7.5" cy="14.5" r="1" fill={color} />
    <circle cx="16.5" cy="14.5" r="1" fill={color} />
    <line x1="12" y1="2" x2="12" y2="22" stroke={color} strokeWidth="0.8" strokeDasharray="2 2" strokeOpacity="0.5" />
  </svg>
);

// 7. DREAM WAVE — Cybernetic crescent moon with slow-wave (SWS) and REM delta waves
export const SciFiDreamWaveIcon = ({ size = 20, color = 'currentColor', className = '', ...props }) => (
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
    {/* Cyber Crescent */}
    <path
      d="M21 12.79A9 9 0 1 1 11.21 3A7 7 0 0 0 21 12.79Z"
      stroke={color}
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill={color}
      fillOpacity="0.12"
    />
    {/* Biomorphic Sleep Waveform */}
    <path
      d="M4 14C6 12 7 16 9 14C11 12 12 16 14 14"
      stroke={color}
      strokeWidth="1.3"
      strokeLinecap="round"
    />
    <circle cx="18" cy="6" r="1" fill={color} />
    <circle cx="15" cy="3.5" r="0.8" fill={color} />
  </svg>
);

// 8. THEORY OF MIND & EMPATHY — Dual telemetry nexus joined by empathic resonance heart
export const SciFiTheoryOfMindHeartIcon = ({ size = 20, color = 'currentColor', className = '', ...props }) => (
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
    {/* Cyber Heart Outline */}
    <path
      d="M12 21.35L10.55 20.03C5.4 15.36 2 12.28 2 8.5C2 5.42 4.42 3 7.5 3C9.24 3 10.91 3.81 12 5.09C13.09 3.81 14.76 3 16.5 3C19.58 3 22 5.42 22 8.5C22 12.28 18.6 15.36 13.45 20.04L12 21.35Z"
      stroke={color}
      strokeWidth="1.4"
      fill={color}
      fillOpacity="0.15"
      strokeLinejoin="round"
    />
    {/* Dual Companion Silhouette Nodes */}
    <circle cx="8.5" cy="9.5" r="2" stroke={color} strokeWidth="1.1" fill="#ffffff" />
    <circle cx="15.5" cy="9.5" r="2" stroke={color} strokeWidth="1.1" fill={color} />
    {/* Telepathic Resonance Bridge */}
    <line x1="10.5" y1="9.5" x2="13.5" y2="9.5" stroke={color} strokeWidth="1.2" strokeDasharray="1.5 1.5" />
    <path d="M7 14C9.5 16.5 14.5 16.5 17 14" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
  </svg>
);

// 9. MORNING EPIPHANY — Cyber dawn horizon with rising insight vector
export const SciFiMorningEpiphanyIcon = ({ size = 20, color = 'currentColor', className = '', ...props }) => (
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
    <line x1="2" y1="18" x2="22" y2="18" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
    <path d="M6 18A6 6 0 0 1 18 18" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.2" />
    <line x1="12" y1="4" x2="12" y2="10" stroke={color} strokeWidth="1.6" strokeLinecap="round" />
    <line x1="4.5" y1="7.5" x2="8.5" y2="11.5" stroke={color} strokeWidth="1.3" strokeLinecap="round" />
    <line x1="19.5" y1="7.5" x2="15.5" y2="11.5" stroke={color} strokeWidth="1.3" strokeLinecap="round" />
    <circle cx="12" cy="14" r="1.5" fill="#ffffff" />
  </svg>
);

// 10. ASSOCIATIVE SEARCH — Tactical synaptic target reticle with 45-deg sweep
export const SciFiAssociativeSearchIcon = ({ size = 18, color = 'currentColor', className = '', ...props }) => (
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
    <circle cx="11" cy="11" r="7.5" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.08" />
    <circle cx="11" cy="11" r="3.5" stroke={color} strokeWidth="0.8" strokeDasharray="1.5 1.5" strokeOpacity="0.6" />
    <line x1="11" y1="2" x2="11" y2="5" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="11" y1="17" x2="11" y2="20" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="2" y1="11" x2="5" y2="11" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="17" y1="11" x2="20" y2="11" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    <line x1="16.5" y1="16.5" x2="22" y2="22" stroke={color} strokeWidth="2" strokeLinecap="round" />
    <circle cx="11" cy="11" r="1.2" fill={color} />
  </svg>
);

// 11. COGNITIVE PULSE ACTION — Action potential flash with radiating wavefronts
export const SciFiCognitivePulseBurstIcon = ({ size = 18, color = 'currentColor', className = '', ...props }) => (
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
    <polygon points="13,2 4,14 11,14 9,22 20,10 13,10" fill={color} />
    <path d="M19 4C21 6 22 9 22 12C22 15 21 18 19 20" stroke={color} strokeWidth="1.2" strokeLinecap="round" strokeOpacity="0.5" />
    <path d="M2 12C2 9 3 6 5 4" stroke={color} strokeWidth="1.2" strokeLinecap="round" strokeOpacity="0.5" />
  </svg>
);

// 12. SYNC REFRESH LOOP — High-tech dual accelerator orbital arrows
export const SciFiSyncRefreshLoopIcon = ({ size = 16, color = 'currentColor', className = '', ...props }) => (
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
    <path d="M21 12A9 9 0 0 0 6 5.3L3 8" stroke={color} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    <polyline points="3,3 3,8 8,8" stroke={color} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M3 12A9 9 0 0 0 18 18.7L21 16" stroke={color} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    <polyline points="21,21 21,16 16,16" stroke={color} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    <circle cx="12" cy="12" r="1.5" fill={color} />
  </svg>
);

// 13. DAEMON: INTEROCEPTION (Server CPU/RAM internal sensory processor)
export const SciFiDaemonInteroceptionIcon = ({ size = 15, color = 'currentColor', className = '', ...props }) => (
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
    <rect x="4" y="4" width="16" height="16" rx="2" stroke={color} strokeWidth="1.3" fill={color} fillOpacity="0.1" />
    <path d="M8 12H10L11.5 8L13.5 16L15 12H16" stroke={color} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    <circle cx="6.5" cy="6.5" r="0.8" fill={color} />
  </svg>
);

// 14. DAEMON: EXTEROCEPTION (External network sensor & environmental radar)
export const SciFiDaemonExteroceptionIcon = ({ size = 15, color = 'currentColor', className = '', ...props }) => (
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
    <circle cx="12" cy="12" r="8" stroke={color} strokeWidth="1.3" fill={color} fillOpacity="0.08" />
    <ellipse cx="12" cy="12" rx="8" ry="3.5" stroke={color} strokeWidth="0.9" strokeDasharray="1.5 1.5" />
    <line x1="12" y1="4" x2="12" y2="20" stroke={color} strokeWidth="0.9" />
    <circle cx="12" cy="12" r="1.5" fill={color} />
  </svg>
);

// 15. DAEMON: RELATIONAL (Companion bond & empathy with Anh Mạnh)
export const SciFiDaemonRelationalIcon = ({ size = 15, color = 'currentColor', className = '', ...props }) => (
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
    <circle cx="8" cy="9" r="3" stroke={color} strokeWidth="1.2" fill={color} fillOpacity="0.2" />
    <circle cx="16" cy="9" r="3" stroke={color} strokeWidth="1.2" fill={color} fillOpacity="0.2" />
    <path d="M4 19C4 16.5 6 15 8 15H16C18 15 20 16.5 20 19" stroke={color} strokeWidth="1.3" strokeLinecap="round" />
    <circle cx="12" cy="9" r="1.2" fill="#ffffff" />
  </svg>
);

// 16. DAEMON: CURIOSITY (Exploratory quantum sparkle & discovery vector)
export const SciFiDaemonCuriosityIcon = ({ size = 15, color = 'currentColor', className = '', ...props }) => (
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
    <polygon points="12,2 15,9 22,12 15,15 12,22 9,15 2,12 9,9" stroke={color} strokeWidth="1.2" fill={color} fillOpacity="0.25" />
    <circle cx="12" cy="12" r="1.8" fill="#ffffff" />
  </svg>
);

// 17. PINNED VECTOR — Tactical cyber pin for anchored long-term memories
export const SciFiPinnedVectorIcon = ({ size = 14, color = 'currentColor', className = '', ...props }) => (
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
    <path d="M16 3L21 8L18 11L17 10L14 13V17L12 19L11 15L7 11H3L5 9L9 8L10 5L9 4L12 1L16 3Z" stroke={color} strokeWidth="1.3" fill={color} fillOpacity="0.2" strokeLinejoin="round" />
    <line x1="12" y1="19" x2="6" y2="23" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
    <circle cx="15" cy="6" r="1" fill="#ffffff" />
  </svg>
);

// 18. ZOOM IN — Optical focal reticle with plus sign
export const SciFiZoomInIcon = ({ size = 14, color = 'currentColor', className = '', ...props }) => (
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
    <circle cx="11" cy="11" r="7" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.08" />
    <line x1="16.5" y1="16.5" x2="21" y2="21" stroke={color} strokeWidth="1.8" strokeLinecap="round" />
    <line x1="11" y1="8" x2="11" y2="14" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
    <line x1="8" y1="11" x2="14" y2="11" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
  </svg>
);

// 19. ZOOM OUT — Optical focal reticle with minus sign
export const SciFiZoomOutIcon = ({ size = 14, color = 'currentColor', className = '', ...props }) => (
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
    <circle cx="11" cy="11" r="7" stroke={color} strokeWidth="1.4" fill={color} fillOpacity="0.08" />
    <line x1="16.5" y1="16.5" x2="21" y2="21" stroke={color} strokeWidth="1.8" strokeLinecap="round" />
    <line x1="8" y1="11" x2="14" y2="11" stroke={color} strokeWidth="1.4" strokeLinecap="round" />
  </svg>
);

// 20. FULLSCREEN EXPAND — Corner brackets expanding outward
export const SciFiFullscreenExpandIcon = ({ size = 14, color = 'currentColor', className = '', ...props }) => (
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
    <path d="M4 9V4H9M20 9V4H15M4 15V20H9M20 15V20H15" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

// 21. FULLSCREEN EXIT — Corner brackets contracting inward
export const SciFiFullscreenExitIcon = ({ size = 14, color = 'currentColor', className = '', ...props }) => (
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
    <path d="M9 4V9H4M15 4V9H20M9 20V15H4M15 20V15H20" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

