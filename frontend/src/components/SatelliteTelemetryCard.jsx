import React from 'react';
import { SciFiCloseIcon, SciFiTargetLockIcon } from './SciFiIcons';

/**
 * SatelliteTelemetryCard - Cyberpunk / NORAD Mission Control HUD Card
 * Renders high-tech telemetry panel when a satellite is clicked on the 3D globe.
 */
export default function SatelliteTelemetryCard({ satellite, onClose, onTrackCamera }) {
  if (!satellite) return null;

  const color = satellite.color || '#00ff9d';
  const isGeo = satellite.type === 'GEO';

  return (
    <div style={{
      position: 'absolute',
      top: '12px',
      right: '12px',
      width: '285px',
      background: 'linear-gradient(135deg, rgba(2,12,24,0.96) 0%, rgba(0,22,42,0.94) 100%)',
      border: `1px solid ${color}`,
      borderLeft: `3px solid ${color}`,
      borderRadius: '4px',
      padding: '10px 12px',
      boxShadow: `0 0 16px rgba(0,243,255,0.2), inset 0 0 10px rgba(0,0,0,0.8)`,
      fontFamily: "'Share Tech Mono', monospace",
      color: '#fff',
      zIndex: 20,
      backdropFilter: 'blur(8px)',
      userSelect: 'none',
      clipPath: 'polygon(8px 0, 100% 0, 100% calc(100% - 8px), calc(100% - 8px) 100%, 0 100%, 0 8px)',
    }}>
      {/* Top title bar */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        borderBottom: '1px solid rgba(0,243,255,0.18)',
        paddingBottom: '6px',
        marginBottom: '8px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            background: color,
            boxShadow: `0 0 6px ${color}`,
          }} />
          <span style={{ fontSize: '0.78rem', fontWeight: 'bold', color, letterSpacing: '0.8px' }}>
            {satellite.name}
          </span>
        </div>
        <button
          onClick={onClose}
          style={{
            background: 'rgba(255,255,255,0.06)',
            border: '1px solid rgba(255,255,255,0.2)',
            color: '#fff',
            cursor: 'pointer',
            padding: '2px 4px',
            borderRadius: '2px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          title="Close telemetry card"
        >
          <SciFiCloseIcon size={11} color="rgba(255,255,255,0.8)" />
        </button>
      </div>

      {/* Code name & mission badge */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        background: 'rgba(0,243,255,0.06)',
        padding: '3px 6px',
        borderRadius: '2px',
        marginBottom: '8px',
        fontSize: '0.66rem',
      }}>
        <span style={{ color: 'rgba(255,255,255,0.7)' }}>{satellite.codeName || satellite.name}</span>
        <span style={{
          background: color,
          color: '#020d1a',
          fontWeight: 'bold',
          padding: '0 4px',
          borderRadius: '2px',
          fontSize: '0.58rem',
        }}>
          {satellite.type}
        </span>
      </div>

      {/* Telemetry data rows */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '0.68rem', marginBottom: '8px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'rgba(255,255,255,0.5)' }}>NORAD CAT ID:</span>
          <span style={{ color: '#fff', fontWeight: 'bold' }}>#{satellite.noradId}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'rgba(255,255,255,0.5)' }}>OPERATOR:</span>
          <span style={{ color: '#00f3ff' }}>{satellite.country}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'rgba(255,255,255,0.5)' }}>ORBIT REGIME:</span>
          <span style={{ color: '#fff' }}>{satellite.regime}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'rgba(255,255,255,0.5)' }}>ALTITUDE:</span>
          <span style={{ color: color, fontWeight: 'bold' }}>{satellite.altitudeKm?.toLocaleString()} km</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'rgba(255,255,255,0.5)' }}>ORBIT VELOCITY:</span>
          <span style={{ color: '#fff' }}>{satellite.velocity}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'rgba(255,255,255,0.5)' }}>INCLINATION:</span>
          <span style={{ color: '#fff' }}>{satellite.inclination}°</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span style={{ color: 'rgba(255,255,255,0.5)' }}>FREQUENCY:</span>
          <span style={{ color: '#ffb700' }}>{satellite.frequency}</span>
        </div>
        {satellite.lat !== undefined && satellite.lng !== undefined && (
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: 'rgba(255,255,255,0.5)' }}>SUB-POINT COORD:</span>
            <span style={{ color: '#00f3ff' }}>
              {satellite.lat.toFixed(2)}°N, {satellite.lng.toFixed(2)}°E
            </span>
          </div>
        )}
        {satellite.groundStation && (
          <div style={{ display: 'flex', justifyContent: 'space-between', borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: '4px', marginTop: '2px' }}>
            <span style={{ color: 'rgba(255,255,255,0.5)' }}>C2 DOWNLINK:</span>
            <span style={{ color: '#00ff9d', fontWeight: 'bold' }}>● LOCKED (HQ)</span>
          </div>
        )}
      </div>

      {/* Action button */}
      <button
        onClick={() => onTrackCamera?.(satellite)}
        style={{
          width: '100%',
          background: 'linear-gradient(90deg, rgba(0,255,157,0.15) 0%, rgba(0,243,255,0.15) 100%)',
          border: `1px solid ${color}`,
          color: '#fff',
          padding: '5px 8px',
          fontSize: '0.68rem',
          fontWeight: 'bold',
          letterSpacing: '0.8px',
          borderRadius: '2px',
          cursor: 'pointer',
          fontFamily: "'Share Tech Mono', monospace",
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '7px',
        }}
      >
        <SciFiTargetLockIcon size={14} color={color} />
        <span>TRACK SATELLITE CAMERA</span>
      </button>
    </div>
  );
}

