import type { QueueRow } from '../types';

interface Props {
  rows: QueueRow[];
  loading: boolean;
  onOpen: (groupId: string) => void;
}

const money = (n: number) =>
  n == null ? '-' : '$' + Math.round(n).toLocaleString('en-US');

function Chip({ status }: { status: string }) {
  return <span className={`chip ${status}`}>{status}</span>;
}

function Spans({ row }: { row: QueueRow }) {
  return (
    <span className="spans">
      <b>{row.models_spanned}</b> mdl / <b>{row.machine_types_spanned}</b> typ /{' '}
      <b>{row.plants_spanned}</b> plt
    </span>
  );
}

export default function MatchQueue({ rows, loading, onOpen }: Props) {
  if (loading) return <div className="loading">Loading match queue…</div>;
  if (!rows.length) return <div className="empty">No match groups for these filters.</div>;

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Category</th>
            <th>Material</th>
            <th className="num">Members</th>
            <th>Spans (mdl/typ/plt)</th>
            <th className="num">Avg sim.</th>
            <th className="num">Annual savings</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.group_id} onClick={() => onOpen(r.group_id)}>
              <td>{r.part_category}</td>
              <td>{r.material}</td>
              <td className="num">{r.member_count}</td>
              <td>
                <Spans row={r} />
              </td>
              <td className="num">{(r.avg_similarity ?? 0).toFixed(3)}</td>
              <td className="num savings">{money(r.savings_potential)}</td>
              <td>
                <Chip status={r.status} />
                {r.normalized && <span className="badge-norm">NORM</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
