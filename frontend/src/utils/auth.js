const TOKEN_KEY = 'srvdash_token';

export const getToken    = () => localStorage.getItem(TOKEN_KEY);
export const setToken    = (token) => localStorage.setItem(TOKEN_KEY, token);
export const removeToken = () => localStorage.removeItem(TOKEN_KEY);

/**
 * Decodes the payload section of a JWT without a library.
 * JWT uses base64url encoding (RFC 7519 §7): '-' instead of '+', '_' instead of '/'.
 * atob() only understands standard base64, so we must convert first.
 * Returns the parsed payload object, or null on any failure.
 */
function decodeJwtPayload(token) {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    // Convert base64url → base64, then pad to a multiple of 4
    const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = b64.padEnd(b64.length + (4 - (b64.length % 4)) % 4, '=');
    return JSON.parse(atob(padded));
  } catch {
    return null;
  }
}

/**
 * Returns true if a valid, non-expired JWT token exists in localStorage.
 */
export const isAuthenticated = () => {
  const token = getToken();
  if (!token) return false;
  const payload = decodeJwtPayload(token);
  return payload !== null && payload.exp * 1000 > Date.now();
};

/**
 * Extracts the username (subject) from the JWT payload.
 */
export const getUsername = () => {
  const token = getToken();
  if (!token) return null;
  const payload = decodeJwtPayload(token);
  return payload?.sub ?? null;
};
