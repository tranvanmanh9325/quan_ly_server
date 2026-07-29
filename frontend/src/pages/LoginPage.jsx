import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';
import { setToken, isAuthenticated } from '../utils/auth';



export default function LoginPage() {
  const navigate = useNavigate();
  const [username, setUsername]     = useState('');
  const [password, setPassword]     = useState('');
  const [error, setError]           = useState('');
  const [loading, setLoading]       = useState(false);
  const [glitch, setGlitch]         = useState(false);
  // Cooldown countdown (seconds) after a failed login attempt
  const [retryAfter, setRetryAfter] = useState(0);
  const cooldownRef = useRef(null);

  // Always logged in → redirect to dashboard
  useEffect(() => {
    if (isAuthenticated()) navigate('/', { replace: true });
  }, [navigate]);

  // Cleanup cooldown timer on unmount to prevent setState on unmounted component
  useEffect(() => () => clearInterval(cooldownRef.current), []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (retryAfter > 0) return; // guard against submit during cooldown
    setError('');
    setLoading(true);
    try {
      const res = await axios.post('/api/auth/login', { username, password });
      setToken(res.data.token);
      // Notify App.jsx to flip isAuth state and start polling effects
      window.dispatchEvent(new Event('auth:login'));
      navigate('/', { replace: true });
    } catch (err) {
      const status = err.response?.status;

      if (status === 429) {
        // Server-side rate limit hit — use Retry-After header if provided
        const serverRetry = parseInt(err.response?.headers?.['retry-after'] ?? '60', 10);
        setError(`RATE LIMITED — Too many attempts. Retry in ${serverRetry}s.`);
        startCooldown(serverRetry);
      } else {
        // 401 or network error
        setError('ACCESS DENIED — Invalid credentials');
        startCooldown(5);
      }

      setGlitch(true);
      setTimeout(() => setGlitch(false), 600);
    } finally {
      setLoading(false);
    }
  };

  const startCooldown = (seconds) => {
    clearInterval(cooldownRef.current);
    setRetryAfter(seconds);
    cooldownRef.current = setInterval(() => {
      setRetryAfter(prev => {
        if (prev <= 1) {
          clearInterval(cooldownRef.current);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  };


  return (
    <div style={styles.root}>
      {/* Animated background grid */}
      <div style={styles.grid} aria-hidden="true" />

      {/* Scanline overlay */}
      <div style={styles.scanlines} aria-hidden="true" />

      <div style={styles.panel} className={glitch ? 'glitch-shake' : ''}>
        {/* Header */}
        <div style={styles.header}>
          <div style={styles.logoRing}>
            <svg width="44" height="44" viewBox="0 0 44 44">
              <circle cx="22" cy="22" r="20" fill="none" stroke="var(--accent-cyan)" strokeWidth="1.5"
                      strokeDasharray="6 3" style={{ animation: 'spin 12s linear infinite' }} />
              <circle cx="22" cy="22" r="12" fill="none" stroke="var(--accent-pink)" strokeWidth="1"
                      strokeDasharray="4 6" style={{ animation: 'spin 8s linear infinite reverse' }} />
              <circle cx="22" cy="22" r="5" fill="var(--accent-cyan)" opacity="0.8" />
            </svg>
          </div>
          <div>
            <div style={styles.title}>SERVER DASHBOARD</div>
            <div style={styles.subtitle}>SECURE ACCESS TERMINAL v2.0</div>
          </div>
        </div>

        {/* Divider */}
        <div style={styles.divider} />

        <form onSubmit={handleSubmit} style={styles.form}>
          <div style={styles.fieldGroup}>
            <label style={styles.label} htmlFor="login-username">OPERATOR ID</label>
            <div style={styles.inputWrap}>
              <span style={styles.inputPrefix}>&gt;</span>
              <input
                id="login-username"
                type="text"
                value={username}
                onChange={e => setUsername(e.target.value)}
                autoComplete="username"
                spellCheck="false"
                autoFocus
                style={styles.input}
                placeholder="enter username"
              />
            </div>
          </div>

          <div style={styles.fieldGroup}>
            <label style={styles.label} htmlFor="login-password">AUTH CODE</label>
            <div style={styles.inputWrap}>
              <span style={styles.inputPrefix}>&gt;</span>
              <input
                id="login-password"
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                autoComplete="current-password"
                style={styles.input}
                placeholder="enter password"
              />
            </div>
          </div>

          {error && (
            <div style={styles.error} aria-live="polite">
              <span style={{ marginRight: 8 }}>⚠</span>{error}
            </div>
          )}

          <button
            id="login-submit"
            type="submit"
            disabled={loading || retryAfter > 0}
            style={{
              ...styles.button,
              opacity: (loading || retryAfter > 0) ? 0.5 : 1,
              cursor:  (loading || retryAfter > 0) ? 'not-allowed' : 'pointer',
            }}
          >
            {loading
              ? 'AUTHENTICATING...'
              : retryAfter > 0
                ? `RETRY IN ${retryAfter}s...`
                : 'INITIALIZE SESSION'}
          </button>
        </form>

        <div style={styles.footer}>
          <span style={{ color: 'var(--accent-green)', marginRight: 6 }}>●</span>
          ENCRYPTED CHANNEL ACTIVE
        </div>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes gridMove {
          0%   { background-position: 0 0; }
          100% { background-position: 40px 40px; }
        }
        @keyframes scanline {
          0%   { transform: translateY(-100%); }
          100% { transform: translateY(100vh); }
        }
        @keyframes glitch-shake {
          0%, 100% { transform: translateX(0); }
          20%       { transform: translateX(-6px); }
          40%       { transform: translateX(6px); }
          60%       { transform: translateX(-4px); }
          80%       { transform: translateX(4px); }
        }
        .glitch-shake { animation: glitch-shake 0.4s ease; }
        #login-username, #login-password {
          outline: none;
        }
        #login-username:focus ~ *, #login-password:focus {
          border-color: var(--accent-cyan);
        }
        input:-webkit-autofill {
          -webkit-box-shadow: 0 0 0 30px #0a0e1a inset !important;
          -webkit-text-fill-color: #e0f7ff !important;
        }
        #login-submit:hover:not(:disabled) {
          background: var(--accent-cyan);
          color: #050810;
          box-shadow: 0 0 20px var(--accent-cyan), 0 0 40px rgba(0,243,255,0.3);
        }
      `}</style>
    </div>
  );
}

const styles = {
  root: {
    width: '100vw',
    height: '100vh',
    background: '#050810',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    position: 'relative',
    overflow: 'hidden',
    fontFamily: "'Share Tech Mono', monospace",
  },
  grid: {
    position: 'absolute',
    inset: 0,
    backgroundImage:
      'linear-gradient(rgba(0,243,255,0.04) 1px, transparent 1px),' +
      'linear-gradient(90deg, rgba(0,243,255,0.04) 1px, transparent 1px)',
    backgroundSize: '40px 40px',
    animation: 'gridMove 4s linear infinite',
    zIndex: 0,
  },
  scanlines: {
    position: 'absolute',
    inset: 0,
    background: 'linear-gradient(transparent 50%, rgba(0,0,0,0.06) 50%)',
    backgroundSize: '100% 4px',
    pointerEvents: 'none',
    zIndex: 1,
  },
  panel: {
    position: 'relative',
    zIndex: 2,
    width: '100%',
    maxWidth: '420px',
    background: 'rgba(10,14,26,0.92)',
    border: '1px solid rgba(0,243,255,0.25)',
    borderRadius: '4px',
    padding: '36px 40px 28px',
    boxShadow:
      '0 0 40px rgba(0,243,255,0.08), 0 0 80px rgba(0,243,255,0.04), inset 0 1px 0 rgba(0,243,255,0.1)',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
    marginBottom: '24px',
  },
  logoRing: {
    flexShrink: 0,
  },
  title: {
    fontSize: '1.1rem',
    fontWeight: 700,
    color: '#fff',
    letterSpacing: '3px',
    textShadow: '0 0 10px rgba(0,243,255,0.5)',
  },
  subtitle: {
    fontSize: '0.6rem',
    color: 'var(--accent-cyan)',
    letterSpacing: '2px',
    marginTop: '2px',
    opacity: 0.7,
  },
  divider: {
    height: '1px',
    background: 'linear-gradient(90deg, transparent, rgba(0,243,255,0.4), transparent)',
    marginBottom: '28px',
  },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: '20px',
  },
  fieldGroup: {
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
  },
  label: {
    fontSize: '0.65rem',
    letterSpacing: '2px',
    color: 'rgba(0,243,255,0.6)',
  },
  inputWrap: {
    display: 'flex',
    alignItems: 'center',
    border: '1px solid rgba(0,243,255,0.2)',
    borderRadius: '2px',
    background: 'rgba(0,243,255,0.03)',
    transition: 'border-color 0.2s',
  },
  inputPrefix: {
    color: 'var(--accent-cyan)',
    padding: '0 10px',
    fontSize: '0.9rem',
    userSelect: 'none',
  },
  input: {
    flex: 1,
    background: 'transparent',
    border: 'none',
    padding: '10px 12px 10px 0',
    color: '#e0f7ff',
    fontSize: '0.85rem',
    fontFamily: "'Share Tech Mono', monospace",
    letterSpacing: '1px',
  },
  error: {
    background: 'rgba(255,0,85,0.1)',
    border: '1px solid rgba(255,0,85,0.3)',
    borderRadius: '2px',
    padding: '10px 14px',
    color: 'var(--accent-pink)',
    fontSize: '0.75rem',
    letterSpacing: '1px',
  },
  button: {
    marginTop: '4px',
    padding: '13px',
    background: 'transparent',
    border: '1px solid var(--accent-cyan)',
    borderRadius: '2px',
    color: 'var(--accent-cyan)',
    fontSize: '0.8rem',
    fontFamily: "'Share Tech Mono', monospace",
    letterSpacing: '3px',
    transition: 'all 0.2s ease',
  },
  footer: {
    marginTop: '24px',
    fontSize: '0.6rem',
    color: 'rgba(255,255,255,0.3)',
    letterSpacing: '2px',
    textAlign: 'center',
  },
};