import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { format, formatDistanceToNow } from 'date-fns';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(date: string | Date): string {
  const d = typeof date === 'string' ? new Date(date) : date;
  return format(d, 'yyyy-MM-dd HH:mm');
}

export function formatRelativeTime(date: string | Date): string {
  const d = typeof date === 'string' ? new Date(date) : date;
  return formatDistanceToNow(d, { addSuffix: true });
}

export function getMarketLabel(market: string): string {
  const labels: Record<string, string> = {
    CN: 'A股',
    HK: '港股',
    US: '美股',
  };
  return labels[market] || market;
}

export function getMarketColor(market: string): string {
  const colors: Record<string, string> = {
    CN: 'text-red-400',
    HK: 'text-blue-400',
    US: 'text-purple-400',
  };
  return colors[market] || 'text-gray-400';
}

export function getDecisionColor(decision: string | undefined): string {
  const colors: Record<string, string> = {
    BUY: 'text-buy',
    SELL: 'text-sell',
    WATCH: 'text-watch',
    NO: 'text-neutral',
  };
  return colors[decision || 'NO'] || 'text-neutral';
}

export function getDecisionBgColor(decision: string | undefined): string {
  const colors: Record<string, string> = {
    BUY: 'bg-buy/10 text-buy border-buy/30',
    SELL: 'bg-sell/10 text-sell border-sell/30',
    WATCH: 'bg-watch/10 text-watch border-watch/30',
    NO: 'bg-neutral/10 text-neutral border-neutral/30',
  };
  return colors[decision || 'NO'] || 'bg-neutral/10 text-neutral border-neutral/30';
}

export function getStatusColor(status: string): string {
  const colors: Record<string, string> = {
    pending: 'text-yellow-400',
    running: 'text-blue-400 animate-pulse',
    completed: 'text-green-400',
    failed: 'text-red-400',
  };
  return colors[status] || 'text-gray-400';
}

export function detectMarket(code: string): string {
  const trimmed = code.trim().toUpperCase();

  if (trimmed.startsWith('HK') || (trimmed.length === 5 && /^\d+$/.test(trimmed) && trimmed.startsWith('0'))) {
    return 'HK';
  }
  if (trimmed.startsWith('US') || /^[A-Z]{1,5}$/.test(trimmed)) {
    return 'US';
  }
  return 'CN';
}
