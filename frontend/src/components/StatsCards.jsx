import { formatCrores, formatCurrency, formatNumber } from '../utils/format';
import './StatsCards.css';

function StatCard({ label, value, hint, loading }) {
  return (
    <div className="stat-card">
      <span className="stat-card__label">{label}</span>
      {loading ? (
        <span className="skeleton stat-card__skeleton" />
      ) : (
        <span className="stat-card__value">{value}</span>
      )}
      <span className="stat-card__hint">{loading ? ' ' : hint}</span>
    </div>
  );
}

export default function StatsCards({ stats, loading }) {
  return (
    <section className="stats" aria-label="Summary statistics">
      <StatCard label="Total trades" value={formatNumber(stats?.total_trades)} hint="Stored in database" loading={loading} />
      <StatCard label="Unique clients" value={formatNumber(stats?.unique_clients)} hint="Distinct client accounts" loading={loading} />
      <StatCard label="Unique symbols" value={formatNumber(stats?.unique_symbols)} hint="Distinct BSE scrips" loading={loading} />
      <StatCard
        label="Total traded value"
        value={formatCurrency(stats?.total_value)}
        hint={stats?.total_value ? formatCrores(stats.total_value) : 'Σ quantity × price'}
        loading={loading}
      />
    </section>
  );
}
