// Shared types for the 3D view. The renderer only sees PointCloudProps, so a different
// library (deck.gl, etc.) can be swapped in without touching data loading or the panel.

export interface ProjectionPayload {
  scope: 'global' | 'block';
  block_key: string;
  method: 'umap' | 'pca';
  count: number;
  columns: {
    part_id: string[];
    part_number: string[];
    x: number[];
    y: number[];
    z: number[];
    category: number[];
    material: number[];
    plant: number[];
    machine_type: number[];
    gt_label: number[];
    group: number[];
  };
  dicts: {
    category: string[];
    material: string[];
    plant: string[];
    machine_type: string[];
    gt_label: string[];
    group: string[];
  };
  groups: { group_id: string; savings?: number; size?: number }[];
}

export interface BlockInfo {
  block_key: string;
  part_category: string;
  material: string;
  parts: number;
  groups: number;
  savings: number;
}

export interface Neighbor {
  part_id: string;
  part_number: string;
  plant_id: string;
  group_id: string | null;
  gt_label: string | null;
  l2: number;
  is_duplicate: boolean;
}

export interface NeighborsResponse {
  part_id: string;
  threshold: number;
  neighbors: Neighbor[];
}

export interface Ray {
  to: number; // point index
  duplicate: boolean;
}

export interface PointCloudProps {
  positions: Float32Array; // xyz * n
  colors: Float32Array; // rgb * n, 0..1
  highlighted: number[]; // indices drawn larger on top (selected group)
  selected: number | null;
  rays: Ray[];
  autoRotate: boolean;
  flyTo: FlyTo | null; // external focus: animate the camera here
  closeup: CloseupView | null; // true-distance group close-up (ghosts the cloud)
  theme: import('./theme').MapTheme;

  onHover: (index: number | null, clientX: number, clientY: number) => void;
  onPick: (index: number | null) => void;
}

// Where the camera should go when something outside the map (queue, filters, Genie) focuses it.
export interface FlyTo {
  center: [number, number, number];
  radius: number;
  nonce: number;
  fit?: boolean; // close-up: frame tightly (no minimum distance)
  keepDist?: boolean; // only move the pivot; keep the current zoom and angle
}

// One request shape for everything that can drive the map.
export interface MapFocus {
  nonce: number;
  label: string;
  scope: string; // 'global' or a block_key ("Category|Material")
  partIds?: string[]; // highlight these parts
  groupIds?: string[];
  categories?: string[]; // dim everything outside these categories
  blocks?: string[]; // dim everything outside these (category|material) blocks
  autoSelect?: boolean; // single group: open its panel + neighbor rays
}

export interface LocateResponse {
  part_ids: string[];
  group_ids: string[];
  blocks: { block_key: string; parts: number }[];
}

export interface CloseupMember {
  part_id: string;
  part_number: string;
  plant_id: string;
  machine_type: string;
  description: string | null;
  best_price: number | null;
  annual_volume: number | null;
  pos: [number, number, number];
}

export interface CloseupNeighbor {
  part_id: string;
  part_number: string;
  plant_id: string;
  machine_type: string;
  in_other_group: boolean;
  gt_label: string | null;
  nearest_member: number;
  l2: number;
  differs_on: string | null;
  pos: [number, number, number];
}

export interface CloseupResponse {
  group_id: string;
  part_category: string;
  material: string;
  threshold: number;
  savings: number | null;
  current_spend: number | null;
  best_price: number | null;
  plants_spanned: number | null;
  members: CloseupMember[];
  edges: { a: number; b: number; l2: number }[];
  neighbors: CloseupNeighbor[];
}

export interface CloseupView {
  data: CloseupResponse;
  anchor: [number, number, number];
  scale: number;
}
