import { Badge } from '@/components/ui/badge';
import type { Decision } from '@/types';

interface DecisionBadgeProps {
  decision: Decision | undefined;
  size?: 'sm' | 'md' | 'lg';
}

const decisionLabels: Record<string, string> = {
  BUY: '买入',
  SELL: '卖出',
  WATCH: '观察',
  NO: '无信号',
};

export function DecisionBadge({ decision, size = 'md' }: DecisionBadgeProps) {
  const variantMap: Record<string, 'buy' | 'sell' | 'watch' | 'neutral'> = {
    BUY: 'buy',
    SELL: 'sell',
    WATCH: 'watch',
    NO: 'neutral',
  };

  const variant = variantMap[decision || 'NO'] || 'neutral';
  const label = decisionLabels[decision || 'NO'] || '无信号';

  const sizeClasses = {
    sm: 'text-xs px-2 py-0.5',
    md: 'text-sm px-2.5 py-0.5',
    lg: 'text-base px-3 py-1',
  };

  return (
    <Badge variant={variant} className={sizeClasses[size]}>
      {label}
    </Badge>
  );
}
