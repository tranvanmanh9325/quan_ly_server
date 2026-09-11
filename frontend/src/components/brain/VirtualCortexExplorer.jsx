import React, { useState } from 'react';
import {
  SciFiVirtualCortexLatticeIcon,
  SciFiAssociativeSearchIcon,
  SciFiCognitivePulseBurstIcon,
  SciFiPinnedVectorIcon,
} from './BrainSciFiIcons';

/**
 * VirtualCortexExplorer - 32GB Virtual Memory Cortex via mmap Demand Paging
 * Hyperdimensional Computing (VSA - Pentti Kanerva) with 10,000-bit vectors.
 * Features an interactive Associative Recall search box for real-time cognitive memory retrieval.
 */
export default function VirtualCortexExplorer({
  cortex = {},
  onRecall,
  loading = false,
}) {
  const [query, setQuery] = useState('');
  const [recallResults, setRecallResults] = useState(null);
  const [isSearching, setIsSearching] = useState(false);
  const [searchLatency, setSearchLatency] = useState(null);

  const vectorCount = typeof cortex.vector_count === 'number' ? cortex.vector_count : 0;
  const capacity = cortex.capacity || 50000;
  const dimensionBits = cortex.dimension_bits || 10000;
  const backingStorage = cortex.backing_storage || '32GB Virtual Memory / mmap Demand Paging';
  const latencyMs = cortex.demand_paging_latency_ms || 0.08;

  const handleSearch = async (e) => {
    if (e) e.preventDefault();
    if (!query.trim() || !onRecall || isSearching) return;

    setIsSearching(true);
    try {
      const resp = await onRecall(query.trim());
      if (resp) {
        setRecallResults(resp.memories || []);
        setSearchLatency(resp.elapsed_ms || 0.1);
      }
    } catch (err) {
      console.error('Lỗi tìm kiếm liên tưởng:', err);
    } finally {
      setIsSearching(false);
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
          <SciFiVirtualCortexLatticeIcon size={18} color="var(--accent-cyan)" />
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
              VỎ NÃO ẢO SIÊU KHÔNG GIAN (32GB VIRTUAL CORTEX)
            </h3>
            <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
              10,000-Bit Hyperdimensional Computing (VSA) • mmap Zero-Copy Demand Paging
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
          ĐỘ TRỄ TRUY XUẤT: &lt; {latencyMs}ms
        </div>
      </div>

      {/* Metrics Row */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
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
            Dung Lượng Bộ Nhớ Ảo:
          </div>
          <div
            style={{
              fontSize: '1rem',
              fontWeight: 700,
              color: 'var(--accent-cyan)',
              fontFamily: 'Share Tech Mono',
            }}
          >
            32.0 GB (mmap)
          </div>
          <div style={{ fontSize: '0.62rem', color: '#00ff9d' }}>{backingStorage}</div>
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
            Số Lượng Siêu Vector:
          </div>
          <div
            style={{
              fontSize: '1rem',
              fontWeight: 700,
              color: 'var(--accent-yellow)',
              fontFamily: 'Share Tech Mono',
            }}
          >
            {vectorCount.toLocaleString()} / {capacity.toLocaleString()}
          </div>
          <div style={{ fontSize: '0.62rem', color: 'rgba(224, 242, 254, 0.5)' }}>
            Độ dài: {dimensionBits.toLocaleString()} bits
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
            Cơ Chế Phân Trang:
          </div>
          <div
            style={{
              fontSize: '0.85rem',
              fontWeight: 700,
              color: '#bd00ff',
              fontFamily: 'Share Tech Mono',
            }}
          >
            Virtual Address Space
          </div>
          <div style={{ fontSize: '0.62rem', color: 'rgba(224, 242, 254, 0.5)' }}>
            Không chiếm dụng RAM vật lý
          </div>
        </div>
      </div>

      {/* Interactive Associative Recall Form */}
      <form onSubmit={handleSearch} style={{ display: 'flex', gap: '8px' }}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Thử truy vấn liên tưởng (VD: server, Mạnh, bảo mật, TikTok, tối ưu...)"
          disabled={isSearching || loading}
          style={{
            flex: 1,
            background: 'rgba(5, 18, 36, 0.8)',
            border: '1px solid rgba(0, 243, 255, 0.3)',
            borderRadius: '2px',
            padding: '8px 12px',
            color: '#e0f2fe',
            fontSize: '0.82rem',
            outline: 'none',
            fontFamily: 'Share Tech Mono, sans-serif',
          }}
        />

        <button
          type="submit"
          disabled={isSearching || loading || !query.trim()}
          style={{
            padding: '8px 16px',
            background: 'rgba(0, 243, 255, 0.15)',
            border: '1px solid var(--accent-cyan)',
            color: 'var(--accent-cyan)',
            borderRadius: '2px',
            cursor: isSearching || !query.trim() ? 'not-allowed' : 'pointer',
            fontSize: '0.8rem',
            fontWeight: 700,
            fontFamily: 'Share Tech Mono',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            whiteSpace: 'nowrap',
            transition: 'all 0.2s ease',
          }}
        >
          {isSearching ? (
            'ĐANG DÒ TÌM...'
          ) : (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              <SciFiAssociativeSearchIcon size={14} color="var(--accent-cyan)" />
              <span>GỢI NHỚ LIÊN TƯỞNG</span>
            </span>
          )}
        </button>
      </form>

      {/* Results Area */}
      {recallResults !== null && (
        <div
          style={{
            background: 'rgba(0, 0, 0, 0.4)',
            border: '1px solid rgba(0, 243, 255, 0.15)',
            borderRadius: '4px',
            padding: '10px',
            display: 'flex',
            flexDirection: 'column',
            gap: '8px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '0.72rem', color: 'var(--accent-cyan)', fontWeight: 600 }}>
              KẾT QUẢ LIÊN TƯỞNG TỪ VỎ NÃO ẢO ({recallResults.length} ký ức tương đồng):
            </span>
            {searchLatency !== null && (
              <span style={{ fontSize: '0.68rem', color: '#00ff9d', fontFamily: 'Share Tech Mono', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                <SciFiCognitivePulseBurstIcon size={12} color="#00ff9d" />
                <span>Tốc độ: {searchLatency}ms</span>
              </span>
            )}
          </div>

          {recallResults.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {recallResults.map((item, i) => (
                <div
                  key={item.id || i}
                  style={{
                    background: 'rgba(5, 18, 36, 0.7)',
                    borderLeft: '3px solid var(--accent-cyan)',
                    padding: '6px 10px',
                    borderRadius: '2px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '4px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ fontSize: '0.78rem', color: '#ffffff', fontWeight: 600 }}>
                      {item.text || item.id}
                    </span>
                    <span
                      style={{
                        fontSize: '0.75rem',
                        color: 'var(--accent-cyan)',
                        fontFamily: 'Share Tech Mono',
                        fontWeight: 700,
                      }}
                    >
                      Độ tương đồng: {item.confidence_percent}%
                    </span>
                  </div>

                  <div style={{ display: 'flex', gap: '10px', fontSize: '0.65rem', color: 'rgba(224, 242, 254, 0.5)' }}>
                    <span>Phân loại: {item.category}</span>
                    {item.pinned && (
                      <span style={{ color: 'var(--accent-yellow)', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                        <SciFiPinnedVectorIcon size={12} color="var(--accent-yellow)" />
                        <span>Cố định</span>
                      </span>
                    )}
                    {item.consolidated_at && <span>Nén lúc: {item.consolidated_at}</span>}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: '0.74rem', color: 'rgba(224, 242, 254, 0.5)', fontStyle: 'italic' }}>
              Không tìm thấy ký ức nào vượt ngưỡng tương đồng cosine &gt; 0.45 với từ khóa "{query}".
            </div>
          )}
        </div>
      )}
    </div>
  );
}
