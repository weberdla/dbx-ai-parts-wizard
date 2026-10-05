import type { FilterOptions, Filters } from '../types';

interface Props {
  options: FilterOptions | null;
  filters: Filters;
  onChange: (f: Filters) => void;
  onReset: () => void;
}

export default function FiltersPanel({ options, filters, onChange, onReset }: Props) {
  const set = (patch: Partial<Filters>) => onChange({ ...filters, ...patch });

  const sel = (
    key: keyof Filters,
    label: string,
    values: string[] | undefined,
    allLabel = 'All'
  ) => (
    <div className="field">
      <label>{label}</label>
      <select
        value={filters[key] as string}
        onChange={(e) => set({ [key]: e.target.value } as Partial<Filters>)}
      >
        <option value="">{allLabel}</option>
        {(values || []).map((v) => (
          <option key={v} value={v}>
            {v}
          </option>
        ))}
      </select>
    </div>
  );

  return (
    <aside className="filters">
      <h2>Filters</h2>

      {sel('status', 'Review status', options?.statuses, 'Any status')}
      {sel('part_category', 'Part category', options?.part_categories)}
      {sel('material', 'Material', options?.materials)}
      {sel('machine_type', 'Machine type', options?.machine_types)}

      <h2 style={{ marginTop: 16 }}>Duplication span</h2>
      <div className="toggles">
        <label className="toggle">
          <input
            type="checkbox"
            checked={filters.spans_models}
            onChange={(e) => set({ spans_models: e.target.checked })}
          />
          Spans &gt; 1 model
        </label>
        <label className="toggle">
          <input
            type="checkbox"
            checked={filters.spans_machine_types}
            onChange={(e) => set({ spans_machine_types: e.target.checked })}
          />
          Spans &gt; 1 machine type
        </label>
        <label className="toggle">
          <input
            type="checkbox"
            checked={filters.spans_plants}
            onChange={(e) => set({ spans_plants: e.target.checked })}
          />
          Spans &gt; 1 plant
        </label>
      </div>

      <h2 style={{ marginTop: 16 }}>Scope</h2>
      {sel('model', 'Model', options?.models)}
      {sel('plant', 'Plant', options?.plants)}
      {sel('supplier', 'Supplier', options?.suppliers)}

      <div className="field">
        <label>Normalized</label>
        <select value={filters.normalized} onChange={(e) => set({ normalized: e.target.value })}>
          <option value="">Any</option>
          <option value="yes">Yes</option>
          <option value="no">No</option>
        </select>
      </div>

      <h2 style={{ marginTop: 16 }}>Thresholds</h2>
      <div className="field">
        <label>Min annual savings ($)</label>
        <input
          type="number"
          value={filters.min_savings}
          placeholder="0"
          onChange={(e) => set({ min_savings: e.target.value })}
        />
      </div>
      <div className="field">
        <label>Min similarity (0-1)</label>
        <input
          type="number"
          step="0.01"
          min="0"
          max="1"
          value={filters.min_similarity}
          placeholder="0.0"
          onChange={(e) => set({ min_similarity: e.target.value })}
        />
      </div>
      <div className="field">
        <label>Min group size</label>
        <input
          type="number"
          value={filters.min_group_size}
          placeholder="1"
          onChange={(e) => set({ min_group_size: e.target.value })}
        />
      </div>

      <div className="filter-actions">
        <button className="btn ghost" onClick={onReset}>
          Reset to default
        </button>
      </div>
    </aside>
  );
}
