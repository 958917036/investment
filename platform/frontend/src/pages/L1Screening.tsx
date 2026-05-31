import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { StockInput } from '@/components/StockInput';
import { runL1Analyze } from '@/lib/api';
import { detectMarket, getMarketLabel } from '@/lib/utils';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Loader2, Zap, ArrowRight } from 'lucide-react';

interface L1Result {
  stock_code: string;
  candidates: Array<{
    code: string;
    name: string;
    price?: number;
    change_pct?: number;
  }>;
  screening_date: string;
}

export function L1Screening() {
  const navigate = useNavigate();
  const [singleCode, setSingleCode] = useState('');
  const [batchCodes, setBatchCodes] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, _setResults] = useState<L1Result[]>([]);
  

  const handleSingleAnalyze = async () => {
    if (!singleCode.trim()) return;
    await analyzeMultiple([singleCode]);
  };

  const handleBatchAnalyze = async () => {
    const codes = batchCodes
      .split(/[\n,]+/)
      .map(c => c.trim().toUpperCase())
      .filter(c => c.length > 0);
    if (codes.length === 0) return;
    await analyzeMultiple(codes);
  };

  const analyzeMultiple = async (codes: string[]) => {
    setLoading(true);
    setError(null);
    try {
      await runL1Analyze(codes);
      // Navigate to batch page for monitoring
      navigate('/batch');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'L1分析启动失败');
      setLoading(false);
    }
  };

  const batchCodeList = batchCodes
    .split(/[\n,]+/)
    .map(c => c.trim().toUpperCase())
    .filter(c => c.length > 0);
  const uniqueBatchCodes = [...new Set(batchCodeList)];

  return (
    <div className="space-y-6 animate-slide-up max-w-4xl">
      <div>
        <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
          <Zap className="h-8 w-8 text-yellow-400" />
          L1 快线筛选
        </h1>
        <p className="text-muted-foreground">快速筛选候选股票，仅运行L1初筛流程</p>
      </div>

      {error && (
        <Card className="border-destructive/50 bg-destructive/10">
          <CardContent className="py-3 text-destructive">{error}</CardContent>
        </Card>
      )}

      <Tabs defaultValue="single" className="w-full">
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="single">单只股票</TabsTrigger>
          <TabsTrigger value="batch">批量筛选</TabsTrigger>
        </TabsList>

        <TabsContent value="single" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>L1 单股筛选</CardTitle>
              <CardDescription>快速检测股票是否通过L1初筛</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <StockInput
                value={singleCode}
                onChange={setSingleCode}
                placeholder="600519 (A股) / HK00700 (港股) / USNVDA (美股)"
                label="股票代码"
              />
              <div className="flex gap-3">
                <Button
                  onClick={handleSingleAnalyze}
                  disabled={!singleCode.trim() || loading}
                  size="lg"
                >
                  {loading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      启动L1筛选...
                    </>
                  ) : (
                    <>
                      <Zap className="mr-2 h-4 w-4" />
                      开始L1筛选
                    </>
                  )}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => setSingleCode('')}
                  disabled={loading}
                >
                  清空
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="batch" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>批量L1筛选</CardTitle>
              <CardDescription>输入多个股票代码，每行一个或逗号分隔</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">股票代码列表</label>
                <textarea
                  value={batchCodes}
                  onChange={(e) => setBatchCodes(e.target.value.toUpperCase())}
                  placeholder={`600519\n000858\nHK00700\nUSNVDA`}
                  className="flex min-h-[200px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                />
              </div>

              {uniqueBatchCodes.length > 0 && (
                <div className="space-y-2">
                  <div className="text-sm font-medium">
                    已识别的股票 ({uniqueBatchCodes.length} 只)
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {uniqueBatchCodes.map((code) => {
                      const market = detectMarket(code);
                      return (
                        <span
                          key={code}
                          className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs bg-muted"
                        >
                          {code}
                          <span className="text-muted-foreground">
                            {getMarketLabel(market)}
                          </span>
                        </span>
                      );
                    })}
                  </div>
                </div>
              )}

              <div className="flex gap-3">
                <Button
                  onClick={handleBatchAnalyze}
                  disabled={uniqueBatchCodes.length === 0 || loading}
                  size="lg"
                  variant="default"
                >
                  {loading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      启动 {uniqueBatchCodes.length} 个L1筛选任务...
                    </>
                  ) : (
                    <>
                      <Zap className="mr-2 h-4 w-4" />
                      开始批量L1筛选 ({uniqueBatchCodes.length})
                    </>
                  )}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => setBatchCodes('')}
                  disabled={loading}
                >
                  清空
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Info Card */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">L1 快线说明</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="p-4 rounded-lg bg-muted/50">
              <div className="flex items-center gap-2 font-medium text-yellow-400 mb-2">
                <Zap className="h-4 w-4" />
                快速筛选
              </div>
              <div className="text-sm text-muted-foreground">
                仅运行L1层筛选，速度快，适合初筛大量候选股票
              </div>
            </div>
            <div className="p-4 rounded-lg bg-muted/50">
              <div className="flex items-center gap-2 font-medium mb-2">
                <ArrowRight className="h-4 w-4" />
                后续流程
              </div>
              <div className="text-sm text-muted-foreground">
                通过L1初筛后，可在结果页面选择进行深度L2/L3/L4分析
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Recent Results */}
      {results.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>本次筛选结果</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {results.map((result) => (
                <div
                  key={result.stock_code}
                  className="flex items-center justify-between p-3 rounded-lg bg-muted/50"
                >
                  <div className="flex items-center gap-3">
                    <span className="font-mono font-medium">{result.stock_code}</span>
                    <span className="text-sm text-muted-foreground">
                      {result.candidates.length} 个候选
                    </span>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => navigate('/batch')}
                  >
                    查看详情
                  </Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
