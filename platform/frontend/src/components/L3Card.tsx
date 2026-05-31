import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Cell } from 'recharts';
import type { Score, AnalysisRecord } from '@/types';

type L3CardData = AnalysisRecord | Record<string, unknown>;

interface L3CardProps {
  data: L3CardData;
  score?: Score;
}

const dimensionLabels: Record<string, string> = {
  moneyflow: '资金流',
  technical: '技术面',
  fundamental: '基本面',
  sector: '行业',
  event: '事件',
};

const dimensionColors = ['#22c55e', '#3b82f6', '#f59e0b', '#8b5cf6', '#ef4444'];

export function L3Card({ data, score: mappedScore }: L3CardProps) {
  // Extract l3_data - handle both cases: data is AnalysisRecord (has l3_data) or data is already l3_data
  const maybeL3Data = (data as AnalysisRecord)?.l3_data;
  const l3Data: Record<string, unknown> | undefined = maybeL3Data !== undefined ? maybeL3Data : (data as Record<string, unknown>);
  const results = l3Data?.results as Array<Record<string, unknown>> | undefined;
  const result0 = results?.[0] as Record<string, unknown> | undefined;
  const score = result0?.score as Record<string, unknown> | undefined;

  // Extract scores from L3 data - results[0].score.scores contains the five dimensions
  const l3Scores = score?.scores as Record<string, number> | undefined;
  const totalScore = score?.total_score as number | undefined;

  // Use L3 scores if available, otherwise fall back to mappedScore
  const scores = l3Scores || (mappedScore as Record<string, number> | undefined);

  if (!scores || Object.keys(scores).length === 0) {
    return (
      <Card className="card-hover-depth">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">L3 五维评分</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-muted-foreground text-sm">暂无五维评分数据</div>
        </CardContent>
      </Card>
    );
  }

  // Prepare radar chart data
  const radarData = Object.entries(scores)
    .filter(([key]) => ['moneyflow', 'technical', 'fundamental', 'sector', 'event'].includes(key))
    .map(([key, value]) => ({
      dimension: dimensionLabels[key] || key,
      value: typeof value === 'number' ? Math.round(value * 100) / 100 : 0,
      fullMark: 100,
    }));

  // Calculate average
  const values = radarData.map(d => d.value);
  const average = values.length > 0
    ? Math.round(values.reduce((sum, v) => sum + v, 0) / values.length * 100) / 100
    : 0;

  return (
    <Card className="card-hover-depth">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">L3 五维评分详情</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid md:grid-cols-2 gap-6">
          {/* Radar Chart */}
          <div>
            <div className="text-xs text-muted-foreground mb-2 text-center">五维雷达图</div>
            <div className="h-[200px]">
              <ResponsiveContainer width="100%" height="100%">
                <RadarChart data={radarData}>
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
          </div>

          {/* Bar Chart for individual scores */}
          <div>
            <div className="text-xs text-muted-foreground mb-2 text-center">各项得分</div>
            <div className="h-[200px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={radarData} layout="vertical">
                  <XAxis type="number" domain={[0, 100]} tick={{ fill: '#888', fontSize: 10 }} />
                  <YAxis
                    type="category"
                    dataKey="dimension"
                    tick={{ fill: '#888', fontSize: 11 }}
                    width={40}
                  />
                  <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                    {radarData.map((_, index) => (
                      <Cell key={`cell-${index}`} fill={dimensionColors[index % dimensionColors.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* Summary */}
        <div className="mt-4 pt-4 border-t border-border">
          <div className="flex items-center justify-between">
            <div className="text-sm text-muted-foreground">综合评分</div>
            <div className="text-2xl font-bold text-primary">{average.toFixed(2)}</div>
          </div>
          {totalScore !== undefined && (
            <div className="text-xs text-muted-foreground mt-1 text-center">
              原始总分: {totalScore.toFixed(2)}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
