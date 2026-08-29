/**
 * High-Precision Coordinates & Maritime Boundaries for Vietnam Archipelagos and Major Islands
 * Designed for High-Performance 2D Canvas & 3D Orthographic Spherical Rendering
 */

export const VIETNAM_MARITIME_ISLANDS = [
  // ── 1. QUẦN ĐẢO HOÀNG SA (PARACEL ARCHIPELAGO) ──
  {
    id: 'hoang_sa_main',
    name: 'Quần đảo Hoàng Sa',
    label: '[Q.Đ HOÀNG SA (VN)]',
    lon: 112.00,
    lat: 16.50,
    type: 'archipelago_cluster',
    color: '#00ff9d',
    islands: [
      { name: 'Đảo Phú Lâm (Woody Island)', lon: 112.337, lat: 16.833, r: 2.2 },
      { name: 'Đảo Hoàng Sa (Pattle Island)', lon: 111.608, lat: 16.534, r: 2.0 },
      { name: 'Đảo Cây (Tree Island)', lon: 112.271, lat: 16.981, r: 1.8 },
      { name: 'Đảo Tri Tôn (Triton Island)', lon: 111.203, lat: 15.783, r: 1.8 },
      { name: 'Đảo Linh Côn (Lincoln Island)', lon: 112.735, lat: 16.664, r: 1.8 },
      { name: 'Đảo Quang Hòa (Duncan Island)', lon: 111.711, lat: 16.452, r: 1.8 },
      { name: 'Đảo Hữu Nhật (Robert Island)', lon: 111.586, lat: 16.505, r: 1.6 },
      { name: 'Đảo Duy Mộng (Drummond Island)', lon: 111.742, lat: 16.463, r: 1.6 },
      { name: 'Đá Lỗi (Discovery Reef)', lon: 111.683, lat: 16.233, r: 1.6 }
    ]
  },

  // ── 2. QUẦN ĐẢO TRƯỜNG SA (SPRATLY ARCHIPELAGO) ──
  {
    id: 'truong_sa_main',
    name: 'Quần đảo Trường Sa',
    label: '[Q.Đ TRƯỜNG SA (VN)]',
    lon: 114.00,
    lat: 9.80,
    type: 'archipelago_cluster',
    color: '#00ff9d',
    islands: [
      { name: 'Đảo Trường Sa Lớn (Spratly Island)', lon: 111.919, lat: 8.644, r: 2.5 },
      { name: 'Đảo Song Tử Tây (Southwest Cay)', lon: 114.331, lat: 11.428, r: 2.0 },
      { name: 'Đảo Nam Yết (Namyit Island)', lon: 114.364, lat: 10.181, r: 2.0 },
      { name: 'Đảo Sinh Tồn (Sin Cowe Island)', lon: 114.329, lat: 9.886, r: 2.0 },
      { name: 'Đảo Sơn Ca (Sand Cay)', lon: 114.479, lat: 10.376, r: 1.8 },
      { name: 'Đảo Trường Sa Đông', lon: 112.348, lat: 8.935, r: 1.8 },
      { name: 'Đảo Phan Vinh (Pearson Reef)', lon: 113.692, lat: 8.969, r: 2.0 },
      { name: 'Đảo Thuyền Chài (Barque Canada Reef)', lon: 113.300, lat: 8.167, r: 2.0 },
      { name: 'Đảo An Bang (Amboyna Cay)', lon: 112.906, lat: 7.887, r: 1.8 },
      { name: 'Đảo Đá Tây (West Reef)', lon: 112.900, lat: 8.850, r: 1.8 },
      { name: 'Đảo Đá Lát (Ladd Reef)', lon: 111.667, lat: 8.667, r: 1.8 },
      { name: 'Đảo Tiên Nữ (Pigeon Reef)', lon: 114.650, lat: 8.850, r: 1.8 },
      { name: 'Đảo Cô Lin (Collins Reef)', lon: 114.267, lat: 9.767, r: 1.6 },
      { name: 'Đảo Len Đao (Lansdowne Reef)', lon: 114.367, lat: 9.783, r: 1.6 },
      { name: 'Đá Lớn (Discovery Great Reef)', lon: 113.850, lat: 10.067, r: 1.6 }
    ]
  },

  // ── 3. CÁC ĐẢO LỚN VÀ HẢI ĐẢO VEN BỜ VIỆT NAM ──
  {
    id: 'phu_quoc',
    name: 'Đảo Phú Quốc',
    label: '[Đ. PHÚ QUỐC]',
    lon: 103.96,
    lat: 10.23,
    type: 'major_island',
    color: '#00f3ff',
    r: 3.5,
    outline: [
      [103.96, 10.46], [104.05, 10.36], [104.07, 10.16],
      [104.03, 10.01], [103.97, 10.02], [103.88, 10.17],
      [103.83, 10.33], [103.96, 10.46]
    ]
  },
  {
    id: 'con_dao',
    name: 'Côn Đảo',
    label: '[CÔN ĐẢO]',
    lon: 106.60,
    lat: 8.68,
    type: 'major_island',
    color: '#00f3ff',
    r: 2.6
  },
  {
    id: 'bach_long_vi',
    name: 'Bạch Long Vĩ',
    label: '[BẠCH LONG VĨ]',
    lon: 107.73,
    lat: 20.13,
    type: 'major_island',
    color: '#00f3ff',
    r: 2.2
  },
  {
    id: 'ly_son',
    name: 'Lý Sơn',
    label: '[LÝ SƠN]',
    lon: 109.12,
    lat: 15.38,
    type: 'minor_island',
    color: '#00f3ff',
    r: 2.0
  },
  {
    id: 'phu_quy',
    name: 'Phú Quý',
    label: '[PHÚ QUÝ]',
    lon: 108.95,
    lat: 10.52,
    type: 'minor_island',
    color: '#00f3ff',
    r: 2.0
  },
  {
    id: 'con_co',
    name: 'Cồn Cỏ',
    label: '[CỒN CỎ]',
    lon: 107.33,
    lat: 17.17,
    type: 'minor_island',
    color: '#00f3ff',
    r: 1.8
  },
  {
    id: 'cu_lao_cham',
    name: 'Cù Lao Chàm',
    label: '[CÙ LAO CHÀM]',
    lon: 108.52,
    lat: 15.96,
    type: 'minor_island',
    color: '#00f3ff',
    r: 1.8
  },
  {
    id: 'tho_chu',
    name: 'Thổ Chu',
    label: '[THỔ CHU]',
    lon: 103.48,
    lat: 9.30,
    type: 'minor_island',
    color: '#00f3ff',
    r: 1.8
  },
  {
    id: 'hon_khoai',
    name: 'Đảo Hòn Khoai',
    label: '[HÒN KHOAI (A2)]',
    lon: 104.832,
    lat: 8.435,
    type: 'minor_island',
    color: '#00f3ff',
    r: 1.8
  },
  {
    id: 'hon_me',
    name: 'Đảo Hòn Mê',
    label: '[HÒN MÊ]',
    lon: 105.925,
    lat: 19.367,
    type: 'minor_island',
    color: '#00f3ff',
    r: 1.8
  },
  {
    id: 'hon_ngu',
    name: 'Đảo Hòn Ngư',
    label: '[HÒN NGƯ]',
    lon: 105.767,
    lat: 18.802,
    type: 'minor_island',
    color: '#00f3ff',
    r: 1.8
  },
  {
    id: 'co_to',
    name: 'Quần đảo Cô Tô',
    label: '[CÔ TÔ]',
    lon: 107.765,
    lat: 20.985,
    type: 'minor_island',
    color: '#00f3ff',
    r: 1.8
  },
  {
    id: 'long_chau',
    name: 'Quần đảo Long Châu',
    label: '[LONG CHÂU (A11)]',
    lon: 107.160,
    lat: 20.623,
    type: 'minor_island',
    color: '#00f3ff',
    r: 1.8
  },
  {
    id: 'dk1_cluster',
    name: 'Cụm Nhà Giàn DK1 (Thềm lục địa)',
    label: '[CỤM DK1 // TƯ CHÍNH]',
    lon: 109.680,
    lat: 7.500,
    type: 'archipelago_cluster',
    color: '#00ff9d',
    islands: [
      { name: 'Nhà giàn DK1/11 (Tư Chính)', lon: 109.683, lat: 7.505, r: 1.6 },
      { name: 'Nhà giàn DK1/2 (Phúc Tần)', lon: 110.583, lat: 8.150, r: 1.6 },
      { name: 'Nhà giàn DK1/6 (Phúc Nguyên)', lon: 110.017, lat: 7.900, r: 1.6 },
      { name: 'Nhà giàn DK1/9 (Ba Kè)', lon: 111.450, lat: 7.450, r: 1.6 }
    ]
  }
];

/**
 * Tactical Maritime Boundary Polygons / Paths (Paracel & Spratly EEZ perimeters)
 * Coords format: [[lat, lng], [lat, lng], ...] for direct ingestion into react-globe.gl pathsData
 */
export const VIETNAM_MARITIME_BOUNDARIES = [
  {
    id: 'hoang_sa_patrol_perimeter',
    name: 'Vùng biển Quần đảo Hoàng Sa (VN)',
    coords: [
      [17.30, 111.00], [17.30, 113.20],
      [15.60, 113.20], [15.60, 111.00],
      [17.30, 111.00]
    ],
    color: 'rgba(0, 255, 157, 0.55)',
    stroke: 0.6,
  },
  {
    id: 'truong_sa_patrol_perimeter',
    name: 'Vùng biển Quần đảo Trường Sa (VN)',
    coords: [
      [12.00, 113.80], [11.80, 117.50],
      [7.20, 115.80], [7.20, 111.50],
      [9.50, 111.50], [12.00, 113.80]
    ],
    color: 'rgba(0, 255, 157, 0.55)',
    stroke: 0.6,
  },
  {
    id: 'gulf_of_tonkin_boundary',
    name: 'Tuyến phân định Vịnh Bắc Bộ (VN-CN 2000)',
    coords: [
      [21.50, 108.05], [21.23, 108.10], [20.78, 108.05],
      [20.13, 107.95], [19.42, 107.50], [18.50, 107.20],
      [17.78, 107.10], [17.17, 107.33]
    ],
    color: 'rgba(0, 243, 255, 0.45)',
    stroke: 0.5,
    dashLength: 0.05,
    dashGap: 0.02,
  },
  {
    id: 'southern_shelf_patrol',
    name: 'Vùng biển Thềm lục địa phía Nam & DK1',
    coords: [
      [8.68, 106.60], [6.50, 107.50], [6.50, 112.00],
      [7.50, 111.50], [8.50, 109.50], [8.68, 106.60]
    ],
    color: 'rgba(0, 255, 157, 0.45)',
    stroke: 0.6,
  }
];


