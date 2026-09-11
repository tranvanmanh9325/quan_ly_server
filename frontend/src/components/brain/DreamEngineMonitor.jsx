import React, { useState } from 'react';
import {
  SciFiDreamWaveIcon,
  SciFiMorningEpiphanyIcon,
  SciFiCheckShieldIcon,
} from './BrainSciFiIcons';
import { SciFiChronoSpinnerIcon } from '../SciFiIcons';

/**
 * DreamEngineMonitor - Subconscious Dream Engine & Synaptic Homeostasis
 * Tracks Slow-Wave Sleep (SWS - Synaptic Downscaling) and REM Sleep (Abstract Synthesis).
 * Displays Morning Epiphany Briefing prepared for Anh Mạnh.
 */
export default function DreamEngineMonitor({
  dream = {},
  onConsolidate,
  loading = false,
}) {
  const [isDreaming, setIsDreaming] = useState(false);
  const [consolidationResult, setConsolidationResult] = useState(null);

  const sleepStage = dream.sleep_stage || 'AWAKE';
  const isSleeping = dream.is_sleeping || false;
  const lastSws = dream.last_sws_time || 'Chưa ghi nhận';
  const lastRem = dream.last_rem_time || 'Chưa ghi nhận';
  const pendingEpiphany = dream.pending_morning_epiphany;
  const totalEpiphanies = dream.total_epiphanies || 0;

  const handleSimulateDream = async () => {
    if (!onConsolidate || isDreaming || loading) return;
    setIsDreaming(true);
    setConsolidationResult(null);
    try {
      const resp = await onConsolidate();
      if (resp) {
        setConsolidationResult(resp);
      }
    } catch (err) {
      console.error('Lỗi mô phỏng giấc mơ:', err);
    } finally {
      setIsDreaming(false);
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
          <SciFiDreamWaveIcon size={18} color="#bd00ff" />
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
              ĐỘNG CƠ GIẤC MƠ TIỀM THỨC (DREAM ENGINE)
            </h3>
            <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
              Chu Kỳ Ngủ SWS / REM • Củng Cố Ký Ức & Cân Bằng Synapse (Homeostasis)
            </span>
          </div>
        </div>

        <div
          style={{
            fontSize: '0.68rem',
            padding: '2px 8px',
            borderRadius: '2px',
            background: isSleeping ? 'rgba(189, 0, 255, 0.2)' : 'rgba(0, 255, 157, 0.12)',
            border: `1px solid ${isSleeping ? '#bd00ff' : '#00ff9d'}`,
            color: isSleeping ? '#bd00ff' : '#00ff9d',
            fontFamily: 'Share Tech Mono',
            fontWeight: 700,
          }}
        >
          {sleepStage}
        </div>
      </div>

      {/* Sleep Stages & Times */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '10px',
        }}
      >
        <div
          style={{
            background: 'rgba(5, 18, 36, 0.6)',
            border: '1px solid rgba(0, 243, 255, 0.15)',
            padding: '8px 12px',
            borderRadius: '4px',
          }}
        >
          <div style={{ fontSize: '0.68rem', color: 'rgba(224, 242, 254, 0.6)' }}>
            Chu Kỳ Sóng Chậm (SWS):
          </div>
          <div style={{ fontSize: '0.82rem', fontWeight: 600, color: '#e0f2fe' }}>
            {lastSws}
          </div>
          <div style={{ fontSize: '0.62rem', color: '#00ff9d' }}>
            Thanh lọc & Tối ưu năng lượng
          </div>
        </div>

        <div
          style={{
            background: 'rgba(5, 18, 36, 0.6)',
            border: '1px solid rgba(0, 243, 255, 0.15)',
            padding: '8px 12px',
            borderRadius: '4px',
          }}
        >
          <div style={{ fontSize: '0.68rem', color: 'rgba(224, 242, 254, 0.6)' }}>
            Chu Kỳ Giấc Mơ REM:
          </div>
          <div style={{ fontSize: '0.82rem', fontWeight: 600, color: '#e0f2fe' }}>
            {lastRem}
          </div>
          <div style={{ fontSize: '0.62rem', color: '#bd00ff' }}>
            Tổng hợp tri thức trừu tượng
          </div>
        </div>

        <div
          style={{
            background: 'rgba(5, 18, 36, 0.6)',
            border: '1px solid rgba(0, 243, 255, 0.15)',
            padding: '8px 12px',
            borderRadius: '4px',
          }}
        >
          <div style={{ fontSize: '0.68rem', color: 'rgba(224, 242, 254, 0.6)' }}>
            Bản Tin Giác Ngộ:
          </div>
          <div
            style={{
              fontSize: '0.82rem',
              fontWeight: 700,
              color: 'var(--accent-cyan)',
              fontFamily: 'Share Tech Mono',
            }}
          >
            {totalEpiphanies} lần đúc kết
          </div>
          <div style={{ fontSize: '0.62rem', color: 'rgba(224, 242, 254, 0.5)' }}>
            Lưu giữ trong vỏ não
          </div>
        </div>
      </div>

      {/* Morning Epiphany Box */}
      <div
        style={{
          background: 'rgba(5, 18, 36, 0.6)',
          borderLeft: '3px solid var(--accent-yellow)',
          padding: '10px 14px',
          borderRadius: '2px',
          display: 'flex',
          flexDirection: 'column',
          gap: '6px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <SciFiMorningEpiphanyIcon size={16} color="var(--accent-yellow)" />
          <span
            style={{
              fontSize: '0.74rem',
              fontWeight: 700,
              color: 'var(--accent-yellow)',
              fontFamily: 'Share Tech Mono',
              letterSpacing: '1px',
            }}
          >
            BẢN TIN GIÁC NGỘ BUỔI SÁNG (MORNING EPIPHANY BRIEFING)
          </span>
        </div>

        <div style={{ fontSize: '0.82rem', color: '#ffffff', lineHeight: '1.4' }}>
          {pendingEpiphany ? (
            pendingEpiphany
          ) : (
            <span style={{ color: 'rgba(224, 242, 254, 0.65)', fontStyle: 'italic' }}>
              "Hệ thống đang tích lũy trải nghiệm ban ngày. Khi bước vào chu kỳ ngủ đêm, Tiểu Bảo Bảo sẽ tổng hợp toàn bộ sự kiện và tự chuẩn bị bản đúc kết gửi riêng cho anh Mạnh vào sáng sớm."
            </span>
          )}
        </div>
      </div>

      {/* Dream Action Button */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px' }}>
        <button
          type="button"
          onClick={handleSimulateDream}
          disabled={isDreaming || loading}
          style={{
            padding: '8px 16px',
            background: 'rgba(189, 0, 255, 0.15)',
            border: '1px solid #bd00ff',
            color: '#bd00ff',
            borderRadius: '2px',
            cursor: isDreaming ? 'not-allowed' : 'pointer',
            fontSize: '0.8rem',
            fontWeight: 700,
            fontFamily: 'Share Tech Mono',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            transition: 'all 0.2s ease',
          }}
        >
          {isDreaming ? (
            <SciFiChronoSpinnerIcon size={14} color="#bd00ff" />
          ) : (
            <SciFiDreamWaveIcon size={14} color="#bd00ff" />
          )}
          <span>{isDreaming ? 'ĐANG CỦNG CỐ KÝ ỨC...' : 'MÔ PHỎNG GIẤC MƠ ĐÊM (CONSOLIDATE)'}</span>
        </button>

        {consolidationResult && (
          <div
            style={{
              fontSize: '0.72rem',
              color: '#00ff9d',
              fontFamily: 'Share Tech Mono',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <SciFiCheckShieldIcon size={12} color="#00ff9d" />
            <span>Đã chuyển {consolidationResult.consolidated_memories_count} ký ức ngắn hạn vào Vỏ Não Ảo!</span>
          </div>
        )}
      </div>
    </div>
  );
}
