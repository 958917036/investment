import { useEffect, useState } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { DecisionBadge } from '@/components/DecisionBadge';
import { ScoreCard } from '@/components/ScoreCard';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogClose,
} from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { compareResults, submitReflection } from '@/lib/api';
import { formatDate } from '@/lib/utils';
import type { CompareData, Score } from '@/types';
import { ArrowLeft, AlertTriangle, XCircle, TrendingUp } from 'lucide-react';

// Skeleton component for Compare page loading state
function CompareSkeleton() {
  return (
    <div className="space-y-6 animate-slide-up">
      {/* Header skeleton */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Skeleton className="h-10 w-10" />
          <div className="space-y-2">
            <Skeleton className="h-8 w-32" />
            <Skeleton className="h-4 w-24" />
          </div>
        </div>
        <Skeleton className="h-10 w-20" />
      </div>

      {/* Summary card skeleton */}
      <Card className="border-primary/30 bg-primary/5">
        <CardContent className="py-3 flex items-center gap-3">
          <Skeleton className="h-4 w-4" />
          <Skeleton className="h-4 w-64" />
        </CardContent>
      </Card>

      {/* Analysis panels skeleton - two columns */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <Skeleton className="h-6 w-20" />
              <Skeleton className="h-5 w-10" />
            </div>
            <Skeleton className="h-4 w-32 mt-2" />
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <Skeleton className="h-4 w-16" />
              <Skeleton className="h-6 w-16" />
            </div>
            <Skeleton className="h-px w-full" />
            <div className="space-y-2">
              <Skeleton className="h-4 w-16" />
              <Skeleton className="h-8 w-24" />
            </div>
            {/* Mock radar chart skeleton */}
            <Skeleton className="h-[180px] w-full" />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <Skeleton className="h-6 w-20" />
              <Skeleton className="h-5 w-10" />
            </div>
            <Skeleton className="h-4 w-32 mt-2" />
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <Skeleton className="h-4 w-16" />
              <Skeleton className="h-6 w-16" />
            </div>
            <Skeleton className="h-px w-full" />
            <div className="space-y-2">
              <Skeleton className="h-4 w-16" />
              <Skeleton className="h-8 w-24" />
            </div>
            {/* Mock radar chart skeleton */}
            <Skeleton className="h-[180px] w-full" />
          </CardContent>
        </Card>
      </div>

      {/* Score comparison card skeleton */}
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-24" />
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Skeleton className="h-4 w-16" />
              <Skeleton className="h-[100px] w-full" />
            </div>
            <div className="space-y-2">
              <Skeleton className="h-4 w-16" />
              <Skeleton className="h-[100px] w-full" />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Indicator changes card skeleton */}
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-24" />
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="flex items-center justify-between">
                <Skeleton className="h-4 w-16" />
                <div className="flex items-center gap-2">
                  <Skeleton className="h-4 w-12" />
                  <Skeleton className="h-4 w-4" />
                  <Skeleton className="h-4 w-12" />
                  <Skeleton className="h-5 w-12" />
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// Helper to extract five-dimensional score with priority: l4_data.five_scores > _five_score > l3 five_score > _judge_components
function extractFiveScore(record: any): Score | undefined {
  const l4Data = record?.l4_data as Record<string, unknown> | undefined;
  const decisions = l4Data?.decisions as Array<Record<string, unknown>> | undefined;

  // Priority 1: five_scores from L4 data (top-level five_scores field)
  const l4FiveScores = l4Data?.five_scores as Record<string, number> | undefined;
  if (l4FiveScores && Object.keys(l4FiveScores).length > 0) {
    return {
      growth: l4FiveScores.growth ?? l4FiveScores.w1_score ?? l4FiveScores.growth_score ?? 0,
      value: l4FiveScores.value ?? l4FiveScores.verdict_score ?? l4FiveScores.value_score ?? 0,
      momentum: l4FiveScores.momentum ?? l4FiveScores.w3_score ?? l4FiveScores.technical_score ?? 0,
      quality: l4FiveScores.quality ?? l4FiveScores.judge_score ?? l4FiveScores.sentiment_score ?? 0,
      risk: l4FiveScores.risk ?? 0,
    };
  }

  // Priority 2: _five_score from L4 decisions
  const l4FiveScore = decisions?.[0]?._five_score as Record<string, number> | undefined;
  if (l4FiveScore && Object.keys(l4FiveScore).length > 0) {
    return {
      growth: l4FiveScore.growth ?? l4FiveScore.w1_score ?? l4FiveScore.growth_score ?? 0,
      value: l4FiveScore.value ?? l4FiveScore.verdict_score ?? l4FiveScore.value_score ?? 0,
      momentum: l4FiveScore.momentum ?? l4FiveScore.w3_score ?? l4FiveScore.technical_score ?? 0,
      quality: l4FiveScore.quality ?? l4FiveScore.judge_score ?? l4FiveScore.sentiment_score ?? 0,
      risk: l4FiveScore.risk ?? 0,
    };
  }

  // Priority 3: L3 five_score from results[0].score.five_score
  const l3Data = record?.l3_data as Record<string, unknown> | undefined;
  const l3Results = l3Data?.results as Array<Record<string, unknown>> | undefined;
  const l3Score = (l3Results?.[0] as Record<string, unknown>)?.score as Record<string, unknown> | undefined;
  const l3FiveScore = l3Score?.five_score as Record<string, number> | undefined;
  if (l3FiveScore && Object.keys(l3FiveScore).length > 0) {
    return {
      growth: l3FiveScore.growth ?? l3FiveScore.w1_score ?? l3FiveScore.growth_score ?? 0,
      value: l3FiveScore.value ?? l3FiveScore.verdict_score ?? l3FiveScore.value_score ?? 0,
      momentum: l3FiveScore.momentum ?? l3FiveScore.w3_score ?? l3FiveScore.technical_score ?? 0,
      quality: l3FiveScore.quality ?? l3FiveScore.judge_score ?? l3FiveScore.sentiment_score ?? 0,
      risk: l3FiveScore.risk ?? 0,
    };
  }

  // Priority 4: _judge_components as fallback
  const judgeComponents = decisions?.[0]?._judge_components as Record<string, number> | undefined;
  if (judgeComponents) {
    return {
      growth: judgeComponents.w1_score ?? 0,
      value: judgeComponents.verdict_score ?? 0,
      momentum: judgeComponents.w3_score ?? 0,
      quality: judgeComponents.judge_score ?? 0,
      risk: 1 - (judgeComponents.volatility ?? 0),
    };
  }

  // Priority 5: direct score field if it has the five dimensions
  const directScore = record?.score as Record<string, number> | undefined;
  if (directScore && ('growth' in directScore || 'value' in directScore || 'momentum' in directScore)) {
    return {
      growth: directScore.growth ?? directScore.w1_score ?? directScore.growth_score ?? 0,
      value: directScore.value ?? directScore.verdict_score ?? directScore.value_score ?? 0,
      momentum: directScore.momentum ?? directScore.w3_score ?? directScore.technical_score ?? 0,
      quality: directScore.quality ?? directScore.judge_score ?? directScore.sentiment_score ?? 0,
      risk: directScore.risk ?? 0,
    };
  }

  return undefined;
}

const ERROR_TAGS = [
  '数据质量问题',
  '模型误判',
  '市场异常',
  '突发事件',
  '参数设置不当',
  '指标理解偏差',
  '周期选择错误',
  '其他',
];

export function Compare() {
  const { code } = useParams<{ code: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [data, setData] = useState<CompareData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reflectionOpen, setReflectionOpen] = useState(false);
  const [wrongAnalysis, setWrongAnalysis] = useState<'A' | 'B' | null>(null);
  const [reflectionText, setReflectionText] = useState('');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (code) {
      const ids = searchParams.get('ids');
      if (ids) {
        loadCompare();
      }
    }
  }, [code, searchParams]);

  const loadCompare = async () => {
    if (!code) return;
    const ids = searchParams.get('ids');
    if (!ids) return;

    setLoading(true);
    setError(null);
    try {
      const [idA, idB] = ids.split(',');
      const result = await compareResults(code, idA.trim(), idB.trim());
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  };

  const toggleTag = (tag: string) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]
    );
  };

  const handleSubmitReflection = async () => {
    if (!data || !wrongAnalysis || !reflectionText.trim()) return;

    setSubmitting(true);
    try {
      const correctId = wrongAnalysis === 'A' ? data.analysis_b.id : data.analysis_a.id;
      await submitReflection({
        analysis_id: wrongAnalysis === 'A' ? data.analysis_a.id : data.analysis_b.id,
        wrong_analysis: wrongAnalysis,
        reflection_text: reflectionText,
        error_tags: selectedTags,
        correct_analysis_id: correctId,
      });
      setReflectionOpen(false);
      setReflectionText('');
      setSelectedTags([]);
      setWrongAnalysis(null);
    } catch (err) {
      console.error('Failed to submit reflection:', err);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return <CompareSkeleton />;
  }

  if (error || !data) {
    return (
      <div className="space-y-6 animate-slide-up">
        <Card>
          <CardContent className="py-8 text-center">
            <div className="text-destructive mb-4">{error || '对比数据未找到'}</div>
            <Button variant="outline" onClick={() => navigate(-1)}>
              <ArrowLeft className="mr-2 h-4 w-4" />
              返回
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const { analysis_a, analysis_b, comparison } = data;

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => navigate(-1)}>
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <div>
            <h1 className="text-3xl font-bold tracking-tight">{code}</h1>
            <p className="text-muted-foreground">对比分析</p>
          </div>
        </div>
        <Dialog open={reflectionOpen} onOpenChange={setReflectionOpen}>
          <DialogTrigger asChild>
            <Button variant="outline">
              <AlertTriangle className="mr-2 h-4 w-4" />
              反思
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-[500px]">
            <DialogHeader>
              <DialogTitle>分析反思</DialogTitle>
              <DialogDescription>
                选择哪个分析结果有问题，帮助系统改进
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label>哪个分析有问题？</Label>
                <div className="grid grid-cols-2 gap-3">
                  <Button
                    variant={wrongAnalysis === 'A' ? 'default' : 'outline'}
                    onClick={() => setWrongAnalysis('A')}
                    className={wrongAnalysis === 'A' ? '' : 'border-2'}
                  >
                    <XCircle className="mr-2 h-4 w-4" />
                    A ({analysis_a.timestamp && formatDate(analysis_a.timestamp).split(' ')[0]})
                  </Button>
                  <Button
                    variant={wrongAnalysis === 'B' ? 'default' : 'outline'}
                    onClick={() => setWrongAnalysis('B')}
                    className={wrongAnalysis === 'B' ? '' : 'border-2'}
                  >
                    <XCircle className="mr-2 h-4 w-4" />
                    B ({analysis_b.timestamp && formatDate(analysis_b.timestamp).split(' ')[0]})
                  </Button>
                </div>
              </div>

              <div className="space-y-2">
                <Label>错误类型（可多选）</Label>
                <div className="flex flex-wrap gap-2">
                  {ERROR_TAGS.map((tag) => (
                    <button
                      key={tag}
                      onClick={() => toggleTag(tag)}
                      className={`px-3 py-1 rounded text-sm transition-colors ${
                        selectedTags.includes(tag)
                          ? 'bg-primary text-primary-foreground'
                          : 'bg-muted hover:bg-muted/80'
                      }`}
                    >
                      {tag}
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-2">
                <Label>反思说明</Label>
                <Textarea
                  value={reflectionText}
                  onChange={(e) => setReflectionText(e.target.value)}
                  placeholder="详细说明哪里出了问题，以及你认为正确的结果应该是什么..."
                  className="min-h-[100px]"
                />
              </div>
            </div>
            <DialogFooter>
              <DialogClose asChild>
                <Button variant="outline">取消</Button>
              </DialogClose>
              <Button
                onClick={handleSubmitReflection}
                disabled={!wrongAnalysis || !reflectionText.trim() || submitting}
              >
                {submitting ? '提交中...' : '提交反思'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {(() => {
        // Calculate summary stats using five-dimensional score
        const fiveScoreA = extractFiveScore(analysis_a);
        const fiveScoreB = extractFiveScore(analysis_b);
        const avgScoreA = fiveScoreA ? (
          Object.values(fiveScoreA)
            .filter(v => typeof v === 'number')
            .reduce((a, b) => a + b, 0) / 5
        ) : 0;
        const avgScoreB = fiveScoreB ? (
          Object.values(fiveScoreB)
            .filter(v => typeof v === 'number')
            .reduce((a, b) => a + b, 0) / 5
        ) : 0;
        const scoreDiff = avgScoreB - avgScoreA;
        const decisionChanged = comparison.decision_changed;

        const summary = decisionChanged
          ? `决策从 ${comparison.decision_a || '?'} 变为 ${comparison.decision_b || '?'}，评分${scoreDiff >= 0 ? '上升' : '下降'}了 ${Math.abs(scoreDiff).toFixed(1)} 分`
          : `评分${scoreDiff >= 0 ? '上升' : '下降'}了 ${Math.abs(scoreDiff).toFixed(1)} 分，决策维持 ${comparison.decision_a || '?'}`;

        return (
          <Card className="border-primary/30 bg-primary/5">
            <CardContent className="py-3 flex items-center gap-3">
              <TrendingUp className="h-4 w-4 text-primary" />
              <span className="text-sm font-medium">{summary}</span>
            </CardContent>
          </Card>
        );
      })()}

      {comparison.decision_changed && (
        <Card className="border-watch/50 bg-watch/10">
          <CardContent className="py-3 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-watch" />
            <span className="text-sm">
              决策发生变化: <span className="font-medium">{comparison.decision_a}</span> → <span className="font-medium">{comparison.decision_b}</span>
            </span>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <AnalysisPanel
          label="A"
          record={analysis_a}
          isLatest={false}
        />
        <AnalysisPanel
          label="B"
          record={analysis_b}
          isLatest={true}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">评分对比</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2">
            <ScoreCard score={extractFiveScore(analysis_a) || comparison.score_a} title="A 评分" />
            <ScoreCard score={extractFiveScore(analysis_b) || comparison.score_b} title="B 评分" />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">指标变化</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {/* L1 indicators from candidates */}
            {(() => {
              const l1A = (analysis_a?.l1_data?.candidates as Record<string, unknown>[])?.[0] || {} as Record<string, unknown>;
              const l1B = (analysis_b?.l1_data?.candidates as Record<string, unknown>[])?.[0] || {} as Record<string, unknown>;
              const l1Indicators = [
                { key: 'pe', label: 'PE', getA: () => l1A.pe, getB: () => l1B.pe, format: 'number' as const },
                { key: 'change_pct', label: '涨跌幅', getA: () => l1A.change_pct, getB: () => l1B.change_pct, format: 'percent' as const },
                { key: 'volume', label: '成交量', getA: () => l1A.volume, getB: () => l1B.volume, format: 'volume' as const },
              ];

              return l1Indicators.map(({ key, label, getA, getB, format }) => {
                const valA = getA();
                const valB = getB();
                if (valA === undefined && valB === undefined) return null;
                const delta = (typeof valB === 'number' ? valB : 0) - (typeof valA === 'number' ? valA : 0);

                const formatVal = (v: unknown) => {
                  if (typeof v !== 'number') return '-';
                  if (format === 'percent') return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
                  if (format === 'volume') return v >= 1e6 ? `${(v / 1e6).toFixed(2)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(2)}K` : v.toFixed(2);
                  return v.toFixed(2);
                };

                return (
                  <div key={key} className="flex items-center justify-between">
                    <span className="text-sm">{label}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-mono">{formatVal(valA)}</span>
                      <span className="text-muted-foreground">→</span>
                      <span className="text-sm font-mono">{formatVal(valB)}</span>
                      <span
                        className={`text-xs font-medium px-2 py-0.5 rounded ${
                          delta > 0 ? 'bg-buy/10 text-buy' : delta < 0 ? 'bg-sell/10 text-sell' : 'bg-muted'
                        }`}
                      >
                        {delta > 0 ? '+' : ''}{format === 'percent' ? delta.toFixed(2) + '%' : format === 'volume' ? (delta >= 1e6 ? `${(delta / 1e6).toFixed(2)}M` : delta >= 1e3 ? `${(delta / 1e3).toFixed(2)}K` : delta.toFixed(2)) : delta.toFixed(2)}
                      </span>
                    </div>
                  </div>
                );
              });
            })()}

            {/* L2 technical indicators */}
            {(() => {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const l2A_stocks = (analysis_a?.l2_data?.stocks as any)?.[0]?._data?.technical_data as Record<string, unknown> | undefined;
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const l2B_stocks = (analysis_b?.l2_data?.stocks as any)?.[0]?._data?.technical_data as Record<string, unknown> | undefined;
              const l2A = l2A_stocks ?? {};
              const l2B = l2B_stocks ?? {};
              const l2Indicators = [
                { key: 'rsi', label: 'RSI', getA: () => l2A.rsi, getB: () => l2B.rsi },
                { key: 'return_m1', label: '1月收益', getA: () => l2A.return_m1, getB: () => l2B.return_m1 },
                { key: 'return_m3', label: '3月收益', getA: () => l2A.return_m3, getB: () => l2B.return_m3 },
              ];

              return l2Indicators.map(({ key, label, getA, getB }) => {
                const valA = getA();
                const valB = getB();
                if (valA === undefined && valB === undefined) return null;
                const delta = (typeof valB === 'number' ? valB : 0) - (typeof valA === 'number' ? valA : 0);

                const formatVal = (v: unknown) => {
                  if (typeof v !== 'number') return '-';
                  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
                };

                return (
                  <div key={key} className="flex items-center justify-between">
                    <span className="text-sm">{label}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-mono">{formatVal(valA)}</span>
                      <span className="text-muted-foreground">→</span>
                      <span className="text-sm font-mono">{formatVal(valB)}</span>
                      <span
                        className={`text-xs font-medium px-2 py-0.5 rounded ${
                          delta > 0 ? 'bg-buy/10 text-buy' : delta < 0 ? 'bg-sell/10 text-sell' : 'bg-muted'
                        }`}
                      >
                        {delta > 0 ? '+' : ''}{delta.toFixed(2)}%
                      </span>
                    </div>
                  </div>
                );
              });
            })()}

            {/* Five-dimensional score changes */}
            {(() => {
              const fiveA = extractFiveScore(analysis_a);
              const fiveB = extractFiveScore(analysis_b);
              if (!fiveA && !fiveB) return null;

              const dimensions = [
                { key: 'growth', label: '成长' },
                { key: 'value', label: '价值' },
                { key: 'momentum', label: '动量' },
                { key: 'quality', label: '质量' },
                { key: 'risk', label: '风险' },
              ];

              return (
                <>
                  <div className="pt-3 border-t border-border">
                    <div className="text-sm text-muted-foreground mb-2">五维评分变化</div>
                    {dimensions.map(({ key, label }) => {
                      const valA = fiveA?.[key] ?? 0;
                      const valB = fiveB?.[key] ?? 0;
                      const delta = valB - valA;
                      return (
                        <div key={key} className="flex items-center justify-between">
                          <span className="text-sm">{label}</span>
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-mono">{valA.toFixed(2)}</span>
                            <span className="text-muted-foreground">→</span>
                            <span className="text-sm font-mono">{valB.toFixed(2)}</span>
                            <span
                              className={`text-xs font-medium px-2 py-0.5 rounded ${
                                delta > 0 ? 'bg-buy/10 text-buy' : delta < 0 ? 'bg-sell/10 text-sell' : 'bg-muted'
                              }`}
                            >
                              {delta > 0 ? '+' : ''}{delta.toFixed(2)}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </>
              );
            })()}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function AnalysisPanel({
  label,
  record,
  isLatest,
}: {
  label: string;
  record: any;
  isLatest: boolean;
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">分析 {label}</CardTitle>
          {isLatest && (
            <span className="text-xs bg-primary/10 text-primary px-2 py-1 rounded">
              最新
            </span>
          )}
        </div>
        <div className="text-sm text-muted-foreground">
          {record.timestamp && formatDate(record.timestamp)}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">决策</span>
          <DecisionBadge decision={record.final_decision} />
        </div>

        {record.score && Object.keys(record.score).length > 0 && (
          <div className="pt-3 border-t border-border">
            <div className="text-sm text-muted-foreground mb-2">综合评分</div>
            <div className="text-2xl font-bold text-primary">
              {(
                Object.values(record.score)
                  .filter((v: unknown) => typeof v === 'number')
                  .reduce((a: number, b: unknown) => a + (b as number), 0) / 5
              ).toFixed(2)}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
