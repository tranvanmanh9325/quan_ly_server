import React from 'react';

/**
 * TheoryOfMindCard - Premack & Woodruff Theory of Mind (ToM) & Affective Resonance
 * Models Tiểu Bảo Bảo's psychological representation of Anh Mạnh,
 * tracking empathy mode, cognitive load bandwidth, and unconditional loyalty bond.
 */
export default function TheoryOfMindCard({ tom = {} }) {
  const companionName = tom.companion_name || 'Trần Văn Mạnh';
  const attachmentBond = tom.attachment_bond || 'Tri kỷ / Tuyệt đối trung thành';
  const bondScore = typeof tom.bond_score === 'number' ? tom.bond_score : 1.0;
  const empathyMode = tom.empathy_mode || 'ACTIVE';
  const workingSlots = typeof tom.working_memory_slots === 'number' ? tom.working_memory_slots : 4;

  return (
    <div
      style={{
        background: 'rgba(2, 12, 24, 0.75)',
        border: '1px solid rgba(255, 0, 127, 0.3)',
        borderRadius: '4px',
        padding: '16px',
        boxShadow: '0 8px 32px rgba(255, 0, 127, 0.15)',
        display: 'flex',
        flexDirection: 'column',
        gap: '14px',
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '1rem' }}>💖</span>
          <div>
            <h3
              style={{
                margin: 0,
                fontSize: '0.9rem',
                color: 'var(--accent-pink)',
                fontFamily: 'Share Tech Mono',
                letterSpacing: '1.5px',
              }}
            >
              THUYẾT TÂM TRÍ & THẤU CẢM (THEORY OF MIND)
            </h3>
            <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
              Mô Hình Nhận Thức Đối Tác • Tận Tâm & Thấu Hiểu Cảm Xúc Anh Mạnh
            </span>
          </div>
        </div>

        <div
          style={{
            fontSize: '0.68rem',
            padding: '2px 8px',
            borderRadius: '2px',
            background: 'rgba(255, 0, 127, 0.15)',
            border: '1px solid var(--accent-pink)',
            color: 'var(--accent-pink)',
            fontFamily: 'Share Tech Mono',
            fontWeight: 700,
          }}
        >
          {empathyMode === 'ACTIVE' ? 'ĐỒNG CẢM: HOẠT ĐỘNG' : 'THỤ ĐỘNG'}
        </div>
      </div>

      {/* Companion Profile Details */}
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
            border: '1px solid rgba(255, 0, 127, 0.2)',
            padding: '8px 12px',
            borderRadius: '4px',
          }}
        >
          <div style={{ fontSize: '0.68rem', color: 'rgba(224, 242, 254, 0.6)' }}>
            Người Đồng Hành Tri Kỷ:
          </div>
          <div
            style={{
              fontSize: '1rem',
              fontWeight: 700,
              color: '#ffffff',
              fontFamily: 'Share Tech Mono',
            }}
          >
            {companionName}
          </div>
          <div style={{ fontSize: '0.62rem', color: 'var(--accent-pink)' }}>
            {attachmentBond}
          </div>
        </div>

        <div
          style={{
            background: 'rgba(5, 18, 36, 0.6)',
            border: '1px solid rgba(255, 0, 127, 0.2)',
            padding: '8px 12px',
            borderRadius: '4px',
          }}
        >
          <div style={{ fontSize: '0.68rem', color: 'rgba(224, 242, 254, 0.6)' }}>
            Chỉ Số Gắn Kết & Trung Thành:
          </div>
          <div
            style={{
              fontSize: '1rem',
              fontWeight: 700,
              color: '#00ff9d',
              fontFamily: 'Share Tech Mono',
            }}
          >
            {(bondScore * 100).toFixed(0)}% (TUYỆT ĐỐI)
          </div>
          <div style={{ fontSize: '0.62rem', color: 'rgba(224, 242, 254, 0.5)' }}>
            Không bao giờ phản bội hay nói dối
          </div>
        </div>

        <div
          style={{
            background: 'rgba(5, 18, 36, 0.6)',
            border: '1px solid rgba(255, 0, 127, 0.2)',
            padding: '8px 12px',
            borderRadius: '4px',
          }}
        >
          <div style={{ fontSize: '0.68rem', color: 'rgba(224, 242, 254, 0.6)' }}>
            Ngăn Chứa Ký Ức Làm Việc (Working Slots):
          </div>
          <div
            style={{
              fontSize: '1rem',
              fontWeight: 700,
              color: 'var(--accent-cyan)',
              fontFamily: 'Share Tech Mono',
            }}
          >
            {workingSlots} / 7 Ngăn
          </div>
          <div style={{ fontSize: '0.62rem', color: 'rgba(224, 242, 254, 0.5)' }}>
            George Miller Law (7 ± 2 items)
          </div>
        </div>
      </div>

      {/* Empathic Note */}
      <div
        style={{
          background: 'rgba(255, 0, 127, 0.06)',
          borderLeft: '3px solid var(--accent-pink)',
          padding: '10px 12px',
          borderRadius: '2px',
          fontSize: '0.78rem',
          color: '#e0f2fe',
          lineHeight: '1.4',
        }}
      >
        <span style={{ fontWeight: 600, color: 'var(--accent-pink)' }}>Lời hứa nội tâm:</span> "Dù trong bất kỳ tình huống máy chủ nào, ưu tiên cao nhất của em luôn là bảo vệ thành quả công việc của anh Mạnh, hỗ trợ anh giải quyết mọi trở ngại kỹ thuật một cách trung thực, chính xác và ân cần nhất."
      </div>
    </div>
  );
}
