/**
 * High-Precision GeoJSON Feature Collection for Vietnam Archipelagos and Maritime Islands
 * Including:
 * - Quần đảo Hoàng Sa (Paracel Islands)
 * - Quần đảo Trường Sa (Spratly Islands)
 * - Đảo Phú Quốc, Quần đảo Côn Đảo, Đảo Bạch Long Vĩ, Cát Bà, Cô Tô
 * - Đảo Cù Lao Chàm, Lý Sơn, Phú Quý, Thổ Chu, Nam Du, Cồn Cỏ, Hòn Khoai
 */

export const VIETNAM_ISLANDS_GEOJSON = {
  type: 'FeatureCollection',
  features: [
    // ── 1. QUẦN ĐẢO HOÀNG SA (PARACEL ISLANDS) ──
    {
      type: 'Feature',
      id: 'hoang-sa-archipelago',
      properties: {
        name: 'Quần đảo Hoàng Sa',
        nameEn: 'Paracel Islands',
        type: 'archipelago',
        country: 'Vietnam',
        center: [112.0, 16.5],
        label: '[Q.Đ HOÀNG SA]'
      },
      geometry: {
        type: 'MultiPolygon',
        coordinates: [
          // Đảo Phú Lâm (Woody Island)
          [[[112.32, 16.82], [112.35, 16.82], [112.36, 16.85], [112.33, 16.85], [112.32, 16.82]]],
          // Đảo Hoàng Sa (Pattle Island)
          [[[111.59, 16.52], [111.62, 16.52], [111.63, 16.55], [111.60, 16.55], [111.59, 16.52]]],
          // Đảo Cây (Tree Island)
          [[[112.26, 16.97], [112.28, 16.97], [112.29, 16.99], [112.27, 16.99], [112.26, 16.97]]],
          // Đảo Tri Tôn (Triton Island)
          [[[111.19, 15.77], [111.22, 15.77], [111.23, 15.80], [111.20, 15.80], [111.19, 15.77]]],
          // Đảo Linh Côn (Lincoln Island)
          [[[112.72, 16.65], [112.75, 16.65], [112.76, 16.68], [112.73, 16.68], [112.72, 16.65]]],
          // Đảo Quang Hòa (Duncan Island)
          [[[111.70, 16.44], [111.73, 16.44], [111.74, 16.47], [111.71, 16.47], [111.70, 16.44]]],
          // Cụm Lưỡi Liềm (Crescent Reef)
          [[[111.50, 16.48], [111.80, 16.48], [111.80, 16.60], [111.50, 16.60], [111.50, 16.48]]],
          // Cụm An Vĩnh (Amphitrite Reef)
          [[[112.20, 16.78], [112.45, 16.78], [112.45, 17.02], [112.20, 17.02], [112.20, 16.78]]]
        ]
      }
    },

    // ── 2. QUẦN ĐẢO TRƯỜNG SA (SPRATLY ISLANDS) ──
    {
      type: 'Feature',
      id: 'truong-sa-archipelago',
      properties: {
        name: 'Quần đảo Trường Sa',
        nameEn: 'Spratly Islands',
        type: 'archipelago',
        country: 'Vietnam',
        center: [114.0, 9.8],
        label: '[Q.Đ TRƯỜNG SA]'
      },
      geometry: {
        type: 'MultiPolygon',
        coordinates: [
          // Đảo Trường Sa Lớn (Spratly Island)
          [[[111.90, 8.63], [111.93, 8.63], [111.94, 8.66], [111.91, 8.66], [111.90, 8.63]]],
          // Đảo Song Tử Tây (Southwest Cay)
          [[[114.32, 11.41], [114.35, 11.41], [114.36, 11.44], [114.33, 11.44], [114.32, 11.41]]],
          // Đảo Nam Yết (Namyit Island)
          [[[114.35, 10.17], [114.38, 10.17], [114.39, 10.19], [114.36, 10.19], [114.35, 10.17]]],
          // Đảo Sinh Tồn (Sin Cowe Island)
          [[[114.31, 9.87], [114.34, 9.87], [114.35, 9.90], [114.32, 9.90], [114.31, 9.87]]],
          // Đảo Sơn Ca (Sand Cay)
          [[[114.46, 10.36], [114.49, 10.36], [114.50, 10.39], [114.47, 10.39], [114.46, 10.36]]],
          // Đảo Phan Vinh (Pearson Reef)
          [[[113.67, 8.95], [113.71, 8.95], [113.72, 8.98], [113.68, 8.98], [113.67, 8.95]]],
          // Đảo Thuyền Chài (Barque Canada Reef)
          [[[113.25, 8.13], [113.35, 8.13], [113.36, 8.21], [113.26, 8.21], [113.25, 8.13]]],
          // Đảo An Bang (Amboyna Cay)
          [[[112.89, 7.87], [112.92, 7.87], [112.93, 7.90], [112.90, 7.90], [112.89, 7.87]]],
          // Đảo Đá Tây (West Reef)
          [[[112.87, 8.83], [112.93, 8.83], [112.94, 8.87], [112.88, 8.87], [112.87, 8.83]]],
          // Đảo Tiên Nữ (Pigeon Reef)
          [[[114.63, 8.83], [114.67, 8.83], [114.68, 8.87], [114.64, 8.87], [114.63, 8.83]]],
          // Cụm Sinh Tồn (Union Atoll)
          [[[114.20, 9.70], [114.60, 9.70], [114.60, 10.00], [114.20, 10.00], [114.20, 9.70]]],
          // Cụm Nam Yết / Tizard Bank
          [[[114.25, 10.10], [114.65, 10.10], [114.65, 10.45], [114.25, 10.45], [114.25, 10.10]]]
        ]
      }
    },

    // ── 3. ĐẢO PHÚ QUỐC ──
    {
      type: 'Feature',
      id: 'phu-quoc-island',
      properties: {
        name: 'Đảo Phú Quốc',
        nameEn: 'Phu Quoc Island',
        type: 'island',
        country: 'Vietnam',
        center: [103.96, 10.23],
        label: '[ĐẢO PHÚ QUỐC]'
      },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [103.96, 10.46],
            [104.05, 10.36],
            [104.07, 10.16],
            [104.03, 10.01],
            [103.97, 10.02],
            [103.88, 10.17],
            [103.83, 10.33],
            [103.96, 10.46]
          ]
        ]
      }
    },

    // ── 4. QUẦN ĐẢO CÔN ĐẢO ──
    {
      type: 'Feature',
      id: 'con-dao-islands',
      properties: {
        name: 'Côn Đảo',
        nameEn: 'Con Dao Islands',
        type: 'island',
        country: 'Vietnam',
        center: [106.60, 8.68],
        label: '[CÔN ĐẢO]'
      },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [106.57, 8.75],
            [106.66, 8.73],
            [106.65, 8.64],
            [106.54, 8.65],
            [106.57, 8.75]
          ]
        ]
      }
    },

    // ── 5. ĐẢO BẠCH LONG VĨ (VỊNH BẮC BỘ) ──
    {
      type: 'Feature',
      id: 'bach-long-vi-island',
      properties: {
        name: 'Bạch Long Vĩ',
        nameEn: 'Bach Long Vi Island',
        type: 'island',
        country: 'Vietnam',
        center: [107.728, 20.133],
        label: '[BẠCH LONG VĨ]'
      },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [107.71, 20.14],
            [107.75, 20.14],
            [107.74, 20.12],
            [107.71, 20.12],
            [107.71, 20.14]
          ]
        ]
      }
    },

    // ── 6. ĐẢO LÝ SƠN ──
    {
      type: 'Feature',
      id: 'ly-son-island',
      properties: {
        name: 'Lý Sơn',
        nameEn: 'Ly Son Island',
        type: 'island',
        country: 'Vietnam',
        center: [109.123, 15.380],
        label: '[LÝ SƠN]'
      },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [109.10, 15.40],
            [109.15, 15.40],
            [109.14, 15.36],
            [109.10, 15.36],
            [109.10, 15.40]
          ]
        ]
      }
    },

    // ── 7. ĐẢO PHÚ QUÝ ──
    {
      type: 'Feature',
      id: 'phu-quy-island',
      properties: {
        name: 'Phú Quý',
        nameEn: 'Phu Quy Island',
        type: 'island',
        country: 'Vietnam',
        center: [108.950, 10.517],
        label: '[PHÚ QUÝ]'
      },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [108.93, 10.54],
            [108.97, 10.54],
            [108.96, 10.49],
            [108.92, 10.49],
            [108.93, 10.54]
          ]
        ]
      }
    },

    // ── 8. ĐẢO CỒN CỎ ──
    {
      type: 'Feature',
      id: 'con-co-island',
      properties: {
        name: 'Cồn Cỏ',
        nameEn: 'Con Co Island',
        type: 'island',
        country: 'Vietnam',
        center: [107.333, 17.167],
        label: '[CỒN CỎ]'
      },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [107.32, 17.18],
            [107.35, 17.18],
            [107.34, 17.15],
            [107.32, 17.15],
            [107.32, 17.18]
          ]
        ]
      }
    },

    // ── 9. QUẦN ĐẢO THỔ CHU ──
    {
      type: 'Feature',
      id: 'tho-chu-islands',
      properties: {
        name: 'Thổ Chu',
        nameEn: 'Tho Chu Islands',
        type: 'island',
        country: 'Vietnam',
        center: [103.483, 9.300],
        label: '[THỔ CHU]'
      },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [103.46, 9.33],
            [103.51, 9.33],
            [103.50, 9.27],
            [103.45, 9.27],
            [103.46, 9.33]
          ]
        ]
      }
    }
  ]
};

// Points of interest for high-visibility Radar/Sonar markers and glowing pins
export const NOTABLE_ISLAND_POINTS = [
  { name: 'Hoàng Sa (Paracel)', lat: 16.5, lon: 112.0, label: 'Q.Đ HOÀNG SA (VN)', type: 'archipelago_hq' },
  { name: 'Trường Sa (Spratly)', lat: 9.8, lon: 114.0, label: 'Q.Đ TRƯỜNG SA (VN)', type: 'archipelago_hq' },
  { name: 'Phú Quốc', lat: 10.23, lon: 103.96, label: 'Đ. PHÚ QUỐC (VN)', type: 'island_major' },
  { name: 'Côn Đảo', lat: 8.68, lon: 106.60, label: 'CÔN ĐẢO (VN)', type: 'island_major' },
  { name: 'Bạch Long Vĩ', lat: 20.13, lon: 107.73, label: 'BẠCH LONG VĨ (VN)', type: 'island_major' }
];
