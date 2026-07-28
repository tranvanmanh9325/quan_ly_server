// ── Settings utility — shared between SettingsPage and App ──────────────────
export const SETTINGS_LS_KEY = 'srvdash_settings';

export const SETTINGS_DEFAULTS = {
  cpuThreshold:   85,
  ramThreshold:   90,
  diskThreshold:  90,
  refreshSpeed:   '10s',
  cursorEffect:   true,
  clickSound:     true,
  scanlineEffect: true,
  gridBackground: true,
  browserNotify:  false,
  notifyOnCritical: true,
};

export function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_LS_KEY);
    return raw ? { ...SETTINGS_DEFAULTS, ...JSON.parse(raw) } : { ...SETTINGS_DEFAULTS };
  } catch {
    return { ...SETTINGS_DEFAULTS };
  }
}

export function saveSettings(settings) {
  try {
    localStorage.setItem(SETTINGS_LS_KEY, JSON.stringify(settings));
  } catch { /* ignore quota errors */ }
}
