import axios from 'axios';
import { getToken, removeToken } from './auth';

/**
 * REQUEST interceptor — attaches the JWT from localStorage to every axios request.
 * Must be registered before any API call is made; import this module once at app
 * entry point (App.jsx) to guarantee that ordering.
 */
axios.interceptors.request.use(config => {
  const token = getToken();
  if (token) {
    config.headers['Authorization'] = `Bearer ${token}`;
  }
  return config;
});

/**
 * RESPONSE interceptor — clears the token and hard-redirects to /login whenever
 * the backend returns 401 (missing token, expired token, etc.).
 * window.location.replace() prevents the login page from being pushed onto
 * the browser history stack (so Back button won't return to the auth-failed page).
 *
 * Import this module once at the app entry point (App.jsx) to ensure the
 * interceptor is registered before any API call is made.
 */
const responseInterceptorId = axios.interceptors.response.use(
  res => res,
  err => {
    if (err.response?.status === 401) {
      removeToken();
      // Only hard-redirect if NOT already on the login page.
      // A hard reload while on /login causes an infinite reload loop because
      // App.jsx starts polling effects even before the user is authenticated.
      if (!window.location.pathname.startsWith('/login')) {
        window.location.replace('/login');
      }
    }
    return Promise.reject(err);
  }
);

// Exposed for testing teardown — eject the interceptors when no longer needed.
export const ejectAuthInterceptor = () =>
  axios.interceptors.response.eject(responseInterceptorId);
