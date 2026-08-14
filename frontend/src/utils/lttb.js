/**
 * Largest Triangle Three Buckets (LTTB) Downsampling Algorithm.
 * Downsamples high-frequency time-series data while preserving visual peaks and valleys.
 *
 * @param {Array<Object>} data - Array of time-series objects e.g. { time, cpu, ram, disk }
 * @param {number} threshold - Target number of points (e.g. 120)
 * @returns {Array<Object>} Downsampled array
 */
export function lttbDownsample(data, threshold = 120) {
  if (!Array.isArray(data) || data.length <= threshold || threshold <= 2) {
    return data || [];
  }

  const sampled = [];
  const dataLength = data.length;
  const bucketSize = (dataLength - 2) / (threshold - 2);

  let a = 0; // First point
  sampled.push(data[a]);

  for (let i = 0; i < threshold - 2; i++) {
    // Calculate point average for next bucket (c)
    let avgX = 0;
    let avgY = 0;
    const avgRangeStart = Math.floor((i + 1) * bucketSize) + 1;
    const avgRangeEnd = Math.min(Math.floor((i + 2) * bucketSize) + 1, dataLength);
    const avgRangeLength = avgRangeEnd - avgRangeStart;

    for (let j = avgRangeStart; j < avgRangeEnd; j++) {
      avgX += j;
      avgY += (data[j]?.cpu ?? data[j]?.ram ?? 0);
    }

    if (avgRangeLength > 0) {
      avgX /= avgRangeLength;
      avgY /= avgRangeLength;
    }

    // Get the range for this bucket
    const rangeOffs = Math.floor(i * bucketSize) + 1;
    const rangeTo = Math.min(Math.floor((i + 1) * bucketSize) + 1, dataLength);

    // Point a coordinates
    const pointAX = a;
    const pointAY = (data[a]?.cpu ?? data[a]?.ram ?? 0);

    let maxArea = -1;
    let nextA = rangeOffs;

    for (let j = rangeOffs; j < rangeTo; j++) {
      const val = (data[j]?.cpu ?? data[j]?.ram ?? 0);
      const area = Math.abs(
        (pointAX - avgX) * (val - pointAY) -
        (pointAX - j) * (avgY - pointAY)
      ) * 0.5;

      if (area > maxArea) {
        maxArea = area;
        nextA = j;
      }
    }

    sampled.push(data[nextA]);
    a = nextA;
  }

  // Always include the last point
  sampled.push(data[dataLength - 1]);
  return sampled;
}
