import React, { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import { useTranslation } from '../i18n/index.jsx';
import {
  SciFiBrainCoreIcon,
  SciFiSynapseIcon,
  SciFiPulseBadge,
  SciFiChronoSpinnerIcon,
} from '../components/SciFiIcons';

import RussellCircumplexRadar from '../components/brain/RussellCircumplexRadar';
import NeurotransmitterGauges from '../components/brain/NeurotransmitterGauges';
import ActiveInferencePanel from '../components/brain/ActiveInferencePanel';
import GlobalWorkspaceStream from '../components/brain/GlobalWorkspaceStream';
import VirtualCortexExplorer from '../components/brain/VirtualCortexExplorer';
import DreamEngineMonitor from '../components/brain/DreamEngineMonitor';
import TheoryOfMindCard from '../components/brain/TheoryOfMindCard';
import NeuralNetwork3DFlow from '../components/brain/NeuralNetwork3DFlow';

export default function BrainCorePage() {
  const { t } = useTranslation();
  const [telemetry, setTelemetry] = useState(null);
  const [loading, setLoading] = useState(true);
  const [isPulsing, setIsPulsing] = useState(false);
  const [pulseCounter, setPulseCounter] = useState(0);
  const [lastActionMessage, setLastActionMessage] = useState(null);
  const [error, setError] = useState(null);
  const pollTimerRef = useRef(null);

  // 1. Fetch Brain Telemetry
  const fetchTelemetry = useCallback(async (isSilent = false) => {
    try {
      const resp = await axios.get('/api/ai/brain/telemetry');
      if (resp.data && resp.data.status === 'ONLINE') {
        setTelemetry(resp.data);
        if (!isSilent) setError(null);
      }
    } catch (err) {
      console.error('Lỗi khi lấy dữ liệu não bộ AI:', err);
      if (!isSilent) {
        setError('Không thể kết nối với Hệ thống Não bộ AI (ai-agent-service). Vui lòng kiểm tra dịch vụ.');
      }
    } finally {
      if (!isSilent) setLoading(false);
    }
  }, []);

  // 2. Setup periodic polling every 3.5s
  useEffect(() => {
    let isSubscribed = true;
    const initialLoad = async () => {
      try {
        const resp = await axios.get('/api/ai/brain/telemetry');
        if (isSubscribed && resp.data && resp.data.status === 'ONLINE') {
          setTelemetry(resp.data);
        }
      } catch (err) {
        if (isSubscribed) {
          console.error('Lỗi khi tải dữ liệu não bộ ban đầu:', err);
          setError('Không thể kết nối với Hệ thống Não bộ AI (ai-agent-service).');
        }
      } finally {
        if (isSubscribed) setLoading(false);
      }
    };

    initialLoad();

    pollTimerRef.current = setInterval(() => {
      if (isSubscribed) {
        fetchTelemetry(true);
      }
    }, 3500);

    return () => {
      isSubscribed = false;
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, [fetchTelemetry]);

  // 3. Trigger immediate cognitive pulse
  const handlePulse = async () => {
    if (isPulsing) return;
    setIsPulsing(true);
    setPulseCounter((p) => p + 1);
    setLastActionMessage(null);
    try {
      const resp = await axios.post('/api/ai/brain/pulse', {
        cpu_usage: 25.0,
        ram_usage: 45.0,
      });
      if (resp.data && resp.data.status === 'success') {
        setLastActionMessage(`⚡ Nhịp đập nhận thức thành công! Ý thức: ${resp.data.winning_consciousness?.summary || 'Tâm trí cân bằng'}`);
        await fetchTelemetry(true);
      }
    } catch (err) {
      console.error('Lỗi kích hoạt nhịp đập:', err);
      setLastActionMessage('⚠️ Kích hoạt nhịp đập thất bại.');
    } finally {
      setTimeout(() => setIsPulsing(false), 400);
      setTimeout(() => setLastActionMessage(null), 5000);
    }
  };

  // 4. Stimulate chemical
  const handleStimulate = async (chemical, delta) => {
    try {
      const resp = await axios.post('/api/ai/brain/stimulate', {
        chemical,
        delta,
        reason: 'Điều biến từ Dashboard Não Bộ',
      });
      if (resp.data && resp.data.status === 'success') {
        await fetchTelemetry(true);
      }
    } catch (err) {
      console.error('Lỗi điều biến hóa chất:', err);
      throw err;
    }
  };

  // 5. Dream consolidate
  const handleDreamConsolidate = async () => {
    try {
      const resp = await axios.post('/api/ai/brain/dream-consolidate');
      if (resp.data && resp.data.status === 'success') {
        await fetchTelemetry(true);
        return resp.data;
      }
    } catch (err) {
      console.error('Lỗi mô phỏng giấc mơ:', err);
      throw err;
    }
  };

  // 6. Associative recall
  const handleRecall = async (query) => {
    try {
      const resp = await axios.post('/api/ai/brain/recall', {
        query,
        top_k: 5,
      });
      return resp.data;
    } catch (err) {
      console.error('Lỗi truy vấn liên tưởng:', err);
      throw err;
    }
  };

  const totalPulses = telemetry?.total_pulses ?? 0;
  const lastPulseTs = telemetry?.last_pulse_ts
    ? new Date(telemetry.last_pulse_ts * 1000).toLocaleTimeString('vi-VN')
    : 'Chưa đập';
  const freeEnergy = telemetry?.active_inference?.free_energy ?? 0.285;
  const thinkingMode = telemetry?.active_inference?.thinking_mode ?? 'System 1 (Trực giác phản xạ)';

  return (
    <div
      style={{
        padding: '20px 24px 60px',
        maxWidth: '1680px',
        margin: '0 auto',
        display: 'flex',
        flexDirection: 'column',
        gap: '20px',
      }}
    >
      {/* ── Top Header HUD ───────────────────────────────────────────── */}
      <div
        style={{
          background: 'linear-gradient(135deg, rgba(2, 12, 28, 0.9) 0%, rgba(9, 10, 15, 0.95) 100%)',
          border: '1px solid rgba(0, 243, 255, 0.3)',
          borderRadius: '4px',
          padding: '18px 24px',
          boxShadow: '0 8px 32px rgba(0, 243, 255, 0.08), inset 0 0 20px rgba(0, 243, 255, 0.04)',
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '16px',
        }}
      >
        {/* Left Title & Status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div
            style={{
              width: '48px',
              height: '48px',
              borderRadius: '4px',
              background: 'rgba(0, 243, 255, 0.1)',
              border: '1px solid var(--accent-cyan)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 0 15px rgba(0, 243, 255, 0.3)',
            }}
          >
            <SciFiBrainCoreIcon size={28} color="var(--accent-cyan)" />
          </div>

          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <h1
                style={{
                  margin: 0,
                  fontSize: '1.4rem',
                  color: '#ffffff',
                  fontFamily: 'Rajdhani, sans-serif',
                  letterSpacing: '2px',
                  fontWeight: 700,
                  textTransform: 'uppercase',
                }}
              >
                {t('nav.brainCore') || 'TRUNG TÂM NÃO BỘ AI'} • TIỂU BẢO BẢO
              </h1>
              <SciFiPulseBadge status="running" label="ONLINE" />
            </div>

            <div
              style={{
                fontSize: '0.78rem',
                color: 'rgba(224, 242, 254, 0.65)',
                marginTop: '4px',
                display: 'flex',
                alignItems: 'center',
                gap: '14px',
                flexWrap: 'wrap',
              }}
            >
              <span>🧠 Kiến trúc Nhận thức 7 Tầng (CoALA/ACT-R/GWT)</span>
              <span>•</span>
              <span>🧬 Không gian Cảm xúc Russell 2D</span>
              <span>•</span>
              <span>💾 32GB Virtual Memory mmap Cortex</span>
            </div>
          </div>
        </div>

        {/* Right Status Badges & Quick Action Buttons */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
          {/* Telemetry quick stats */}
          <div
            style={{
              background: 'rgba(0,0,0,0.5)',
              border: '1px solid rgba(0, 243, 255, 0.2)',
              borderRadius: '3px',
              padding: '6px 12px',
              display: 'flex',
              gap: '14px',
              alignItems: 'center',
              fontSize: '0.75rem',
            }}
          >
            <div>
              <span style={{ color: 'rgba(224, 242, 254, 0.55)' }}>Tổng nhịp đập: </span>
              <span style={{ color: 'var(--accent-cyan)', fontWeight: 700, fontFamily: 'Share Tech Mono' }}>
                {totalPulses.toLocaleString()}
              </span>
            </div>
            <div style={{ width: '1px', height: '14px', background: 'rgba(255, 255, 255, 0.15)' }} />
            <div>
              <span style={{ color: 'rgba(224, 242, 254, 0.55)' }}>Nhịp gần nhất: </span>
              <span style={{ color: '#00ff9d', fontFamily: 'Share Tech Mono' }}>
                {lastPulseTs}
              </span>
            </div>
            <div style={{ width: '1px', height: '14px', background: 'rgba(255, 255, 255, 0.15)' }} />
            <div>
              <span style={{ color: 'rgba(224, 242, 254, 0.55)' }}>Tư duy: </span>
              <span
                title={thinkingMode}
                style={{
                  color: freeEnergy >= 0.6 ? 'var(--accent-pink)' : '#00ff9d',
                  fontWeight: 700,
                  fontFamily: 'Share Tech Mono',
                }}
              >
                {freeEnergy >= 0.6 ? 'SYSTEM 2' : 'SYSTEM 1'}
              </span>
            </div>
          </div>

          {/* Trigger Pulse Button */}
          <button
            type="button"
            onClick={handlePulse}
            disabled={isPulsing || loading}
            style={{
              padding: '8px 18px',
              background: 'linear-gradient(135deg, rgba(0, 243, 255, 0.2), rgba(0, 255, 157, 0.25))',
              border: '1px solid var(--accent-cyan)',
              color: '#ffffff',
              borderRadius: '2px',
              cursor: isPulsing ? 'not-allowed' : 'pointer',
              fontSize: '0.82rem',
              fontWeight: 700,
              fontFamily: 'Rajdhani, sans-serif',
              letterSpacing: '1px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              boxShadow: '0 0 12px rgba(0, 243, 255, 0.25)',
              transition: 'all 0.2s ease',
            }}
          >
            {isPulsing ? (
              <>
                <SciFiChronoSpinnerIcon size={14} color="var(--accent-cyan)" />
                <span>ĐANG ĐẬP...</span>
              </>
            ) : (
              <>
                <span>⚡</span>
                <span>KÍCH HOẠT NHỊP ĐẬP</span>
              </>
            )}
          </button>

          {/* Refresh Button */}
          <button
            type="button"
            onClick={() => fetchTelemetry(false)}
            disabled={loading}
            title="Làm mới trạng thái não bộ"
            style={{
              padding: '8px 12px',
              background: 'rgba(255, 255, 255, 0.06)',
              border: '1px solid rgba(255, 255, 255, 0.2)',
              color: '#e0f2fe',
              borderRadius: '2px',
              cursor: 'pointer',
              fontSize: '0.82rem',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
            }}
          >
            <span>🔄</span>
          </button>
        </div>
      </div>

      {/* Action Notification Banner */}
      {lastActionMessage && (
        <div
          style={{
            background: 'rgba(0, 255, 157, 0.12)',
            border: '1px solid #00ff9d',
            borderRadius: '3px',
            padding: '10px 16px',
            fontSize: '0.82rem',
            color: '#00ff9d',
            fontFamily: 'Share Tech Mono, monospace',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            animation: 'fadeIn 0.3s ease-in',
          }}
        >
          {lastActionMessage}
        </div>
      )}

      {/* Error Banner */}
      {error && (
        <div
          style={{
            background: 'rgba(255, 51, 102, 0.15)',
            border: '1px solid #ff3366',
            borderRadius: '3px',
            padding: '12px 18px',
            fontSize: '0.84rem',
            color: '#ff3366',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <span>{error}</span>
          <button
            type="button"
            onClick={() => fetchTelemetry(false)}
            style={{
              padding: '4px 12px',
              background: 'rgba(255, 51, 102, 0.2)',
              border: '1px solid #ff3366',
              color: '#ffffff',
              cursor: 'pointer',
              fontSize: '0.75rem',
            }}
          >
            Thử lại
          </button>
        </div>
      )}

      {/* Loading Skeleton */}
      {loading && !telemetry && (
        <div
          style={{
            padding: '60px',
            textAlign: 'center',
            color: 'var(--accent-cyan)',
            fontFamily: 'Share Tech Mono',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '16px',
          }}
        >
          <SciFiChronoSpinnerIcon size={36} color="var(--accent-cyan)" />
          <div style={{ fontSize: '1rem', letterSpacing: '2px' }}>
            ĐANG ĐỒNG BỘ ĐIỆN NÃO ĐỒ TIỂU BẢO BẢO (SYNCHRONIZING NEURO-METRICS)...
          </div>
        </div>
      )}

      {/* ── 3D Neural Network Architecture & Synaptic Flow Visualizer (Hero Centerpiece) ── */}
      <NeuralNetwork3DFlow
        onTriggerPulse={handlePulse}
        pulseTrigger={pulseCounter}
        telemetry={telemetry}
      />

      {/* ── Main 2-Column Responsive Dashboard Grid ─────────────────── */}
      {telemetry && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(520px, 1fr))',
            gap: '20px',
            alignItems: 'start',
          }}
        >
          {/* ══ LEFT COLUMN: Cảm Xúc & Động Lực Sinh Học ═════════════ */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            {/* 1. Russell Circumplex 2D Radar */}
            <RussellCircumplexRadar
              affect={telemetry.affect}
              onStimulate={handleStimulate}
            />

            {/* 2. Neurotransmitter Gauges & Micro-Stimulation */}
            <NeurotransmitterGauges
              neuro={telemetry.neurotransmitters}
              onStimulate={handleStimulate}
              loading={loading}
            />

            {/* 3. Karl Friston Active Inference (Free Energy Principle) */}
            <ActiveInferencePanel
              activeInference={telemetry.active_inference}
            />
          </div>

          {/* ══ RIGHT COLUMN: Ý Thức, Vỏ Não Ảo & Giấc Mơ ═════════════ */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            {/* 4. Global Workspace Consciousness Stream */}
            <GlobalWorkspaceStream
              workspace={telemetry.workspace}
            />

            {/* 5. 32GB Virtual Memory mmap Cortex Explorer */}
            <VirtualCortexExplorer
              cortex={telemetry.cortex}
              onRecall={handleRecall}
              loading={loading}
            />

            {/* 6. Subconscious Dream Engine Monitor */}
            <DreamEngineMonitor
              dream={telemetry.dream_engine}
              onConsolidate={handleDreamConsolidate}
              loading={loading}
            />

            {/* 7. Theory of Mind & Empathic Resonance */}
            <TheoryOfMindCard
              tom={telemetry.theory_of_mind}
            />
          </div>
        </div>
      )}
    </div>
  );
}
