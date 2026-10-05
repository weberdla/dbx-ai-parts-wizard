import type {
  QueueResponse,
  FilterOptions,
  GroupDetailResponse,
  Filters,
} from './types';

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

export async function getMe(): Promise<{ reviewer: string }> {
  return json(await fetch('/api/me'));
}

export async function getFilters(): Promise<FilterOptions> {
  return json(await fetch('/api/filters'));
}

export async function getQueue(
  f: Filters,
  sort: string,
  direction: string,
  limit = 100,
  offset = 0
): Promise<QueueResponse> {
  const p = new URLSearchParams();
  if (f.part_category) p.set('part_category', f.part_category);
  if (f.material) p.set('material', f.material);
  if (f.machine_type) p.set('machine_type', f.machine_type);
  if (f.spans_models) p.set('spans_models', 'true');
  if (f.spans_machine_types) p.set('spans_machine_types', 'true');
  if (f.spans_plants) p.set('spans_plants', 'true');
  if (f.model) p.set('model', f.model);
  if (f.plant) p.set('plant', f.plant);
  if (f.supplier) p.set('supplier', f.supplier);
  if (f.min_savings) p.set('min_savings', f.min_savings);
  if (f.min_similarity) p.set('min_similarity', f.min_similarity);
  if (f.status) p.set('status', f.status);
  if (f.normalized) p.set('normalized', f.normalized);
  if (f.min_group_size) p.set('min_group_size', f.min_group_size);
  p.set('sort', sort);
  p.set('direction', direction);
  p.set('limit', String(limit));
  p.set('offset', String(offset));
  return json(await fetch(`/api/queue?${p.toString()}`));
}

export async function getGroup(groupId: string): Promise<GroupDetailResponse> {
  return json(await fetch(`/api/groups/${groupId}`));
}

export async function setDisposition(
  groupId: string,
  status: string,
  notes: string
): Promise<void> {
  await json(
    await fetch(`/api/groups/${groupId}/disposition`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status, notes }),
    })
  );
}

export interface ChatResponse {
  conversation_id: string | null;
  message_id: string | null;
  status: string | null;
  answer: string | null;
  sql: string | null;
  columns: string[];
  rows: (string | number | null)[][];
  error: string | null;
}

export async function askGenie(
  question: string,
  conversationId: string | null
): Promise<ChatResponse> {
  return json(
    await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, conversation_id: conversationId }),
    })
  );
}

export async function setNormalize(
  groupId: string,
  enterprise_part_number: string,
  notes: string
): Promise<void> {
  await json(
    await fetch(`/api/groups/${groupId}/normalize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enterprise_part_number, notes }),
    })
  );
}
