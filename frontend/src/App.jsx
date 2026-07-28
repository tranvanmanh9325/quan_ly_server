import React, { useState, useEffect, useRef, useMemo } from 'react';
import axios from 'axios';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import LoginPage from './pages/LoginPage';
import ProtectedRoute from './components/ProtectedRoute';
import DashboardPage from './pages/DashboardPage';
import ProcessesPage from './pages/ProcessesPage';
import ServicesPage from './pages/ServicesPage';
import SecurityPage from './pages/SecurityPage';
import FileManagerPage from './pages/FileManagerPage';
import ContainersPage from './pages/ContainersPage';
import TerminalPage from './pages/TerminalPage';
import WorldMapPage from './pages/WorldMapPage';
import ErrorBoundary from './components/ErrorBoundary';
import SpaceInteractionLayer from './components/SpaceInteractionLayer';
import SettingsPage from './pages/SettingsPage';
import { loadSettings } from './utils/settings';
import { getToken } from './utils/auth';
// Register the global axios 401 interceptor once at app startup (side-effect only import)
import './utils/axiosInterceptor';
import './index.css';
import './App.css';
import { 
  parseCpu, parseRam, parseDisks, parseNetwork, parseProcesses, parseTemperature, 
  parseVoltage, parseFan, parseDiskIo, parseGpu, parseLoadAverage 
} from './utils/parsers';

const API_BASE = '/api/metrics';

// Khoảng thời gian polling mặc định (ms)
const METRICS_INTERVAL_NORMAL = 10_000;
const METRICS_INTERVAL_SLOW   = 20_000; // Tự động chuyển khi SSH phản hồi chậm (> 5s)
const PROCESS_INTERVAL        = 30_000;
const ADAPTIVE_THRESHOLD_MS   = 5_000;  // Ngưỡng để xem SSH là "đang chậm"

function App() {
  // Attach JWT token to every outgoing API request
  useEffect(() => {
    const id = axios.interceptors.request.use(config => {
      const token = getToken();
      if (token) config.headers['Authorization'] = `Bearer ${token}`;
      return config;
    });
    return () => axios.interceptors.request.eject(id);
  }, []);

  // Load persisted alert thresholds from localStorage
  const [alertThresholds, setAlertThresholds] = React.useState(() => {
    const s = loadSettings();
    return { cpu: s.cpuThreshold, ram: s.ramThreshold, disk: s.diskThreshold };
  });

  // Re-read thresholds when user saves settings
  useEffect(() => {
    const onSettings = (e) => {
      const s = e.detail || {};
      setAlertThresholds({ cpu: s.cpuThreshold, ram: s.ramThreshold, disk: s.diskThreshold });
    };
    window.addEventListener('srvdash:settings', onSettings);
    return () => window.removeEventListener('srvdash:settings', onSettings);
  }, []);

  const [processes, setProcesses]   = useState([]);
  const [system, setSystem]         = useState('');
  const [cpuHistory, setCpuHistory] = useState(Array(60).fill({ name: '', value: 0 }));
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [systemLogs, setSystemLogs] = useState('');
  const [dockerData, setDockerData] = useState({ status: 'LOADING', data: [] });
  const [ramData, setRamData]       = useState({ total: 0, used: 0, free: 0, cached: 0, percent: 0, swapTotal: 0, swapUsed: 0 });
  const [diskData, setDiskData]     = useState([]);
  const [networkData, setNetworkData] = useState({ rxSpeed: 0, txSpeed: 0, totalRx: 0, totalTx: 0, interfaceName: '' });
  const lastNetRef = useRef({ rx: 0, tx: 0, time: 0 });
  const [connections, setConnections]   = useState([]);
  const [temperatureData, setTemperatureData] = useState([]); // Array<{ label, value, status }>
  const [voltageData, setVoltageData]   = useState([]); // Array<{ label, value, status }>
  const [fanData, setFanData]           = useState([]); // Array<{ label, value }>
  const [sysInfo, setSysInfo]           = useState({ kernel: 'N/A', hostname: 'N/A', os: 'N/A', cpuModel: 'N/A' });
  const [diskIoData, setDiskIoData]     = useState({ readSpeed: '0 B/s', writeSpeed: '0 B/s', readSpeedRaw: 0, writeSpeedRaw: 0 });
  const lastDiskIoRef                   = useRef({ readBytes: 0, writeBytes: 0, time: 0 });
  const [gpuData, setGpuData]           = useState([]);
  const [loadAvgData, setLoadAvgData]   = useState({ m1: 0, m5: 0, m15: 0 });
  const [refreshSpeed, setRefreshSpeed] = useState('10s');

  // ─── Effect 0: Fetch History Data on Mount ──────────────────
  useEffect(() => {
    axios.get(`${API_BASE}/history`).then(res => {
      if (res.data && res.data.length > 0) {
        // Lấy tối đa 60 bản ghi cuối cùng để vẽ biểu đồ
        const historyData = res.data.slice(-60).map(item => {
          const date = new Date(item.timestamp);
          const timeStr = date.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
          return { name: timeStr, value: item.cpuPercent || 0 };
        });
        
        setCpuHistory(prev => {
          // Gộp dữ liệu cũ (mặc định) và dữ liệu mới
          const merged = [...prev];
          for (let i = 0; i < historyData.length; i++) {
            merged[60 - historyData.length + i] = historyData[i];
          }
          return merged;
        });
      }
      setHistoryLoaded(true);
    }).catch(err => {
      console.error('Lỗi lấy lịch sử:', err);
      setHistoryLoaded(true);
    });
  }, []);

  // ─── Effect 1: Lightweight metrics — poll theo refreshSpeed ────────────
  useEffect(() => {
    let isMounted    = true;
    let isFetching   = false;
    let timerId = null;

    const getIntervalMs = () => {
      if (refreshSpeed === '5s') return 5_000;
      if (refreshSpeed === '10s') return 10_000;
      if (refreshSpeed === '15s') return 15_000;
      if (refreshSpeed === '30s') return 30_000;
      if (refreshSpeed === 'PAUSE') return 999_999_999;
      return 10_000;
    };

    const loadMetrics = async () => {
      if (isFetching || refreshSpeed === 'PAUSE') return;
      isFetching = true;

      try {
        const batchRes = await axios.get(`${API_BASE}/batch`);
        if (!isMounted) return;

        const batchData = batchRes.data || {};

        if (batchData.connections?.data) setConnections(batchData.connections.data);
        
        if (batchData.system?.data) {
          setSystem(batchData.system.data);
          setLoadAvgData(parseLoadAverage(batchData.system.data));
        }

        if (batchData.cpu?.data) {
          const cpuPercent = parseCpu(batchData.cpu.data);
          setCpuHistory(prev => {
            const timeStr = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
            return [...prev.slice(1), { name: timeStr, value: cpuPercent }];
          });
        }

        if (batchData.ram?.data)  setRamData(parseRam(batchData.ram.data));
        if (batchData.disk?.data) setDiskData(parseDisks(batchData.disk.data));

        if (batchData.network?.data) {
          const result = parseNetwork(batchData.network.data, lastNetRef.current);
          lastNetRef.current = { rx: result.totalRx, tx: result.totalTx, time: Date.now() };
          setNetworkData(result);
        }

        if (batchData.temperature?.data) {
          const temps = parseTemperature(batchData.temperature.data);
          setTemperatureData(temps);
        }

        if (batchData.voltage?.data) {
          setVoltageData(parseVoltage(batchData.voltage.data));
          setFanData(parseFan(batchData.voltage.data));
        }

        if (batchData.sysinfo) {
          setSysInfo(prev => ({ ...prev, ...batchData.sysinfo }));
        }

        if (batchData.logs?.data) {
          setSystemLogs(batchData.logs.data);
        }

        if (batchData.docker) {
          setDockerData({ status: batchData.docker.status, data: batchData.docker.data || [] });
        }

        if (batchData.diskIo?.data) {
          const ioResult = parseDiskIo(batchData.diskIo.data, lastDiskIoRef.current);
          if (ioResult && typeof ioResult.totalReadBytes !== 'undefined') {
            lastDiskIoRef.current = { readBytes: ioResult.totalReadBytes, writeBytes: ioResult.totalWriteBytes, time: Date.now() };
            setDiskIoData(ioResult);
          }
        }

        if (batchData.gpu?.data) {
          setGpuData(parseGpu(batchData.gpu.data));
        }

      } catch (error) {
        console.error('Lỗi lấy metrics:', error);
      } finally {
        isFetching = false;
      }
    };

    const schedule = () => {
      if (document.visibilityState === 'hidden' || refreshSpeed === 'PAUSE') {
        timerId = setTimeout(schedule, 2000);
        return;
      }
      loadMetrics().finally(() => {
        if (isMounted) timerId = setTimeout(schedule, getIntervalMs());
      });
    };

    if (historyLoaded) {
      if (refreshSpeed !== 'PAUSE') loadMetrics();
      timerId = setTimeout(schedule, getIntervalMs());
    }

    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible' && isMounted && refreshSpeed !== 'PAUSE') {
        clearTimeout(timerId);
        loadMetrics().finally(() => {
          if (isMounted) timerId = setTimeout(schedule, getIntervalMs());
        });
      }
    };
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      isMounted = false;
      clearTimeout(timerId);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [historyLoaded, refreshSpeed]);


  // ─── Effect 2: Process list nặng — poll riêng mỗi 30 giây ──────────────────
  useEffect(() => {
    let isMounted      = true;
    let isFetchingProcs = false;
    let timerId        = null;

    const loadProcesses = async () => {
      if (isFetchingProcs) return;
      isFetchingProcs = true;
      try {
        const pRes = await axios.get(`${API_BASE}/processes`);
        if (!isMounted) return;
        if (pRes.data?.data) setProcesses(parseProcesses(pRes.data.data));
      } catch (error) {
        console.error('Lỗi lấy processes:', error);
      } finally {
        isFetchingProcs = false;
      }
    };

    const schedule = () => {
      if (document.visibilityState === 'hidden') {
        timerId = setTimeout(schedule, 1000);
        return;
      }
      loadProcesses().finally(() => {
        if (isMounted) timerId = setTimeout(schedule, PROCESS_INTERVAL);
      });
    };

    loadProcesses().finally(() => {
      if (isMounted) timerId = setTimeout(schedule, PROCESS_INTERVAL);
    });

    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible' && isMounted) {
        clearTimeout(timerId);
        loadProcesses().finally(() => {
          if (isMounted) timerId = setTimeout(schedule, PROCESS_INTERVAL);
        });
      }
    };
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      isMounted = false;
      clearTimeout(timerId);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, []);

  // ─── Alerting Logic ──────────────────
  const isAlerting = useMemo(() => {
    let alert = false;
    const lastCpu = cpuHistory[cpuHistory.length - 1]?.value || 0;
    if (lastCpu > alertThresholds.cpu) alert = true;
    if (ramData.percent > alertThresholds.ram) alert = true;
    if (diskData.some(d => d.percent > alertThresholds.disk)) alert = true;
    
    return alert;
  }, [cpuHistory, ramData, diskData, alertThresholds]);

  const context = {
    system, sysInfo, cpuHistory, ramData, diskData, 
    networkData, temperatureData, voltageData, fanData,
    processes, dockerData, systemLogs, connections,
    diskIoData, gpuData, loadAvgData,
    refreshSpeed, setRefreshSpeed, alertThresholds
  };

  return (
    <ErrorBoundary>
      <SpaceInteractionLayer />
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <Layout isAlerting={isAlerting} context={context} />
              </ProtectedRoute>
            }
          >
            <Route index element={<DashboardPage />} />
            <Route path="processes" element={<ProcessesPage />} />
            <Route path="services" element={<ServicesPage />} />
            <Route path="files" element={<FileManagerPage />} />
            <Route path="containers" element={<ContainersPage />} />
            <Route path="map" element={<WorldMapPage />} />
            <Route path="terminal" element={<TerminalPage />} />
            <Route path="security" element={<SecurityPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  );
}

export default App;