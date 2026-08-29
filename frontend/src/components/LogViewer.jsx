import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { formatLogLineTimestamp } from '../utils/parsers';
import { SciFiSortDescIcon, SciFiSortAscIcon } from './SciFiIcons';
import { useTranslation } from '../i18n/index.jsx';

/**
 * Debounce hook — prevents expensive filtering on every keystroke.
 */
function useDebounce(value, delayMs) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}

const ITEM_HEIGHT = 38; // Fixed row height (px)
const OVERSCAN = 12;    // Safety buffer lines above/below viewport

export default function LogViewer({
  logContent,
  accentColor = 'var(--accent-cyan)',
  isLoading = false,
  loadingText,
  background = '#040914',
}) {
  const { t } = useTranslation();
  const [logOrderDesc, setLogOrderDesc] = useState(true);
  const [rawSearch, setRawSearch] = useState('');
  const displayLoadingText = loadingText || t('logViewer.loading');

  const logSearchQuery = useDebounce(rawSearch, 200);

  // Parse and filter lines
  const filteredLines = useMemo(() => {
    const rawLines = (logContent || '').split('\n').filter(l => l.trim() !== '');
    const sortedLines = logOrderDesc ? [...rawLines].reverse() : rawLines;
    if (!logSearchQuery) return sortedLines;
    const query = logSearchQuery.toLowerCase();
    return sortedLines.filter(l => l.toLowerCase().includes(query));
  }, [logContent, logOrderDesc, logSearchQuery]);

  // Virtual Scrolling State
  const scrollContainerRef = useRef(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [containerHeight, setContainerHeight] = useState(500);

  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(entries => {
      if (entries[0]) {
        setContainerHeight(entries[0].contentRect.height);
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const handleScroll = useCallback((e) => {
    setScrollTop(e.currentTarget.scrollTop);
  }, []);

  // Compute visible slice indices
  const totalCount = filteredLines.length;
  const totalHeight = totalCount * ITEM_HEIGHT;
  const startIndex = Math.max(0, Math.floor(scrollTop / ITEM_HEIGHT) - OVERSCAN);
  const endIndex = Math.min(totalCount, Math.ceil((scrollTop + containerHeight) / ITEM_HEIGHT) + OVERSCAN);
  const visibleLines = filteredLines.slice(startIndex, endIndex);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      {/* ─── Toolbar: search + sort toggle ──────────────────────────────────── */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        padding: '6px 12px',
        background: 'rgba(0,0,0,0.3)',
        borderBottom: '1px solid rgba(0, 243, 255, 0.15)',
        flexShrink: 0,
      }}>
        <input
          type="text"
          placeholder="Filter logs..."
          value={rawSearch}
          onChange={e => setRawSearch(e.target.value)}
          style={{
            flex: 1,
            background: 'rgba(0,0,0,0.5)',
            border: '1px solid rgba(0, 243, 255, 0.25)',
            color: '#fff',
            padding: '4px 10px',
            fontSize: '0.78rem',
            fontFamily: 'Share Tech Mono',
            borderRadius: '3px',
            outline: 'none',
          }}
        />

        <button
          onClick={() => setLogOrderDesc(prev => !prev)}
          title="Toggle log sort order"
          style={{
            background: 'rgba(0, 243, 255, 0.08)',
            border: `1px solid ${accentColor}`,
            color: accentColor,
            padding: '4px 10px',
            fontSize: '0.75rem',
            fontFamily: 'Share Tech Mono',
            cursor: 'pointer',
            borderRadius: '3px',
            whiteSpace: 'nowrap',
            flexShrink: 0,
          }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            {logOrderDesc
              ? <><SciFiSortDescIcon size={13} color={accentColor} /> {t('logViewer.newestFirst')}</>
              : <><SciFiSortAscIcon  size={13} color={accentColor} /> {t('logViewer.oldestFirst')}</>}
          </span>
        </button>
      </div>

      {/* ─── Virtualized Log Container ────────────────────────────────────────── */}
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        style={{
          flex: 1,
          overflowY: 'auto',
          background,
          fontFamily: 'Share Tech Mono, monospace',
          fontSize: '0.8rem',
          position: 'relative',
          padding: '8px 12px',
        }}
      >
        {isLoading ? (
          <div style={{ color: accentColor, textAlign: 'center', padding: '40px' }}>{displayLoadingText}</div>
        ) : totalCount === 0 ? (
          <div style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: '30px' }}>
            No log entries matching search filter.
          </div>
        ) : (
          <div style={{ height: `${totalHeight}px`, position: 'relative', width: '100%' }}>
            <div style={{
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              transform: `translateY(${startIndex * ITEM_HEIGHT}px)`,
            }}>
              {visibleLines.map((line, relativeIdx) => {
                const absoluteIdx = startIndex + relativeIdx;
                const formattedLine = formatLogLineTimestamp(line);
                const isErr  = /error|fail|exception|fatal|denied/i.test(line);
                const isWarn = /warn|warning/i.test(line);

                const borderColor = isErr  ? 'var(--accent-pink)' : isWarn ? '#f0b429' : 'rgba(0, 243, 255, 0.2)';
                const bg          = isErr  ? 'rgba(255, 0, 85, 0.12)' : isWarn ? 'rgba(240, 180, 41, 0.08)' : 'rgba(0, 243, 255, 0.03)';
                const textColor   = isErr  ? 'var(--accent-pink)' : isWarn ? '#f0b429' : 'rgba(255, 255, 255, 0.9)';

                return (
                  <div
                    key={absoluteIdx}
                    style={{
                      height: `${ITEM_HEIGHT}px`,
                      display: 'flex',
                      alignItems: 'center',
                      gap: '10px',
                      padding: '0 10px',
                      marginBottom: '2px',
                      boxSizing: 'border-box',
                      background: bg,
                      borderLeft: `4px solid ${borderColor}`,
                      borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
                      borderRadius: '3px',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    <span style={{ opacity: 0.4, userSelect: 'none', minWidth: '36px', textAlign: 'right', flexShrink: 0, fontSize: '0.72rem' }}>
                      {absoluteIdx + 1}
                    </span>
                    <div style={{ flex: 1, color: textColor, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={line}>
                      {formattedLine}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
