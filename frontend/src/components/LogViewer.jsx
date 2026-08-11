import { useState, useEffect, useMemo } from 'react';
import { formatLogLineTimestamp } from '../utils/parsers';
import { SciFiSortDescIcon, SciFiSortAscIcon } from './SciFiIcons';
import { useTranslation } from '../i18n/index.jsx';

/**
 * Debounce hook — prevents the expensive useMemo from re-running on every single
 * keystroke when the user is typing a log search query.
 */
function useDebounce(value, delayMs) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}

/**
 * Shared log viewer component used by ServicesPage and ContainersPage.
 *
 * Centralises:
 *  - Sort order toggle (newest/oldest first)
 *  - Keyword filter input (debounced)
 *  - Coloured log line rendering (error / warn / default)
 *  - Timestamp reformatting via formatLogLineTimestamp
 *
 * @param {object}   props
 * @param {string}   props.logContent     - Raw log string (newline-separated)
 * @param {string}   props.accentColor    - CSS colour string for the search border / icon
 * @param {boolean}  props.isLoading      - Shows a loading message when true
 * @param {string}   props.loadingText    - Custom loading label (optional)
 * @param {string}   props.background     - Background colour of the scroll container (optional)
 */
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

  // Debounce search to avoid re-filtering on every keystroke
  const logSearchQuery = useDebounce(rawSearch, 200);

  // Recomputes only when content, sort order, or debounced search query changes
  const renderedLines = useMemo(() => {
    const rawLines = (logContent || '').split('\n').filter(l => l.trim() !== '');
    const sortedLines = logOrderDesc ? [...rawLines].reverse() : rawLines;
    const filteredLines = logSearchQuery
      ? sortedLines.filter(l => l.toLowerCase().includes(logSearchQuery.toLowerCase()))
      : sortedLines;

    if (filteredLines.length === 0) {
      return (
        <div style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: '30px' }}>
          No log entries matching search filter.
        </div>
      );
    }

    return filteredLines.map((line, idx) => {
      const formattedLine = formatLogLineTimestamp(line);
      const isErr  = /error|fail|exception|fatal|denied/i.test(line);
      const isWarn = /warn|warning/i.test(line);

      const borderColor = isErr  ? 'var(--accent-pink)'          : isWarn ? '#f0b429'                    : 'rgba(0, 243, 255, 0.2)';
      const bg          = isErr  ? 'rgba(255, 0, 85, 0.12)'      : isWarn ? 'rgba(240, 180, 41, 0.08)'   : 'rgba(0, 243, 255, 0.03)';
      const textColor   = isErr  ? 'var(--accent-pink)'          : isWarn ? '#f0b429'                    : 'rgba(255, 255, 255, 0.9)';

      return (
        <div
          key={idx}
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: '10px',
            padding: '7px 10px',
            marginBottom: '4px',
            background: bg,
            borderLeft: `4px solid ${borderColor}`,
            borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
            borderRadius: '3px',
            lineHeight: '1.45',
            wordBreak: 'break-all',
          }}
        >
          <span style={{ opacity: 0.4, userSelect: 'none', minWidth: '32px', textAlign: 'right', flexShrink: 0, fontSize: '0.72rem' }}>
            {idx + 1}
          </span>
          <div style={{ flex: 1, color: textColor, whiteSpace: 'pre-wrap' }}>
            {formattedLine}
          </div>
        </div>
      );
    });
  }, [logContent, logOrderDesc, logSearchQuery]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>

      {/* ─── Toolbar: search + sort toggle ──────────────────────────────────── */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        padding: '6px 12px',
        background: 'rgba(0,0,0,0.3)',
        borderBottom: `1px solid rgba(0, 243, 255, 0.15)`,
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
            border: `1px solid rgba(0, 243, 255, 0.25)`,
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

      {/* ─── Log content area ────────────────────────────────────────────────── */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        background,
        fontFamily: 'Share Tech Mono, monospace',
        fontSize: '0.8rem',
        padding: '12px',
      }}>
        {isLoading
          ? <div style={{ color: accentColor, textAlign: 'center', padding: '40px' }}>{displayLoadingText}</div>
          : renderedLines}
      </div>

    </div>
  );
}
