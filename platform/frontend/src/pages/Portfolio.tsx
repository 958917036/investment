import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { DecisionBadge } from '@/components/DecisionBadge';
import { ScoreCard } from '@/components/ScoreCard';
import { Skeleton } from '@/components/ui/skeleton';
import { getPortfolio, removeFromPortfolio, getCachedStockPrice } from '@/lib/api';
import type { PortfolioItem } from '@/types';
import { Trash2, PieChart, AlertCircle } from 'lucide-react';

export function Portfolio() {
  const [items, setItems] = useState<PortfolioItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadPortfolio();
  }, []);

  // Auto-refresh current prices when portfolio loads
  useEffect(() => {
    if (items.length === 0) return;
    const codes = items.map(i => i.stock_code);
    Promise.all(codes.map(code => getCachedStockPrice(code))).then(prices => {
      setItems(prev => prev.map((item, idx) => {
        const priceData = prices[idx];
        if (priceData?.price_history?.length) {
          const latestPrice = priceData.price_history[priceData.price_history.length - 1].close;
          const currentValue = latestPrice * (item.quantity || 0);
          return { ...item, current_price: latestPrice, current_value: currentValue };
        }
        return item;
      }));
    }).catch(() => {});
  }, [items.length]);

  const loadPortfolio = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getPortfolio();
      setItems(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  };

  const handleRemove = async (stockCode: string) => {
    try {
      await removeFromPortfolio(stockCode);
      setItems(items.filter(item => item.stock_code !== stockCode));
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    }
  };

  // Calculate summary stats
  const totalValue = items.reduce((sum, item) => sum + (item.current_value || 0), 0);
  const totalCost = items.reduce((sum, item) => sum + (item.cost || 0) * (item.quantity || 0), 0);
  const totalProfit = totalValue - totalCost;
  const profitPercent = totalCost > 0 ? ((totalProfit / totalCost) * 100).toFixed(2) : '0.00';

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
            <Button variant="outline" onClick={loadPortfolio}>重试</Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <PieChart className="h-8 w-8 text-primary" />
          <h1 className="text-3xl font-bold tracking-tight">持仓管理</h1>
        </div>
        <Button variant="outline" onClick={loadPortfolio}>刷新</Button>
      </div>

      {/* Summary Cards */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">持仓市值</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">¥{totalValue.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">总成本</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">¥{totalCost.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">盈亏金额</CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${totalProfit >= 0 ? 'text-buy' : 'text-sell'}`}>
              {totalProfit >= 0 ? '+' : ''}¥{totalProfit.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">收益率</CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-2xl font-bold ${Number(profitPercent) >= 0 ? 'text-buy' : 'text-sell'}`}>
              {Number(profitPercent) >= 0 ? '+' : ''}{profitPercent}%
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Holdings List */}
      <Card>
        <CardHeader>
          <CardTitle>持仓明细 ({items.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {items.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <AlertCircle className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p>暂无持仓记录</p>
              <p className="text-sm mt-2">从分析结果中添加股票到持仓</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border">
                    <th className="text-left py-3 px-2 font-medium">股票代码</th>
                    <th className="text-left py-3 px-2 font-medium">名称</th>
                    <th className="text-right py-3 px-2 font-medium">持仓数量</th>
                    <th className="text-right py-3 px-2 font-medium">成本价</th>
                    <th className="text-right py-3 px-2 font-medium">当前价</th>
                    <th className="text-right py-3 px-2 font-medium">市值</th>
                    <th className="text-right py-3 px-2 font-medium">盈亏</th>
                    <th className="text-right py-3 px-2 font-medium">收益率</th>
                    <th className="text-center py-3 px-2 font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => {
                    const marketValue = (item.current_value || 0);
                    const costTotal = (item.cost || 0) * (item.quantity || 0);
                    const profit = marketValue - costTotal;
                    const profitRate = costTotal > 0 ? ((profit / costTotal) * 100) : 0;

                    return (
                      <tr key={item.stock_code} className="border-b border-border hover:bg-muted/50">
                        <td className="py-3 px-2">
                          <Link to={`/result/${encodeURIComponent(item.latest_analysis?.id || '')}`} className="hover:text-primary">
                            {item.stock_code}
                          </Link>
                        </td>
                        <td className="py-3 px-2">{item.stock_name || '-'}</td>
                        <td className="py-3 px-2 text-right">{item.quantity?.toLocaleString()}</td>
                        <td className="py-3 px-2 text-right">¥{(item.cost || 0).toFixed(2)}</td>
                        <td className="py-3 px-2 text-right">¥{(item.current_price || 0).toFixed(2)}</td>
                        <td className="py-3 px-2 text-right">¥{marketValue.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</td>
                        <td className={`py-3 px-2 text-right ${profit >= 0 ? 'text-buy' : 'text-sell'}`}>
                          {profit >= 0 ? '+' : ''}¥{profit.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}
                        </td>
                        <td className={`py-3 px-2 text-right ${profitRate >= 0 ? 'text-buy' : 'text-sell'}`}>
                          {profitRate >= 0 ? '+' : ''}{profitRate.toFixed(2)}%
                        </td>
                        <td className="py-3 px-2 text-center">
                          <div className="flex items-center justify-center gap-2">
                            {item.latest_analysis && (
                              <DecisionBadge decision={item.latest_analysis.final_decision} size="sm" />
                            )}
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

      {/* Score Cards Grid for Holdings */}
      {items.length > 0 && items.some(item => item.latest_analysis?.score) && (
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