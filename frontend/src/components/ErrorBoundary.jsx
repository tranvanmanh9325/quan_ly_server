import React from 'react';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("ErrorBoundary caught an exception:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          minHeight: '400px',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          padding: '40px',
          fontFamily: 'Share Tech Mono, monospace'
        }}>
          <div className="glass-panel" style={{
            maxWidth: '600px',
            width: '100%',
            padding: '30px',
            border: '1px solid var(--accent-pink)',
            boxShadow: '0 0 30px rgba(255, 0, 85, 0.2)',
            textAlign: 'center',
            background: 'rgba(9, 10, 15, 0.95)'
          }}>
            <div style={{ fontSize: '2rem', marginBottom: '10px' }}>⚠️</div>
            <h2 style={{ color: 'var(--accent-pink)', margin: '0 0 10px 0', letterSpacing: '1px' }}>
              SYSTEM DIAGNOSTIC EXCEPTION
            </h2>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginBottom: '20px', lineHeight: 1.5 }}>
              An unhandled rendering exception occurred in this module component interface.
            </p>
            <div style={{
              background: '#040914',
              border: '1px solid rgba(255, 0, 85, 0.3)',
              padding: '10px 14px',
              color: 'var(--accent-pink)',
              fontSize: '0.75rem',
              textAlign: 'left',
              marginBottom: '20px',
              wordBreak: 'break-all',
              maxHeight: '120px',
              overflowY: 'auto'
            }}>
              {this.state.error?.toString() || 'Unknown Component Failure'}
            </div>
            <button
              onClick={() => window.location.reload()}
              style={{
                background: 'var(--accent-cyan)',
                color: '#000',
                border: 'none',
                padding: '10px 24px',
                fontWeight: 'bold',
                fontFamily: 'Share Tech Mono',
                cursor: 'pointer',
                borderRadius: '3px'
              }}
            >
              RELOAD DASHBOARD SYSTEM
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}