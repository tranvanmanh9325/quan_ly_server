import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { 
  SciFiFolderIcon, SciFiFileIcon, SciFiSearchIcon, 
  SciFiRefreshIcon, SciFiHomeIcon, SciFiDownloadIcon 
} from '../components/SciFiIcons';

export default function FileManagerPage() {
  const [currentPath, setCurrentPath] = useState('/');
  const [inputPath, setInputPath] = useState('/');
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');

  // File Preview Modal States
  const [previewFile, setPreviewFile] = useState(null); // { name, path }
  const [fileContent, setFileContent] = useState('');
  const [previewLines, setPreviewLines] = useState(100);
  const [isPreviewLoading, setIsPreviewLoading] = useState(false);
  const [previewSearch, setPreviewSearch] = useState('');
  const [copySuccess, setCopySuccess] = useState(false);

  const fetchDirectory = async (targetPath) => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const res = await axios.get(`/api/files/list?path=${encodeURIComponent(targetPath)}`);
      if (res.data && res.data.status === 'success') {
        const normPath = res.data.path || targetPath;
        setCurrentPath(normPath);
        setInputPath(normPath);
        setFiles(res.data.files || []);
      } else {
        setErrorMsg(res.data.message || 'Access denied or failed to list directory');
      }
    } catch (err) {
      setErrorMsg(`Failed to fetch directory: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let isMounted = true;
    const loadInitialDir = async () => {
      try {
        const res = await axios.get(`/api/files/list?path=${encodeURIComponent('/')}`);
        if (!isMounted) return;
        if (res.data && res.data.status === 'success') {
          const normPath = res.data.path || '/';
          setCurrentPath(normPath);
          setInputPath(normPath);
          setFiles(res.data.files || []);
        } else {
          setErrorMsg(res.data.message || 'Access denied or failed to list directory');
        }
      } catch (err) {
        if (isMounted) setErrorMsg(`Failed to fetch directory: ${err.message}`);
      } finally {
        if (isMounted) setLoading(false);
      }
    };

    loadInitialDir();
    return () => {
      isMounted = false;
    };
  }, []);

  const handleNavigate = (path) => {
    fetchDirectory(path);
  };

  const handlePathSubmit = (e) => {
    e.preventDefault();
    if (inputPath.trim()) {
      fetchDirectory(inputPath.trim());
    }
  };

  const handleParentDirectory = () => {
    if (currentPath === '/') return;
    const parts = currentPath.split('/').filter(Boolean);
    parts.pop();
    const parent = '/' + parts.join('/');
    fetchDirectory(parent || '/');
  };

  const openFilePreview = async (fileName) => {
    const fullPath = currentPath === '/' ? `/${fileName}` : `${currentPath}/${fileName}`;
    setPreviewFile({ name: fileName, path: fullPath });
    fetchFileContent(fullPath, previewLines);
  };

  const fetchFileContent = async (filePath, lines = 100) => {
    setIsPreviewLoading(true);
    try {
      const res = await axios.get(`/api/files/read?path=${encodeURIComponent(filePath)}&lines=${lines}`);
      if (res.data && res.data.status === 'success') {
        setFileContent(res.data.data || '(Empty File)');
      } else {
        setFileContent(`Error reading file: ${res.data.data || res.data.message || 'Permission denied'}`);
      }
    } catch (err) {
      setFileContent(`Failed to read file content: ${err.message}`);
    } finally {
      setIsPreviewLoading(false);
    }
  };

  const formatFileSize = (bytesStr) => {
    const bytes = parseInt(bytesStr, 10);
    if (isNaN(bytes)) return bytesStr || '0 B';
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  // Filtered files
  const filteredFiles = files.filter(f => {
    if (!searchQuery.trim()) return true;
    return f.name.toLowerCase().includes(searchQuery.toLowerCase());
  });

  // Breadcrumbs
  const pathSegments = currentPath.split('/').filter(Boolean);

  const handleCopyContent = () => {
    if (!fileContent) return;
    navigator.clipboard.writeText(fileContent);
    setCopySuccess(true);
    setTimeout(() => setCopySuccess(false), 2000);
  };

  return (
    <div style={{ padding: '20px', height: '100%', display: 'flex', flexDirection: 'column', gap: '16px', overflowY: 'auto' }}>
      
      {/* Header Bar */}
      <div className="glass-panel" style={{ padding: '16px 20px', display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <SciFiFolderIcon size={26} color="var(--accent-yellow)" />
          <div>
            <h2 className="title-glow" style={{ margin: 0, fontSize: '1.2rem', letterSpacing: '1px' }}>
              FILE MANAGER & STORAGE EXPLORER
            </h2>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>
              SSH POSIX REMOTE FILE SYSTEM CONTROL
            </span>
          </div>
        </div>

        {/* Quick Location Shortcuts */}
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>QUICK NAV:</span>
          {[
            { label: 'Root (/)', path: '/' },
            { label: 'Home (~)', path: '/home' },
            { label: 'Config (/etc)', path: '/etc' },
            { label: 'Logs (/var/log)', path: '/var/log' },
            { label: 'Web (/var/www)', path: '/var/www' }
          ].map((loc, idx) => (
            <button
              key={idx}
              onClick={() => handleNavigate(loc.path)}
              style={{
                background: currentPath === loc.path ? 'rgba(0, 243, 255, 0.2)' : 'rgba(0, 0, 0, 0.4)',
                border: currentPath === loc.path ? '1px solid var(--accent-cyan)' : '1px solid rgba(0, 243, 255, 0.2)',
                color: currentPath === loc.path ? 'var(--accent-cyan)' : '#ccc',
                padding: '4px 10px',
                fontSize: '0.75rem',
                fontFamily: 'Share Tech Mono',
                borderRadius: '3px',
                cursor: 'pointer'
              }}
            >
              {loc.label}
            </button>
          ))}
        </div>
      </div>

      {/* Navigation Toolbar */}
      <div className="glass-panel" style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
        
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
          <button
            onClick={handleParentDirectory}
            disabled={currentPath === '/'}
            style={{
              background: 'rgba(0, 243, 255, 0.1)',
              border: '1px solid var(--accent-cyan)',
              color: 'var(--accent-cyan)',
              padding: '6px 14px',
              fontFamily: 'Share Tech Mono',
              fontSize: '0.8rem',
              fontWeight: 'bold',
              cursor: currentPath === '/' ? 'not-allowed' : 'pointer',
              opacity: currentPath === '/' ? 0.5 : 1,
              borderRadius: '3px'
            }}
          >
            ⬆ UP LEVEL
          </button>

          <button
            onClick={() => fetchDirectory(currentPath)}
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
            <span>REFRESH</span>
          </button>

          {/* Path Form Input */}
          <form onSubmit={handlePathSubmit} style={{ flex: 1, display: 'flex', gap: '8px', minWidth: '240px' }}>
            <input
              type="text"
              value={inputPath}
              onChange={e => setInputPath(e.target.value)}
              placeholder="Enter remote directory path..."
              style={{
                flex: 1,
                background: 'rgba(0, 0, 0, 0.5)',
                border: '1px solid rgba(0, 243, 255, 0.3)',
                color: '#fff',
                padding: '6px 12px',
                fontFamily: 'Share Tech Mono',
                fontSize: '0.85rem',
                borderRadius: '3px'
              }}
            />
            <button
              type="submit"
              style={{
                background: 'rgba(0, 243, 255, 0.15)',
                border: '1px solid var(--accent-cyan)',
                color: 'var(--accent-cyan)',
                padding: '6px 14px',
                fontFamily: 'Share Tech Mono',
                fontSize: '0.8rem',
                fontWeight: 'bold',
                cursor: 'pointer',
                borderRadius: '3px'
              }}
            >
              GO
            </button>
          </form>

          {/* Search Filter */}
          <div style={{ position: 'relative', minWidth: '200px' }}>
            <input
              type="text"
              placeholder="Filter current folder..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              style={{
                width: '100%',
                background: 'rgba(0,0,0,0.4)',
                border: '1px solid rgba(0, 243, 255, 0.2)',
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

        {/* Interactive Breadcrumbs */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexWrap: 'wrap', fontFamily: 'Share Tech Mono', fontSize: '0.82rem' }}>
          <span style={{ color: 'var(--text-secondary)' }}>PATH:</span>
          <span 
            onClick={() => handleNavigate('/')}
            style={{ color: 'var(--accent-cyan)', cursor: 'pointer', textDecoration: 'underline', padding: '0 4px' }}
          >
            /
          </span>
          {pathSegments.map((seg, idx) => {
            const pathUpTo = '/' + pathSegments.slice(0, idx + 1).join('/');
            const isLast = idx === pathSegments.length - 1;
            return (
              <React.Fragment key={idx}>
                <span style={{ color: 'var(--text-secondary)' }}>/</span>
                <span
                  onClick={() => !isLast && handleNavigate(pathUpTo)}
                  style={{
                    color: isLast ? 'var(--accent-yellow)' : 'var(--accent-cyan)',
                    cursor: isLast ? 'default' : 'pointer',
                    fontWeight: isLast ? 'bold' : 'normal',
                    textDecoration: isLast ? 'none' : 'underline',
                    padding: '0 4px'
                  }}
                >
                  {seg}
                </span>
              </React.Fragment>
            );
          })}
        </div>

      </div>

      {/* Directory Content Table */}
      <div className="glass-panel" style={{ flex: 1, padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        
        {errorMsg ? (
          <div style={{ padding: '30px', textAlign: 'center', color: 'var(--accent-pink)', fontFamily: 'Share Tech Mono' }}>
            <h3 style={{ margin: '0 0 10px 0' }}>⚠️ ACCESS ERROR</h3>
            <p>{errorMsg}</p>
            <button
              onClick={() => handleNavigate('/')}
              style={{
                marginTop: '12px',
                background: 'rgba(255, 0, 85, 0.15)',
                border: '1px solid var(--accent-pink)',
                color: 'var(--accent-pink)',
                padding: '6px 16px',
                fontFamily: 'Share Tech Mono',
                cursor: 'pointer'
              }}
            >
              RETURN TO ROOT (/)
            </button>
          </div>
        ) : loading ? (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono' }}>
            LOADING DIRECTORY CONTENTS...
          </div>
        ) : filteredFiles.length === 0 ? (
          <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)', fontFamily: 'Share Tech Mono' }}>
            No files or directories found in "{currentPath}"
          </div>
        ) : (
          <div style={{ overflowX: 'auto', flex: 1 }}>
            <table className="sci-fi-table" style={{ width: '100%', minWidth: '850px' }}>
              <thead>
                <tr>
                  <th style={{ width: '60px', textAlign: 'center' }}>TYPE</th>
                  <th style={{ minWidth: '220px' }}>NAME</th>
                  <th style={{ width: '140px' }}>PERMISSIONS</th>
                  <th style={{ width: '110px' }}>SIZE</th>
                  <th style={{ width: '160px' }}>OWNER / GROUP</th>
                  <th style={{ width: '200px' }}>DATE MODIFIED</th>
                  <th style={{ width: '120px', textAlign: 'center' }}>ACTION</th>
                </tr>
              </thead>
              <tbody>
                {filteredFiles.map((file, idx) => {
                  const isDir = file.isDir === 'true';
                  return (
                    <tr key={idx} style={{ transition: 'background 0.2s' }}>
                      <td>
                        {isDir ? (
                          <SciFiFolderIcon size={18} color="var(--accent-yellow)" />
                        ) : (
                          <SciFiFileIcon size={18} color="var(--accent-cyan)" />
                        )}
                      </td>
                      <td>
                        <span
                          onClick={() => {
                            if (isDir) {
                              const newP = currentPath === '/' ? `/${file.name}` : `${currentPath}/${file.name}`;
                              handleNavigate(newP);
                            } else {
                              openFilePreview(file.name);
                            }
                          }}
                          style={{
                            color: isDir ? 'var(--accent-yellow)' : '#fff',
                            fontWeight: isDir ? 'bold' : 'normal',
                            cursor: 'pointer'
                          }}
                        >
                          {file.name}
                        </span>
                      </td>
                      <td style={{ fontFamily: 'Share Tech Mono', fontSize: '0.8rem', color: 'var(--accent-cyan)' }}>
                        {file.permissions}
                      </td>
                      <td style={{ fontFamily: 'Share Tech Mono', fontSize: '0.8rem' }}>
                        {isDir ? '<DIR>' : formatFileSize(file.size)}
                      </td>
                      <td style={{ fontFamily: 'Share Tech Mono', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                        {file.owner}:{file.group}
                      </td>
                      <td style={{ fontFamily: 'Share Tech Mono', fontSize: '0.8rem', opacity: 0.8 }}>
                        {file.date}
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        {isDir ? (
                          <button
                            onClick={() => {
                              const newP = currentPath === '/' ? `/${file.name}` : `${currentPath}/${file.name}`;
                              handleNavigate(newP);
                            }}
                            style={{
                              background: 'rgba(255, 187, 0, 0.1)',
                              border: '1px solid var(--accent-yellow)',
                              color: 'var(--accent-yellow)',
                              padding: '2px 8px',
                              fontSize: '0.72rem',
                              fontFamily: 'Share Tech Mono',
                              cursor: 'pointer',
                              borderRadius: '3px'
                            }}
                          >
                            OPEN DIR
                          </button>
                        ) : (
                          <button
                            onClick={() => openFilePreview(file.name)}
                            style={{
                              background: 'rgba(0, 243, 255, 0.1)',
                              border: '1px solid var(--accent-cyan)',
                              color: 'var(--accent-cyan)',
                              padding: '2px 8px',
                              fontSize: '0.72rem',
                              fontFamily: 'Share Tech Mono',
                              cursor: 'pointer',
                              borderRadius: '3px'
                            }}
                          >
                            PREVIEW
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

      </div>

      {/* File Preview Modal */}
      {previewFile && (
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
            width: '900px',
            maxWidth: '94vw',
            height: '620px',
            maxHeight: '92vh',
            display: 'flex',
            flexDirection: 'column',
            border: '1px solid var(--accent-cyan)',
            padding: 0,
            overflow: 'hidden'
          }}>
            {/* Modal Header */}
            <div style={{
              background: 'rgba(0, 243, 255, 0.1)',
              borderBottom: '1px solid rgba(0, 243, 255, 0.3)',
              padding: '12px 18px',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--accent-cyan)', fontFamily: 'Share Tech Mono', fontWeight: 'bold' }}>
                <SciFiFileIcon size={20} color="var(--accent-cyan)" />
                <span>FILE PREVIEW: {previewFile.path}</span>
              </div>
              <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                <button
                  onClick={handleCopyContent}
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
                  {copySuccess ? '✓ COPIED' : 'COPY CONTENT'}
                </button>
                <button
                  onClick={() => setPreviewFile(null)}
                  style={{ background: 'none', border: 'none', color: 'var(--accent-pink)', fontSize: '1.2rem', cursor: 'pointer', fontWeight: 'bold' }}
                >
                  ✕
                </button>
              </div>
            </div>

            {/* Modal Controls */}
            <div style={{
              background: 'rgba(0,0,0,0.4)',
              borderBottom: '1px solid rgba(0,243,255,0.15)',
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
                  value={previewLines}
                  onChange={e => {
                    const l = parseInt(e.target.value, 10);
                    setPreviewLines(l);
                    fetchFileContent(previewFile.path, l);
                  }}
                  style={{
                    background: '#000',
                    border: '1px solid rgba(0,243,255,0.3)',
                    color: 'var(--accent-cyan)',
                    padding: '2px 6px',
                    fontSize: '0.75rem',
                    fontFamily: 'Share Tech Mono'
                  }}
                >
                  <option value={50}>50 Lines</option>
                  <option value={100}>100 Lines</option>
                  <option value={300}>300 Lines</option>
                  <option value={500}>500 Lines</option>
                  <option value={1000}>1000 Lines</option>
                </select>
              </div>

              <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span>SEARCH IN FILE:</span>
                <input
                  type="text"
                  placeholder="Find text..."
                  value={previewSearch}
                  onChange={e => setPreviewSearch(e.target.value)}
                  style={{
                    flex: 1,
                    background: '#000',
                    border: '1px solid rgba(0,243,255,0.3)',
                    color: '#fff',
                    padding: '3px 8px',
                    fontSize: '0.78rem',
                    fontFamily: 'Share Tech Mono'
                  }}
                />
              </div>
            </div>

            {/* Modal Body / Viewer */}
            <div style={{
              flex: 1,
              background: '#040810',
              padding: '16px',
              overflowY: 'auto',
              fontFamily: 'Share Tech Mono, monospace',
              fontSize: '0.82rem',
              color: 'rgba(255,255,255,0.9)',
              lineHeight: '1.5',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all'
            }}>
              {isPreviewLoading ? (
                <div style={{ color: 'var(--accent-cyan)', textAlign: 'center', padding: '40px' }}>
                  FETCHING FILE CONTENT FROM SSH HOST...
                </div>
              ) : (
                fileContent.split('\n').map((line, i) => {
                  if (previewSearch && line.toLowerCase().includes(previewSearch.toLowerCase())) {
                    return (
                      <div key={i} style={{ background: 'rgba(255, 230, 0, 0.25)', color: '#fff' }}>
                        <span style={{ opacity: 0.4, marginRight: '12px', userSelect: 'none' }}>{i + 1}</span>
                        {line}
                      </div>
                    );
                  }
                  return (
                    <div key={i}>
                      <span style={{ opacity: 0.4, marginRight: '12px', userSelect: 'none', display: 'inline-block', width: '35px', textAlign: 'right' }}>
                        {i + 1}
                      </span>
                      {line}
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
