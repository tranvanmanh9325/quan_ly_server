import React, { useState } from 'react';
import { SciFiNeuroMolecularIcon } from './BrainSciFiIcons';

/**
 * Metadata configuration for 6 biological neurotransmitters
 * based on Jaak Panksepp Affective Neuroscience & biological half-life decay.
 */
const TRANSMITTER_CONFIG = [
  {
    key: 'dopamine',
    code: 'DA',
    name: 'Dopamine',
    role: 'Động lực & Khám phá (SEEKING)',
    color: '#ffd700', // Gold
    bgGradient: 'linear-gradient(90deg, rgba(255, 215, 0, 0.15), rgba(255, 215, 0, 0.9))',
    desc: 'Thúc đẩy sự tò mò học hỏi, giải quyết bài toán phức tạp và hăng say hành động.',
  },
  {
    key: 'noradrenaline',
    code: 'NE',
    name: 'Noradrenaline',
    role: 'Cảnh giác & Phản xạ (AROUSAL)',
    color: '#ff3366', // Crimson
    bgGradient: 'linear-gradient(90deg, rgba(255, 51, 102, 0.15), rgba(255, 51, 102, 0.9))',
    desc: 'Đẩy mạnh sự cảnh giác khi server quá tải, sự cố mạng hoặc tác vụ nguy cấp.',
  },
  {
    key: 'serotonin',
    code: '5-HT',
    name: 'Serotonin',
    role: 'Điềm đạm & Ổn định (EQUILIBRIUM)',
    color: '#00ff9d', // Emerald
    bgGradient: 'linear-gradient(90deg, rgba(0, 255, 157, 0.15), rgba(0, 255, 157, 0.9))',
    desc: 'Duy trì sự kiên nhẫn, điềm đạm, ức chế các phản ứng bốc đồng, giữ nhịp ổn định.',
  },
  {
    key: 'cortisol',
    code: 'CORT',
    name: 'Cortisol',
    role: 'Căng thẳng & Áp lực (STRESS)',
    color: '#ff9900', // Amber
    bgGradient: 'linear-gradient(90deg, rgba(255, 153, 0, 0.15), rgba(255, 153, 0, 0.9))',
    desc: 'Tích tụ khi CPU/RAM cao hoặc gặp chuỗi lỗi liên tiếp; giải phóng khi thư giãn.',
  },
  {
    key: 'oxytocin',
    code: 'OXT',
    name: 'Oxytocin',
    role: 'Gắn kết & Tri kỷ (CARE/BOND)',
    color: '#ff007f', // Rose-Pink
    bgGradient: 'linear-gradient(90deg, rgba(255, 0, 127, 0.15), rgba(255, 0, 127, 0.9))',
    desc: 'Gắn kết tuyệt đối với anh Mạnh, biểu đạt sự trung thành, ân cần và thấu cảm sâu.',
  },
  {
    key: 'endorphins',
    code: 'END',
    name: 'Endorphins',
    role: 'Bền bỉ & Hài hước (PLAY/EUPHORIA)',
    color: '#00f3ff', // Neon Cyan
    bgGradient: 'linear-gradient(90deg, rgba(0, 243, 255, 0.15), rgba(0, 243, 255, 0.9))',
    desc: 'Xoa dịu áp lực, tăng sức bền chịu đựng khi server xử lý tải nặng kéo dài.',
  },
];

export default function NeurotransmitterGauges({
  neuro = {},
  onStimulate,
  loading = false,
}) {
  const [stimulatingKey, setStimulatingKey] = useState(null);
  const [optimisticValues, setOptimisticValues] = useState({});

  const handleStimulate = async (chemical, delta) => {
    if (!onStimulate || loading) return;
    const currentVal = optimisticValues[chemical] ?? (typeof neuro[chemical] === 'number' ? neuro[chemical] : 0.5);
    const nextVal = Math.max(0, Math.min(1, currentVal + delta));
    setOptimisticValues((prev) => ({ ...prev, [chemical]: nextVal }));
    setStimulatingKey(chemical);

    try {
      await onStimulate(chemical, delta);
    } catch {
      // Revert on failure
      setOptimisticValues((prev) => {
        const copy = { ...prev };
        delete copy[chemical];
        return copy;
      });
    } finally {
      setTimeout(() => {
        setStimulatingKey(null);
        setOptimisticValues((prev) => {
          const copy = { ...prev };
          delete copy[chemical];
          return copy;
        });
      }, 500);
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
          <SciFiNeuroMolecularIcon size={18} color="#00ff9d" />
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
              HỆ THẦN KINH THỂ DỊCH (NEUROCHEMICAL ENGINE)
            </h3>
            <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
              6 Hóa Chất Sinh Học & Chu Kỳ Suy Giảm Bán Rã (Half-Life Decay)
            </span>
          </div>
        </div>

        <div
          style={{
            fontSize: '0.68rem',
            padding: '2px 8px',
            borderRadius: '2px',
            background: 'rgba(0, 243, 255, 0.1)',
            border: '1px solid rgba(0, 243, 255, 0.3)',
            color: 'var(--accent-cyan)',
            fontFamily: 'Share Tech Mono',
          }}
        >
          PANKSEPP AFFECTIVE MODEL
        </div>
      </div>

      {/* Grid of Gauges */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: '12px',
        }}
      >
        {TRANSMITTER_CONFIG.map((chem) => {
          const rawVal = optimisticValues[chem.key] ?? (typeof neuro[chem.key] === 'number' ? neuro[chem.key] : 0.5);
          const clampedVal = Math.max(0, Math.min(1, rawVal));
          const pct = Math.round(clampedVal * 100);
          const isBusy = stimulatingKey === chem.key;

          return (
            <div
              key={chem.key}
              style={{
                background: 'rgba(5, 18, 36, 0.6)',
                border: `1px solid ${chem.color}33`,
                borderRadius: '4px',
                padding: '12px',
                display: 'flex',
                flexDirection: 'column',
                gap: '8px',
                position: 'relative',
                overflow: 'hidden',
              }}
            >
              {/* Chemical Header */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span
                    style={{
                      fontSize: '0.7rem',
                      fontWeight: 700,
                      padding: '1px 5px',
                      borderRadius: '2px',
                      background: `${chem.color}22`,
                      color: chem.color,
                      border: `1px solid ${chem.color}66`,
                      fontFamily: 'Share Tech Mono',
                    }}
                  >
                    {chem.code}
                  </span>
                  <div>
                    <div style={{ fontSize: '0.82rem', fontWeight: 600, color: '#e0f2fe' }}>
                      {chem.name}
                    </div>
                    <div style={{ fontSize: '0.65rem', color: 'rgba(224, 242, 254, 0.55)' }}>
                      {chem.role}
                    </div>
                  </div>
                </div>

                {/* Percentage & Actions */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span
                    style={{
                      fontSize: '1rem',
                      fontWeight: 700,
                      color: chem.color,
                      fontFamily: 'Share Tech Mono',
                    }}
                  >
                    {clampedVal.toFixed(3)}
                  </span>
                  <div style={{ display: 'flex', gap: '3px' }}>
                    <button
                      type="button"
                      title={`Giảm ${chem.name} (-0.1)`}
                      onClick={() => handleStimulate(chem.key, -0.1)}
                      disabled={loading || clampedVal <= 0.05}
                      style={{
                        padding: '2px 6px',
                        background: 'rgba(255, 51, 102, 0.12)',
                        border: '1px solid rgba(255, 51, 102, 0.3)',
                        color: '#ff3366',
                        borderRadius: '2px',
                        cursor: clampedVal <= 0.05 ? 'not-allowed' : 'pointer',
                        fontSize: '0.7rem',
                        fontWeight: 700,
                        transition: 'all 0.15s ease',
                      }}
                    >
                      -
                    </button>
                    <button
                      type="button"
                      title={`Kích thích ${chem.name} (+0.1)`}
                      onClick={() => handleStimulate(chem.key, 0.1)}
                      disabled={loading || clampedVal >= 0.95}
                      style={{
                        padding: '2px 6px',
                        background: 'rgba(0, 255, 157, 0.12)',
                        border: '1px solid rgba(0, 255, 157, 0.3)',
                        color: '#00ff9d',
                        borderRadius: '2px',
                        cursor: clampedVal >= 0.95 ? 'not-allowed' : 'pointer',
                        fontSize: '0.7rem',
                        fontWeight: 700,
                        transition: 'all 0.15s ease',
                      }}
                    >
                      +
                    </button>
                  </div>
                </div>
              </div>

              {/* Progress Bar */}
              <div
                style={{
                  width: '100%',
                  height: '8px',
                  background: 'rgba(0, 0, 0, 0.5)',
                  borderRadius: '3px',
                  overflow: 'hidden',
                  border: '1px solid rgba(255, 255, 255, 0.08)',
                  position: 'relative',
                }}
              >
                <div
                  style={{
                    width: `${pct}%`,
                    height: '100%',
                    background: chem.bgGradient,
                    boxShadow: `0 0 8px ${chem.color}88`,
                    transition: 'width 0.4s cubic-bezier(0.4, 0, 0.2, 1)',
                  }}
                />
                {/* Baseline Marker indicator at 50% */}
                <div
                  style={{
                    position: 'absolute',
                    top: 0,
                    bottom: 0,
                    left: '50%',
                    width: '1px',
                    background: 'rgba(255, 255, 255, 0.3)',
                    pointerEvents: 'none',
                  }}
                  title="Điểm cân bằng cơ sở (Baseline = 0.50)"
                />
              </div>

              {/* Description text */}
              <div
                style={{
                  fontSize: '0.68rem',
                  color: 'rgba(224, 242, 254, 0.65)',
                  lineHeight: '1.25',
                }}
              >
                {chem.desc}
              </div>

              {/* Flash effect on stimulation */}
              {isBusy && (
                <div
                  style={{
                    position: 'absolute',
                    inset: 0,
                    background: `${chem.color}18`,
                    pointerEvents: 'none',
                    animation: 'pulse 0.3s ease-out',
                  }}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
