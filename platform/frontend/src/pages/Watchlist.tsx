import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { DecisionBadge } from '@/components/DecisionBadge';
import { ScoreCard } from '@/components/ScoreCard';
import { Skeleton } from '@/components/ui/skeleton';
import { getWatchlist, removeFromWatchlist } from '@/lib/api';
import { formatRelativeTime } from '@/lib/utils';
import type { WatchlistItem } from '@/types';
import { Eye, Star, Trash2, AlertCircle, BarChart3 } from 'lucide-react';

export function Watchlist() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadWatchlist();
  }, []);

  const loadWatchlist = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getWatchlist();
      setItems(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  };

  const handleRemove = async (stockCode: string) => {
    try {
      await removeFromWatchlist(stockCode);
      setItems(items.filter(item => item.stock_code !== stockCode));
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    }
  };

  // Count decisions
  const decisionCounts = items.reduce((acc, item) => {
    const decision = item.latest_analysis?.final_decision || 'NO';
    acc[decision] = (acc[decision] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  if (loading) {
    return (
      <div className="space-y-6 animate-slide-up">
        <Skeleton className="h-10 w-48" />
        <div className="grid gap-4 md:grid-cols-4">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
        <Skeleton className="h-[400px]" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6 animate-slide-up">
        <Card>
          <CardContent className="py-8 text-center">
            <div className="text-destructive mb-4">{error}</div>
            <Button variant="outline" onClick={loadWatchlist}>重试</Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Eye className="h-8 w-8 text-primary" />
          <h1 className="text-3xl font-bold tracking-tight">关注列表</h1>
        </div>
        <Button variant="outline" onClick={loadWatchlist}>刷新</Button>
      </div>

      {/* Summary Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">关注总数</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{items.length}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">买入信号</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-buy">{decisionCounts.BUY || 0}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">观望信号</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-watch">{decisionCounts.WATCH || 0}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">无信号</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-neutral">{decisionCounts.NO || 0}</div>
          </CardContent>
        </Card>
      </div>

      {/* Watchlist Table */}
      <Card>
        <CardHeader>
          <CardTitle>关注股票 ({items.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {items.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <AlertCircle className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p>暂无关注股票</p>
              <p className="text-sm mt-2">从分析结果中添加股票到关注列表</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border">
                    <th className="text-left py-3 px-2 font-medium">股票代码</th>
                    <th className="text-left py-3 px-2 font-medium">名称</th>
                    <th className="text-center py-3 px-2 font-medium">最新决策</th>
                    <th className="text-right py-3 px-2 font-medium">综合评分</th>
                    <th className="text-left py-3 px-2 font-medium">最后分析</th>
                    <th className="text-center py-3 px-2 font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => {
                    const score = item.latest_analysis?.score;
                    const avgScore = score 
                      ? Object.values(score).filter(v => typeof v === 'number').reduce((a, b) => a + (b as number), 0) / 
                        Object.values(score).filter(v => typeof v === 'number').length
                      : null;

                    return (
                      <tr key={item.stock_code} className="border-b border-border hover:bg-muted/50">
                        <td className="py-3 px-2">
                          {item.latest_analysis?.id ? (
                            <Link to={`/result/${encodeURIComponent(item.latest_analysis.id)}`} className="hover:text-primary font-mono">
                              {item.stock_code}
                            </Link>
                          ) : (
                            <span className="font-mono">{item.stock_code}</span>
                          )}
                        </td>
                        <td className="py-3 px-2">{item.stock_name || '-'}</td>
                        <td className="py-3 px-2 text-center">
                          {item.latest_analysis?.final_decision ? (
                            <DecisionBadge decision={item.latest_analysis.final_decision} size="sm" />
                          ) : (
                            <span className="text-muted-foreground">-</span>
                          )}
                        </td>
                        <td className="py-3 px-2 text-right">
                          {avgScore !== null ? (
                            <span className="font-semibold">{avgScore.toFixed(1)}</span>
                          ) : (
                            <span className="text-muted-foreground">-</span>
                          )}
                        </td>
                        <td className="py-3 px-2 text-muted-foreground">
                          {item.latest_analysis?.timestamp 
                            ? formatRelativeTime(item.latest_analysis.timestamp)
                            : '-'}
                        </td>
                        <td className="py-3 px-2">
                          <div className="flex items-center justify-center gap-2">
                            {item.latest_analysis?.id && (
                              <Link to={`/result/${encodeURIComponent(item.latest_analysis.id)}`}>
                                <Button variant="ghost" size="icon" className="h-8 w-8">
                                  <BarChart3 className="h-4 w-4" />
                                </Button>
                              </Link>
                            )}
                            <Link to={`/history/${item.stock_code}`}>
                              <Button variant="ghost" size="icon" className="h-8 w-8">
                                <Star className="h-4 w-4" />
                              </Button>
                            </Link>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 text-muted-foreground hover:text-destructive"
                              onClick={() => handleRemove(item.stock_code)}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Score Cards Grid */}
      {items.length > 0 && items.filter(item => item.latest_analysis?.score).length > 0 && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {items.filter(item => item.latest_analysis?.score).slice(0, 6).map((item) => (
            <ScoreCard
              key={item.stock_code}
              score={item.latest_analysis?.score}
              title={`${item.stock_code} 评分`}
            />
          ))}
        </div>
      )}
    </div>
  );
}