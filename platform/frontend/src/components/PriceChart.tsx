import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

interface PriceChartProps {
  data: Array<{
    date: string;
    close: number;
    open?: number;
    high?: number;
    low?: number;
    volume?: number;
  }>;
  height?: number;
}

export function PriceChart({ data, height = 200 }: PriceChartProps) {
  if (!data || data.length === 0) {
    return (
      <div className="flex items-center justify-center h-[200px] text-muted-foreground text-sm">
        价格数据加载中...
      </div>
    );
  }

  // Determine up/down color based on first and last close
  const firstClose = data[0]?.close || 0;
  const lastClose = data[data.length - 1]?.close || 0;
  const isUp = lastClose >= firstClose;
  const strokeColor = isUp ? '#22c55e' : '#ef4444';
  const fillColor = isUp ? '#22c55e' : '#ef4444';

  // Custom tooltip
  const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: Array<{ payload: { date: string; close: number } }> }) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-background border border-border rounded-lg p-2 shadow-lg text-xs">
          <div className="text-muted-foreground">{payload[0].payload.date}</div>
          <div className="font-semibold">收盘价: ${payload[0].payload.close.toFixed(2)}</div>
        </div>
      );
    }
    return null;
  };

  // Only show first and last date on X axis
  const tickFormatter = (value: string, index: number) => {
    if (index === 0 || index === data.length - 1) {
      return value;
    }
    return '';
  };

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
          <defs>
            <linearGradient id="colorClose" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={fillColor} stopOpacity={0.3} />
              <stop offset="95%" stopColor={fillColor} stopOpacity={0.05} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="date"
            tickFormatter={tickFormatter}
            tick={{ fill: '#888', fontSize: 11 }}
            axisLine={{ stroke: '#333' }}
            tickLine={{ stroke: '#333' }}
          />
          <YAxis
            domain={['auto', 'auto']}
            tick={{ fill: '#888', fontSize: 11 }}
            axisLine={{ stroke: '#333' }}
            tickLine={{ stroke: '#333' }}
            tickFormatter={(v: number) => `$${v.toFixed(0)}`}
            width={50}
          />
          <Tooltip content={<CustomTooltip />} />
          <Area
            type="monotone"
            dataKey="close"
            stroke={strokeColor}
            strokeWidth={2}
            fill="url(#colorClose)"
            animationDuration={500}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
