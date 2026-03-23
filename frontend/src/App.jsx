import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import { LayoutDashboard, BarChart2, Folder, Users, Settings, FileText, Search, Bell, User, MoreHorizontal, Activity } from 'lucide-react';
import './index.css';
import './App.css';

const API_BASE = '/api/metrics';

function App() {
  const [processes, setProcesses] = useState([]);
  const [system, setSystem] = useState('');
  const [cpuHistory, setCpuHistory] = useState(Array(15).fill({ name: '', value: 0 }));
  const [ramData, setRamData] = useState({ total: 0, used: 0, percent: 0 });
  const [diskData, setDiskData] = useState({ percent: 0, usedStr: '', totalStr: '' });
  const [isServerModalOpen, setIsServerModalOpen] = useState(false);

  useEffect(() => {
    let isMounted = true;

    const loadData = async () => {
      try {
        const [pRes, sysRes, cpuRes, ramRes, diskRes] = await Promise.all([
          axios.get(`${API_BASE}/processes`),
          axios.get(`${API_BASE}/system`),
          axios.get(`${API_BASE}/cpu`),
          axios.get(`${API_BASE}/ram`),
          axios.get(`${API_BASE}/disk`)
        ]);

        if (!isMounted) return;

        if (pRes.data && pRes.data.data) {
          const lines = pRes.data.data.split('\n');
          const procs = lines.slice(1).map((line, i) => {
            const parts = line.trim().split(/\s+/);
            if (parts.length >= 5) {
              return { id: 10001 + i, user: parts[1], cpu: parts[2] + '%', mem: parts[3] + '%', name: parts.slice(4).join(' ') };
            }
            return null;
          }).filter(Boolean);
          setProcesses(procs);
        }

        if (sysRes.data) {
          setSystem(sysRes.data.data);
        }

        if (cpuRes.data && cpuRes.data.data) {
          const match = cpuRes.data.data.match(/(\d+\.\d+)\s+id/);
          let cpuPercent = 0;
          if (match && match[1]) {
             const idle = parseFloat(match[1]);
             cpuPercent = Math.max(0, 100 - idle).toFixed(1);
          }
          setCpuHistory(prev => {
            const timeStr = new Date().toLocaleTimeString('en-US', {hour12:false, hour:'2-digit', minute:'2-digit', second:'2-digit'});
            return [...prev.slice(1), { name: timeStr, value: parseFloat(cpuPercent) }];
          });
        }

        if (ramRes.data && ramRes.data.data) {
          const lines = ramRes.data.data.split('\n');
          if (lines.length >= 2) {
             const parts = lines[1].trim().split(/\s+/);
             if (parts.length >= 3) {
                const total = parseInt(parts[1], 10);
                const used = parseInt(parts[2], 10);
                const percent = total > 0 ? ((used / total) * 100).toFixed(1) : 0;
                setRamData({ total, used, percent: parseFloat(percent) });
             }
          }
        }

        if (diskRes.data && diskRes.data.data) {
          const lines = diskRes.data.data.split('\n');
          for (let i = 1; i < lines.length; i++) {
             if (lines[i].includes('/')) {
                const parts = lines[i].trim().split(/\s+/);
                const percentPartIndex = parts.findIndex(p => p.endsWith('%'));
                if (percentPartIndex !== -1) {
                   const percent = parseInt(parts[percentPartIndex].replace('%', ''), 10);
                   const usedStr = parts[percentPartIndex - 2];
                   const totalStr = parts[percentPartIndex - 3];
                   setDiskData({ percent, usedStr, totalStr });
                   break;
                }
             }
          }
        }
      } catch (error) {
        console.error("Lỗi lấy dữ liệu:", error);
      }
    };

    loadData();
    const interval = setInterval(loadData, 5000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  return (
    <div className="app-container">
      {/* Main Content Area */}
      <main className="main-content">
        <header className="top-header">
          <h1 className="title-glow">Server Dashboard</h1>
        </header>

        <div className="dashboard-grid">
          {/* Server Overview (Top Center) */}
          <section className="glass-panel analytics-section">
            <div className="section-header">
              <h2>Server Overview</h2>
              <div className="filters">
                <button className="btn-cyan">Refresh</button>
              </div>
            </div>
            
            <div className="kpi-row">
              <div className="kpi">
                <span className="kpi-label">CPU Usage</span>
                <span className="kpi-val">{cpuHistory[cpuHistory.length-1]?.value}%</span>
              </div>
              <div className="kpi">
                <span className="kpi-label">RAM Usage</span>
                <span className="kpi-val">{ramData.percent}% <small className="green">({(ramData.used/1024).toFixed(1)}GB / {(ramData.total/1024).toFixed(1)}GB)</small></span>
              </div>
              <div className="kpi">
                <span className="kpi-label">Disk Space</span>
                <span className="kpi-val">{diskData.percent}% <small className="green">({diskData.usedStr} / {diskData.totalStr})</small></span>
              </div>
            </div>

            <div className="charts-container">
              <div className="chart line-chart">
                <h4 style={{textAlign: 'center', margin: 0, fontSize: '12px', color: 'var(--text-secondary)'}}>CPU Usage History</h4>
                <ResponsiveContainer width="100%" height={150}>
                  <LineChart data={cpuHistory} margin={{ top: 10, right: 10, left: 0, bottom: 10 }}>
                    <Tooltip cursor={{fill: 'transparent'}} contentStyle={{backgroundColor: 'var(--glass-bg)', borderColor: 'var(--glass-border)', color: '#fff'}} />
                    <Line type="monotone" dataKey="value" stroke="var(--accent-cyan)" strokeWidth={3} dot={{r: 0}} activeDot={{r: 4}} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="chart pie-chart">
                <h4 style={{textAlign: 'center', margin: 0, fontSize: '12px', color: 'var(--text-secondary)'}}>RAM Usage</h4>
                <ResponsiveContainer width="100%" height={150}>
                  <PieChart>
                    <Pie data={[{name: 'Used', value: ramData.percent, color: '#00f0ff'}, {name: 'Free', value: 100 - ramData.percent, color: 'rgba(255,255,255,0.1)'}]} innerRadius={30} outerRadius={50} paddingAngle={0} dataKey="value" stroke="none">
                      {[{color: '#00f0ff'}, {color: 'rgba(255,255,255,0.1)'}].map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={{backgroundColor: 'var(--glass-bg)', borderColor: 'var(--glass-border)', color: '#fff'}} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="chart pie-chart">
                <h4 style={{textAlign: 'center', margin: 0, fontSize: '12px', color: 'var(--text-secondary)'}}>Disk Usage</h4>
                <ResponsiveContainer width="100%" height={150}>
                  <PieChart>
                    <Pie data={[{name: 'Used', value: diskData.percent, color: '#9d4edd'}, {name: 'Free', value: 100 - diskData.percent, color: 'rgba(255,255,255,0.1)'}]} innerRadius={30} outerRadius={50} paddingAngle={0} dataKey="value" stroke="none">
                      {[{color: '#9d4edd'}, {color: 'rgba(255,255,255,0.1)'}].map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={{backgroundColor: 'var(--glass-bg)', borderColor: 'var(--glass-border)', color: '#fff'}} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>
          </section>

          {/* Right Column */}
          <aside className="right-column">
             {/* Recent Activity */}
             <div className="glass-panel recent-activity">
                <div className="section-header">
                  <h3>Recent Activity</h3>
                  <MoreHorizontal size={16} />
                </div>
                <div className="activity-list">
                  <div className="activity-item">
                    <User size={16} />
                    <div className="act-info">
                      <p>Uptime check</p>
                      <small>{system.substring(0, 30)}</small>
                    </div>
                  </div>
                  <div className="activity-item">
                    <Activity size={16} color="var(--accent-pink)" />
                    <div className="act-info">
                      <p>SSH Connected</p>
                      <small>Just now</small>
                    </div>
                  </div>
                </div>
             </div>

             {/* System Status Gauge */}
             <div className="glass-panel status-gauge" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                <div className="section-header" style={{ width: '100%' }}>
                  <h3>System Status</h3>
                  <MoreHorizontal size={16} />
                </div>
                <div className="gauge-circle">
                   <div className="gauge-inner">Online</div>
                </div>
                <div style={{ color: 'var(--text-secondary)', marginTop: '15px', textAlign: 'center', lineHeight: '1.5', fontSize: '0.8rem' }}>
                  {system ? (
                    <>
                      <strong style={{ color: 'var(--accent-cyan)' }}>Uptime</strong><br />
                      {system}
                    </>
                  ) : 'Fetching uptime...'}
                </div>
             </div>
             
             {/* Server Info */}
             <div className="glass-panel team-members clickable" onClick={() => setIsServerModalOpen(true)}>
                <div className="section-header">
                  <h3>Server Info</h3>
                  <MoreHorizontal size={16} />
                </div>
                <div className="team-list">
                    <div className="team-item">
                      <div className="avatar"><Activity size={14}/></div>
                      <div className="team-info">
                        <p>OS Platform</p>
                        <small>Linux Server</small>
                      </div>
                    </div>
                    <div className="team-item">
                      <div className="avatar"><Settings size={14}/></div>
                      <div className="team-info">
                        <p>Network</p>
                        <small>Connected</small>
                      </div>
                    </div>
                </div>
             </div>
          </aside>

          {/* Master Record Table */}
          <section className="glass-panel master-record">
            <div className="section-header">
              <h2>Master Record (Processes)</h2>
              <button className="btn-cyan">Refresh</button>
            </div>
            <div className="table-controls">
               <div className="search-bar glass-panel">
                  <Search size={16} />
                  <input type="text" placeholder="Search..." />
               </div>
               <div className="filters">
                  <select className="glass-select"><option>CPU</option></select>
                  <select className="glass-select"><option>Filter</option></select>
               </div>
            </div>
            
            <table className="glass-table">
              <thead>
                <tr>
                  <th>PID</th>
                  <th>Name/Comm</th>
                  <th>User</th>
                  <th>CPU %</th>
                  <th>MEM %</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {processes.map(p => (
                  <tr key={p.id}>
                    <td>{p.id}</td>
                    <td>{p.name}</td>
                    <td>{p.user}</td>
                    <td><span className="status-badge" style={{color: 'var(--accent-cyan)'}}>{p.cpu}</span></td>
                    <td><span className="status-badge" style={{color: 'var(--accent-purple)'}}>{p.mem}</span></td>
                    <td><Settings size={14} className="action-icon" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          {/* Server Modal */}
          {isServerModalOpen && (
            <div className="modal-overlay" onClick={() => setIsServerModalOpen(false)}>
              <div className="modal-content glass-panel" onClick={e => e.stopPropagation()}>
                <div className="section-header" style={{ marginBottom: '20px' }}>
                  <h3 style={{ margin: 0 }}>Chi tiết thiết bị</h3>
                  <button className="btn-close-modal" onClick={() => setIsServerModalOpen(false)}>X</button>
                </div>
                <div className="server-details-list">
                  <div className="detail-item"><strong>OS Platform:</strong> Linux Server</div>
                  <div className="detail-item"><strong>Network:</strong> Connected</div>
                  <div className="detail-item"><strong>Uptime:</strong> {system || 'Đang lấy dữ liệu...'}</div>
                  <div className="detail-item">
                    <strong>CPU Usage:</strong> {cpuHistory.length > 0 ? `${cpuHistory[cpuHistory.length - 1].value}%` : '0%'}
                  </div>
                  <div className="detail-item">
                    <strong>RAM Usage:</strong> {ramData.percent}% ({(ramData.used/1024).toFixed(1)}GB / {(ramData.total/1024).toFixed(1)}GB)
                  </div>
                  <div className="detail-item">
                    <strong>Disk Space:</strong> {diskData.percent}% ({diskData.usedStr} / {diskData.totalStr})
                  </div>
                </div>
              </div>
            </div>
          )}

        </div>
      </main>
    </div>
  );
}

export default App;
