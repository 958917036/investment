import { LineChart, Line, ResponsiveContainer } from 'recharts';

interface SparklineProps {
  data: Array<{ value: number }>;
  height?: number;
}

export function Sparkline({ data, height = 32 }: SparklineProps) {
  if (!data || data.length === 0) {
    return <div style={{ height }} className="w-16" />;
  }

  const isUp = data[data.length - 1]?.value >= data[0]?.value;
  const strokeColor = isUp ? '#22c55e' : '#ef4444';

  return (
    <div style={{ height, width: 64 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <Line
            type="monotone"
            dataKey="value"
            stroke={strokeColor}
            strokeWidth={1.5}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
