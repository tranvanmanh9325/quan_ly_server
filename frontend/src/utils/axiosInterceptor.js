import axios from 'axios';
import { getToken, removeToken } from './auth';

let isSetup = false;
let responseInterceptorId = null;

/**
 * Robust, explicit setup function to register request & response interceptors.
 * Callable multiple times safely (idempotent).
 */
export const setupAxiosInterceptors = () => {
  if (isSetup) return;
  isSetup = true;

  // 1. Sync existing token to common headers immediately
  const initialToken = getToken();
  if (initialToken) {
    axios.defaults.headers.common['Authorization'] = `Bearer ${initialToken}`;
  }

  // 2. Dynamic REQUEST interceptor — guarantees token is on every outgoing request
  axios.interceptors.request.use(config => {
    const token = getToken();
    if (token) {
      if (config.headers && typeof config.headers.set === 'function') {
        config.headers.set('Authorization', `Bearer ${token}`);
      } else {
        config.headers = config.headers || {};
        config.headers['Authorization'] = `Bearer ${token}`;
      }
    }
    return config;
  });

  // 3. RESPONSE interceptor — handles 401 Unauthorized gracefully
  responseInterceptorId = axios.interceptors.response.use(
    res => res,
    err => {
      if (err.response?.status === 401) {
        // Do not intercept 401 from login itself
        const isLogin = err.config?.url?.includes('/api/auth/login');
        if (!isLogin) {
          removeToken();
          if (!window.location.pathname.startsWith('/login')) {
            window.location.replace('/login');
          }
        }
      }
      return Promise.reject(err);
    }
  );
};

// Auto-run once on module evaluation
setupAxiosInterceptors();

// Exposed for testing teardown
export const ejectAuthInterceptor = () => {
  if (responseInterceptorId !== null) {
    axios.interceptors.response.eject(responseInterceptorId);
    responseInterceptorId = null;
    isSetup = false;
  }
};
