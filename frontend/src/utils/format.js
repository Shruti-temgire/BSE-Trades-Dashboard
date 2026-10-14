const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });
const inrPrecise = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2 });
const integer = new Intl.NumberFormat('en-IN');

export const formatNumber = (n) => (n == null ? '—' : integer.format(n));
export const formatCurrency = (n) => (n == null ? '—' : inr.format(n));
export const formatPrice = (n) => (n == null ? '—' : inrPrecise.format(n));

// Indian convention: 1 crore = 10,000,000
export function formatCrores(n) {
  if (n == null) return '';
  return `≈ ₹${(n / 1e7).toLocaleString('en-IN', { maximumFractionDigits: 2 })} Cr`;
}

const tradeTime = new Intl.DateTimeFormat('en-IN', {
  timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short',
  hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
});
const localDateTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'medium' });

export const formatTradeTime = (iso) => (iso ? tradeTime.format(new Date(iso)) : '—');
export const formatDateTime = (iso) => (iso ? localDateTime.format(new Date(iso)) : 'Never');
