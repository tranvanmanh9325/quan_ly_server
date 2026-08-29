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
      flexWrap: 'wrap',
      minHeight: '36px',
      background: 'linear-gradient(180deg, rgba(6,18,33,0.82) 0%, rgba(2,8,16,0.92) 100%)',
      backdropFilter: 'blur(10px)',
      WebkitBackdropFilter: 'blur(10px)',
      border: '1px solid rgba(0,243,255,0.22)',
      clipPath: 'polygon(8px 0, 100% 0, 100% calc(100% - 8px), calc(100% - 8px) 100%, 0 100%, 0 8px)',
      boxShadow: 'inset 0 1px 0 rgba(0,243,255,0.35), inset 0 0 14px rgba(0,243,255,0.04), 0 6px 20px rgba(0,0,0,0.65)',
      fontFamily: "'Share Tech Mono', monospace",
      userSelect: 'none',
      flexShrink: 0,
      overflow: 'hidden',
    }}>
      <style>{STYLES}</style>

      {/* Corner brackets */}
      <div style={{ position:'absolute', top:0, left:0, width:'7px', height:'7px', borderTop:'1.5px solid #00f3ff', borderLeft:'1.5px solid #00f3ff', pointerEvents:'none' }} />
      <div style={{ position:'absolute', bottom:0, right:0, width:'7px', height:'7px', borderBottom:'1.5px solid #00f3ff', borderRight:'1.5px solid #00f3ff', pointerEvents:'none' }} />

      {/* Header badge */}
      <div style={{ padding:'8px 12px', borderRight:'1px solid rgba(0,243,255,0.15)', display:'flex', alignItems:'center', gap:'6px', flexShrink:0 }}>
        <div style={{
          width:'6px', height:'6px', borderRadius:'50%',
          background: isLive ? '#00ff9d' : '#ff0055',
          boxShadow: isLive ? '0 0 6px #00ff9d' : '0 0 6px #ff0055',
          animation: isLive ? 'hudStatusBlink 1.8s ease-in-out infinite' : 'none',
          flexShrink:0,
        }} />
        <span style={{ fontSize:'0.58rem', letterSpacing:'1.5px', color:'rgba(0,243,255,0.55)', fontWeight:'bold' }}>
          HUD // TELEMETRY
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

      {/* LASER ARC */}
      <LegendItem>
        <LaserBeam />
        <LabelGroup label="LASER ARC" badge="STREAM" badgeColor="#00f3ff" />
      </LegendItem>
    </div>
  );
});

function LegendItem({ children, borderRight }) {
  return (
    <div style={{
      padding: '6px 14px',
      borderRight: borderRight ? '1px solid rgba(0,243,255,0.12)' : 'none',
      display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0,
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

function LaserBeam() {
  return (
    <div style={{ width:'32px', height:'16px', display:'flex', alignItems:'center', flexShrink:0 }}>
      <svg width="32" height="12" viewBox="0 0 32 12" fill="none" style={{ overflow:'visible' }}>
        <line x1="1" y1="6" x2="25" y2="6"
          stroke="#00f3ff" strokeWidth="1.8" strokeDasharray="4 3" strokeLinecap="round"
          style={{ animation:'hudLaserFlow 1.0s linear infinite', filter:'drop-shadow(0 0 3px #00f3ff)' }}
        />
        <line x1="1" y1="6" x2="25" y2="6"
          stroke="#ffffff" strokeWidth="0.7" strokeDasharray="4 3" strokeLinecap="round"
          style={{ animation:'hudLaserFlow 1.0s linear infinite' }}
        />
        <polygon points="25,3.2 32,6 25,8.8" fill="#00f3ff"
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
    <div style={{ display:'flex', alignItems:'baseline', gap:'4px' }}>
      <span style={{ fontSize:'0.68rem', fontWeight:700, color:'#fff', letterSpacing:'0.8px', fontFamily:"'Share Tech Mono',monospace" }}>
        {label}
      </span>
      <span style={{
        fontSize:'0.55rem', color: badgeColor,
        background: bg, border: `1px solid ${bd}`,
        padding:'0 3px', borderRadius:'2px', lineHeight:'1.3',
        fontFamily:"'Share Tech Mono',monospace", letterSpacing:'0.5px',
      }}>
        [{badge}]
      </span>
    </div>
  );
}

export default GlobeHudLegend;
