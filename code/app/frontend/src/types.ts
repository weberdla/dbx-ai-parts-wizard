export interface QueueRow {
  group_id: string;
  part_category: string;
  material: string;
  member_count: number;
  models_spanned: number;
  machine_types_spanned: number;
  plants_spanned: number;
  avg_similarity: number;
  group_best_price: number;
  total_current_spend: number;
  savings_potential: number;
  status: string;
  normalized: boolean;
  enterprise_part_number: string | null;
}

export interface QueueResponse {
  total: number;
  rows: QueueRow[];
}

export interface FilterOptions {
  part_categories: string[];
  materials: string[];
  machine_types: string[];
  models: string[];
  plants: string[];
  suppliers: string[];
  statuses: string[];
}

export interface Member {
  part_id: string;
  part_number: string;
  description: string;
  model_id: string;
  machine_type: string;
  plant_id: string;
  similarity: number;
  member_best_price: number;
  annual_volume: number;
}

export interface Offer {
  part_id: string;
  part_number: string;
  supplier_name: string;
  price_per_unit: number;
  net_price: number;
  unit_discount: number;
  lead_time_days: number;
  currency: string;
}

export interface GroupDetailResponse {
  group: QueueRow & {
    reviewer: string | null;
    notes: string | null;
    updated_at: string | null;
    enterprise_part_number: string | null;
    assigned_by: string | null;
    assigned_at: string | null;
    normalize_notes: string | null;
  };
  members: Member[];
  offers: Offer[];
}

export interface Filters {
  part_category: string;
  material: string;
  machine_type: string;
  spans_models: boolean;
  spans_machine_types: boolean;
  spans_plants: boolean;
  model: string;
  plant: string;
  supplier: string;
  min_savings: string;
  min_similarity: string;
  status: string;
  normalized: string;
  min_group_size: string;
}
