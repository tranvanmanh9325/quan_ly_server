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
        <SonarDot color="#00ff9d" />
        <LabelGroup label="SERVER HQ" badge={serverCount > 0 ? `C2·${serverCount}` : 'C2'} badgeColor="#00ff9d" />
      </LegendItem>

      {/* CLIENT NODE */}
      <LegendItem borderRight>
        <SonarDot color="#00f3ff" delay="0.5s" duration="2s" />
        <LabelGroup label="CLIENT NODE" badge={clientCount > 0 ? `EXT·${clientCount}` : 'EXT'} badgeColor="#00f3ff" />
      </LegendItem>

      {/* VN ISLANDS */}
      <LegendItem borderRight>
        <DiamondMarker />
        <LabelGroup label="VN ISLANDS" badge="GEO·VN" badgeColor="#00ff9d" />
      </LegendItem>

      {/* SATELLITES */}
      <LegendItem borderRight>
        <SatelliteMarker />
        <LabelGroup label="SATELLITES" badge="SAT·8" badgeColor="#ffe600" />
      </LegendItem>

      {/* LASER ARC */}
      <LegendItem>
        <LaserBeam />
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

function SonarDot({ color, delay = '0s', duration = '2.2s' }) {
  return (
    <div style={{ position:'relative', width:'16px', height:'16px', display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0 }}>
      <span style={{
        position:'absolute', width:'12px', height:'12px', borderRadius:'50%',
        border: `1.2px solid ${color}`,
        animation: `hudSonarWave ${duration} cubic-bezier(0,0.2,0.8,1) infinite ${delay}`,
        pointerEvents:'none',
      }} />
      <span style={{
        position:'relative', width:'6px', height:'6px', borderRadius:'50%',
        background: `radial-gradient(circle, #ffffff 20%, ${color} 100%)`,
        boxShadow: `0 0 6px ${color}, 0 0 12px ${color}`,
        display:'inline-block',
      }} />
    </div>
  );
}

function DiamondMarker() {
  return (
    <div style={{ position:'relative', width:'16px', height:'16px', display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0 }}>
      <span style={{
        width:'8px', height:'8px',
        background: 'rgba(0,255,157,0.3)',
        border: '1.2px solid #00ff9d',
        display:'inline-block',
        animation: 'hudDiamondPulse 2.4s ease-in-out infinite',
      }} />
    </div>
  );
}

function SatelliteMarker() {

  return (
    <div style={{ width:'14px', height:'14px', display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0 }}>
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
        {/* Central satellite body */}
        <rect x="5" y="5" width="4" height="4" fill="#ffe600" stroke="#fff" strokeWidth="0.5" />
        {/* Solar panels */}
        <rect x="1" y="5.5" width="3" height="3" fill="#00f3ff" opacity="0.9" />
        <rect x="10" y="5.5" width="3" height="3" fill="#00f3ff" opacity="0.9" />
        {/* Antenna */}
        <line x1="7" y1="5" x2="7" y2="2" stroke="#ffe600" strokeWidth="1" />
        <circle cx="7" cy="2" r="1" fill="#ffe600" />
      </svg>
    </div>
  );
}

function LaserBeam() {

  return (
    <div style={{ width:'26px', height:'14px', display:'flex', alignItems:'center', flexShrink:0 }}>
      <svg width="26" height="10" viewBox="0 0 26 10" fill="none" style={{ overflow:'visible' }}>
        <line x1="1" y1="5" x2="20" y2="5"
          stroke="#00f3ff" strokeWidth="1.6" strokeDasharray="4 3" strokeLinecap="round"
          style={{ animation:'hudLaserFlow 1.0s linear infinite', filter:'drop-shadow(0 0 3px #00f3ff)' }}
        />
        <line x1="1" y1="5" x2="20" y2="5"
          stroke="#ffffff" strokeWidth="0.6" strokeDasharray="4 3" strokeLinecap="round"
          style={{ animation:'hudLaserFlow 1.0s linear infinite' }}
        />
        <polygon points="20,2.5 26,5 20,7.5" fill="#00f3ff"
          style={{ filter:'drop-shadow(0 0 2px #00f3ff)' }}
        />
      </svg>
    </div>
  );
}

function LabelGroup({ label, badge, badgeColor }) {
  const isGreen = badgeColor === '#00ff9d';
  const bg = isGreen ? 'rgba(0,255,157,0.1)' : 'rgba(0,243,255,0.1)';
  const bd = isGreen ? 'rgba(0,255,157,0.3)' : 'rgba(0,243,255,0.3)';
  return (
    <div style={{ display:'flex', alignItems:'baseline', gap:'3px', whiteSpace:'nowrap' }}>
      <span style={{ fontSize:'0.65rem', fontWeight:700, color:'#fff', letterSpacing:'0.6px', fontFamily:"'Share Tech Mono',monospace" }}>
        {label}
      </span>
      <span style={{
        fontSize:'0.52rem', color: badgeColor,
        background: bg, border: `1px solid ${bd}`,
        padding:'0 2px', borderRadius:'2px', lineHeight:'1.3',
        fontFamily:"'Share Tech Mono',monospace", letterSpacing:'0.3px',
      }}>
        [{badge}]
      </span>
    </div>
  );
}

export default GlobeHudLegend;
