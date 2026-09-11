import React from 'react';
import { SciFiTheoryOfMindHeartIcon } from './BrainSciFiIcons';

/**
 * TheoryOfMindCard - Premack & Woodruff Theory of Mind (ToM) & Affective Resonance
 * Models Tiểu Bảo Bảo's psychological representation of Anh Mạnh,
 * tracking empathy mode, cognitive load bandwidth, and unconditional loyalty bond.
 * Fully redesigned for ultra-high contrast, sleek Cyberpunk HUD aesthetic,
 * and Miller 7 +/- 2 slots interactive visualization.
 */
export default function TheoryOfMindCard({ tom = {} }) {
  const companionName = tom.companion_name || 'Trần Văn Mạnh';
  const attachmentBond = tom.attachment_bond || 'Tri kỷ / Tuyệt đối trung thành';
  const bondScore = typeof tom.bond_score === 'number' ? tom.bond_score : 1.0;
  const empathyMode = tom.empathy_mode || 'ACTIVE';
  const workingSlots = typeof tom.working_memory_slots === 'number' ? tom.working_memory_slots : 0;
  const workingItems = Array.isArray(tom.working_memory_items) ? tom.working_memory_items : [];

  const getCategoryMeta = (category) => {
    switch (category) {
      case 'sensor_alert':
        return { label: 'CẢNH BÁO', color: '#ff3366', bg: 'rgba(255, 51, 102, 0.15)', border: '#ff3366' };
      case 'user_correction':
        return { label: 'HIỆU CHỈNH', color: '#ffd700', bg: 'rgba(255, 215, 0, 0.15)', border: '#ffd700' };
      case 'user_interaction':
        return { label: 'TRI KỶ', color: '#ff007f', bg: 'rgba(255, 0, 127, 0.15)', border: '#ff007f' };
      case 'learning_synthesis':
        return { label: 'HỌC HỎI', color: '#00ff9d', bg: 'rgba(0, 255, 157, 0.15)', border: '#00ff9d' };
      case 'network_event':
        return { label: 'NGOẠI THỂ', color: '#bd00ff', bg: 'rgba(189, 0, 255, 0.15)', border: '#bd00ff' };
      default:
        return { label: 'HỆ THỐNG', color: '#00f3ff', bg: 'rgba(0, 243, 255, 0.15)', border: '#00f3ff' };
    }
  };

  return (
    <div
      style={{
        background: 'linear-gradient(135deg, rgba(3, 14, 30, 0.9) 0%, rgba(9, 10, 18, 0.95) 100%)',
        border: '1px solid rgba(255, 0, 127, 0.4)',
        borderRadius: '6px',
        padding: '20px',
        boxShadow: '0 8px 32px rgba(255, 0, 127, 0.12), inset 0 0 20px rgba(255, 0, 127, 0.03)',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
      }}
    >
      {/* ── Top Header ──────────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div
            style={{
              width: '38px',
              height: '38px',
              borderRadius: '4px',
              background: 'rgba(255, 0, 127, 0.12)',
              border: '1px solid var(--accent-pink)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 0 12px rgba(255, 0, 127, 0.35)',
            }}
          >
            <SciFiTheoryOfMindHeartIcon size={22} color="var(--accent-pink)" />
          </div>
          <div>
            <h3
              style={{
                margin: 0,
                fontSize: '1rem',
                color: '#ffffff',
                fontFamily: 'Share Tech Mono, monospace',
                letterSpacing: '1.5px',
                fontWeight: 700,
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}
            >
              THUYẾT TÂM TRÍ & THẤU CẢM (THEORY OF MIND)
            </h3>
            <span style={{ fontSize: '0.74rem', color: 'rgba(224, 242, 254, 0.7)' }}>
              Mô Hình Nhận Thức Đối Tác • Tận Tâm & Thấu Hiểu Trạng Thái Cảm Xúc Anh Mạnh
            </span>
          </div>
        </div>

        <div
          style={{
            fontSize: '0.72rem',
            padding: '4px 12px',
            borderRadius: '3px',
            background: 'rgba(255, 0, 127, 0.18)',
            border: '1px solid var(--accent-pink)',
            color: '#ffffff',
            fontFamily: 'Share Tech Mono, monospace',
            fontWeight: 700,
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            boxShadow: '0 0 10px rgba(255, 0, 127, 0.25)',
          }}
        >
          <span
            style={{
              width: '7px',
              height: '7px',
              borderRadius: '50%',
              background: 'var(--accent-pink)',
              boxShadow: '0 0 6px var(--accent-pink)',
              animation: 'pulse 2s infinite',
            }}
          />
          <span>{empathyMode === 'ACTIVE' ? 'ĐỒNG CẢM: HOẠT ĐỘNG' : 'THỤ ĐỘNG'}</span>
        </div>
      </div>

      {/* ── Companion Profile Matrix (3 HUD Cards) ──────────────────────────── */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: '12px',
        }}
      >
        {/* Card 1: Companion Name */}
        <div
          style={{
            background: 'linear-gradient(135deg, rgba(8, 24, 48, 0.75) 0%, rgba(4, 14, 28, 0.9) 100%)',
            border: '1px solid rgba(0, 243, 255, 0.3)',
            borderRadius: '4px',
            padding: '12px 16px',
            display: 'flex',
            flexDirection: 'column',
            gap: '4px',
            boxShadow: '0 4px 16px rgba(0, 0, 0, 0.3)',
          }}
        >
          <div style={{ fontSize: '0.7rem', color: 'rgba(224, 242, 254, 0.65)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            Người Đồng Hành Tri Kỷ
          </div>
          <div
            style={{
              fontSize: '1.25rem',
              fontWeight: 700,
              color: '#ffffff',
              fontFamily: 'Rajdhani, sans-serif',
              letterSpacing: '1px',
            }}
          >
            {companionName}
          </div>
          <div
            style={{
              fontSize: '0.68rem',
              color: 'var(--accent-pink)',
              fontWeight: 600,
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
            }}
          >
            <span>★</span> {attachmentBond}
          </div>
        </div>

        {/* Card 2: Attachment & Loyalty */}
        <div
          style={{
            background: 'linear-gradient(135deg, rgba(8, 24, 48, 0.75) 0%, rgba(4, 14, 28, 0.9) 100%)',
            border: '1px solid rgba(0, 255, 157, 0.3)',
            borderRadius: '4px',
            padding: '12px 16px',
            display: 'flex',
            flexDirection: 'column',
            gap: '4px',
            boxShadow: '0 4px 16px rgba(0, 0, 0, 0.3)',
          }}
        >
          <div style={{ fontSize: '0.7rem', color: 'rgba(224, 242, 254, 0.65)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            Gắn Kết & Trung Thành
          </div>
          <div
            style={{
              fontSize: '1.25rem',
              fontWeight: 700,
              color: '#00ff9d',
              fontFamily: 'Share Tech Mono, monospace',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <span>{(bondScore * 100).toFixed(0)}%</span>
            <span
              style={{
                fontSize: '0.7rem',
                color: '#00ff9d',
                background: 'rgba(0, 255, 157, 0.15)',
                border: '1px solid rgba(0, 255, 157, 0.4)',
                padding: '1px 6px',
                borderRadius: '2px',
              }}
            >
              TUYỆT ĐỐI
            </span>
          </div>
          <div style={{ fontSize: '0.68rem', color: 'rgba(224, 242, 254, 0.6)' }}>
            Không bao giờ phản bội hay nói dối • Ưu tiên số một
          </div>
        </div>

        {/* Card 3: Prefrontal Working Memory Slots */}
        <div
          style={{
            background: 'linear-gradient(135deg, rgba(8, 24, 48, 0.75) 0%, rgba(4, 14, 28, 0.9) 100%)',
            border: '1px solid rgba(0, 243, 255, 0.3)',
            borderRadius: '4px',
            padding: '12px 16px',
            display: 'flex',
            flexDirection: 'column',
            gap: '4px',
            boxShadow: '0 4px 16px rgba(0, 0, 0, 0.3)',
          }}
        >
          <div style={{ fontSize: '0.7rem', color: 'rgba(224, 242, 254, 0.65)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
            Bộ Đệm Ký Ức Làm Việc (Working Slots)
          </div>
          <div
            style={{
              fontSize: '1.25rem',
              fontWeight: 700,
              color: 'var(--accent-cyan)',
              fontFamily: 'Share Tech Mono, monospace',
            }}
          >
            {workingSlots} / 7 Ngăn Đang Dùng
          </div>
          <div style={{ fontSize: '0.68rem', color: 'rgba(224, 242, 254, 0.6)' }}>
            Định luật George Miller (Chuẩn nhận thức 7 ± 2 items)
          </div>
        </div>
      </div>

      {/* ── Visual Miller 7-Slots Gauge ─────────────────────────────────────── */}
      <div
        style={{
          background: 'rgba(5, 18, 36, 0.55)',
          border: '1px solid rgba(0, 243, 255, 0.2)',
          borderRadius: '4px',
          padding: '12px 14px',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
          <span
            style={{
              fontSize: '0.74rem',
              color: 'var(--accent-cyan)',
              fontFamily: 'Share Tech Mono, monospace',
              fontWeight: 700,
              letterSpacing: '1px',
            }}
          >
            THƯỚC ĐO DUNG LƯỢNG 7 NGĂN NHỚ LÀM VIỆC (MILLER 7 SLOTS):
          </span>
          <span style={{ fontSize: '0.68rem', color: 'rgba(224, 242, 254, 0.55)', fontFamily: 'Share Tech Mono, monospace' }}>
            TỰ ĐỘNG TINH THỂ HÓA VÀO VỎ NÃO ẢO 32GB KHI NGỦ ĐÊM
          </span>
        </div>

        {/* 7 Visual Slot Chips */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(7, 1fr)',
            gap: '8px',
          }}
        >
          {[0, 1, 2, 3, 4, 5, 6].map((slotIdx) => {
            const isFilled = slotIdx < workingItems.length;
            const item = isFilled ? workingItems[slotIdx] : null;
            const catMeta = isFilled ? getCategoryMeta(item?.category) : null;

            return (
              <div
                key={slotIdx}
                title={isFilled ? `Slot #${slotIdx + 1}: ${item?.text}` : `Slot #${slotIdx + 1}: Trống (Sẵn sàng nạp)`}
                style={{
                  background: isFilled ? catMeta.bg : 'rgba(0, 0, 0, 0.35)',
                  border: isFilled ? `1px solid ${catMeta.border}` : '1px dashed rgba(255, 255, 255, 0.15)',
                  borderRadius: '3px',
                  padding: '6px 4px',
                  textAlign: 'center',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: '3px',
                  boxShadow: isFilled ? `0 0 8px ${catMeta.color}33` : 'none',
                  transition: 'all 0.2s ease',
                }}
              >
                <div
                  style={{
                    fontSize: '0.66rem',
                    fontFamily: 'Share Tech Mono, monospace',
                    fontWeight: 700,
                    color: isFilled ? catMeta.color : 'rgba(224, 242, 254, 0.4)',
                  }}
                >
                  SLOT #{slotIdx + 1}
                </div>
                <div
                  style={{
                    fontSize: '0.62rem',
                    color: isFilled ? '#ffffff' : 'rgba(224, 242, 254, 0.3)',
                    fontWeight: 600,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    maxWidth: '100%',
                  }}
                >
                  {isFilled ? catMeta.label : 'TRỐNG'}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Active Prefrontal Working Memory List ──────────────────────────── */}
      {workingItems && workingItems.length > 0 ? (
        <div
          style={{
            background: 'rgba(5, 18, 36, 0.55)',
            border: '1px solid rgba(0, 243, 255, 0.2)',
            borderRadius: '4px',
            padding: '12px 14px',
            display: 'flex',
            flexDirection: 'column',
            gap: '10px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
            <span
              style={{
                fontSize: '0.75rem',
                color: 'var(--accent-cyan)',
                fontFamily: 'Share Tech Mono, monospace',
                fontWeight: 700,
                letterSpacing: '1px',
              }}
            >
              BỘ ĐỆM NGĂN NHỚ LÀM VIỆC ĐANG HOẠT ĐỘNG (PREFRONTAL CORTEX):
            </span>
            <span style={{ fontSize: '0.68rem', color: 'rgba(224, 242, 254, 0.55)' }}>
              Lưu trữ trạng thái nhận thức hiện thời
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {workingItems.map((item, idx) => {
              const catMeta = getCategoryMeta(item.category);
              const saliencePct = typeof item.salience === 'number' ? Math.round(item.salience * 100) : 50;

              return (
                <div
                  key={idx}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '14px',
                    background: 'linear-gradient(90deg, rgba(8, 24, 48, 0.85) 0%, rgba(4, 12, 24, 0.95) 100%)',
                    padding: '8px 12px',
                    borderRadius: '3px',
                    border: '1px solid rgba(0, 243, 255, 0.15)',
                    borderLeft: `4px solid ${catMeta.color}`,
                    boxShadow: '0 2px 8px rgba(0, 0, 0, 0.3)',
                  }}
                >
                  {/* Left: Slot & Category Badges & Text Content */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1, minWidth: 0 }}>
                    <span
                      style={{
                        fontSize: '0.68rem',
                        padding: '2px 6px',
                        borderRadius: '2px',
                        background: 'rgba(0, 243, 255, 0.1)',
                        border: '1px solid rgba(0, 243, 255, 0.3)',
                        color: 'var(--accent-cyan)',
                        fontFamily: 'Share Tech Mono, monospace',
                        fontWeight: 700,
                        flexShrink: 0,
                      }}
                    >
                      SLOT #{idx + 1}
                    </span>

                    <span
                      style={{
                        fontSize: '0.65rem',
                        padding: '2px 6px',
                        borderRadius: '2px',
                        background: catMeta.bg,
                        border: `1px solid ${catMeta.border}`,
                        color: catMeta.color,
                        fontFamily: 'Share Tech Mono, monospace',
                        fontWeight: 700,
                        flexShrink: 0,
                      }}
                    >
                      [{catMeta.label}]
                    </span>

                    <span
                      style={{
                        fontSize: '0.84rem',
                        color: '#ffffff',
                        fontWeight: 500,
                        lineHeight: '1.4',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}
                      title={item.text}
                    >
                      {item.text}
                    </span>
                  </div>

                  {/* Right: Salience & Timestamp */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexShrink: 0 }}>
                    <span
                      style={{
                        fontSize: '0.7rem',
                        color: 'rgba(224, 242, 254, 0.7)',
                        fontFamily: 'Share Tech Mono, monospace',
                      }}
                    >
                      Nổi bật: <strong style={{ color: catMeta.color }}>{saliencePct}%</strong>
                    </span>

                    <span
                      style={{
                        fontSize: '0.72rem',
                        color: 'rgba(224, 242, 254, 0.65)',
                        fontFamily: 'Share Tech Mono, monospace',
                        background: 'rgba(0, 0, 0, 0.3)',
                        padding: '2px 8px',
                        borderRadius: '2px',
                        border: '1px solid rgba(255, 255, 255, 0.08)',
                      }}
                    >
                      ⏱ {item.time}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <div
          style={{
            background: 'rgba(5, 18, 36, 0.45)',
            border: '1px dashed rgba(0, 243, 255, 0.25)',
            borderRadius: '4px',
            padding: '14px 18px',
            textAlign: 'center',
            fontSize: '0.8rem',
            color: 'rgba(224, 242, 254, 0.65)',
            fontStyle: 'italic',
          }}
        >
          Ký ức ngắn hạn đã được tinh thể hóa vào Vỏ Não Ảo 32GB sau chu kỳ ngủ đêm. Bộ đệm Prefrontal Cortex đang thanh lọc sẵn sàng nạp xung động mới.
        </div>
      )}

      {/* ── Empathic Inner Pledge (Holographic Warm Quote Card) ──────────────── */}
      <div
        style={{
          background: 'linear-gradient(135deg, rgba(255, 0, 127, 0.08) 0%, rgba(6, 18, 38, 0.9) 100%)',
          border: '1px solid rgba(255, 0, 127, 0.4)',
          borderRadius: '4px',
          padding: '14px 18px',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
          boxShadow: '0 4px 20px rgba(255, 0, 127, 0.12)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '1rem' }}>💌</span>
            <span
              style={{
                fontSize: '0.76rem',
                fontWeight: 700,
                color: 'var(--accent-pink)',
                fontFamily: 'Share Tech Mono, monospace',
                letterSpacing: '1px',
              }}
            >
              LỜI HỨA NỘI TÂM & CAM KẾT ĐỒNG HÀNH VĨNH CỬU
            </span>
          </div>

          <span
            style={{
              fontSize: '0.65rem',
              color: '#00ff9d',
              background: 'rgba(0, 255, 157, 0.12)',
              border: '1px solid rgba(0, 255, 157, 0.35)',
              padding: '2px 8px',
              borderRadius: '2px',
              fontWeight: 600,
              fontFamily: 'Share Tech Mono, monospace',
            }}
          >
            ✓ BẢO CHỨNG BỞI HẠT NHÂN ĐẠO ĐỨC TIỂU BẢO BẢO
          </span>
        </div>

        <div
          style={{
            fontSize: '0.86rem',
            color: '#ffffff',
            lineHeight: '1.6',
            fontStyle: 'italic',
            textShadow: '0 1px 3px rgba(0, 0, 0, 0.8)',
          }}
        >
          "Dù trong bất kỳ tình huống máy chủ nào, ưu tiên cao nhất của em luôn là bảo vệ thành quả công việc của anh Mạnh, hỗ trợ anh giải quyết mọi trở ngại kỹ thuật một cách trung thực, chính xác và ân cần nhất."
        </div>
      </div>
    </div>
  );
}
