import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { DecisionBadge } from '@/components/DecisionBadge';
import { Sparkline } from '@/components/Sparkline';
import { Skeleton } from '@/components/ui/skeleton';
import { getDashboardStats, getCachedStockPrices, getCachedStockPrice } from '@/lib/api';
import { formatRelativeTime, getMarketLabel } from '@/lib/utils';
import type { DashboardStats, Decision } from '@/types';
import { BarChart3, TrendingUp, Clock, Activity, Plus, List } from 'lucide-react';

interface RecentAnalysisItem {
  id: string;
  stock_code: string;
  stock_name?: string;
  market?: string;
  timestamp: string;
  status: string;
  final_decision?: Decision;
  sparklineData?: Array<{ value: number }>;
}

export function Dashboard() {
  const navigate = useNavigate();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [recentWithSparklines, setRecentWithSparklines] = useState<RecentAnalysisItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [priceLoading, setPriceLoading] = useState(false);

  // Load main stats data (fast, no price data)
  useEffect(() => {
    loadStats();
    const interval = setInterval(loadStats, 30000);
    return () => clearInterval(interval);
  }, []);

  // Load price data separately (non-blocking, parallel)
  useEffect(() => {
    if (!stats?.recent_analyses?.length) return;
    const codes = [...new Set(stats.recent_analyses.map(a => a.stock_code))];
    setPriceLoading(true);
    getCachedStockPrices(codes).then(priceMap => {
      setRecentWithSparklines(prev => {
        // Only update if the list hasn't changed
        if (prev.length !== stats.recent_analyses.length) return prev;
        return stats.recent_analyses.map(item => {
          const priceData = priceMap.get(item.stock_code);
          const history = priceData?.price_history || [];
          const sparklineData = history.slice(-30).map(p => ({ value: p.close }));
          return { ...item, sparklineData };
        });
      });
      setPriceLoading(false);
    }).catch(() => {
      setPriceLoading(false);
    });
  }, [stats?.recent_analyses?.length]);

  const loadStats = async () => {
    try {
      const data = await getDashboardStats();
      setStats(data);
      // Initialize with empty sparklines (price data loads separately)
      setRecentWithSparklines(data.recent_analyses.map(item => ({ ...item, sparklineData: [] as Array<{ value: number }> })));
    } catch (error) {
      console.error('Failed to load stats:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">神农分析平台</h1>
          <p className="text-muted-foreground">AI驱动的多市场股票筛选与量化分析系统</p>
        </div>
        <div className="flex gap-3">
          <Button onClick={() => navigate('/analyze')} size="lg">
            <Plus className="mr-2 h-4 w-4" />
            新建分析
          </Button>
          <Button onClick={() => navigate('/batch')} variant="outline" size="lg">
            <List className="mr-2 h-4 w-4" />
            批次任务
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="grid gap-4 md:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <Card key={i}>
              <CardHeader className="pb-2">
                <Skeleton className="h-4 w-24" />
              </CardHeader>
              <CardContent>
                <Skeleton className="h-8 w-16" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : stats ? (
        <>
          <div className="grid gap-4 md:grid-cols-4">
            <StatCard
              title="总分析次数"
              value={stats.total_analyses}
              icon={<BarChart3 className="h-4 w-4" />}
              description="历史累计"
            />
            <StatCard
              title="买入信号"
              value={stats.buy_count}
              icon={<TrendingUp className="h-4 w-4 text-buy" />}
              description="当前BUY信号"
              valueClassName="text-buy"
            />
            <StatCard
              title="本周新增"
              value={stats.window_analyses}
              icon={<Activity className="h-4 w-4 text-blue-400" />}
              description="最近7天"
            />
            <StatCard
              title="进行中"
              value={stats.active_tasks}
              icon={<Clock className="h-4 w-4 text-yellow-400" />}
              description="活跃任务"
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-lg">最近分析任务</CardTitle>
            </CardHeader>
            <CardContent>
              {stats.recent_analyses.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  暂无分析记录，<Link to="/analyze" className="text-primary hover:underline">开始分析</Link>
                </div>
              ) : (
                <div className="space-y-3">
                  {recentWithSparklines.map((item) => (
                    <Link
                      key={item.id}
                      to={`/result/${encodeURIComponent(item.id)}`}
                      className="flex items-center justify-between p-3 rounded-lg bg-muted/50 hover:bg-muted transition-colors"
                      onMouseEnter={() => {
                        // Prefetch price on hover for instant chart rendering
                        getCachedStockPrice(item.stock_code).catch(() => {});
                      }}
                    >
                      <div className="flex items-center gap-3">
                        <div className="font-mono font-medium">
                          {item.stock_code}
                          {item.stock_name && (
                            <span className="ml-2 text-sm text-muted-foreground">
                              {item.stock_name}
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {item.market && getMarketLabel(item.market)}
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        {priceLoading && (!item.sparklineData || item.sparklineData.length === 0) ? (
                          <Skeleton className="h-8 w-16" />
                        ) : item.sparklineData && item.sparklineData.length > 0 ? (
                          <Sparkline data={item.sparklineData} height={32} />
                        ) : null}
                        <DecisionBadge decision={item.final_decision} size="sm" />
                        <span className="text-xs text-muted-foreground">
                          {formatRelativeTime(item.timestamp)}
                        </span>
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </>
      ) : (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            加载数据失败，请检查后端服务
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function StatCard({
  title,
  value,
  icon,
  description,
  valueClassName,
}: {
  title: string;
  value: number;
  icon: React.ReactNode;
  description: string;
  valueClassName?: string;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        {icon}
      </CardHeader>
      <CardContent>
        <div className={`text-2xl font-bold ${valueClassName || ''}`}>{value}</div>
        <p className="text-xs text-muted-foreground mt-1">{description}</p>
      </CardContent>
    </Card>
  );
}
