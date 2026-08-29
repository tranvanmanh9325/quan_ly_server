import { memo } from 'react';

const STYLES = `
  @keyframes hudSonarWave {
    0%   { transform: scale(0.6); opacity: 0.9; }
    70%  { opacity: 0.35; }
    100% { transform: scale(2.6); opacity: 0; }
  }
  @keyframes hudLaserFlow {
    0%   { stroke-dashoffset: 0; }
    100% { stroke-dashoffset: -16; }
  }
  @keyframes hudDiamondPulse {
    0%, 100% { transform: rotate(45deg) scale(1);    filter: drop-shadow(0 0 2px #00ff9d); }
    50%       { transform: rotate(45deg) scale(1.22); filter: drop-shadow(0 0 7px #00ff9d); }
  }
  @keyframes hudStatusBlink {
    0%, 100% { opacity: 1; }
    50%       { opacity: 0.3; }
  }
`;

/**
 * GlobeHudLegend — Military/Palantir-style HUD legend bar for the 3D Globe panel.
 * 100% inline styles + embedded keyframes — zero external CSS class dependency.
 */
const GlobeHudLegend = memo(function GlobeHudLegend({
  serverCount = 1,
  clientCount = 0,
  isLive = true,
}) {
  return (
    <div style={{
      position: 'relative',
      display: 'flex',
      alignItems: 'center',
      flexWrap: 'nowrap',
      minHeight: '34px',
      overflowX: 'auto',
      background: 'linear-gradient(180deg, rgba(6,18,33,0.82) 0%, rgba(2,8,16,0.92) 100%)',
      backdropFilter: 'blur(10px)',
      WebkitBackdropFilter: 'blur(10px)',
      border: '1px solid rgba(0,243,255,0.22)',
      clipPath: 'polygon(8px 0, 100% 0, 100% calc(100% - 8px), calc(100% - 8px) 100%, 0 100%, 0 8px)',
      boxShadow: 'inset 0 1px 0 rgba(0,243,255,0.35), inset 0 0 14px rgba(0,243,255,0.04), 0 6px 20px rgba(0,0,0,0.65)',
      fontFamily: "'Share Tech Mono', monospace",
      userSelect: 'none',
      flexShrink: 0,

    }}>
      <style>{STYLES}</style>

      {/* Corner brackets */}
      <div style={{ position:'absolute', top:0, left:0, width:'7px', height:'7px', borderTop:'1.5px solid #00f3ff', borderLeft:'1.5px solid #00f3ff', pointerEvents:'none' }} />
      <div style={{ position:'absolute', bottom:0, right:0, width:'7px', height:'7px', borderBottom:'1.5px solid #00f3ff', borderRight:'1.5px solid #00f3ff', pointerEvents:'none' }} />

      {/* Header badge */}
      <div style={{ padding:'6px 8px', borderRight:'1px solid rgba(0,243,255,0.15)', display:'flex', alignItems:'center', gap:'5px', flexShrink:0 }}>
        <div style={{
          width:'5px', height:'5px', borderRadius:'50%',
          background: isLive ? '#00ff9d' : '#ff0055',
          boxShadow: isLive ? '0 0 6px #00ff9d' : '0 0 6px #ff0055',
          animation: isLive ? 'hudStatusBlink 1.8s ease-in-out infinite' : 'none',
          flexShrink:0,
        }} />
        <span style={{ fontSize:'0.56rem', letterSpacing:'1.5px', color:'rgba(0,243,255,0.5)', fontWeight:'bold', whiteSpace:'nowrap' }}>
          TELEMETRY
        </span>
      </div>

      {/* SERVER HQ */}
      <LegendItem borderRight>
        <HudServerHQIcon />
        <LabelGroup label="SERVER HQ" badge={serverCount > 0 ? `C2·${serverCount}` : 'C2'} badgeColor="#00ff9d" />
      </LegendItem>

      {/* CLIENT NODE */}
      <LegendItem borderRight>
        <HudClientNodeIcon />
        <LabelGroup label="CLIENT NODE" badge={clientCount > 0 ? `EXT·${clientCount}` : 'EXT'} badgeColor="#00f3ff" />
      </LegendItem>

      {/* VN ISLANDS */}
      <LegendItem borderRight>
        <HudIslandDiamondIcon />
        <LabelGroup label="VN ISLANDS" badge="GEO·VN" badgeColor="#00ff9d" />
      </LegendItem>

      {/* SATELLITES */}
      <LegendItem borderRight>
        <HudSatelliteIcon />
        <LabelGroup label="SATELLITES" badge="SAT·8" badgeColor="#ffe600" />
      </LegendItem>

      {/* LASER ARC */}
      <LegendItem>
        <HudLaserBeamIcon />
        <LabelGroup label="LASER ARC" badge="TX" badgeColor="#00f3ff" />
      </LegendItem>
    </div>
  );
});


function LegendItem({ children, borderRight }) {
  return (
    <div style={{
      padding: '5px 10px',
      borderRight: borderRight ? '1px solid rgba(0,243,255,0.12)' : 'none',
      display: 'flex', alignItems: 'center', gap: '7px', flexShrink: 0,
    }}>
      {children}
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════
// HAND-CRAFTED HIGH-TECH CYBERPUNK SVG ICONS (100% EXCLUSIVE VECTOR ART)
// ═════════════════════════════════════════════════════════════════════

/**
 * 1. HudServerHQIcon — Command C2 Tower with Sonar Wave Rings
 */
function HudServerHQIcon() {
  return (
    <div style={{ position: 'relative', width: '18px', height: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
      {/* Background Pulsing Sonar Wave */}
      <span style={{
        position: 'absolute',
        width: '14px',
        height: '14px',
        borderRadius: '50%',
        border: '1.2px solid #00ff9d',
        animation: 'hudSonarWave 2.4s cubic-bezier(0,0.2,0.8,1) infinite',
        pointerEvents: 'none',
      }} />
      <svg width="18" height="16" viewBox="0 0 18 16" fill="none" style={{ position: 'relative', overflow: 'visible' }}>
        {/* Chassis Foundation */}
        <rect x="2" y="11" width="14" height="4" rx="0.8" fill="rgba(0,255,157,0.15)" stroke="#00ff9d" strokeWidth="1" />
        <circle cx="4.5" cy="13" r="0.7" fill="#00ff9d" />
        <circle cx="13.5" cy="13" r="0.7" fill="#00ff9d" />
        {/* Mid C2 Unit */}
        <polygon points="9,2 14,8 4,8" fill="rgba(0,255,157,0.3)" stroke="#00ff9d" strokeWidth="1" strokeLinejoin="round" />
        {/* Zenith Mast & Emitter */}
        <line x1="9" y1="2" x2="9" y2="0" stroke="#00ff9d" strokeWidth="1.2" strokeLinecap="round" />
        <circle cx="9" cy="0" r="0.8" fill="#ffffff" style={{ filter: 'drop-shadow(0 0 3px #00ff9d)' }} />
      </svg>
    </div>
  );
}

/**
 * 2. HudClientNodeIcon — Tactical Octagonal Node with Cyan Beacon
 */
function HudClientNodeIcon() {
  return (
    <div style={{ position: 'relative', width: '18px', height: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
      <span style={{
        position: 'absolute',
        width: '14px',
        height: '14px',
        borderRadius: '50%',
        border: '1.2px solid #00f3ff',
        animation: 'hudSonarWave 2.0s cubic-bezier(0,0.2,0.8,1) infinite 0.4s',
        pointerEvents: 'none',
      }} />
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ position: 'relative', overflow: 'visible' }}>
        {/* Tactical Outer Reticle */}
        <circle cx="8" cy="8" r="6.5" stroke="#00f3ff" strokeWidth="0.9" strokeDasharray="3 2" opacity="0.85" />
        {/* Diamond Core */}
        <polygon points="8,4 12,8 8,12 4,8" fill="rgba(0,243,255,0.25)" stroke="#00f3ff" strokeWidth="1.1" strokeLinejoin="round" />
        {/* Center Glowing Dot */}
        <circle cx="8" cy="8" r="1.4" fill="#ffffff" style={{ filter: 'drop-shadow(0 0 4px #00f3ff)' }} />
      </svg>
    </div>
  );
}

/**
 * 3. HudIslandDiamondIcon — Dual Concentric Diamond Sovereignty Emblem
 */
function HudIslandDiamondIcon() {
  return (
    <div style={{ position: 'relative', width: '16px', height: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ overflow: 'visible' }}>
        {/* Outer Pulsing Diamond */}
        <g style={{ animation: 'hudDiamondPulse 2.6s ease-in-out infinite', transformOrigin: '8px 8px' }}>
          <polygon points="8,1 15,8 8,15 1,8" stroke="#00ff9d" strokeWidth="1.1" fill="rgba(0,255,157,0.12)" strokeLinejoin="round" />
          {/* Inner Diamond */}
          <polygon points="8,4 12,8 8,12 4,8" stroke="#00ff9d" strokeWidth="0.8" fill="rgba(0,255,157,0.35)" />
          {/* Center Point */}
          <circle cx="8" cy="8" r="1.2" fill="#ffffff" style={{ filter: 'drop-shadow(0 0 3px #00ff9d)' }} />
        </g>
      </svg>
    </div>
  );
}

/**
 * 4. HudSatelliteIcon — NASA-Grade 3D Spacecraft Vector Icon
 * Hand-crafted with Golden Kapton Bus, Blue Multi-Junction Solar Wings with Wafer Grids,
 * Nadir Parabolic Downlink Dish, Feed Horn, and Zenith Communication Mast.
 */
function HudSatelliteIcon() {
  return (
    <div style={{ position: 'relative', width: '22px', height: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
      <svg width="22" height="16" viewBox="0 0 22 16" fill="none" style={{ overflow: 'visible' }}>
        {/* ── Left Solar Wing (Multi-Junction Solar Array) ── */}
        <g>
          {/* Left Wing Frame */}
          <rect x="0.5" y="4" width="6.2" height="8" rx="0.6" fill="rgba(0,243,255,0.18)" stroke="#00f3ff" strokeWidth="0.9" />
          {/* Grid lines (Solar Cell Busbars) */}
          <line x1="3.6" y1="4" x2="3.6" y2="12" stroke="#00f3ff" strokeWidth="0.6" strokeOpacity="0.5" />
          <line x1="0.5" y1="8" x2="6.7" y2="8" stroke="#00f3ff" strokeWidth="0.6" strokeOpacity="0.5" />
          {/* Wing Yoke / Hinge Connection */}
          <line x1="6.7" y1="8" x2="8" y2="8" stroke="#ffffff" strokeWidth="1.2" strokeLinecap="round" />
        </g>

        {/* ── Right Solar Wing (Multi-Junction Solar Array) ── */}
        <g>
          {/* Right Wing Frame */}
          <rect x="15.3" y="4" width="6.2" height="8" rx="0.6" fill="rgba(0,243,255,0.18)" stroke="#00f3ff" strokeWidth="0.9" />
          {/* Grid lines (Solar Cell Busbars) */}
          <line x1="18.4" y1="4" x2="18.4" y2="12" stroke="#00f3ff" strokeWidth="0.6" strokeOpacity="0.5" />
          <line x1="15.3" y1="8" x2="21.5" y2="8" stroke="#00f3ff" strokeWidth="0.6" strokeOpacity="0.5" />
          {/* Wing Yoke / Hinge Connection */}
          <line x1="14" y1="8" x2="15.3" y2="8" stroke="#ffffff" strokeWidth="1.2" strokeLinecap="round" />
        </g>

        {/* ── Central Golden Avionics Bus (Hexagonal Prism) ── */}
        <polygon
          points="11,3 14,5.2 14,10.8 11,13 8,10.8 8,5.2"
          fill="rgba(255,230,0,0.3)"
          stroke="#ffe600"
          strokeWidth="1.1"
          strokeLinejoin="round"
          style={{ filter: 'drop-shadow(0 0 2px rgba(255,230,0,0.5))' }}
        />
        {/* Core Circuit / Star Tracker Sensor */}
        <circle cx="11" cy="8" r="1.2" fill="#ffffff" />

        {/* ── Zenith Mast & Transponder Beacon ── */}
        <line x1="11" y1="3" x2="11" y2="0.8" stroke="#ffe600" strokeWidth="1" strokeLinecap="round" />
        <circle cx="11" cy="0.8" r="0.7" fill="#ffffff" style={{ filter: 'drop-shadow(0 0 3px #ffe600)' }} />

        {/* ── Nadir Parabolic Communication Dish & Feed Horn ── */}
        <path d="M8.5 13.5 C9.5 15.5 12.5 15.5 13.5 13.5" stroke="#ffe600" strokeWidth="1.1" strokeLinecap="round" fill="none" />
        <line x1="11" y1="12.5" x2="11" y2="14.8" stroke="#ffffff" strokeWidth="0.8" strokeLinecap="round" />
      </svg>
    </div>
  );
}

/**
 * 5. HudLaserBeamIcon — Coherent Photon Stream with Diamond Arrowhead
 */
function HudLaserBeamIcon() {
  return (
    <div style={{ width: '26px', height: '14px', display: 'flex', alignItems: 'center', flexShrink: 0 }}>
      <svg width="26" height="12" viewBox="0 0 26 12" fill="none" style={{ overflow: 'visible' }}>
        {/* Outer Glow Laser */}
        <line x1="1" y1="6" x2="19" y2="6"
          stroke="#00f3ff" strokeWidth="2" strokeDasharray="5 3" strokeLinecap="round"
          style={{ animation: 'hudLaserFlow 1.0s linear infinite', filter: 'drop-shadow(0 0 4px #00f3ff)' }}
        />
        {/* Inner High-Energy Core */}
        <line x1="1" y1="6" x2="19" y2="6"
          stroke="#ffffff" strokeWidth="0.8" strokeDasharray="5 3" strokeLinecap="round"
          style={{ animation: 'hudLaserFlow 1.0s linear infinite' }}
        />
        {/* Diamond Arrowhead */}
        <polygon points="19,3 25,6 19,9 20.5,6" fill="#00f3ff"
          style={{ filter: 'drop-shadow(0 0 3px #00f3ff)' }}
        />
        <circle cx="21" cy="6" r="0.8" fill="#ffffff" />
      </svg>
    </div>
  );
}

function LabelGroup({ label, badge, badgeColor }) {
  const isGreen = badgeColor === '#00ff9d';
  const bg = isGreen ? 'rgba(0,255,157,0.1)' : badgeColor === '#ffe600' ? 'rgba(255,230,0,0.1)' : 'rgba(0,243,255,0.1)';
  const bd = isGreen ? 'rgba(0,255,157,0.3)' : badgeColor === '#ffe600' ? 'rgba(255,230,0,0.3)' : 'rgba(0,243,255,0.3)';
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: '3px', whiteSpace: 'nowrap' }}>
      <span style={{ fontSize: '0.65rem', fontWeight: 700, color: '#fff', letterSpacing: '0.6px', fontFamily: "'Share Tech Mono',monospace" }}>
        {label}
      </span>
      <span style={{
        fontSize: '0.52rem', color: badgeColor,
        background: bg, border: `1px solid ${bd}`,
        padding: '0 2px', borderRadius: '2px', lineHeight: '1.3',
        fontFamily: "'Share Tech Mono',monospace", letterSpacing: '0.3px',
      }}>
        [{badge}]
      </span>
    </div>
  );
}

export default GlobeHudLegend;

