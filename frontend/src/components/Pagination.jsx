import { formatNumber } from '../utils/format';
import './Pagination.css';

export default function Pagination({ page, totalPages, onChange, disabled }) {
  if (totalPages <= 1) return null;
  const go = (p) => onChange(Math.min(Math.max(1, p), totalPages));

  return (
    <nav className="pagination" aria-label="Trades pages">
      <button type="button" className="button button--small" onClick={() => go(1)} disabled={disabled || page === 1}>
        « First
      </button>
      <button type="button" className="button button--small" onClick={() => go(page - 1)} disabled={disabled || page === 1}>
        ‹ Prev
      </button>
      <span className="pagination__label">
        Page <strong>{formatNumber(page)}</strong> of {formatNumber(totalPages)}
      </span>
      <button type="button" className="button button--small" onClick={() => go(page + 1)} disabled={disabled || page >= totalPages}>
        Next ›
      </button>
      <button type="button" className="button button--small" onClick={() => go(totalPages)} disabled={disabled || page >= totalPages}>
        Last »
      </button>
    </nav>
  );
}
