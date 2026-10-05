import { useEffect, useState } from 'react';
import type { GroupDetailResponse } from '../types';
import { getGroup, setDisposition, setNormalize } from '../api';

interface Props {
  groupId: string;
  onClose: () => void;
  onChanged: () => void;
  toast: (msg: string) => void;
}

const money = (n: number | null | undefined, cur = 'USD') =>
  n == null ? '-' : '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const DISPOSITIONS = ['reviewed', 'consolidated', 'dismissed'];

export default function GroupDetail({ groupId, onClose, onChanged, toast }: Props) {
  const [data, setData] = useState<GroupDetailResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [dispNotes, setDispNotes] = useState('');
  const [epn, setEpn] = useState('');
  const [normNotes, setNormNotes] = useState('');
  const [saving, setSaving] = useState(false);

  const load = () => {
    setErr(null);
    getGroup(groupId)
      .then((d) => {
        setData(d);
        setEpn(d.group.enterprise_part_number || '');
        setNormNotes(d.group.normalize_notes || '');
        setDispNotes(d.group.notes || '');
      })
      .catch((e) => setErr(String(e)));
  };

  useEffect(load, [groupId]);

  const doDisposition = async (status: string) => {
    setSaving(true);
    try {
      await setDisposition(groupId, status, dispNotes);
      toast(`Marked ${status}`);
      onChanged();
      load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setSaving(false);
    }
  };

  const doNormalize = async () => {
    if (!epn.trim()) return;
    setSaving(true);
    try {
      await setNormalize(groupId, epn.trim(), normNotes);
      toast('Enterprise part number assigned');
      onChanged();
      load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setSaving(false);
    }
  };

  const g = data?.group;
  // Net (after-discount) price is what savings are computed on; offers arrive sorted by it.
  const bestOffer = data?.offers?.length ? data.offers[0].net_price : null;

  return (
    <div className="overlay" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <div>
            <h2>
              {g ? `${g.part_category} · ${g.material}` : 'Group'}
            </h2>
            <div className="gid">{groupId}</div>
          </div>
          <button className="close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="drawer-body">
          {err && <div className="err">{err}</div>}
          {!data && !err && <div className="loading">Loading…</div>}

          {g && (
            <>
              <div className="card">
                <div className="stat-row">
                  <div className="stat">
                    <span className="v">{g.member_count}</span>
                    <span className="k">Members</span>
                  </div>
                  <div className="stat">
                    <span className="v">
                      {g.models_spanned}/{g.machine_types_spanned}/{g.plants_spanned}
                    </span>
                    <span className="k">Spans mdl/typ/plt</span>
                  </div>
                  <div className="stat">
                    <span className="v">{(g.avg_similarity ?? 0).toFixed(3)}</span>
                    <span className="k">Avg similarity</span>
                  </div>
                  <div className="stat">
                    <span className="v">{money(g.total_current_spend)}</span>
                    <span className="k">Annual spend</span>
                  </div>
                  <div className="stat">
                    <span className="v savings">{money(g.savings_potential)}</span>
                    <span className="k">Annual savings</span>
                  </div>
                  <div className="stat">
                    <span className="v">
                      <span className={`chip ${g.status}`}>{g.status}</span>
                    </span>
                    <span className="k">Status</span>
                  </div>
                </div>
              </div>

              <div className="card">
                <h3>Member parts ({data?.members.length})</h3>
                <div className="table-wrap" style={{ maxHeight: 260 }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Part #</th>
                        <th>Description</th>
                        <th>Model</th>
                        <th>Machine</th>
                        <th>Plant</th>
                        <th className="num">Sim.</th>
                        <th className="num">Best net price</th>
                        <th className="num">Annual vol.</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data?.members.map((m) => (
                        <tr key={m.part_id}>
                          <td className="mono">{m.part_number}</td>
                          <td>{m.description}</td>
                          <td className="mono">{m.model_id}</td>
                          <td>{m.machine_type}</td>
                          <td className="mono">{m.plant_id}</td>
                          <td className="num">{(m.similarity ?? 0).toFixed(3)}</td>
                          <td className="num">{money(m.member_best_price)}</td>
                          <td className="num">{(m.annual_volume ?? 0).toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="card">
                <h3>
                  Supplier pricing — best net price in group {bestOffer != null ? money(bestOffer) : ''}
                </h3>
                <div className="table-wrap" style={{ maxHeight: 300 }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Supplier</th>
                        <th>Part #</th>
                        <th className="num">List price</th>
                        <th className="num">Discount</th>
                        <th className="num">Net price</th>
                        <th className="num">vs best</th>
                        <th className="num">Lead (d)</th>
                        <th>Cur</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data?.offers.map((o, i) => {
                        const gap =
                          bestOffer != null && o.net_price != null
                            ? o.net_price - bestOffer
                            : 0;
                        return (
                          <tr key={`${o.part_id}-${o.supplier_name}-${i}`} className={i === 0 ? 'offer-best' : ''}>
                            <td className="supplier">{o.supplier_name}</td>
                            <td className="mono">{o.part_number}</td>
                            <td className="num">{money(o.price_per_unit)}</td>
                            <td className="num">{o.unit_discount != null ? (o.unit_discount * 100).toFixed(0) + '%' : '-'}</td>
                            <td className="num">{money(o.net_price)}</td>
                            <td className="num pricegap">
                              {gap <= 0 ? (
                                <span>best</span>
                              ) : (
                                <span className="up">+{money(gap)}</span>
                              )}
                            </td>
                            <td className="num">{o.lead_time_days ?? '-'}</td>
                            <td>{o.currency}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="card">
                <h3>Actions</h3>
                {g.reviewer && (
                  <div className="current-status">
                    Last disposition: <b>{g.status}</b> by {g.reviewer}
                    {g.updated_at ? ` · ${new Date(g.updated_at).toLocaleString()}` : ''}
                  </div>
                )}
                <div className="actions">
                  <div className="action-group">
                    <label style={{ fontSize: 12, color: 'var(--muted)' }}>Set disposition</label>
                    <textarea
                      placeholder="Optional notes…"
                      value={dispNotes}
                      onChange={(e) => setDispNotes(e.target.value)}
                    />
                    <div className="disp-btns">
                      {DISPOSITIONS.map((d) => (
                        <button
                          key={d}
                          className={`btn ${g.status === d ? 'active' : ''}`}
                          disabled={saving}
                          onClick={() => doDisposition(d)}
                        >
                          {d}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="action-group">
                    <label style={{ fontSize: 12, color: 'var(--muted)' }}>
                      Assign enterprise part number
                      {g.enterprise_part_number ? ` (current: ${g.enterprise_part_number})` : ''}
                    </label>
                    <div className="row">
                      <input
                        type="text"
                        placeholder="e.g. ENT-000123"
                        value={epn}
                        onChange={(e) => setEpn(e.target.value)}
                        style={{ flex: 1 }}
                      />
                    </div>
                    <textarea
                      placeholder="Optional notes…"
                      value={normNotes}
                      onChange={(e) => setNormNotes(e.target.value)}
                    />
                    <div className="row">
                      <button className="btn primary" disabled={saving || !epn.trim()} onClick={doNormalize}>
                        Assign & consolidate
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
