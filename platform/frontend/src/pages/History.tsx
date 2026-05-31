import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { DecisionBadge } from '@/components/DecisionBadge';
import { Sparkline } from '@/components/Sparkline';
import { Skeleton } from '@/components/ui/skeleton';
import { getStockRecords, searchStocks, getCachedStockPrices, analyzeStocks } from '@/lib/api';
import { formatDate, formatRelativeTime, getMarketLabel } from '@/lib/utils';
import type { AnalysisRecord, StockProfile } from '@/types';
import { ArrowLeft, GitCompare, Clock, BarChart3, Search } from 'lucide-react';

interface RecordWithSparkline extends AnalysisRecord {
  sparklineData?: Array<{ value: number }>;
}

export function History() {
  const { code } = useParams<{ code: string }>();
  const navigate = useNavigate();
  const [records, setRecords] = useState<RecordWithSparkline[]>([]);
  const [loading, setLoading] = useState(true);
  const [priceLoading, setPriceLoading] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<StockProfile[]>([]);
  const [searching, setSearching] = useState(false);
  const [currentCode, setCurrentCode] = useState<string | null>(code || null);

  // Search for stocks when query changes
  useEffect(() => {
    if (searchQuery.trim().length < 1) {
      setSearchResults([]);
      return;
    }
    const timer = setTimeout(async () => {
      setSearching(true);
      try {
        const results = await searchStocks(searchQuery);
        setSearchResults(results);
      } catch (e) {
        console.error('Search failed:', e);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Load history when code changes
  useEffect(() => {
    if (currentCode) {
      loadHistory(currentCode);
    } else {
      setRecords([]);
      setLoading(false);
    }
  }, [currentCode]);

  // Load price data separately (non-blocking, parallel)
  useEffect(() => {
    if (!records.length) return;
    const codes = [...new Set(records.map(r => r.stock_code))];
    setPriceLoading(true);
    getCachedStockPrices(codes).then(priceMap => {
      setRecords(prev => prev.map(record => {
        const priceData = priceMap.get(record.stock_code);
        const history = priceData?.price_history || [];
        const sparklineData = history.slice(-30).map(p => ({ value: p.close }));
        return { ...record, sparklineData };
      }));
      setPriceLoading(false);
    }).catch(() => setPriceLoading(false));
  }, [records.length, currentCode]);

  const loadHistory = async (stockCode: string) => {
    setLoading(true);
    setError(null);
    setSelected([]);
    try {
      const data = await getStockRecords(stockCode);
      // Map API response to expected format with proper type casting
      const withSparklines: RecordWithSparkline[] = (data.items || []).map(record => ({
        id: record.id,
        stock_code: record.stock_code,
        stock_name: record.stock_name || undefined,
        market: (record.market || 'CN') as AnalysisRecord['market'],
        timestamp: record.timestamp || new Date().toISOString(),
        status: (record.status || 'completed') as AnalysisRecord['status'],
        l1_data: record.l1_data || undefined,
        l2_data: record.l2_data || undefined,
        l3_data: record.l3_data || undefined,
        l4_data: record.l4_data || undefined,
        final_decision: (record.final_decision || 'NO') as AnalysisRecord['final_decision'],
        score: record.score || undefined,
        raw_data: record.raw_data || undefined,
        batch_id: record.batch_id || undefined,
        sparklineData: [] as Array<{ value: number }>,
      }));
      setRecords(withSparklines);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  };

  const handleSelectStock = (stockCode: string) => {
    setSearchQuery('');
    setSearchResults([]);
    setCurrentCode(stockCode);
    navigate(`/history/${stockCode}`);
  };

  const handleAnalyzeStock = async (stockCode: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setSearchQuery('');
    setSearchResults([]);
    try {
      const result = await analyzeStocks([stockCode]);
      navigate(`/batch?task_id=${result.batch_id}`);
    } catch (err) {
      console.error('Analyze failed:', err);
    }
  };

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      if (prev.includes(id)) {
        return prev.filter((x) => x !== id);
      }
      if (prev.length >= 2) {
        return [prev[1], id];
      }
      return [...prev, id];
    });
  };

  const handleCompare = () => {
    if (selected.length === 2 && currentCode) {
      navigate(`/compare/${currentCode}?ids=${selected[0]},${selected[1]}`);
    }
  };

  if (!currentCode) {
    return (
      <div className="space-y-6 animate-slide-up">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">历史分析记录</h1>
          <p className="text-muted-foreground">选择一只股票查看其历史分析记录</p>
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

        {searchQuery.trim() && (
          <Card className="absolute top-full left-0 right-0 z-50 mt-1">
            <CardContent className="p-2">
              {searching ? (
                <div className="py-4 text-center text-muted-foreground">搜索中...</div>
              ) : searchResults.length > 0 ? (
                searchResults.map((stock) => (
                  <div
                    key={stock.stock_code}
                    className="flex items-center justify-between p-3 hover:bg-muted/50 cursor-pointer rounded-md"
                    onClick={() => handleSelectStock(stock.stock_code)}
                  >
                    <div className="flex items-center gap-3">
                      <span className="font-mono font-medium">{stock.stock_code}</span>
                      {stock.stock_name && (
                        <span className="text-sm text-muted-foreground">{stock.stock_name}</span>
                      )}
                      <span className="text-xs text-muted-foreground">{getMarketLabel(stock.market)}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="text-sm text-muted-foreground">
                        {stock.analysis_count} 次分析
                      </span>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={(e) => handleAnalyzeStock(stock.stock_code, e)}
                      >
                        分析
                      </Button>
                    </div>
                  </div>
                ))
              ) : (
                <div className="py-4 text-center text-muted-foreground">未找到匹配的股票</div>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-6 animate-slide-up">
        <div className="flex items-center gap-4">
          <Skeleton className="h-10 w-10" />
          <Skeleton className="h-8 w-48" />
        </div>
        <Skeleton className="h-[400px]" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6 animate-slide-up">
        <Card>
          <CardContent className="py-8 text-center text-destructive">
            {error}
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => navigate('/stocks')}>
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <div>
            <h1 className="text-3xl font-bold tracking-tight">{currentCode}</h1>
            <p className="text-muted-foreground">
              历史分析记录 ({records.length} 次)
            </p>
          </div>
        </div>
        {selected.length === 2 && (
          <Button onClick={handleCompare}>
            <GitCompare className="mr-2 h-4 w-4" />
            对比选中项
          </Button>
        )}
      </div>

      {records.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            暂无历史记录
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {records.map((record, index) => (
            <Card
              key={record.id}
              className={`transition-colors ${
                selected.includes(record.id)
                  ? 'border-primary bg-primary/5'
                  : 'hover:bg-muted/50'
              }`}
            >
              <CardContent className="py-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-6">
                    <input
                      type="checkbox"
                      checked={selected.includes(record.id)}
                      onChange={() => toggleSelect(record.id)}
                      className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary cursor-pointer"
                    />
                    <div 
                      className="flex items-center gap-6 cursor-pointer"
                      onClick={() => navigate(`/result/${encodeURIComponent(record.id)}`)}
                    >
                      <div className="flex items-center gap-2">
                        <Clock className="h-4 w-4 text-muted-foreground" />
                        <span className="text-sm font-medium">
                          {formatDate(record.timestamp)}
                        </span>
                      </div>
                      <div className="text-sm text-muted-foreground">
                        {formatRelativeTime(record.timestamp)}
                      </div>
                      {record.market && (
                        <div className="text-sm text-muted-foreground">
                          {getMarketLabel(record.market)}
                        </div>
                      )}
                      {record.score && Object.keys(record.score).length > 0 && (
                        <div className="flex items-center gap-1">
                          <BarChart3 className="h-4 w-4 text-muted-foreground" />
                          <span className="text-sm">
                            {(Object.values(record.score)
                              .filter((v) => typeof v === 'number')
                              .reduce((a, b) => (a as number) + (b as number), 0) / 5).toFixed(1)}
                          </span>
                        </div>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    {index === 0 && (
                      <span className="text-xs bg-primary/10 text-primary px-2 py-1 rounded">
                        最新
                      </span>
                    )}
                    {priceLoading && (!record.sparklineData || record.sparklineData.length === 0) ? (
                      <Skeleton className="h-8 w-16" />
                    ) : record.sparklineData && record.sparklineData.length > 0 ? (
                      <Sparkline data={record.sparklineData} height={32} />
                    ) : null}
                    <DecisionBadge decision={record.final_decision} />
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {records.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">选择说明</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            点击任意记录可将其选中用于对比分析。选中两条记录后，点击"对比选中项"按钮进行对比分析。
          </CardContent>
        </Card>
      )}
    </div>
  );
}
