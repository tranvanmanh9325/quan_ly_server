import React, { useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import axios from 'axios';
import { SciFiPulseIcon, SciFiSearchIcon, SciFiKillIcon, SciFiDownloadIcon } from '../components/SciFiIcons';

export default function ProcessesPage() {
  const { processes } = useOutletContext();
  const [searchTerm, setSearchTerm] = useState('');
  const [filterMode, setFilterMode] = useState('ALL'); // ALL, HIGH_CPU, HIGH_MEM
  const [sortBy, setSortBy] = useState('cpu'); // cpu, mem, pid, name
  const [sortOrder, setSortOrder] = useState('desc');

  // Confirmation Modal & Toast State
  const [confirmModal, setConfirmModal] = useState(null); // { pid, name }
  const [toast, setToast] = useState(null); // { message, isError }
  const [actionLoading, setActionLoading] = useState(false);

  const triggerToast = (msg, isError = false) => {
    setToast({ message: msg, isError });
    setTimeout(() => setToast(null), 4000);
  };

  const handleKillClick = (pid, name) => {
    setConfirmModal({ pid, name });
  };

  const confirmKillProcess = async () => {
    if (!confirmModal) return;
    const { pid, name } = confirmModal;
    setActionLoading(true);
    try {
      const res = await axios.post(`/api/metrics/kill-process?pid=${pid}`);
      if (res.data && res.data.status === 'success') {
        triggerToast(`Process [${name}] (PID: ${pid}) terminated successfully!`);
      } else {
        triggerToast(`Failed to kill [${name}]: ${res.data?.message || 'Permission denied'}`, true);
      }
    } catch (err) {
      triggerToast(`Execution error killing [${name}]: ${err.message}`, true);
    } finally {
      setActionLoading(false);
      setConfirmModal(null);
    }
  };

  // Filter processes
  const filtered = processes.filter(p => {
    const matchSearch = p.name.toLowerCase().includes(searchTerm.toLowerCase()) || 
                        p.user.toLowerCase().includes(searchTerm.toLowerCase()) ||
                        String(p.pid).includes(searchTerm);
    if (filterMode === 'HIGH_CPU') return matchSearch && (parseFloat(p.cpu) || 0) >= 20;
    if (filterMode === 'HIGH_MEM') return matchSearch && (parseFloat(p.mem) || 0) >= 100;
    return matchSearch;
  });

  // Sort processes
  const sorted = [...filtered].sort((a, b) => {
    let valA, valB;
    if (sortBy === 'cpu') {
      valA = parseFloat(a.cpu) || 0;
      valB = parseFloat(b.cpu) || 0;
    } else if (sortBy === 'mem') {
      valA = parseFloat(a.mem) || 0;
      valB = parseFloat(b.mem) || 0;
    } else if (sortBy === 'pid') {
      valA = parseInt(a.pid, 10) || 0;
      valB = parseInt(b.pid, 10) || 0;
    } else {
      valA = a.name.toLowerCase();
      valB = b.name.toLowerCase();
    }
    if (valA < valB) return sortOrder === 'asc' ? -1 : 1;
    if (valA > valB) return sortOrder === 'asc' ? 1 : -1;
    return 0;
  });

  const toggleSort = (field) => {
    if (sortBy === field) {
      setSortOrder(prev => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortBy(field);
      setSortOrder('desc');
    }
  };

  const exportProcessesCSV = () => {
    if (sorted.length === 0) {
      triggerToast('No processes to export.', true);
      return;
    }
    const headers = ['PID', 'Name', 'User', 'Threads', 'CPU (%)', 'Memory (MB)', 'Command'];
    const rows = sorted.map(p => [
      p.pid,
      `"${p.name}"`,
      `"${p.user}"`,
      p.threads,
      p.cpu,
      p.mem,
      `"${(p.command || '').replace(/"/g, '""')}"`
    ]);
    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `server_processes_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    triggerToast('Processes exported to CSV successfully!');
  };

  const highCpuCount = processes.filter(p => (parseFloat(p.cpu) || 0) >= 20).length;
  const highMemCount = processes.filter(p => (parseFloat(p.mem) || 0) >= 100).length;

  return (
    <main className="main-content" style={{ display: 'flex', flexDirection: 'column' }}>
      
      {/* Toast Alert */}
      {toast && (
        <div style={{
          padding: '10px 16px',
          marginBottom: '15px',
          borderRadius: '4px',
          background: toast.isError ? 'rgba(255, 0, 85, 0.2)' : 'rgba(0, 243, 255, 0.2)',
          border: toast.isError ? '1px solid var(--accent-pink)' : '1px solid var(--accent-cyan)',
          color: toast.isError ? 'var(--accent-pink)' : 'var(--accent-cyan)',
          fontFamily: 'Share Tech Mono',
          fontSize: '0.85rem',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <span>⚡ {toast.message}</span>
          <button onClick={() => setToast(null)} style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', fontWeight: 'bold' }}>✕</button>
        </div>
      )}

      {/* Sci-Fi Confirmation Modal */}
      {confirmModal && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0, 0, 0, 0.75)',
          backdropFilter: 'blur(6px)',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          zIndex: 9999
        }}>
          <div className="glass-panel" style={{
            width: '420px',
            padding: '24px',
            border: '1px solid var(--accent-pink)',
            boxShadow: '0 0 30px rgba(255, 0, 85, 0.3)',
            display: 'flex',
            flexDirection: 'column',
            gap: '16px'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--accent-pink)' }}>
              <SciFiKillIcon size={24} color="var(--accent-pink)" />
              <h3 style={{ margin: 0, fontFamily: 'Orbitron, sans-serif', letterSpacing: '1px', fontSize: '1.1rem' }}>CONFIRM PROCESS TERMINATION</h3>
            </div>
            
            <p style={{ color: '#ccc', fontSize: '0.85rem', lineHeight: '1.5', margin: 0 }}>
              Are you sure you want to force kill process <strong style={{ color: 'var(--accent-pink)', fontFamily: 'Share Tech Mono' }}>{confirmModal.name}</strong> (PID: <span style={{ color: 'var(--accent-cyan)' }}>{confirmModal.pid}</span>)?
            </p>
            
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', background: 'rgba(255,0,85,0.08)', padding: '8px 12px', borderLeft: '3px solid var(--accent-pink)' }}>
              ⚠️ Warning: Terminating system or user processes may result in unsaved data loss or process instability.
            </div>

            <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '10px' }}>
              <button
                onClick={() => setConfirmModal(null)}
                disabled={actionLoading}
                style={{
                  background: 'rgba(255, 255, 255, 0.08)',
                  border: '1px solid rgba(255, 255, 255, 0.2)',
                  color: '#fff',
                  padding: '6px 16px',
                  fontSize: '0.8rem',
                  fontFamily: 'Share Tech Mono',
                  cursor: 'pointer'
                }}
              >
                CANCEL
              </button>
              <button
                onClick={confirmKillProcess}
                disabled={actionLoading}
                style={{
                  background: 'rgba(255, 0, 85, 0.2)',
                  border: '1px solid var(--accent-pink)',
                  color: 'var(--accent-pink)',
                  padding: '6px 18px',
                  fontSize: '0.8rem',
                  fontFamily: 'Share Tech Mono',
                  fontWeight: 'bold',
                  cursor: 'pointer',
                  boxShadow: '0 0 10px rgba(255, 0, 85, 0.4)'
                }}
              >
                {actionLoading ? 'KILLING...' : 'KILL PROCESS'}
              </button>
            </div>
          </div>
        </div>
      )}

      <section className="glass-panel master-record" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        
        {/* Header */}
        <div className="section-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <SciFiPulseIcon size={22} color="var(--accent-cyan)" /> Process Explorer
          </h2>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <span style={{ fontSize: '0.7rem', fontFamily: 'Share Tech Mono', color: 'var(--accent-cyan)', background: 'rgba(0, 243, 255, 0.08)', padding: '2px 8px', border: '1px solid rgba(0, 243, 255, 0.3)' }}>
              TOTAL: {processes.length}
            </span>
            {highCpuCount > 0 && (
              <span style={{ fontSize: '0.7rem', fontFamily: 'Share Tech Mono', color: 'var(--accent-pink)', background: 'rgba(255, 0, 85, 0.08)', padding: '2px 8px', border: '1px solid rgba(255, 0, 85, 0.3)' }}>
                HIGH CPU: {highCpuCount}
              </span>
            )}
            {highMemCount > 0 && (
              <span style={{ fontSize: '0.7rem', fontFamily: 'Share Tech Mono', color: '#f0b429', background: 'rgba(240, 180, 41, 0.08)', padding: '2px 8px', border: '1px solid rgba(240, 180, 41, 0.3)' }}>
                HIGH MEM: {highMemCount}
              </span>
            )}
            <button
              onClick={exportProcessesCSV}
              style={{
                background: 'rgba(0, 243, 255, 0.1)',
                border: '1px solid var(--accent-cyan)',
                color: 'var(--accent-cyan)',
                padding: '3px 10px',
                fontSize: '0.7rem',
                fontFamily: 'Share Tech Mono',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                borderRadius: '2px'
              }}
              title="Export processes to CSV"
            >
              <SciFiDownloadIcon size={12} color="var(--accent-cyan)" /> EXPORT CSV
            </button>
          </div>
        </div>

        {/* Controls Toolbar */}
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '15px', marginBottom: '12px', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', gap: '8px', flex: 1, minWidth: '240px' }}>
            <div style={{ position: 'relative', flex: 1 }}>
              <div style={{ position: 'absolute', left: '10px', top: '50%', transform: 'translateY(-50%)' }}>
                <SciFiSearchIcon size={16} color="var(--accent-cyan)" />
              </div>
              <input 
                type="text" 
                placeholder="Search by PID, Process name or User..." 
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                style={{
                  width: '100%',
                  padding: '6px 10px 6px 34px',
                  background: 'rgba(0,0,0,0.4)',
                  border: '1px solid rgba(0,243,255,0.2)',
                  color: '#fff',
                  fontSize: '0.8rem',
                  fontFamily: 'Share Tech Mono',
                  borderRadius: '3px'
                }}
              />
            </div>
          </div>

          <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            {/* Filter Tabs */}
            <div style={{ display: 'flex', gap: '2px', background: 'rgba(0,0,0,0.4)', padding: '2px', borderRadius: '3px' }}>
              {[
                { id: 'ALL', label: 'ALL' },
                { id: 'HIGH_CPU', label: 'HIGH CPU (>20%)' },
                { id: 'HIGH_MEM', label: 'HIGH MEM (>100MB)' }
              ].map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setFilterMode(tab.id)}
                  style={{
                    background: filterMode === tab.id ? 'var(--accent-cyan)' : 'transparent',
                    color: filterMode === tab.id ? '#000' : 'var(--text-secondary)',
                    border: 'none',
                    padding: '4px 10px',
                    fontSize: '0.7rem',
                    fontFamily: 'Share Tech Mono',
                    cursor: 'pointer',
                    fontWeight: 'bold',
                    borderRadius: '2px'
                  }}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {/* Sort Dropdown */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.75rem', fontFamily: 'Share Tech Mono', color: 'var(--text-secondary)' }}>
              <span>SORT:</span>
              <select
                value={`${sortBy}-${sortOrder}`}
                onChange={e => {
                  const [f, o] = e.target.value.split('-');
                  setSortBy(f);
                  setSortOrder(o);
                }}
                style={{
                  background: 'rgba(0,0,0,0.5)',
                  border: '1px solid rgba(0,243,255,0.3)',
                  color: 'var(--accent-cyan)',
                  padding: '4px 8px',
                  fontSize: '0.75rem',
                  fontFamily: 'Share Tech Mono',
                  borderRadius: '3px',
                  cursor: 'pointer'
                }}
              >
                <option value="cpu-desc">CPU % (High to Low)</option>
                <option value="mem-desc">Memory MB (High to Low)</option>
                <option value="pid-asc">PID (Low to High)</option>
                <option value="name-asc">Name (A-Z)</option>
              </select>
            </div>
          </div>
        </div>
        
        {/* Table */}
        <div style={{ overflowY: 'auto', flex: 1, minHeight: 0 }}>
          <table className="glass-table" style={{ width: '100%', fontSize: '0.82rem' }}>
            <thead>
              <tr>
                <th onClick={() => toggleSort('pid')} style={{ cursor: 'pointer' }}>
                  PID {sortBy === 'pid' ? (sortOrder === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th onClick={() => toggleSort('name')} style={{ cursor: 'pointer' }}>
                  Name / Command {sortBy === 'name' ? (sortOrder === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th>User</th>
                <th>Threads</th>
                <th onClick={() => toggleSort('cpu')} style={{ cursor: 'pointer' }}>
                  CPU % {sortBy === 'cpu' ? (sortOrder === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th onClick={() => toggleSort('mem')} style={{ cursor: 'pointer' }}>
                  Memory {sortBy === 'mem' ? (sortOrder === 'asc' ? '▲' : '▼') : ''}
                </th>
                <th style={{ textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((p, i) => {
                const cpuVal = parseFloat(p.cpu) || 0;
                const memVal = parseFloat(p.mem) || 0;
                return (
                  <tr key={i}>
                    <td style={{ fontFamily: 'Share Tech Mono', color: 'var(--accent-cyan)' }}>{p.pid}</td>
                    <td>
                      <div style={{ fontWeight: 'bold', fontFamily: 'Share Tech Mono' }}>{p.name}</div>
                      <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', maxWidth: '280px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={p.command}>
                        {p.command}
                      </div>
                    </td>
                    <td style={{ color: 'var(--text-secondary)' }}>{p.user}</td>
                    <td style={{ fontFamily: 'Share Tech Mono' }}>{p.threads}</td>
                    <td>
                      <span className="status-badge" style={{
                        color: cpuVal > 30 ? 'var(--accent-pink)' : cpuVal > 10 ? '#f0b429' : 'var(--accent-green)',
                        borderColor: cpuVal > 30 ? 'var(--accent-pink)' : cpuVal > 10 ? '#f0b429' : 'var(--accent-green)',
                        fontFamily: 'Share Tech Mono'
                      }}>
                        {p.cpu}%
                      </span>
                    </td>
                    <td style={{ fontFamily: 'Share Tech Mono', color: memVal > 200 ? '#f0b429' : 'inherit' }}>
                      {p.mem} MB
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <button 
                        onClick={() => handleKillClick(p.pid, p.name)}
                        style={{
                          background: 'rgba(255, 0, 60, 0.1)', 
                          border: '1px solid var(--accent-pink)', 
                          color: 'var(--accent-pink)',
                          padding: '2px 8px',
                          fontSize: '0.7rem',
                          cursor: 'pointer',
                          fontFamily: 'Share Tech Mono'
                        }}>
                        KILL
                      </button>
                    </td>
                  </tr>
                );
              })}
              {sorted.length === 0 && (
                <tr>
                  <td colSpan="7" style={{ textAlign: 'center', color: 'var(--text-secondary)' }}>No processes matching current filter.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}