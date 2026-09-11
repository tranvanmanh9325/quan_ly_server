import React from 'react';
import { SciFiFreeEnergySpiralIcon, SciFiThresholdArrowIcon } from './BrainSciFiIcons';

/**
 * ActiveInferencePanel - Karl Friston's Variational Free Energy Principle (FEP)
 * Displays current Free Energy F (Surprise), System 1 vs System 2 thinking mode,
 * and bayesian beliefs distribution over server and environment states.
 */
export default function ActiveInferencePanel({ activeInference = {} }) {
  const freeEnergy = typeof activeInference.free_energy === 'number'
    ? activeInference.free_energy
    : 0.285;
  const thinkingMode = activeInference.thinking_mode || 'System 1 (Trực giác phản xạ)';
  const beliefs = activeInference.beliefs || {
    system_stable: 0.95,
    user_engaged: 0.88,
    low_latency: 0.92,
    anomaly_detected: 0.05,
  };

  const isSystem2 = freeEnergy >= 0.60;
  const fePercent = Math.min(100, Math.max(0, (freeEnergy / 1.5) * 100));

  // Friendly Vietnamese names for beliefs
  const getBeliefLabel = (key) => {
    switch (key) {
      case 'system_stable': return 'Máy chủ ổn định';
      case 'user_engaged': return 'Anh Mạnh đang tương tác';
      case 'low_latency': return 'Độ trễ thấp / Mạng mượt';
      case 'anomaly_detected': return 'Phát hiện bất thường';
      default: return key.replace(/_/g, ' ').toUpperCase();
    }
  };

  return (
    <div
      style={{
        background: 'rgba(2, 12, 24, 0.75)',
        border: '1px solid rgba(0, 243, 255, 0.25)',
        borderRadius: '4px',
        padding: '16px',
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        display: 'flex',
        flexDirection: 'column',
        gap: '14px',
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <SciFiFreeEnergySpiralIcon size={18} color="var(--accent-cyan)" />
          <div>
            <h3
              style={{
                margin: 0,
                fontSize: '0.9rem',
                color: 'var(--accent-cyan)',
                fontFamily: 'Share Tech Mono',
                letterSpacing: '1.5px',
              }}
            >
              SUY LUẬN CHỦ ĐỘNG & NĂNG LƯỢNG TỰ DO (FEP)
            </h3>
            <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
              Karl Friston Active Inference • Variational Free Energy F (Surprise)
            </span>
          </div>
        </div>

        <div
          style={{
            fontSize: '0.68rem',
            padding: '2px 8px',
            borderRadius: '2px',
            background: isSystem2 ? 'rgba(255, 0, 85, 0.15)' : 'rgba(0, 255, 157, 0.15)',
            border: `1px solid ${isSystem2 ? 'var(--accent-pink)' : '#00ff9d'}`,
            color: isSystem2 ? 'var(--accent-pink)' : '#00ff9d',
            fontFamily: 'Share Tech Mono',
            fontWeight: 700,
          }}
        >
          {isSystem2 ? 'SYSTEM 2 (ANALYTICAL)' : 'SYSTEM 1 (INTUITIVE)'}
        </div>
      </div>

      {/* Free Energy Meter */}
      <div
        style={{
          background: 'rgba(5, 18, 36, 0.6)',
          border: '1px solid rgba(0, 243, 255, 0.15)',
          borderRadius: '4px',
          padding: '12px',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '0.78rem', color: 'rgba(224, 242, 254, 0.8)' }}>
            Mức Độ Bất Ngờ / Năng Lượng Tự Do (Free Energy F):
          </span>
          <span
            style={{
              fontSize: '1.2rem',
              fontWeight: 700,
              fontFamily: 'Share Tech Mono',
              color: isSystem2 ? '#ff3366' : '#00f3ff',
            }}
          >
            F = {freeEnergy.toFixed(3)}
          </span>
        </div>

        {/* Meter bar */}
        <div
          style={{
            width: '100%',
            height: '10px',
            background: 'rgba(0, 0, 0, 0.6)',
            borderRadius: '4px',
            overflow: 'hidden',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            position: 'relative',
          }}
        >
          <div
            style={{
              width: `${fePercent}%`,
              height: '100%',
              background: isSystem2
                ? 'linear-gradient(90deg, #ff9900, #ff0055)'
                : 'linear-gradient(90deg, #00f3ff, #00ff9d)',
              boxShadow: isSystem2 ? '0 0 10px #ff0055' : '0 0 10px #00ff9d',
              transition: 'width 0.4s ease',
            }}
          />
          {/* System 1 / 2 Threshold Marker at F = 0.60 (40% of 1.5) */}
          <div
            style={{
              position: 'absolute',
              top: 0,
              bottom: 0,
              left: '40%',
              width: '2px',
              background: '#ffffff',
              boxShadow: '0 0 4px #ffffff',
            }}
            title="Ngưỡng kích hoạt System 2 (F = 0.60)"
          />
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.68rem', color: 'rgba(224, 242, 254, 0.5)' }}>
          <span>0.00 (Hoàn toàn dự đoán được)</span>
          <span style={{ color: 'var(--accent-yellow)', display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
            <SciFiThresholdArrowIcon size={10} color="var(--accent-yellow)" />
            <span>Ngưỡng F=0.60</span>
          </span>
          <span>1.50+ (Bất ngờ cực đại)</span>
        </div>

        {/* Current mode explanation */}
        <div
          style={{
            fontSize: '0.74rem',
            color: '#e0f2fe',
            background: 'rgba(0, 243, 255, 0.05)',
            borderLeft: `3px solid ${isSystem2 ? '#ff0055' : '#00ff9d'}`,
            padding: '6px 10px',
            marginTop: '4px',
          }}
        >
          <strong>{thinkingMode}:</strong>{' '}
          {isSystem2
            ? 'Độ bất ngờ cao vượt ngưỡng. Não bộ tạm dừng phản xạ nhanh để kích hoạt suy luận nhiều bước, tự phản biện và đối chiếu vỏ não.'
            : 'Môi trường ổn định, độ bất ngờ thấp. Não bộ vận hành bằng trực giác phản xạ siêu tốc, tiết kiệm năng lượng nhận thức.'}
        </div>
      </div>

      {/* Bayesian Beliefs Distribution */}
      <div>
        <div
          style={{
            fontSize: '0.74rem',
            fontWeight: 600,
            color: 'var(--accent-cyan)',
            fontFamily: 'Share Tech Mono',
            letterSpacing: '1px',
            marginBottom: '8px',
          }}
        >
          PHÂN BỐ NIỀM TIN BAYESIAN (BELIEFS DISTRIBUTION):
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {Object.entries(beliefs).map(([key, val]) => {
            const numVal = typeof val === 'number' ? Math.max(0, Math.min(1, val)) : 0.5;
            const pct = Math.round(numVal * 100);
            return (
              <div
                key={key}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  background: 'rgba(0,0,0,0.3)',
                  padding: '4px 8px',
                  borderRadius: '2px',
                }}
              >
                <div
                  style={{
                    width: '180px',
                    fontSize: '0.72rem',
                    color: '#e0f2fe',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                  title={key}
                >
                  {getBeliefLabel(key)}
                </div>

                <div
                  style={{
                    flex: 1,
                    height: '6px',
                    background: 'rgba(255, 255, 255, 0.08)',
                    borderRadius: '2px',
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      width: `${pct}%`,
                      height: '100%',
                      background: 'var(--accent-cyan)',
                      boxShadow: '0 0 6px var(--accent-cyan)',
                      transition: 'width 0.3s ease',
                    }}
                  />
                </div>

                <div
                  style={{
                    width: '45px',
                    textAlign: 'right',
                    fontSize: '0.75rem',
                    fontFamily: 'Share Tech Mono',
                    color: 'var(--accent-cyan)',
                  }}
                >
                  {(numVal * 100).toFixed(1)}%
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
