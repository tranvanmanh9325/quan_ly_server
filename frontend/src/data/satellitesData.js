/**
 * Real-World Satellites Catalog & Keplerian Orbital Mechanics Engine
 * Provides real-time orbital calculations for Vietnamese and international satellites.
 */

export const SATELLITE_CATALOG = [
  {
    id: 'vinasat-1',
    name: 'VINASAT-1',
    codeName: 'VN-SAT-1 // GEO C2',
    noradId: 32767,
    country: 'Việt Nam (VNPT)',
    launchYear: 2008,
    type: 'GEO',
    regime: 'Geostationary Orbit (Địa tĩnh)',
    altitudeKm: 35786,
    globeAlt: 0.38, // Compressed visualization altitude
    inclination: 0.05,
    periodMin: 1436.07, // 23h 56m 04s
    raan: 132.0, // Fixed at 132.0° E
    velocity: '11,052 km/h (3.07 km/s)',
    frequency: '14.25 GHz (Ku-Band) / C-Band',
    mission: 'Viễn thông quốc gia, truyền hình, bảo đảm an ninh quốc phòng biển đảo',
    color: '#00ff9d', // Neon Green
    groundStation: { name: 'Trạm mặt đất Quế Dương (Hà Nội)', lat: 21.0285, lng: 105.8542 },
  },
  {
    id: 'vinasat-2',
    name: 'VINASAT-2',
    codeName: 'VN-SAT-2 // GEO TELECOM',
    noradId: 38332,
    country: 'Việt Nam (VNPT)',
    launchYear: 2012,
    type: 'GEO',
    regime: 'Geostationary Orbit (Địa tĩnh)',
    altitudeKm: 35786,
    globeAlt: 0.38,
    inclination: 0.06,
    periodMin: 1436.07,
    raan: 131.8, // Fixed at 131.8° E
    velocity: '11,052 km/h (3.07 km/s)',
    frequency: '14.50 GHz (Ku-Band Extended)',
    mission: 'Dự phòng & mở rộng năng lực truyền dẫn viễn thông quốc tế',
    color: '#00f3ff', // Cyan
    groundStation: { name: 'Trạm mặt đất Nam Định & Hà Nội', lat: 20.4200, lng: 106.1683 },
  },
  {
    id: 'vnredsat-1',
    name: 'VNREDSat-1',
    codeName: 'VNREDSAT-1 // EARTH OBS',
    noradId: 39160,
    country: 'Việt Nam (VAST)',
    launchYear: 2013,
    type: 'LEO',
    regime: 'Sun-Synchronous (Đồng bộ MT)',
    altitudeKm: 680,
    globeAlt: 0.12,
    inclination: 98.13,
    periodMin: 98.3,
    raan: 42.5,
    velocity: '27,036 km/h (7.51 km/s)',
    frequency: '8.20 GHz (X-Band Payload)',
    mission: 'Giám sát tài nguyên thiên nhiên, môi trường, chủ quyền biển đảo Hoàng Sa - Trường Sa',
    color: '#ff0055', // Neon Pink
    groundStation: { name: 'Trung tâm Vệ tinh Quốc gia (Cầu Giấy, HN)', lat: 21.0478, lng: 105.7989 },
  },
  {
    id: 'iss-space-station',
    name: 'ISS (Space Station)',
    codeName: 'ISS // ALPHA HABITAT',
    noradId: 25544,
    country: 'International (NASA/ESA/JAXA)',
    launchYear: 1998,
    type: 'LEO',
    regime: 'Low Earth Orbit (Quỹ đạo thấp)',
    altitudeKm: 420,
    globeAlt: 0.08,
    inclination: 51.64,
    periodMin: 92.9,
    raan: 185.0,
    velocity: '27,576 km/h (7.66 km/s)',
    frequency: '145.80 MHz (VHF) / S-Band',
    mission: 'Trạm nghiên cứu khoa học không gian quốc tế có người ở liên tục',
    color: '#ffe600', // Yellow
    groundStation: null,
  },
  {
    id: 'starlink-mesh',
    name: 'STARLINK-K1',
    codeName: 'STARLINK // MESH RELAY',
    noradId: 44713,
    country: 'Hoa Kỳ (SpaceX)',
    launchYear: 2019,
    type: 'LEO',
    regime: 'Low Earth Orbit Constellation',
    altitudeKm: 550,
    globeAlt: 0.10,
    inclination: 53.05,
    periodMin: 95.2,
    raan: 295.0,
    velocity: '27,324 km/h (7.59 km/s)',
    frequency: '12.40 GHz (Ka-Band Inter-sat)',
    mission: 'Chùm vệ tinh Internet băng thông rộng toàn cầu',
    color: '#38bdf8', // Sky Blue
    groundStation: null,
  },
  {
    id: 'gps-navstar',
    name: 'GPS NAVSTAR (PRN 13)',
    codeName: 'NAVSTAR // GPS-MEO',
    noradId: 24876,
    country: 'Hoa Kỳ (US Space Force)',
    launchYear: 1997,
    type: 'MEO',
    regime: 'Medium Earth Orbit (Định vị)',
    altitudeKm: 20180,
    globeAlt: 0.28,
    inclination: 55.0,
    periodMin: 718.0, // 11h 58m
    raan: 148.9,
    velocity: '13,932 km/h (3.87 km/s)',
    frequency: '1575.42 MHz (L1) / 1227.60 MHz (L2)',
    mission: 'Hệ thống định vị toàn cầu độ chính xác cao',
    color: '#a855f7', // Purple
    groundStation: null,
  }
];

/**
 * Calculates instantaneous satellite position [lat, lng, altitude] at timestamp (seconds)
 * Using analytical Keplerian mechanics with Earth rotation correction.
 */
export function getSatellitePosition(sat, timestampSec) {
  const rad = Math.PI / 180;
  const incRad = sat.inclination * rad;

  // Orbital angular speed (radians/sec)
  const orbitalSpeed = (2 * Math.PI) / (sat.periodMin * 60);
  const theta = (orbitalSpeed * timestampSec) % (2 * Math.PI);

  // Earth's rotation speed (radians/sec) — 1 revolution / 86400s
  const earthRotationSpeed = (2 * Math.PI) / 86400;
  const earthRot = (earthRotationSpeed * timestampSec) % (2 * Math.PI);

  // Spherical coordinate trigonometry
  const latRad = Math.asin(Math.sin(incRad) * Math.sin(theta));
  const dLngRad = Math.atan2(Math.cos(incRad) * Math.sin(theta), Math.cos(theta));

  const lat = latRad * (180 / Math.PI);
  let lng = (sat.raan + dLngRad * (180 / Math.PI) - (earthRot * 180 / Math.PI)) % 360;
  if (lng > 180) lng -= 360;
  if (lng < -180) lng += 360;

  return {
    lat,
    lng,
    altitude: sat.globeAlt,
    altitudeKm: sat.altitudeKm,
  };
}

/**
 * Generates closed 3D orbit trajectory loop for react-globe.gl pathsData
 */
export function getSatelliteOrbitPath(sat, numSegments = 72) {
  const coords = [];
  const rad = Math.PI / 180;
  const incRad = sat.inclination * rad;

  for (let i = 0; i <= numSegments; i++) {
    const theta = (i / numSegments) * (2 * Math.PI);
    const latRad = Math.asin(Math.sin(incRad) * Math.sin(theta));
    const dLngRad = Math.atan2(Math.cos(incRad) * Math.sin(theta), Math.cos(theta));

    const lat = latRad * (180 / Math.PI);
    let lng = (sat.raan + dLngRad * (180 / Math.PI)) % 360;
    if (lng > 180) lng -= 360;
    if (lng < -180) lng += 360;

    coords.push([lat, lng, sat.globeAlt]);
  }

  return {
    id: `orbit-${sat.id}`,
    name: sat.name,
    coords,
    color: sat.color || '#00f3ff',
    stroke: 0.35,
    dashLength: 0.04,
    dashGap: 0.02,
  };
}
