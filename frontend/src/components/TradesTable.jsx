import { formatCurrency, formatNumber, formatPrice, formatTradeTime } from '../utils/format';
import Pagination from './Pagination';
import './TradesTable.css';

const SKELETON_ROWS = 8;

function EmptyState({ search }) {
  return (
    <div className="table-empty">
      <div className="table-empty__icon" aria-hidden="true">{search ? '🔍' : '📊'}</div>
      {search ? (
        <>
          <p className="table-empty__title">No trades match “{search}”</p>
          <p className="table-empty__text">Try a symbol (e.g. RELIANCE), a client name or a trade ID.</p>
        </>
      ) : (
        <>
          <p className="table-empty__title">No trades stored yet</p>
          <p className="table-empty__text">Click <strong>Pull Trades</strong> to fetch them from BSE. They will appear here live.</p>
        </>
      )}
    </div>
  );
}

export default function TradesTable({
  table, searchInput, onSearchChange, onPageChange, loading, error, onRetry,
  freshIds, pendingNew, onShowLatest,
}) {
  const { items, total, page, totalPages, search } = table;
  const showSkeleton = loading && items.length === 0;

  return (
    <section className="panel trades" aria-label="Trades">
      <div className="trades__toolbar">
        <div>
          <h2 className="panel__title">Trades</h2>
          <p className="trades__count">
            {search ? `${formatNumber(total)} matching trades` : `${formatNumber(total)} trades · newest first`}
          </p>
        </div>
        <label className="search">
          <span className="visually-hidden">Search trades</span>
          <svg className="search__icon" viewBox="0 0 20 20" width="16" height="16" aria-hidden="true">
            <path d="M8.5 3a5.5 5.5 0 014.38 8.82l3.65 3.65-1.06 1.06-3.65-3.65A5.5 5.5 0 118.5 3zm0 1.5a4 4 0 100 8 4 4 0 000-8z" fill="currentColor" />
          </svg>
          <input
            type="search"
            className="search__input"
            placeholder="Search trade ID, client or symbol…"
            value={searchInput}
            onChange={(e) => onSearchChange(e.target.value)}
            maxLength={100}
          />
          {loading && items.length > 0 && <span className="search__spinner" aria-label="Loading" />}
        </label>
      </div>

      {pendingNew > 0 && (
        <button type="button" className="new-banner" onClick={onShowLatest}>
          {formatNumber(pendingNew)} new trade{pendingNew === 1 ? '' : 's'} stored · Show latest
        </button>
      )}

      {error && (
        <div className="inline-alert inline-alert--error trades__error">
          {error}
          <button type="button" className="button button--small" onClick={onRetry}>Retry</button>
        </div>
      )}

      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Trade ID</th>
              <th>Time (IST)</th>
              <th>Client</th>
              <th>Symbol</th>
              <th className="num">Quantity</th>
              <th className="num">Price</th>
              <th className="num">Value</th>
            </tr>
          </thead>
          <tbody>
            {showSkeleton &&
              Array.from({ length: SKELETON_ROWS }, (_, i) => (
                <tr key={`sk-${i}`} className="table__skeleton-row">
                  {Array.from({ length: 7 }, (__, j) => (
                    <td key={j}><span className="skeleton" /></td>
                  ))}
                </tr>
              ))}
            {!showSkeleton &&
              items.map((t) => (
                <tr key={t.trade_id} className={freshIds.has(t.trade_id) ? 'row--new' : undefined}>
                  <td className="mono">{t.trade_id}</td>
                  <td className="nowrap">{formatTradeTime(t.timestamp)}</td>
                  <td className="client">{t.client}</td>
                  <td><span className="symbol">{t.symbol}</span></td>
                  <td className="num">{formatNumber(t.quantity)}</td>
                  <td className="num">{formatPrice(t.price)}</td>
                  <td className="num strong">{formatCurrency(t.value)}</td>
                </tr>
              ))}
          </tbody>
        </table>
        {!showSkeleton && !error && items.length === 0 && <EmptyState search={search} />}
      </div>

      <Pagination page={page} totalPages={totalPages} onChange={onPageChange} disabled={loading} />
    </section>
  );
}
