import * as satellite from 'satellite.js';

/**
 * NASA SGP4 / SDP4 Orbital Propagation Engine
 * Computes exact real-world satellite geodetic coordinates, velocities, and 3D orbit trajectories
 * using official NORAD Two-Line Element sets (TLEs) compliant with Spacetrack Report #3 / Vallado 2006.
 */

// In-memory cache of parsed SatRec objects to prevent redundant TLE parsing overhead
const satrecCache = new Map();

/**
 * Parses and caches a two-line element set into a satellite.js SatRec record.
 * @param {string} line1 - TLE line 1
 * @param {string} line2 - TLE line 2
 * @param {string} id - Unique satellite identifier
 * @returns {object|null} SatRec record or null if invalid
 */
export function getOrCreateSatrec(line1, line2, id) {
  if (!line1 || !line2) return null;
  const cacheKey = `${id || line1.slice(2, 7)}_${line1.slice(18, 32)}`;
  if (satrecCache.has(cacheKey)) {
    return satrecCache.get(cacheKey);
  }

  try {
    const satrec = satellite.twoline2satrec(line1.trim(), line2.trim());
    if (satrec && !satrec.error) {
      satrecCache.set(cacheKey, satrec);
      return satrec;
    }
  } catch (err) {
    console.warn(`[SGP4] Failed to parse TLE for ${id}:`, err);
  }
  return null;
}

/**
 * Propagates a satellite state vector at a specific UTC timestamp.
 * Returns exact real-world Latitude, Longitude, Altitude (km), and Orbital Velocity (km/s).
 * @param {object} satrec - Parsed satellite.js SatRec record
 * @param {Date} date - Evaluation timestamp (defaults to live Date.now())
 * @param {number} globeAlt - Visualized altitude on 3D globe (defaults to 0.38)
 * @returns {object|null} Evaluated geodetic state or null if propagation failed
 */
export function propagateSatelliteState(satrec, date = new Date(), globeAlt = 0.38) {
  if (!satrec) return null;

  try {
    const posVel = satellite.propagate(satrec, date);
    if (!posVel || !posVel.position || !posVel.velocity) {
      return null;
    }

    const gmst = satellite.gstime(date);
    const geodetic = satellite.eciToGeodetic(posVel.position, gmst);

    const lat = satellite.degreesLat(geodetic.latitude);
    let lng = satellite.degreesLong(geodetic.longitude);

    // Normalize longitude to [-180, 180]
    while (lng > 180) lng -= 360;
    while (lng < -180) lng += 360;

    const altKm = Math.max(0, geodetic.height);
    const vx = posVel.velocity.x;
    const vy = posVel.velocity.y;
    const vz = posVel.velocity.z;
    const speedKmS = Math.sqrt(vx * vx + vy * vy + vz * vz);
    const speedKmH = speedKmS * 3600;

    // Orbital period in minutes: T = 2 * PI / mean_motion (rad/min)
    const periodMin = satrec.no ? (2 * Math.PI) / satrec.no : 90;

    return {
      lat,
      lng,
      altitude: globeAlt,
      altitudeKm: Math.round(altKm),
      speedKmS: Number(speedKmS.toFixed(2)),
      speedKmH: Math.round(speedKmH),
      periodMin: Number(periodMin.toFixed(2)),
      inclinationDeg: Number(satellite.radiansToDegrees(satrec.inclo).toFixed(2)),
      timestamp: date,
      valid: true,
    };
  } catch (err) {
    console.warn('[SGP4] Propagation error:', err);
    return null;
  }
}

/**
 * Computes 3D orbital trajectory loop for react-globe.gl pathsData over 1 full period T.
 * Spans from [now - T/2] to [now + T/2] to show the true orbital path in Earth's rotating frame.
 * @param {object} satrec - Parsed satellite.js SatRec record
 * @param {Date} centerDate - Center time (defaults to now)
 * @param {number} numSamples - Number of coordinate points along the orbit
 * @param {number} globeAlt - Altitude for 3D globe display
 * @returns {Array<[number, number, number]>} Array of [lat, lng, alt] 3D coordinates
 */
export function generateOrbitalTrajectory(satrec, centerDate = new Date(), numSamples = 96, globeAlt = 0.38) {
  if (!satrec) return [];

  const periodMin = satrec.no ? (2 * Math.PI) / satrec.no : 90;
  const periodMs = periodMin * 60 * 1000;
  const halfPeriodMs = periodMs / 2;
  const startTimeMs = centerDate.getTime() - halfPeriodMs;
  const stepMs = periodMs / numSamples;

  const points = [];

  for (let i = 0; i <= numSamples; i++) {
    const sampleDate = new Date(startTimeMs + i * stepMs);
    try {
      const posVel = satellite.propagate(satrec, sampleDate);
      if (!posVel || !posVel.position) continue;

      const gmst = satellite.gstime(sampleDate);
      const geodetic = satellite.eciToGeodetic(posVel.position, gmst);

      const lat = satellite.degreesLat(geodetic.latitude);
      let lng = satellite.degreesLong(geodetic.longitude);

      while (lng > 180) lng -= 360;
      while (lng < -180) lng += 360;

      points.push([lat, lng, globeAlt]);
    } catch {
      // Ignore individual point failures during orbit generation
    }
  }

  return points;
}

/**
 * Fetches fresh live TLE from CelesTrak GP API and updates cached SatRec.
 * Falls back gracefully to offline bundled TLE if network fails or offline.
 * @param {number} noradId - NORAD Catalog ID (e.g. 32767 for VINASAT-1)
 * @returns {Promise<{ line1: string, line2: string, name: string }|null>}
 */
export async function fetchLiveTLEFromCelesTrak(noradId) {
  if (!noradId) return null;
  const url = `https://celestrak.org/NORAD/elements/gp.php?CATNR=${noradId}&FORMAT=TLE`;

  try {
    const res = await fetch(url, { mode: 'cors' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const text = await res.text();
    const lines = text.trim().split(/\r?\n/).map(l => l.trim()).filter(Boolean);

    if (lines.length >= 3) {
      return {
        name: lines[0],
        line1: lines[1],
        line2: lines[2],
      };
    } else if (lines.length === 2) {
      return {
        name: `NORAD-${noradId}`,
        line1: lines[0],
        line2: lines[1],
      };
    }
  } catch (err) {
    console.debug(`[SGP4] CelesTrak live fetch skipped for ${noradId} (using offline cache):`, err.message);
  }
  return null;
}
