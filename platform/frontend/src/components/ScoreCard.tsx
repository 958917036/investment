import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar, ResponsiveContainer } from 'recharts';
import type { Score } from '@/types';

interface ScoreCardProps {
  score: Score | undefined;
  title?: string;
  showDetails?: boolean;
  compact?: boolean;
}

const dimensionLabels: Record<string, string> = {
  growth: '成长',
  value: '价值',
  momentum: '动量',
  quality: '质量',
  risk: '风险',
};

const dimensionColors = ['#22c55e', '#3b82f6', '#f59e0b', '#8b5cf6', '#ef4444'];

export function ScoreCard({ score, title = '五维评分', showDetails = true, compact = false }: ScoreCardProps) {
  if (!score || Object.keys(score).length === 0) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center text-muted-foreground py-8">暂无评分数据</div>
        </CardContent>
      </Card>
    );
  }

  const data = Object.entries(score)
    .filter(([key]) => ['growth', 'value', 'momentum', 'quality', 'risk'].includes(key))
    .map(([key, value]) => ({
      dimension: dimensionLabels[key] || key,
      value: typeof value === 'number' ? Math.round(value * 100) / 100 : 0,
      fullMark: 100,
    }));

  const average = data.length > 0
    ? Math.round(data.reduce((sum, d) => sum + d.value, 0) / data.length * 100) / 100
    : 0;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className={compact ? 'h-[150px]' : 'h-[200px]'}>
          <ResponsiveContainer width="100%" height="100%">
            <RadarChart data={data}>
              <PolarGrid stroke="#333" />
              <PolarAngleAxis
                dataKey="dimension"
                tick={{ fill: '#888', fontSize: 12 }}
              />
              <PolarRadiusAxis
                angle={90}
                domain={[0, 100]}
                tick={{ fill: '#666', fontSize: 10 }}
              />
              <Radar
                name="评分"
                dataKey="value"
                stroke="#22c55e"
                fill="#22c55e"
                fillOpacity={0.3}
                strokeWidth={2}
              />
            </RadarChart>
          </ResponsiveContainer>
        </div>
        {showDetails && (
          <>
            <div className={`mt-4 grid grid-cols-5 gap-2 text-center ${compact ? 'grid-cols-3' : ''}`}>
              {data.map((d, i) => (
                <div key={d.dimension} className="space-y-1">
                  <div className="text-xs text-muted-foreground">{d.dimension}</div>
                  <div className="text-sm font-semibold" style={{ color: dimensionColors[i % dimensionColors.length] }}>
                    {d.value.toFixed(1)}
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4 pt-4 border-t border-border text-center">
              <span className="text-sm text-muted-foreground">综合评分: </span>
              <span className="text-lg font-bold text-primary">{average.toFixed(2)}</span>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// Mini version for inline use
export function ScoreBadge({ score }: { score: Score | undefined }) {
  if (!score || Object.keys(score).length === 0) return null;

  const values = Object.entries(score)
    .filter(([key]) => ['growth', 'value', 'momentum', 'quality', 'risk'].includes(key))
    .map(([, value]) => typeof value === 'number' ? value : 0);

  const average = values.length > 0
    ? Math.round(values.reduce((sum, v) => sum + v, 0) / values.length * 100) / 100
    : 0;

  return (
    <span className="inline-flex items-center px-2 py-1 rounded text-xs font-semibold bg-primary/10 text-primary">
      {average.toFixed(1)}
    </span>
  );
}