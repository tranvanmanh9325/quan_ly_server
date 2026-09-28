import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import axios from 'axios';
import { 
  SciFiContainerIcon, SciFiFolderIcon, SciFiFileIcon,
  SciFiSearchIcon, SciFiRefreshIcon, 
  SciFiPlayIcon, SciFiStopIcon, SciFiPulseBadge, SciFiWarningIcon,
  SciFiChronoSpinnerIcon
} from '../components/SciFiIcons';
import { parseDockerStats } from '../utils/parsers';
import LogViewer from '../components/LogViewer';

const STANDALONE_PROJECT_KEY = 'STANDALONE CONTAINERS';

const SENSITIVE_LINE_REGEX = /^\s*(?:export\s+)?[A-Za-z0-9_]*(TOKEN|KEY|SECRET|PASSWORD|PASSWD|PWD|AUTH|CREDENTIAL|PRIVATE|CERT)[A-Za-z0-9_]*\s*=.*$/i;

function maskEnvSecrets(text) {
  if (!text) return '';
  return text
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .split('\n')
    .map(line => {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) return line;
      if (SENSITIVE_LINE_REGEX.test(line)) {
        const eqIdx = line.indexOf('=');
        if (eqIdx !== -1) {
          return `${line.substring(0, eqIdx + 1)}••••••••`;
        }
      }
      return line;
    })
    .join('\n');
}

function safeDecodeBase64(content) {
  if (typeof content !== 'string' || !content.trim()) return '';
  const trimmed = content.trim();
  const isLikelyBase64 = !trimmed.includes('\n') && 
                         trimmed.length % 4 === 0 && 
                         /^[A-Za-z0-9+/]+={0,2}$/.test(trimmed);
  if (isLikelyBase64) {
    try {
      return decodeURIComponent(escape(atob(trimmed)));
    } catch {
      return content;
    }
  }
  return content;
}

export default function ContainersPage() {
  const [containers, setContainers] = useState([]);
  const [dockerStatus, setDockerStatus] = useState('LOADING');
  const [dockerStats, setDockerStats] = useState({});
  const [loading, setLoading] = useState(true);
  
  // Search & Filter
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');

  // Accordion State: [projectName]: boolean (default true if undefined)
  const [expandedProjects, setExpandedProjects] = useState({});

  // Feedback Toast & Async Loading States
  const [actionMessage, setActionMessage] = useState(null);
  const [actionLoading, setActionLoading] = useState({});
  const [projectActionLoading, setProjectActionLoading] = useState({});

  // .ENV Modal States (Milestone 4 Cyberpunk .env Editor)
  const [envModalOpen, setEnvModalOpen] = useState(false);
  const [envProject, setEnvProject] = useState('');
  const [envWorkingDir, setEnvWorkingDir] = useState('');
  const [envFilePath, setEnvFilePath] = useState('');
  const [envHasBackup, setEnvHasBackup] = useState(false);
  const [envRawContent, setEnvRawContent] = useState('');
  const [envInitialContent, setEnvInitialContent] = useState('');
  const [envMaskedMode, setEnvMaskedMode] = useState(true);
  const [envLoading, setEnvLoading] = useState(false);
  const [envSaving, setEnvSaving] = useState(false);
  const [envRestartAfterSave, setEnvRestartAfterSave] = useState(true);
  const [envCopySuccess, setEnvCopySuccess] = useState(false);
  const [envShowConfirmClose, setEnvShowConfirmClose] = useState(false);

  // Synchronized scroll refs for line numbers gutter and textarea
  const gutterRef = useRef(null);
  const textareaRef = useRef(null);

  // Container Log Modal
  const [logContainer, setLogContainer] = useState(null); // { id, name }
  const [logContent, setLogContent] = useState('');
  const [logLinesCount, setLogLinesCount] = useState(100);
  const [isLogsLoading, setIsLogsLoading] = useState(false);
  const [copySuccess, setCopySuccess] = useState(false);

  const fetchDockerData = useCallback(async () => {
    setLoading(true);
    try {
      const [listRes, statsRes] = await Promise.all([
        axios.get('/api/metrics/docker'),
        axios.get('/api/metrics/docker/stats').catch(() => ({ data: { data: '' } }))
      ]);

      if (listRes.data) {
        setDockerStatus(listRes.data.status || 'UNKNOWN');
        setContainers(listRes.data.data || []);
      }

      if (statsRes.data && statsRes.data.data) {
        setDockerStats(parseDockerStats(statsRes.data.data));
      }
    } catch (err) {
      console.error('Failed to fetch Docker containers page data:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let isMounted = true;

    const loadData = async () => {
      try {
        const [listRes, statsRes] = await Promise.all([
          axios.get('/api/metrics/docker'),
          axios.get('/api/metrics/docker/stats').catch(() => ({ data: { data: '' } }))
        ]);

        if (!isMounted) return;

        if (listRes.data) {
          setDockerStatus(listRes.data.status || 'UNKNOWN');
          setContainers(listRes.data.data || []);
        }

        if (statsRes.data && statsRes.data.data) {
          setDockerStats(parseDockerStats(statsRes.data.data));
        }
      } catch (err) {
        console.error('Failed to fetch Docker containers page data:', err);
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    loadData();
    const interval = setInterval(loadData, 15000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  // Compute baseline health stats for all projects before filtering
  const rawProjectStats = useMemo(() => {
    const map = Object.create(null);
    containers.forEach(c => {
      const raw = (c.project || '').trim();
      const projName = raw || STANDALONE_PROJECT_KEY;
      const isUp = (c.status || '').toLowerCase().includes('up');

      if (!map[projName]) {
        map[projName] = {
          rawTotal: 0,
          rawRunning: 0,
          workingDir: c.workingDir || '',
          configFiles: c.configFiles || ''
        };
      }

      map[projName].rawTotal += 1;
      if (isUp) map[projName].rawRunning += 1;
      if (!map[projName].workingDir && c.workingDir) {
        map[projName].workingDir = c.workingDir;
      }
      if (!map[projName].configFiles && c.configFiles) {
        map[projName].configFiles = c.configFiles;
      }
    });
    return map;
  }, [containers]);

  // Extract all known project names for Expand All / Collapse All
  const allProjectNames = useMemo(() => {
    const names = new Set();
    containers.forEach(c => {
      const raw = (c.project || '').trim();
      names.add(raw || STANDALONE_PROJECT_KEY);
    });
    return Array.from(names);
  }, [containers]);

  const normalizedQuery = searchQuery.trim().toLowerCase();

  // Group containers by project and apply filters
  const groupedProjects = useMemo(() => {
    const groupsMap = Object.create(null);

    containers.forEach(c => {
      // 1. Status Filter
      const isUp = (c.status || '').toLowerCase().includes('up');
      if (statusFilter === 'RUNNING' && !isUp) return;
      if (statusFilter === 'EXITED' && isUp) return;

      // 2. Search Query filter (matches name, service, id, image, ports, project)
      if (normalizedQuery) {
        const matchName = (c.name || '').toLowerCase().includes(normalizedQuery);
        const matchService = (c.service || '').toLowerCase().includes(normalizedQuery);
        const matchId = (c.id || '').toLowerCase().includes(normalizedQuery);
        const matchImage = (c.image || '').toLowerCase().includes(normalizedQuery);
        const matchPorts = (c.ports || '').toLowerCase().includes(normalizedQuery);
        const matchProject = (c.project || '').toLowerCase().includes(normalizedQuery);

        if (!matchName && !matchService && !matchId && !matchImage && !matchPorts && !matchProject) {
          return;
        }
      }

      // 3. Project Group key
      const raw = (c.project || '').trim();
      const isStandalone = !raw;
      const projName = isStandalone ? STANDALONE_PROJECT_KEY : raw;

      if (!groupsMap[projName]) {
        const stats = rawProjectStats[projName] || {
          rawTotal: 0,
          rawRunning: 0,
          workingDir: '',
          configFiles: ''
        };

        groupsMap[projName] = {
          name: projName,
          isStandalone,
          workingDir: stats.workingDir || c.workingDir || '',
          configFiles: stats.configFiles || c.configFiles || '',
          rawTotalCount: stats.rawTotal,
          rawRunningCount: stats.rawRunning,
          containers: []
        };
      }

      groupsMap[projName].containers.push(c);
    });

    const result = Object.values(groupsMap).map(group => {
      const rawTotal = group.rawTotalCount;
      const rawRunning = group.rawRunningCount;

      let statusType;
      let statusBadgeText;

      if (rawRunning === rawTotal && rawTotal > 0) {
        statusType = 'RUNNING';
        statusBadgeText = `${rawTotal}/${rawTotal} RUNNING`;
      } else if (rawRunning > 0) {
        statusType = 'MIXED';
        statusBadgeText = `MIXED (${rawRunning}/${rawTotal})`;
      } else {
        statusType = 'STOPPED';
        statusBadgeText = `0/${rawTotal} RUNNING`;
      }

      return {
        ...group,
        matchingCount: group.containers.length,
        statusType,
        statusBadgeText
      };
    });

    // Sort: Compose projects alphabetically A-Z, STANDALONE at bottom
    result.sort((a, b) => {
      if (a.isStandalone && !b.isStandalone) return 1;
      if (!a.isStandalone && b.isStandalone) return -1;
      return a.name.localeCompare(b.name);
    });

    return result;
  }, [containers, rawProjectStats, statusFilter, normalizedQuery]);

  // Real-time search auto-expand: expand all matching project groups when query changes
  const prevSearchQueryRef = useRef('');

  useEffect(() => {
    const currentQuery = searchQuery.trim().toLowerCase();
    const prevQuery = prevSearchQueryRef.current;

    if (currentQuery && currentQuery !== prevQuery) {
      setExpandedProjects(prev => {
        const next = { ...prev };
        groupedProjects.forEach(group => {
          next[group.name] = true;
        });
        return next;
      });
    }

    prevSearchQueryRef.current = currentQuery;
  }, [searchQuery, groupedProjects]);

  const toggleProject = (projectName) => {
    setExpandedProjects(prev => {
      const currentlyExpanded = prev[projectName] !== false;
      return {
        ...prev,
        [projectName]: !currentlyExpanded
      };
    });
  };

  const handleExpandAll = () => {
    const next = {};
    allProjectNames.forEach(name => {
      next[name] = true;
    });
    setExpandedProjects(next);
  };

  const handleCollapseAll = () => {
    const next = {};
    allProjectNames.forEach(name => {
      next[name] = false;
    });
    setExpandedProjects(next);
  };

  const handleContainerAction = async (containerId, action) => {
    setActionLoading(prev => ({ ...prev, [containerId]: true }));
    setActionMessage(null);

    try {
      const res = await axios.post(`/api/metrics/docker/control?containerId=${encodeURIComponent(containerId)}&action=${encodeURIComponent(action)}`);
      if (res.data && res.data.status === 'success') {
        setActionMessage({ type: 'success', text: `Action '${action}' executed successfully on container ${containerId}` });
        fetchDockerData();
      } else {
        setActionMessage({ type: 'error', text: `Failed to ${action} container: ${res.data.message || 'Error'}` });
      }
    } catch (err) {
      setActionMessage({ type: 'error', text: `Error executing container action: ${err.message}` });
    } finally {
      setActionLoading(prev => ({ ...prev, [containerId]: false }));
      setTimeout(() => setActionMessage(null), 5000);
    }
  };

  const handleProjectAction = async (projectName, action, workingDir) => {
    if (!projectName || !action) return;
    if (projectActionLoading[projectName]) return;

    setProjectActionLoading(prev => ({ ...prev, [projectName]: action }));
    setActionMessage(null);

    try {
      const res = await axios.post('/api/metrics/docker/project/control', {
        project: projectName,
        action: action,
        workingDir: workingDir || `/home/kirito/${projectName}`
      });

      if (res.data && res.data.status === 'success') {
        setActionMessage({
          type: 'success',
          text: `PROJECT [${projectName.toUpperCase()}]: ${action.toUpperCase()} ALL hoàn tất thành công.`
        });
        fetchDockerData();
      } else {
        const errorDetail = res.data?.message || 'Lỗi không xác định từ máy chủ.';
        setActionMessage({
          type: 'error',
          text: `PROJECT [${projectName.toUpperCase()}]: Thất bại khi ${action} — ${errorDetail}`
        });
      }
    } catch (err) {
      const errorDetail = err.response?.data?.message || err.message || 'Lỗi kết nối';
      setActionMessage({
        type: 'error',
        text: `PROJECT [${projectName.toUpperCase()}]: Lỗi thực thi ${action} — ${errorDetail}`
      });
    } finally {
      setProjectActionLoading(prev => ({ ...prev, [projectName]: null }));
      setTimeout(() => setActionMessage(null), 6000);
    }
  };

  // M4 Dirty Tracking & Computed Line Numbers
  const isModified = envRawContent !== envInitialContent;

  const lineCount = useMemo(() => {
    const content = envMaskedMode ? maskEnvSecrets(envRawContent) : envRawContent;
    if (!content) return 1;
    return content.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n').length;
  }, [envMaskedMode, envRawContent]);

  const lineNumbers = useMemo(() => {
    return Array.from({ length: Math.max(lineCount, 1) }, (_, i) => i + 1);
  }, [lineCount]);

  const handleTextareaScroll = (e) => {
    if (gutterRef.current) {
      gutterRef.current.scrollTop = e.target.scrollTop;
    }
  };

  const openEnvEditor = async (projectName, workingDir) => {
    const dir = workingDir || '';
    const defaultPath = dir ? `${dir}/.env` : `/home/kirito/${projectName}/.env`;
    setEnvProject(projectName);
    setEnvWorkingDir(dir);
    setEnvFilePath(defaultPath);
    setEnvHasBackup(false);
    setEnvRawContent('');
    setEnvInitialContent('');
    setEnvMaskedMode(true);
    setEnvRestartAfterSave(true);
    setEnvCopySuccess(false);
    setEnvShowConfirmClose(false);
    setEnvModalOpen(true);
    setEnvLoading(true);

    try {
      const res = await axios.get(
        `/api/metrics/docker/env?project=${encodeURIComponent(projectName)}&workingDir=${encodeURIComponent(dir)}`
      );
      if (res.data && res.data.status === 'success') {
        const rawContent = res.data.content || '';
        const decoded = safeDecodeBase64(rawContent).replace(/\r\n/g, '\n').replace(/\r/g, '\n');
        setEnvRawContent(decoded);
        setEnvInitialContent(decoded);
        if (res.data.filePath) {
          setEnvFilePath(res.data.filePath);
        }
        setEnvHasBackup(Boolean(res.data.hasBackup));
      } else {
        const errorMsg = res.data?.message || 'Không thể đọc tệp .env từ máy chủ.';
        setEnvRawContent('# Tệp .env chưa tồn tại hoặc rỗng trên máy chủ.\n# Bạn có thể khởi tạo các biến môi trường tại đây:\n');
        setEnvInitialContent('');
        setActionMessage({
          type: 'info',
          text: `[ENV CONFIG] ${errorMsg}`
        });
      }
    } catch (err) {
      const errorMsg = err.response?.data?.message || err.message || 'Lỗi kết nối khi tải .env';
      setEnvRawContent('# Lỗi kết nối khi tải tệp .env từ máy chủ.\n# Vui lòng kiểm tra quyền truy cập hoặc thử lại sau.\n');
      setEnvInitialContent('');
      setActionMessage({
        type: 'error',
        text: `[ENV CONFIG ERROR] ${errorMsg}`
      });
    } finally {
      setEnvLoading(false);
    }
  };

  const forceCloseEnvModal = () => {
    setEnvModalOpen(false);
    setEnvShowConfirmClose(false);
    setEnvProject('');
    setEnvWorkingDir('');
    setEnvRawContent('');
    setEnvInitialContent('');
    setEnvCopySuccess(false);
  };

  const handleCloseEnvModal = () => {
    if (envRawContent !== envInitialContent) {
      setEnvShowConfirmClose(true);
    } else {
      forceCloseEnvModal();
    }
  };

  const handleCopyEnvContent = async () => {
    if (!envRawContent) return;
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(envRawContent);
      } else {
        const ta = document.createElement('textarea');
        ta.value = envRawContent;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }
      setEnvCopySuccess(true);
      setTimeout(() => setEnvCopySuccess(false), 2000);
    } catch (err) {
      console.error('Failed to copy .env content to clipboard:', err);
    }
  };

  const handleReloadEnv = () => {
    if (isModified) {
      const confirmReload = window.confirm('Tải lại từ máy chủ sẽ hủy bỏ mọi thay đổi chưa lưu trong file .env. Bạn có chắc chắn muốn tải lại?');
      if (!confirmReload) return;
    }
    if (envProject) {
      setEnvLoading(true);
      axios.get(`/api/metrics/docker/env?project=${encodeURIComponent(envProject)}&workingDir=${encodeURIComponent(envWorkingDir || '')}`)
        .then(res => {
          if (res.data && res.data.status === 'success') {
            const rawContent = res.data.content || '';
            const decoded = safeDecodeBase64(rawContent).replace(/\r\n/g, '\n').replace(/\r/g, '\n');
            setEnvRawContent(decoded);
            setEnvInitialContent(decoded);
            if (res.data.filePath) setEnvFilePath(res.data.filePath);
            setEnvHasBackup(Boolean(res.data.hasBackup));
            setActionMessage({
              type: 'success',
              text: `[ENV CONFIG] Đã tải lại tệp .env cho dự án '${envProject}'.`
            });
          } else {
            setActionMessage({
              type: 'error',
              text: `[ENV CONFIG] ${res.data?.message || 'Không thể tải lại tệp .env'}`
            });
          }
        })
        .catch(err => {
          setActionMessage({
            type: 'error',
            text: `[ENV CONFIG ERROR] Lỗi khi tải lại .env: ${err.message}`
          });
        })
        .finally(() => {
          setEnvLoading(false);
        });
    }
  };

  const saveEnvContent = async () => {
    if (envSaving || !isModified || envMaskedMode) {
      return;
    }
    if (!envProject) {
      setActionMessage({
        type: 'error',
        text: '[ENV CONFIG ERROR] Không xác định được tên dự án để lưu file .env.'
      });
      return;
    }

    setEnvSaving(true);
    try {
      const res = await axios.post('/api/metrics/docker/env', {
        project: envProject,
        workingDir: envWorkingDir,
        content: envRawContent,
        restartProject: envRestartAfterSave
      });

      if (res.data && res.data.status === 'success') {
        setEnvInitialContent(envRawContent);
        setEnvHasBackup(true);
        const backupMsg = res.data.backupPath ? ` (Backup: ${res.data.backupPath.split('/').pop()})` : '';
        setActionMessage({
          type: 'success',
          text: `[ENV CONFIG] Đã lưu file .env cho dự án '${envProject}' thành công!${backupMsg}`
        });

        if (envRestartAfterSave) {
          setActionMessage({
            type: 'info',
            text: `[DOCKER COMPOSE] Đang khởi động lại dự án '${envProject}'...`
          });
          setTimeout(() => {
            fetchDockerData();
          }, 2500);
        }
      } else {
        const errorMsg = res.data?.message || 'Lỗi không xác định khi lưu file .env';
        setActionMessage({
          type: 'error',
          text: `[ENV CONFIG ERROR] ${errorMsg}`
        });
      }
    } catch (err) {
      const errorMsg = err.response?.data?.message || err.message || 'Lỗi kết nối khi lưu .env';
      setActionMessage({
        type: 'error',
        text: `[ENV CONFIG ERROR] ${errorMsg}`
      });
    } finally {
      setEnvSaving(false);
    }
  };

  const fetchContainerLogs = async (containerId, lines = 100) => {
    setIsLogsLoading(true);
    try {
      const res = await axios.get(`/api/metrics/docker/logs?containerId=${encodeURIComponent(containerId)}&lines=${lines}`);
      if (res.data && res.data.data) {
        setLogContent(res.data.data);
      } else {
        setLogContent('No logs returned or container stopped.');
      }
    } catch (err) {
      setLogContent(`Failed to fetch container logs: ${err.message}`);
    } finally {
      setIsLogsLoading(false);
    }
  };

  const openLogViewer = (id, name) => {
    setLogContainer({ id, name });
    fetchContainerLogs(id, logLinesCount);
  };

  const totalContainers = containers.length;
  const runningCount = containers.filter(c => (c.status || '').toLowerCase().includes('up')).length;
  const stoppedCount = totalContainers - runningCount;

  const handleCopyLogs = () => {
    if (!logContent) return;
    navigator.clipboard.writeText(logContent);
    setCopySuccess(true);
    setTimeout(() => setCopySuccess(false), 2000);
  };

  return (
    <div style={{ padding: '20px', height: '100%', display: 'flex', flexDirection: 'column', gap: '16px', overflowY: 'auto' }}>
      
      {/* Action Message Toast */}
      {actionMessage && (
        <div style={{
          background: actionMessage.type === 'success' 
            ? 'rgba(0, 255, 157, 0.15)' 
            : actionMessage.type === 'info'
            ? 'rgba(0, 243, 255, 0.15)'
            : 'rgba(255, 0, 85, 0.15)',
          border: actionMessage.type === 'success' 
            ? '1px solid var(--accent-green)' 
            : actionMessage.type === 'info'
            ? '1px solid var(--accent-cyan)'
            : '1px solid var(--accent-pink)',
          color: actionMessage.type === 'success' 
            ? 'var(--accent-green)' 
            : actionMessage.type === 'info'
            ? 'var(--accent-cyan)'
            : 'var(--accent-pink)',
          padding: '10px 16px',
          borderRadius: '4px',
          fontFamily: 'Share Tech Mono',
          fontSize: '0.85rem',
          fontWeight: 'bold',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <span>{actionMessage.text}</span>
          <button 
            type="button"
            onClick={() => setActionMessage(null)} 
            style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }}
          >
            ✕
          </button>
        </div>
      )}

      {/* Header Bar */}
      <div className="glass-panel" style={{ padding: '16px 20px', display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <SciFiContainerIcon size={28} color="var(--accent-green)" />
          <div>
            <h2 className="title-glow" style={{ margin: 0, fontSize: '1.2rem', letterSpacing: '1px' }}>
              DOCKER CONTAINER MANAGER & STATS
            </h2>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>
              CONTAINERIZED APPLICATION ORCHESTRATION & METRICS
            </span>
          </div>
        </div>

        <button
          type="button"
          onClick={fetchDockerData}
          disabled={loading}
          style={{
            background: 'rgba(0, 255, 157, 0.1)',
            border: '1px solid var(--accent-green)',
            color: 'var(--accent-green)',
            padding: '6px 14px',
            fontFamily: 'Share Tech Mono',
            fontSize: '0.8rem',
            fontWeight: 'bold',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            borderRadius: '3px'
          }}
        >
          <SciFiRefreshIcon size={14} color="var(--accent-green)" />
          <span>REFRESH DOCKER</span>
        </button>
      </div>

      {/* KPI Cards Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
        
        <div className="glass-panel" style={{ padding: '16px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ padding: '10px', borderRadius: '50%', background: 'rgba(0, 243, 255, 0.1)', border: '1px solid var(--accent-cyan)' }}>
            <SciFiContainerIcon size={24} color="var(--accent-cyan)" />
          </div>
          <div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>TOTAL CONTAINERS</div>
            <div style={{ fontSize: '1.6rem', fontWeight: 'bold', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono' }}>{totalContainers}</div>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '16px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ padding: '10px', borderRadius: '50%', background: 'rgba(0, 255, 157, 0.1)', border: '1px solid var(--accent-green)' }}>
            <SciFiPulseBadge size={24} color="var(--accent-green)" />
          </div>
          <div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>RUNNING / ACTIVE</div>
            <div style={{ fontSize: '1.6rem', fontWeight: 'bold', color: 'var(--accent-green)', fontFamily: 'Share Tech Mono' }}>{runningCount}</div>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '16px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ padding: '10px', borderRadius: '50%', background: 'rgba(255, 0, 85, 0.1)', border: '1px solid var(--accent-pink)' }}>
            <SciFiStopIcon size={20} color="var(--accent-pink)" />
          </div>
          <div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>STOPPED / EXITED</div>
            <div style={{ fontSize: '1.6rem', fontWeight: 'bold', color: 'var(--accent-pink)', fontFamily: 'Share Tech Mono' }}>{stoppedCount}</div>
          </div>
        </div>

        <div className="glass-panel" style={{ padding: '16px', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>DAEMON STATUS</div>
            <div style={{ fontSize: '1.1rem', fontWeight: 'bold', color: dockerStatus === 'RUNNING' ? 'var(--accent-green)' : 'var(--accent-pink)', fontFamily: 'Share Tech Mono', marginTop: '4px' }}>
              {dockerStatus}
            </div>
          </div>
        </div>

      </div>

      {/* Filter & Search Bar */}
      <div className="glass-panel" style={{ padding: '12px 16px', display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
        
        {/* Left Side: Status Tabs + Expand/Collapse All Buttons */}
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
          {/* Status Tabs */}
          <div style={{ display: 'flex', gap: '8px' }}>
            {['ALL', 'RUNNING', 'EXITED'].map(st => (
              <button
                key={st}
                type="button"
                onClick={() => setStatusFilter(st)}
                style={{
                  background: statusFilter === st ? 'rgba(0, 255, 157, 0.2)' : 'rgba(0,0,0,0.4)',
                  border: statusFilter === st ? '1px solid var(--accent-green)' : '1px solid rgba(0, 255, 157, 0.2)',
                  color: statusFilter === st ? 'var(--accent-green)' : '#ccc',
                  padding: '4px 12px',
                  fontSize: '0.75rem',
                  fontFamily: 'Share Tech Mono',
                  borderRadius: '3px',
                  cursor: 'pointer'
                }}
              >
                {st}
              </button>
            ))}
          </div>

          {/* Separator */}
          <div style={{ width: '1px', height: '18px', background: 'rgba(0, 243, 255, 0.2)' }} />

          {/* Expand / Collapse All 1-touch Buttons */}
          <div style={{ display: 'flex', gap: '6px' }}>
            <button
              type="button"
              onClick={handleExpandAll}
              style={{
                background: 'rgba(0, 243, 255, 0.08)',
                border: '1px solid rgba(0, 243, 255, 0.3)',
                color: 'var(--accent-cyan)',
                padding: '4px 10px',
                fontSize: '0.75rem',
                fontFamily: 'Share Tech Mono',
                borderRadius: '3px',
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '5px'
              }}
              title="Expand all project sections"
            >
              <span>▼</span>
              <span>EXPAND ALL</span>
            </button>

            <button
              type="button"
              onClick={handleCollapseAll}
              style={{
                background: 'rgba(255, 255, 255, 0.04)',
                border: '1px solid rgba(255, 255, 255, 0.2)',
                color: '#aaa',
                padding: '4px 10px',
                fontSize: '0.75rem',
                fontFamily: 'Share Tech Mono',
                borderRadius: '3px',
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '5px'
              }}
              title="Collapse all project sections"
            >
              <span>▶</span>
              <span>COLLAPSE ALL</span>
            </button>
          </div>
        </div>

        {/* Right Side: Real-time Search Field */}
        <div style={{ position: 'relative', minWidth: '260px' }}>
          <input
            type="text"
            placeholder="Search service, name, ID, image, project..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            style={{
              width: '100%',
              background: 'rgba(0,0,0,0.4)',
              border: '1px solid rgba(0, 243, 255, 0.25)',
              color: '#fff',
              padding: '6px 10px 6px 30px',
              fontSize: '0.8rem',
              fontFamily: 'Share Tech Mono',
              borderRadius: '3px'
            }}
          />
          <div style={{ position: 'absolute', left: '8px', top: '50%', transform: 'translateY(-50%)' }}>
            <SciFiSearchIcon size={14} color="var(--accent-cyan)" />
          </div>
        </div>

      </div>

      {/* Containers Grouped Accordion Table */}
      <div className="glass-panel" style={{ flex: 1, padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        
        {dockerStatus === 'NOT_INSTALLED' ? (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--accent-pink)', fontFamily: 'Share Tech Mono', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
            <SciFiWarningIcon size={16} color="var(--accent-pink)" />
            <span>DOCKER IS NOT INSTALLED OR DAEMON IS NOT RUNNING ON SSH HOST</span>
          </div>
        ) : loading && containers.length === 0 ? (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--accent-green)', fontFamily: 'Share Tech Mono' }}>
            FETCHING DOCKER CONTAINERS...
          </div>
        ) : groupedProjects.length === 0 ? (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>
            No containers matching filter criteria: &quot;{searchQuery || statusFilter}&quot;
          </div>
        ) : (
          <div style={{ overflowX: 'auto', flex: 1 }}>
            <table className="sci-fi-table" style={{ width: '100%', minWidth: '1050px', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={{ minWidth: '220px' }}>SERVICE / NAME</th>
                  <th style={{ width: '130px' }}>CONTAINER ID</th>
                  <th style={{ minWidth: '170px' }}>IMAGE</th>
                  <th style={{ minWidth: '150px' }}>STATUS</th>
                  <th style={{ minWidth: '150px' }}>PORTS</th>
                  <th style={{ width: '90px' }}>CPU %</th>
                  <th style={{ width: '130px' }}>MEM USAGE</th>
                  <th style={{ width: '130px' }}>NET I/O</th>
                  <th style={{ width: '170px', textAlign: 'center' }}>ACTIONS</th>
                </tr>
              </thead>

              {groupedProjects.map(group => {
                const isExpanded = expandedProjects[group.name] !== false;
                const currentProjAction = projectActionLoading[group.name];
                const isProjBusy = !!currentProjAction;

                return (
                  <tbody key={group.name} style={{ borderBottom: '2px solid rgba(0, 243, 255, 0.2)' }}>
                    {/* Project Accordion Header Row */}
                    <tr
                      onClick={() => toggleProject(group.name)}
                      style={{
                        cursor: 'pointer',
                        background: 'linear-gradient(90deg, rgba(0, 243, 255, 0.08) 0%, rgba(9, 10, 15, 0.95) 100%)',
                        borderTop: '1px solid rgba(0, 243, 255, 0.3)',
                        borderBottom: '1px solid rgba(0, 243, 255, 0.2)',
                        userSelect: 'none'
                      }}
                    >
                      <td colSpan={9} style={{ padding: '8px 14px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px' }}>
                          
                          {/* Left side: Toggle Arrow, SciFiFolderIcon, Project Name, Status Badge, WorkingDir */}
                          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                            <span style={{
                              color: 'var(--accent-cyan)',
                              fontSize: '0.8rem',
                              transition: 'transform 0.15s ease',
                              display: 'inline-block',
                              transform: isExpanded ? 'rotate(0deg)' : 'rotate(-90deg)',
                              fontFamily: 'Share Tech Mono'
                            }}>
                              ▼
                            </span>

                            {group.isStandalone ? (
                              <SciFiContainerIcon size={18} color="rgba(0, 243, 255, 0.7)" />
                            ) : (
                              <SciFiFolderIcon size={18} color="var(--accent-cyan)" />
                            )}

                            <span style={{
                              fontFamily: 'Share Tech Mono',
                              fontWeight: 'bold',
                              fontSize: '0.95rem',
                              color: group.isStandalone ? 'var(--accent-yellow)' : '#fff',
                              letterSpacing: '1px',
                              textShadow: '0 0 8px rgba(0, 243, 255, 0.3)'
                            }}>
                              {group.name.toUpperCase()}
                            </span>

                            {/* Aggregated Status Badge */}
                            <span style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              padding: '2px 8px',
                              borderRadius: '3px',
                              fontSize: '0.72rem',
                              fontFamily: 'Share Tech Mono',
                              fontWeight: 'bold',
                              gap: '5px',
                              background: group.statusType === 'RUNNING'
                                ? 'rgba(0, 255, 102, 0.12)'
                                : group.statusType === 'MIXED'
                                ? 'rgba(255, 187, 0, 0.12)'
                                : 'rgba(255, 0, 85, 0.12)',
                              border: `1px solid ${
                                group.statusType === 'RUNNING'
                                  ? 'var(--accent-green)'
                                  : group.statusType === 'MIXED'
                                  ? 'var(--accent-yellow)'
                                  : 'var(--accent-pink)'
                              }`,
                              color: group.statusType === 'RUNNING'
                                ? 'var(--accent-green)'
                                : group.statusType === 'MIXED'
                                ? 'var(--accent-yellow)'
                                : 'var(--accent-pink)'
                            }}>
                              <span style={{
                                display: 'inline-block',
                                width: '6px',
                                height: '6px',
                                borderRadius: '50%',
                                background: 'currentColor',
                                boxShadow: '0 0 6px currentColor'
                              }} />
                              <span>{group.statusBadgeText}</span>
                              {group.matchingCount < group.rawTotalCount && (
                                <span style={{ opacity: 0.75, fontWeight: 'normal' }}>
                                  ({group.matchingCount} shown)
                                </span>
                              )}
                            </span>

                            {/* Working Directory Chip */}
                            {!group.isStandalone && group.workingDir && (
                              <span
                                title={group.workingDir}
                                style={{
                                  fontSize: '0.7rem',
                                  fontFamily: 'Share Tech Mono',
                                  color: 'rgba(224, 242, 254, 0.7)',
                                  background: 'rgba(0, 243, 255, 0.05)',
                                  border: '1px solid rgba(0, 243, 255, 0.15)',
                                  padding: '2px 6px',
                                  borderRadius: '2px',
                                  maxWidth: '260px',
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                  whiteSpace: 'nowrap'
                                }}
                              >
                                📁 {group.workingDir}
                              </span>
                            )}
                          </div>

                          {/* Right side: Project Quick Action buttons cluster */}
                          <div
                            onClick={e => e.stopPropagation()}
                            style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'nowrap' }}
                          >
                            {!group.isStandalone ? (
                              <>
                                {/* .ENV Button */}
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    openEnvEditor(group.name, group.workingDir);
                                  }}
                                  disabled={isProjBusy}
                                  title={isProjBusy ? 'Đang thực thi tác vụ khác...' : `Xem & Chỉnh sửa cấu hình .env của ${group.name}`}
                                  style={{
                                    background: 'rgba(0, 243, 255, 0.12)',
                                    border: '1px solid var(--accent-cyan)',
                                    color: 'var(--accent-cyan)',
                                    padding: '3px 8px',
                                    fontSize: '0.72rem',
                                    fontFamily: 'Share Tech Mono',
                                    fontWeight: 'bold',
                                    cursor: isProjBusy ? 'not-allowed' : 'pointer',
                                    borderRadius: '3px',
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '4px',
                                    opacity: isProjBusy ? 0.45 : 1
                                  }}
                                >
                                  <SciFiFileIcon size={12} color="var(--accent-cyan)" />
                                  <span>.ENV</span>
                                </button>

                                {/* START ALL */}
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleProjectAction(group.name, 'start', group.workingDir);
                                  }}
                                  disabled={isProjBusy}
                                  title={isProjBusy ? 'Đang thực thi tác vụ...' : `Khởi động toàn bộ container trong ${group.name}`}
                                  style={{
                                    background: 'rgba(0, 255, 102, 0.12)',
                                    border: '1px solid var(--accent-green)',
                                    color: 'var(--accent-green)',
                                    padding: '3px 8px',
                                    fontSize: '0.72rem',
                                    fontFamily: 'Share Tech Mono',
                                    fontWeight: 'bold',
                                    cursor: isProjBusy ? 'not-allowed' : 'pointer',
                                    borderRadius: '3px',
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '4px',
                                    opacity: isProjBusy && currentProjAction !== 'start' ? 0.45 : 1
                                  }}
                                >
                                  {currentProjAction === 'start' ? (
                                    <>
                                      <SciFiChronoSpinnerIcon size={12} color="var(--accent-green)" />
                                      <span>STARTING...</span>
                                    </>
                                  ) : (
                                    <>
                                      <SciFiPlayIcon size={11} color="var(--accent-green)" />
                                      <span>START ALL</span>
                                    </>
                                  )}
                                </button>

                                {/* STOP ALL */}
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleProjectAction(group.name, 'stop', group.workingDir);
                                  }}
                                  disabled={isProjBusy}
                                  title={isProjBusy ? 'Đang thực thi tác vụ...' : `Dừng toàn bộ container trong ${group.name}`}
                                  style={{
                                    background: 'rgba(255, 0, 85, 0.12)',
                                    border: '1px solid var(--accent-pink)',
                                    color: 'var(--accent-pink)',
                                    padding: '3px 8px',
                                    fontSize: '0.72rem',
                                    fontFamily: 'Share Tech Mono',
                                    fontWeight: 'bold',
                                    cursor: isProjBusy ? 'not-allowed' : 'pointer',
                                    borderRadius: '3px',
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '4px',
                                    opacity: isProjBusy && currentProjAction !== 'stop' ? 0.45 : 1
                                  }}
                                >
                                  {currentProjAction === 'stop' ? (
                                    <>
                                      <SciFiChronoSpinnerIcon size={12} color="var(--accent-pink)" />
                                      <span>STOPPING...</span>
                                    </>
                                  ) : (
                                    <>
                                      <SciFiStopIcon size={11} color="var(--accent-pink)" />
                                      <span>STOP ALL</span>
                                    </>
                                  )}
                                </button>

                                {/* RESTART ALL */}
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleProjectAction(group.name, 'restart', group.workingDir);
                                  }}
                                  disabled={isProjBusy}
                                  title={isProjBusy ? 'Đang thực thi tác vụ...' : `Khởi động lại toàn bộ container trong ${group.name}`}
                                  style={{
                                    background: 'rgba(255, 187, 0, 0.12)',
                                    border: '1px solid var(--accent-yellow)',
                                    color: 'var(--accent-yellow)',
                                    padding: '3px 8px',
                                    fontSize: '0.72rem',
                                    fontFamily: 'Share Tech Mono',
                                    fontWeight: 'bold',
                                    cursor: isProjBusy ? 'not-allowed' : 'pointer',
                                    borderRadius: '3px',
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '4px',
                                    opacity: isProjBusy && currentProjAction !== 'restart' ? 0.45 : 1
                                  }}
                                >
                                  {currentProjAction === 'restart' ? (
                                    <>
                                      <SciFiChronoSpinnerIcon size={12} color="var(--accent-yellow)" />
                                      <span>RESTARTING...</span>
                                    </>
                                  ) : (
                                    <>
                                      <SciFiRefreshIcon size={11} color="var(--accent-yellow)" />
                                      <span>RESTART ALL</span>
                                    </>
                                  )}
                                </button>
                              </>
                            ) : (
                              <div style={{
                                fontFamily: 'Share Tech Mono',
                                fontSize: '0.72rem',
                                color: 'var(--text-secondary)',
                                fontStyle: 'italic',
                                padding: '2px 8px',
                                border: '1px dashed rgba(255, 255, 255, 0.15)',
                                borderRadius: '3px',
                                userSelect: 'none'
                              }}>
                                [STANDALONE — NO COMPOSE ACTIONS]
                              </div>
                            )}
                          </div>

                        </div>
                      </td>
                    </tr>

                    {/* Child Container Rows (Tree Branch Visual) */}
                    {isExpanded && group.containers.map((c, cIdx) => {
                      const isLast = cIdx === group.containers.length - 1;
                      const isUp = (c.status || '').toLowerCase().includes('up');
                      const stat = dockerStats[c.id] || dockerStats[c.name] || {};
                      const isActLoading = actionLoading[c.id] || isProjBusy;

                      return (
                        <tr
                          key={c.id || cIdx}
                          style={{
                            background: 'rgba(9, 10, 15, 0.55)',
                            borderLeft: '3px solid rgba(0, 243, 255, 0.3)'
                          }}
                        >
                          {/* 1. SERVICE / NAME (Tree Branch glyph) */}
                          <td style={{ paddingLeft: '24px', verticalAlign: 'middle' }}>
                            <div style={{ display: 'flex', alignItems: 'center' }}>
                              <span style={{
                                color: 'var(--accent-cyan)',
                                fontFamily: 'Share Tech Mono',
                                fontSize: '0.9rem',
                                marginRight: '6px',
                                userSelect: 'none',
                                opacity: 0.8
                              }}>
                                {isLast ? '└─' : '├─'}
                              </span>
                              <div>
                                <span style={{ fontWeight: 'bold', color: '#fff' }}>
                                  {c.service || c.name || '-'}
                                </span>
                                {c.service && c.name && c.service !== c.name && (
                                  <div style={{ fontSize: '0.72rem', color: 'rgba(224, 242, 254, 0.55)', fontFamily: 'Share Tech Mono' }}>
                                    ({c.name})
                                  </div>
                                )}
                              </div>
                            </div>
                          </td>

                          {/* 2. CONTAINER ID */}
                          <td style={{ fontFamily: 'Share Tech Mono', color: 'var(--accent-cyan)', fontWeight: 'bold' }}>
                            {c.id}
                          </td>

                          {/* 3. IMAGE */}
                          <td style={{ fontFamily: 'Share Tech Mono', fontSize: '0.78rem', opacity: 0.85 }} title={c.image}>
                            {c.image}
                          </td>

                          {/* 4. STATUS */}
                          <td>
                            <span style={{
                              padding: '3px 8px',
                              borderRadius: '3px',
                              fontSize: '0.73rem',
                              fontFamily: 'Share Tech Mono',
                              fontWeight: 'bold',
                              whiteSpace: 'nowrap',
                              display: 'inline-block',
                              background: isUp ? 'rgba(0, 255, 102, 0.12)' : 'rgba(255, 0, 85, 0.12)',
                              border: isUp ? '1px solid var(--accent-green)' : '1px solid var(--accent-pink)',
                              color: isUp ? 'var(--accent-green)' : 'var(--accent-pink)'
                            }}>
                              {c.status}
                            </span>
                          </td>

                          {/* 5. PORTS */}
                          <td style={{ fontFamily: 'Share Tech Mono', fontSize: '0.75rem', opacity: 0.75 }}>
                            {c.ports || '—'}
                          </td>

                          {/* 6. CPU % */}
                          <td style={{ fontFamily: 'Share Tech Mono', fontSize: '0.8rem', color: 'var(--accent-yellow)' }}>
                            {stat.cpu || (isUp ? '—' : '0.00%')}
                          </td>

                          {/* 7. MEM USAGE */}
                          <td style={{ fontFamily: 'Share Tech Mono', fontSize: '0.8rem', color: 'var(--accent-cyan)' }}>
                            {stat.mem || (isUp ? '—' : '0B / 0B')}
                          </td>

                          {/* 8. NET I/O */}
                          <td style={{ fontFamily: 'Share Tech Mono', fontSize: '0.78rem', opacity: 0.8 }}>
                            {stat.netIO || '0B / 0B'}
                          </td>

                          {/* 9. ACTIONS */}
                          <td style={{ textAlign: 'center' }}>
                            <div style={{ display: 'flex', gap: '6px', justifyContent: 'center' }}>
                              {isUp ? (
                                <button
                                  type="button"
                                  onClick={() => handleContainerAction(c.id, 'stop')}
                                  disabled={isActLoading}
                                  style={{
                                    background: 'rgba(255, 0, 85, 0.15)',
                                    border: '1px solid var(--accent-pink)',
                                    color: 'var(--accent-pink)',
                                    padding: '2px 6px',
                                    fontSize: '0.7rem',
                                    fontFamily: 'Share Tech Mono',
                                    cursor: isActLoading ? 'not-allowed' : 'pointer',
                                    borderRadius: '3px',
                                    opacity: isActLoading ? 0.5 : 1
                                  }}
                                  title="Stop Container"
                                >
                                  STOP
                                </button>
                              ) : (
                                <button
                                  type="button"
                                  onClick={() => handleContainerAction(c.id, 'start')}
                                  disabled={isActLoading}
                                  style={{
                                    background: 'rgba(0, 255, 102, 0.15)',
                                    border: '1px solid var(--accent-green)',
                                    color: 'var(--accent-green)',
                                    padding: '2px 6px',
                                    fontSize: '0.7rem',
                                    fontFamily: 'Share Tech Mono',
                                    cursor: isActLoading ? 'not-allowed' : 'pointer',
                                    borderRadius: '3px',
                                    opacity: isActLoading ? 0.5 : 1
                                  }}
                                  title="Start Container"
                                >
                                  START
                                </button>
                              )}

                              <button
                                type="button"
                                onClick={() => handleContainerAction(c.id, 'restart')}
                                disabled={isActLoading}
                                style={{
                                  background: 'rgba(0, 243, 255, 0.15)',
                                  border: '1px solid var(--accent-cyan)',
                                  color: 'var(--accent-cyan)',
                                  padding: '2px 6px',
                                  fontSize: '0.7rem',
                                  fontFamily: 'Share Tech Mono',
                                  cursor: isActLoading ? 'not-allowed' : 'pointer',
                                  borderRadius: '3px',
                                  opacity: isActLoading ? 0.5 : 1
                                }}
                                title="Restart Container"
                              >
                                RESTART
                              </button>

                              <button
                                type="button"
                                onClick={() => openLogViewer(c.id, c.name)}
                                style={{
                                  background: 'rgba(255, 187, 0, 0.15)',
                                  border: '1px solid var(--accent-yellow)',
                                  color: 'var(--accent-yellow)',
                                  padding: '2px 6px',
                                  fontSize: '0.7rem',
                                  fontFamily: 'Share Tech Mono',
                                  cursor: 'pointer',
                                  borderRadius: '3px'
                                }}
                                title="View Container Logs"
                              >
                                LOGS
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                );
              })}
            </table>
          </div>
        )}

      </div>

      {/* Complete Cyberpunk .env Editor Modal (Milestone 4 Specification) */}
      {envModalOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="env-modal-title"
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(5, 10, 20, 0.85)',
            backdropFilter: 'blur(8px)',
            WebkitBackdropFilter: 'blur(8px)',
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            zIndex: 10000,
            padding: '16px'
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget) {
              handleCloseEnvModal();
            }
          }}
        >
          <div
            className="glass-panel"
            style={{
              width: '94vw',
              maxWidth: '920px',
              height: '680px',
              maxHeight: '88vh',
              display: 'flex',
              flexDirection: 'column',
              border: '1px solid rgba(0, 243, 255, 0.4)',
              boxShadow: '0 0 35px rgba(0, 243, 255, 0.2)',
              padding: 0,
              overflow: 'hidden',
              position: 'relative'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* 1. Modal Header Bar */}
            <div
              style={{
                background: 'linear-gradient(90deg, rgba(0, 243, 255, 0.12) 0%, rgba(9, 10, 15, 0.95) 100%)',
                borderBottom: '1px solid rgba(0, 243, 255, 0.3)',
                padding: '12px 20px',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: '12px',
                flexWrap: 'wrap'
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                <SciFiFileIcon size={22} color="var(--accent-cyan)" />
                <h3
                  id="env-modal-title"
                  style={{
                    margin: 0,
                    fontSize: '1rem',
                    color: '#fff',
                    fontFamily: 'Share Tech Mono',
                    letterSpacing: '1.5px',
                    textShadow: '0 0 8px rgba(0, 243, 255, 0.4)'
                  }}
                >
                  .ENV CONFIGURATION — {envProject.toUpperCase()}
                </h3>

                {/* Target File Path Badge */}
                <span
                  title={envFilePath || (envWorkingDir ? `${envWorkingDir}/.env` : `/home/kirito/${envProject}/.env`)}
                  style={{
                    fontSize: '0.72rem',
                    fontFamily: 'Share Tech Mono',
                    color: 'rgba(224, 242, 254, 0.85)',
                    background: 'rgba(0, 243, 255, 0.08)',
                    border: '1px solid rgba(0, 243, 255, 0.25)',
                    padding: '2px 8px',
                    borderRadius: '3px',
                    maxWidth: '340px',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap'
                  }}
                >
                  📁 {envFilePath || (envWorkingDir ? `${envWorkingDir}/.env` : `/home/kirito/${envProject}/.env`)}
                </span>

                {envHasBackup && (
                  <span
                    title="Đã có file sao lưu (.env.bak) trên máy chủ"
                    style={{
                      fontSize: '0.68rem',
                      fontFamily: 'Share Tech Mono',
                      color: 'var(--accent-green)',
                      background: 'rgba(0, 255, 102, 0.1)',
                      border: '1px solid rgba(0, 255, 102, 0.3)',
                      padding: '1px 6px',
                      borderRadius: '3px'
                    }}
                  >
                    ✓ BACKUP SẴN SÀNG
                  </span>
                )}
              </div>

              {/* Close Button */}
              <button
                type="button"
                onClick={handleCloseEnvModal}
                title="Đóng cửa sổ"
                style={{
                  background: 'rgba(255, 0, 85, 0.12)',
                  border: '1px solid rgba(255, 0, 85, 0.35)',
                  color: 'var(--accent-pink)',
                  fontSize: '1.1rem',
                  lineHeight: 1,
                  cursor: 'pointer',
                  width: '28px',
                  height: '28px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  borderRadius: '3px',
                  transition: 'all 0.2s ease'
                }}
              >
                ✕
              </button>
            </div>

            {/* 2. Action Controls Toolbar */}
            <div
              style={{
                background: 'rgba(5, 8, 16, 0.92)',
                borderBottom: '1px solid rgba(0, 243, 255, 0.18)',
                padding: '8px 20px',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: '10px'
              }}
            >
              {/* Left Action Buttons */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                {/* Toggle Mask Secrets */}
                <button
                  type="button"
                  onClick={() => setEnvMaskedMode(!envMaskedMode)}
                  title={envMaskedMode ? 'Bấm để bỏ che mờ và mở khóa chỉnh sửa' : 'Bấm để che mờ các khóa nhạy cảm và bật ReadOnly'}
                  style={{
                    background: envMaskedMode ? 'rgba(0, 243, 255, 0.18)' : 'rgba(255, 0, 85, 0.12)',
                    border: `1px solid ${envMaskedMode ? 'var(--accent-cyan)' : 'var(--accent-pink)'}`,
                    color: envMaskedMode ? 'var(--accent-cyan)' : 'var(--accent-pink)',
                    padding: '4px 10px',
                    fontFamily: 'Share Tech Mono',
                    fontSize: '0.75rem',
                    fontWeight: 'bold',
                    cursor: 'pointer',
                    borderRadius: '3px',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    boxShadow: envMaskedMode ? '0 0 10px rgba(0, 243, 255, 0.3)' : 'none',
                    transition: 'all 0.2s ease'
                  }}
                >
                  <span>{envMaskedMode ? '👁 MASK SECRETS: ON' : '🔓 MASK SECRETS: OFF'}</span>
                </button>

                {/* Copy Button */}
                <button
                  type="button"
                  onClick={handleCopyEnvContent}
                  title="Sao chép nội dung thực tế (unmasked) vào clipboard"
                  style={{
                    background: envCopySuccess ? 'rgba(0, 255, 102, 0.2)' : 'rgba(255, 255, 255, 0.05)',
                    border: `1px solid ${envCopySuccess ? 'var(--accent-green)' : 'rgba(255, 255, 255, 0.25)'}`,
                    color: envCopySuccess ? 'var(--accent-green)' : '#e0f2fe',
                    padding: '4px 10px',
                    fontFamily: 'Share Tech Mono',
                    fontSize: '0.75rem',
                    cursor: 'pointer',
                    borderRadius: '3px',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '5px',
                    transition: 'all 0.2s ease'
                  }}
                >
                  <span>{envCopySuccess ? '✓ COPIED!' : '📋 COPY'}</span>
                </button>

                {/* Reload Button */}
                <button
                  type="button"
                  onClick={handleReloadEnv}
                  disabled={envLoading}
                  title="Tải lại nội dung từ máy chủ"
                  style={{
                    background: 'rgba(0, 243, 255, 0.08)',
                    border: '1px solid rgba(0, 243, 255, 0.3)',
                    color: 'var(--accent-cyan)',
                    padding: '4px 10px',
                    fontFamily: 'Share Tech Mono',
                    fontSize: '0.75rem',
                    cursor: envLoading ? 'not-allowed' : 'pointer',
                    borderRadius: '3px',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '5px'
                  }}
                >
                  <SciFiRefreshIcon size={12} color="var(--accent-cyan)" />
                  <span>RELOAD</span>
                </button>
              </div>

              {/* Right Status Indicators */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                {/* Modified Status Badge */}
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '3px 10px',
                    borderRadius: '3px',
                    fontSize: '0.72rem',
                    fontFamily: 'Share Tech Mono',
                    fontWeight: 'bold',
                    background: isModified ? 'rgba(255, 187, 0, 0.15)' : 'rgba(0, 255, 102, 0.12)',
                    border: `1px solid ${isModified ? 'var(--accent-yellow)' : 'var(--accent-green)'}`,
                    color: isModified ? 'var(--accent-yellow)' : 'var(--accent-green)',
                    boxShadow: isModified ? '0 0 10px rgba(255, 187, 0, 0.25)' : 'none'
                  }}
                >
                  <span
                    style={{
                      width: '7px',
                      height: '7px',
                      borderRadius: '50%',
                      background: 'currentColor',
                      boxShadow: '0 0 6px currentColor'
                    }}
                  />
                  <span>{isModified ? '● MODIFIED (Chưa lưu)' : '✓ UP TO DATE'}</span>
                </span>

                {/* Line Count Chip */}
                <span
                  style={{
                    fontSize: '0.72rem',
                    fontFamily: 'Share Tech Mono',
                    color: 'rgba(224, 242, 254, 0.65)',
                    background: 'rgba(255, 255, 255, 0.04)',
                    border: '1px solid rgba(255, 255, 255, 0.15)',
                    padding: '2px 8px',
                    borderRadius: '3px'
                  }}
                >
                  L: {lineCount}
                </span>
              </div>
            </div>

            {/* 3. Warning Banner (when masked mode is on) */}
            {envMaskedMode && (
              <div
                style={{
                  background: 'rgba(0, 243, 255, 0.08)',
                  borderBottom: '1px solid rgba(0, 243, 255, 0.25)',
                  padding: '6px 18px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  fontFamily: 'Share Tech Mono',
                  fontSize: '0.75rem',
                  color: 'var(--accent-cyan)'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span>🔒 CHẾ ĐỘ CHE MỜ ĐANG BẬT — Đã ẩn các biến nhạy cảm. Trình soạn thảo đang ở chế độ CHỈ ĐỌC (ReadOnly) để bảo vệ thông tin mật trên server.</span>
                </div>
                <button
                  type="button"
                  onClick={() => setEnvMaskedMode(false)}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: 'var(--accent-yellow)',
                    cursor: 'pointer',
                    fontSize: '0.75rem',
                    fontFamily: 'Share Tech Mono',
                    textDecoration: 'underline',
                    padding: 0,
                    whiteSpace: 'nowrap',
                    marginLeft: '8px'
                  }}
                >
                  Mở khóa để sửa
                </button>
              </div>
            )}

            {/* 4. Editor Body (Line Numbers Gutter + Synchronized Textarea) */}
            <div
              style={{
                flex: 1,
                minHeight: 0,
                display: 'flex',
                overflow: 'hidden',
                background: '#040711',
                position: 'relative'
              }}
            >
              {/* Loading Overlay */}
              {envLoading && (
                <div
                  style={{
                    position: 'absolute',
                    inset: 0,
                    background: 'rgba(4, 7, 17, 0.85)',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '12px',
                    zIndex: 10,
                    fontFamily: 'Share Tech Mono',
                    color: 'var(--accent-cyan)'
                  }}
                >
                  <SciFiChronoSpinnerIcon size={28} color="var(--accent-cyan)" />
                  <span>ĐANG TẢI NỘI DUNG TỆP .ENV TỪ MÁY CHỦ...</span>
                </div>
              )}

              {/* Line Numbers Gutter */}
              <div
                ref={gutterRef}
                aria-hidden="true"
                style={{
                  width: '52px',
                  minWidth: '52px',
                  background: 'rgba(0, 0, 0, 0.4)',
                  color: 'rgba(0, 243, 255, 0.45)',
                  borderRight: '1px solid rgba(0, 243, 255, 0.2)',
                  overflowY: 'hidden',
                  overflowX: 'hidden',
                  userSelect: 'none',
                  padding: '12px 6px',
                  textAlign: 'right',
                  fontFamily: 'Share Tech Mono, monospace',
                  fontSize: '13px',
                  lineHeight: '24px',
                  boxSizing: 'border-box'
                }}
              >
                {lineNumbers.map((num) => (
                  <div
                    key={num}
                    style={{
                      height: '24px',
                      lineHeight: '24px'
                    }}
                  >
                    {num}
                  </div>
                ))}
              </div>

              {/* Textarea */}
              <textarea
                ref={textareaRef}
                value={envMaskedMode ? maskEnvSecrets(envRawContent) : envRawContent}
                onChange={(e) => {
                  if (!envMaskedMode) {
                    setEnvRawContent(e.target.value);
                  }
                }}
                onScroll={handleTextareaScroll}
                readOnly={envMaskedMode || envSaving || envLoading}
                wrap="off"
                spellCheck="false"
                placeholder="# Nhập biến môi trường tại đây..."
                style={{
                  flex: 1,
                  height: '100%',
                  background: 'transparent',
                  color: '#e0f7fa',
                  fontFamily: 'Share Tech Mono, monospace',
                  fontSize: '13px',
                  lineHeight: '24px',
                  padding: '12px',
                  border: 'none',
                  outline: 'none',
                  resize: 'none',
                  whiteSpace: 'pre',
                  overflow: 'auto',
                  boxSizing: 'border-box',
                  cursor: envMaskedMode ? 'not-allowed' : 'text'
                }}
              />
            </div>

            {/* 5. Bottom Action Bar */}
            <div
              style={{
                background: 'rgba(5, 8, 16, 0.95)',
                borderTop: '1px solid rgba(0, 243, 255, 0.25)',
                padding: '12px 20px',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: '12px'
              }}
            >
              {/* Left: Auto-reload Checkbox */}
              <label
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '8px',
                  cursor: 'pointer',
                  fontFamily: 'Share Tech Mono',
                  fontSize: '0.8rem',
                  color: envRestartAfterSave ? 'var(--accent-green)' : 'rgba(224, 242, 254, 0.75)',
                  userSelect: 'none'
                }}
              >
                <input
                  type="checkbox"
                  checked={envRestartAfterSave}
                  onChange={(e) => setEnvRestartAfterSave(e.target.checked)}
                  style={{
                    accentColor: 'var(--accent-green)',
                    width: '16px',
                    height: '16px',
                    cursor: 'pointer'
                  }}
                />
                <span>Tự động tải lại dự án sau khi lưu (docker compose up -d)</span>
              </label>

              {/* Right: Cancel & Save Buttons */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <button
                  type="button"
                  onClick={handleCloseEnvModal}
                  disabled={envSaving}
                  style={{
                    background: 'rgba(255, 255, 255, 0.05)',
                    border: '1px solid rgba(255, 255, 255, 0.25)',
                    color: '#ccc',
                    padding: '7px 18px',
                    fontFamily: 'Share Tech Mono',
                    fontSize: '0.8rem',
                    fontWeight: 'bold',
                    cursor: envSaving ? 'not-allowed' : 'pointer',
                    borderRadius: '3px',
                    transition: 'all 0.2s ease'
                  }}
                >
                  CANCEL
                </button>

                <button
                  type="button"
                  onClick={saveEnvContent}
                  disabled={envSaving || !isModified || envMaskedMode}
                  title={
                    envMaskedMode
                      ? 'Vui lòng tắt Mask Secrets trước khi lưu'
                      : !isModified
                      ? 'Nội dung chưa có thay đổi'
                      : 'Lưu thay đổi vào .env và tạo snapshot dự phòng'
                  }
                  style={{
                    background:
                      !isModified || envMaskedMode
                        ? 'rgba(0, 255, 102, 0.08)'
                        : 'linear-gradient(135deg, #00ff66 0%, #00cc52 100%)',
                    border: `1px solid ${!isModified || envMaskedMode ? 'rgba(0, 255, 102, 0.25)' : 'var(--accent-green)'}`,
                    color: !isModified || envMaskedMode ? 'rgba(0, 255, 102, 0.35)' : '#040810',
                    padding: '7px 22px',
                    fontFamily: 'Share Tech Mono',
                    fontSize: '0.8rem',
                    fontWeight: 'bold',
                    letterSpacing: '1px',
                    cursor: !isModified || envMaskedMode || envSaving ? 'not-allowed' : 'pointer',
                    borderRadius: '3px',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '8px',
                    boxShadow: isModified && !envMaskedMode ? '0 0 16px rgba(0, 255, 102, 0.4)' : 'none',
                    transition: 'all 0.2s ease'
                  }}
                >
                  {envSaving ? (
                    <>
                      <SciFiChronoSpinnerIcon size={14} color="#040810" />
                      <span>SAVING .ENV...</span>
                    </>
                  ) : (
                    <>
                      <span>💾</span>
                      <span>SAVE .ENV</span>
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* 6. Unsaved Changes Confirm Close Dialog */}
            {envShowConfirmClose && (
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  background: 'rgba(5, 10, 20, 0.94)',
                  backdropFilter: 'blur(5px)',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '16px',
                  zIndex: 20,
                  padding: '24px',
                  textAlign: 'center'
                }}
              >
                <div style={{ color: 'var(--accent-yellow)', fontSize: '2rem' }}>⚠️</div>
                <h4
                  style={{
                    margin: 0,
                    fontFamily: 'Share Tech Mono',
                    color: '#fff',
                    fontSize: '1rem',
                    letterSpacing: '1px'
                  }}
                >
                  BẠN CÓ THAY ĐỔI CHƯA LƯU TRONG .ENV
                </h4>
                <p
                  style={{
                    margin: 0,
                    fontFamily: 'Share Tech Mono',
                    color: 'rgba(224, 242, 254, 0.8)',
                    fontSize: '0.85rem',
                    maxWidth: '440px'
                  }}
                >
                  Bạn có thay đổi chưa lưu trong .env của dự án '{envProject}'. Bạn có chắc chắn muốn thoát? Mọi sửa đổi chưa lưu sẽ bị hủy bỏ.
                </p>
                <div style={{ display: 'flex', gap: '12px', marginTop: '8px' }}>
                  <button
                    type="button"
                    onClick={() => setEnvShowConfirmClose(false)}
                    style={{
                      background: 'rgba(0, 243, 255, 0.15)',
                      border: '1px solid var(--accent-cyan)',
                      color: 'var(--accent-cyan)',
                      padding: '8px 18px',
                      fontFamily: 'Share Tech Mono',
                      fontSize: '0.8rem',
                      fontWeight: 'bold',
                      borderRadius: '3px',
                      cursor: 'pointer'
                    }}
                  >
                    TIẾP TỤC CHỈNH SỬA
                  </button>
                  <button
                    type="button"
                    onClick={forceCloseEnvModal}
                    style={{
                      background: 'rgba(255, 0, 85, 0.2)',
                      border: '1px solid var(--accent-pink)',
                      color: 'var(--accent-pink)',
                      padding: '8px 18px',
                      fontFamily: 'Share Tech Mono',
                      fontSize: '0.8rem',
                      fontWeight: 'bold',
                      borderRadius: '3px',
                      cursor: 'pointer'
                    }}
                  >
                    HỦY THAY ĐỔI & THOÁT
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Container Log Viewer Modal */}
      {logContainer && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.85)',
          backdropFilter: 'blur(8px)',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          zIndex: 10000
        }}>
          <div className="glass-panel" style={{
            width: '880px',
            maxWidth: '94vw',
            height: '600px',
            maxHeight: '92vh',
            display: 'flex',
            flexDirection: 'column',
            border: '1px solid var(--accent-green)',
            padding: 0,
            overflow: 'hidden'
          }}>
            {/* Modal Header */}
            <div style={{
              background: 'rgba(0, 255, 157, 0.1)',
              borderBottom: '1px solid rgba(0, 255, 157, 0.3)',
              padding: '12px 18px',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--accent-green)', fontFamily: 'Share Tech Mono', fontWeight: 'bold' }}>
                <SciFiContainerIcon size={20} color="var(--accent-green)" />
                <span>CONTAINER LOGS: {logContainer.name} ({logContainer.id})</span>
              </div>
              <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                <button
                  type="button"
                  onClick={handleCopyLogs}
                  style={{
                    background: copySuccess ? 'rgba(0, 255, 157, 0.2)' : 'rgba(255,255,255,0.08)',
                    border: copySuccess ? '1px solid var(--accent-green)' : '1px solid rgba(255,255,255,0.2)',
                    color: copySuccess ? 'var(--accent-green)' : '#ccc',
                    fontSize: '0.75rem',
                    fontFamily: 'Share Tech Mono',
                    padding: '4px 10px',
                    cursor: 'pointer'
                  }}
                >
                  {copySuccess ? '✓ COPIED' : 'COPY LOGS'}
                </button>
                <button
                  type="button"
                  onClick={() => setLogContainer(null)}
                  style={{ background: 'none', border: 'none', color: 'var(--accent-pink)', fontSize: '1.2rem', cursor: 'pointer', fontWeight: 'bold' }}
                >
                  ✕
                </button>
              </div>
            </div>

            {/* Modal Controls Bar */}
            <div style={{
              background: 'rgba(0,0,0,0.4)',
              borderBottom: '1px solid rgba(0, 255, 157, 0.15)',
              padding: '8px 16px',
              display: 'flex',
              gap: '16px',
              alignItems: 'center',
              flexWrap: 'wrap',
              fontSize: '0.8rem',
              fontFamily: 'Share Tech Mono'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span>TAIL LINES:</span>
                <select
                  value={logLinesCount}
                  onChange={e => {
                    const l = parseInt(e.target.value, 10);
                    setLogLinesCount(l);
                    fetchContainerLogs(logContainer.id, l);
                  }}
                  style={{
                    background: '#000',
                    border: '1px solid rgba(0,255,157,0.3)',
                    color: 'var(--accent-green)',
                    padding: '2px 6px',
                    fontSize: '0.75rem',
                    fontFamily: 'Share Tech Mono'
                  }}
                >
                  <option value={50}>50 Lines</option>
                  <option value={100}>100 Lines</option>
                  <option value={200}>200 Lines</option>
                  <option value={500}>500 Lines</option>
                  <option value={1000}>1000 Lines</option>
                </select>
              </div>

              <button
                type="button"
                onClick={() => fetchContainerLogs(logContainer.id, logLinesCount)}
                style={{
                  background: 'rgba(0,255,157,0.15)',
                  border: '1px solid var(--accent-green)',
                  color: 'var(--accent-green)',
                  padding: '3px 10px',
                  fontSize: '0.75rem',
                  fontFamily: 'Share Tech Mono',
                  cursor: 'pointer'
                }}
              >
                REFRESH LOGS
              </button>
            </div>

            {/* Log Output Console */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
              <LogViewer
                logContent={logContent}
                accentColor="var(--accent-green)"
                isLoading={isLogsLoading}
                loadingText="FETCHING CONTAINER LOGS FROM DOCKER DAEMON..."
                background="#040810"
              />
            </div>

          </div>
        </div>
      )}

    </div>
  );
}