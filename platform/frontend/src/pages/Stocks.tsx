import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { DecisionBadge } from '@/components/DecisionBadge';
import { listStocks, searchStocks } from '@/lib/api';
import { formatRelativeTime, getMarketLabel, getMarketColor } from '@/lib/utils';
import type { StockProfile } from '@/types';
import { Search, BarChart3, Clock } from 'lucide-react';

export function Stocks() {
  const navigate = useNavigate();
  const [stocks, setStocks] = useState<StockProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  
  useEffect(() => {
    loadStocks();
  }, []);

  useEffect(() => {
    if (searchQuery.trim()) {
      performSearch();
    } else {
      loadStocks();
    }
  }, [searchQuery]);

  const loadStocks = async () => {
    try {
      const data = await listStocks();
      setStocks(data);
    } catch (error) {
      console.error('Failed to load stocks:', error);
    } finally {
      setLoading(false);
    }
  };

  const performSearch = async () => {
    if (!searchQuery.trim()) {
      loadStocks();
      return;
    }

    try {
      const data = await searchStocks(searchQuery);
      setStocks(data);
    } catch (error) {
      console.error('Failed to search stocks:', error);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6 animate-slide-up">
        <Skeleton className="h-10 w-full max-w-md" />
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-slide-up">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">股票库</h1>
        <p className="text-muted-foreground">所有已分析的股票</p>
      </div>

      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="搜索股票代码或名称..."
          className="pl-10"
        />
      </div>

      {stocks.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            {searchQuery
              ? '未找到匹配的股票'
              : '暂无股票数据，请先进行分析'}
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="text-sm text-muted-foreground">
            共 {stocks.length} 只股票
          </div>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {stocks.map((stock) => (
              <Card
                key={stock.stock_code}
                className="hover:bg-muted/50 transition-colors cursor-pointer"
                onClick={() => navigate(`/history/${stock.stock_code}`)}
              >
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-medium">
                        {stock.stock_code}
                      </span>
                      <span className={`text-xs ${getMarketColor(stock.market || 'CN')}`}>
                        {getMarketLabel(stock.market || 'CN')}
                      </span>
                    </div>
                    <DecisionBadge decision={stock.latest_decision} size="sm" />
                  </div>
                  {stock.stock_name && (
                    <div className="text-sm text-muted-foreground">
                      {stock.stock_name}
                    </div>
                  )}
                </CardHeader>
                <CardContent className="pt-2">
                  <div className="flex items-center justify-between text-sm">
                    <div className="flex items-center gap-1 text-muted-foreground">
                      <BarChart3 className="h-3 w-3" />
                      <span>{stock.analysis_count} 次分析</span>
                    </div>
                    {stock.last_analysis_date && (
                      <div className="flex items-center gap-1 text-muted-foreground">
                        <Clock className="h-3 w-3" />
                        <span>{formatRelativeTime(stock.last_analysis_date)}</span>
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
