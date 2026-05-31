import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { searchStocks, analyzeStocks } from '@/lib/api';
import type { StockProfile, Market } from '@/types';
import { cn, detectMarket, getMarketLabel } from '@/lib/utils';
import {
  Search,
  Zap,
  Building2,
  Globe,
  ArrowRight,
  Loader2,
  X,
  CheckCircle2,
  AlertCircle,
  ListFilter,
  TrendingUp,
} from 'lucide-react';

// Market selector
const MARKET_OPTIONS: { value: 'auto' | Market; label: string; icon: React.ReactNode }[] = [
  { value: 'auto', label: '自动', icon: <Zap className="h-3.5 w-3.5" /> },
  { value: 'CN', label: 'A股', icon: <Building2 className="h-3.5 w-3.5" /> },
  { value: 'HK', label: '港股', icon: <Globe className="h-3.5 w-3.5" /> },
  { value: 'US', label: '美股', icon: <Globe className="h-3.5 w-3.5" /> },
];

// Stock search result item
function StockSearchItem({
  stock,
  onSelect,
  onAnalyze,
}: {
  stock: StockProfile;
  onSelect: (code: string) => void;
  onAnalyze: (code: string) => void;
}) {
  return (
    <div className="flex items-center justify-between p-3 rounded-lg hover:bg-accent/60 transition-colors group">
      <button
        className="flex-1 text-left flex items-center gap-3"
        onClick={() => onSelect(stock.stock_code)}
      >
        <div className="flex flex-col">
          <span className="font-mono font-semibold text-sm">{stock.stock_code}</span>
          {stock.stock_name && (
            <span className="text-xs text-muted-foreground">{stock.stock_name}</span>
          )}
        </div>
        <Badge variant="outline" className="text-xs">
          {getMarketLabel(stock.market)}
        </Badge>
      </button>
      <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
        <span className="text-xs text-muted-foreground">{stock.analysis_count}次分析</span>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 px-2 text-xs"
          onClick={(e) => {
            e.stopPropagation();
            onAnalyze(stock.stock_code);
          }}
        >
          <Zap className="h-3 w-3 mr-1" />
          分析
        </Button>
      </div>
    </div>
  );
}

export function Analyze() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<'single' | 'batch'>('single');

  // Single mode
  const [singleCode, setSingleCode] = useState('');
  const [singleMarket, setSingleMarket] = useState<'auto' | Market>('auto');
  const [searchResults, setSearchResults] = useState<StockProfile[]>([]);
  const [, setSearching] = useState(false);
  const [selectedStock, setSelectedStock] = useState<StockProfile | null>(null);
  const [analyzing, setAnalyzing] = useState(false);

  // Batch mode
  const [batchText, setBatchText] = useState('');
  const [batchMarket, setBatchMarket] = useState<'auto' | Market>('auto');
  const [analyzingBatch, setAnalyzingBatch] = useState(false);

  // Parse and deduplicate batch codes
  const batchCodes = batchText
    .split(/[\n,]+/)
    .map(c => c.trim().toUpperCase())
    .filter(c => c.length > 0);
  const uniqueBatchCodes = [...new Set(batchCodes)];

  // Search handler with debounce
  useEffect(() => {
    if (singleCode.trim().length < 1) {
      setSearchResults([]);
      return;
    }
    const timer = setTimeout(async () => {
      setSearching(true);
      try {
        const results = await searchStocks(singleCode);
        setSearchResults(results.slice(0, 8));
      } catch {
        setSearchResults([]);
      } finally {
        setSearching(false);
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [singleCode]);

  // Single stock submit
  const handleSingleAnalyze = useCallback(async () => {
    const code = singleCode.trim().toUpperCase();
    if (!code) return;
    setAnalyzing(true);
    try {
      const result = await analyzeStocks([code]);
      navigate(`/batch?task_id=${result.batch_id}`);
    } catch {
      setAnalyzing(false);
    }
  }, [singleCode, navigate]);

  // Batch submit
  const handleBatchAnalyze = useCallback(async () => {
    if (uniqueBatchCodes.length === 0) return;
    setAnalyzingBatch(true);
    try {
      const result = await analyzeStocks(uniqueBatchCodes);
      navigate(`/batch?task_id=${result.batch_id}`);
    } catch {
      setAnalyzingBatch(false);
    }
  }, [uniqueBatchCodes, navigate]);

  // Select from search results
  const handleSelectStock = (code: string) => {
    const stock = searchResults.find(s => s.stock_code === code);
    if (stock) {
      setSelectedStock(stock);
      setSingleCode(code);
    }
    setSearchResults([]);
  };

  // Handle Enter key
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && mode === 'single' && singleCode.trim()) {
      handleSingleAnalyze();
    }
  };

  const detectedMarket = singleCode.trim() ? detectMarket(singleCode) : null;

  return (
    <div className="max-w-3xl mx-auto space-y-8 animate-fade-slide">
      {/* Page header */}
      <div className="space-y-1">
        <h1 className="text-3xl font-bold tracking-tight">
          <span className="gradient-text">发起分析</span>
        </h1>
        <p className="text-muted-foreground text-sm">
          输入股票代码，AI 将进行 L1→L2→L3→L4 全链路量化分析
        </p>
      </div>

      {/* Mode Tabs */}
      <Tabs value={mode} onValueChange={(v) => setMode(v as 'single' | 'batch')} className="w-full">
        <TabsList className="grid w-full grid-cols-2 h-11 bg-secondary/50">
          <TabsTrigger
            value="single"
            className={cn(
              "text-sm font-medium transition-all",
              mode === 'single' && "tab-indicator bg-primary/10 text-primary"
            )}
          >
            <Zap className="h-4 w-4 mr-2" />
            单只分析
          </TabsTrigger>
          <TabsTrigger
            value="batch"
            className={cn(
              "text-sm font-medium transition-all",
              mode === 'batch' && "tab-indicator bg-primary/10 text-primary"
            )}
          >
            <ListFilter className="h-4 w-4 mr-2" />
            批量分析
          </TabsTrigger>
        </TabsList>

        {/* Single Analysis Tab */}
        <TabsContent value="single" className="mt-6 space-y-4">
          <Card className="border-border/60">
            <CardContent className="p-6 space-y-5">
              {/* Stock code input */}
              <div className="space-y-2">
                <label className="text-sm font-medium">股票代码</label>
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    value={singleCode}
                    onChange={(e) => {
                      setSingleCode(e.target.value.toUpperCase());
                      setSelectedStock(null);
                    }}
                    onKeyDown={handleKeyDown}
                    placeholder="输入代码或名称搜索，如 00700、腾讯、NVDA"
                    className="pl-10 h-12 bg-secondary/50 border-border/80 font-mono text-base placeholder:text-muted-foreground/50 focus:border-primary/50 focus:ring-primary/20"
                  />
                  {singleCode && (
                    <button
                      onClick={() => { setSingleCode(''); setSelectedStock(null); setSearchResults([]); }}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  )}
                </div>

                {/* Auto-detected market badge */}
                {detectedMarket && singleCode.trim() && (
                  <div className="flex items-center gap-1.5">
                    <Badge variant="outline" className="text-xs bg-secondary/50">
                      检测到: {getMarketLabel(detectedMarket)}
                    </Badge>
                  </div>
                )}
              </div>

              {/* Search results dropdown */}
              {searchResults.length > 0 && (
                <Card className="absolute z-50 w-full max-w-xl border-border/80 shadow-xl">
                  <CardContent className="p-2">
                    {searchResults.map(stock => (
                      <StockSearchItem
                        key={stock.stock_code}
                        stock={stock}
                        onSelect={handleSelectStock}
                        onAnalyze={(code) => {
                          setSingleCode(code);
                          setSearchResults([]);
                          setTimeout(() => handleSingleAnalyze(), 100);
                        }}
                      />
                    ))}
                  </CardContent>
                </Card>
              )}

              {/* Selected stock preview */}
              {selectedStock && (
                <div className="flex items-center gap-3 p-3 rounded-lg bg-primary/5 border border-primary/20">
                  <CheckCircle2 className="h-4 w-4 text-primary" />
                  <div className="flex-1">
                    <span className="font-mono font-semibold">{selectedStock.stock_code}</span>
                    {selectedStock.stock_name && (
                      <span className="text-muted-foreground ml-2">{selectedStock.stock_name}</span>
                    )}
                  </div>
                  <Badge variant="outline">{getMarketLabel(selectedStock.market)}</Badge>
                </div>
              )}

              {/* Market selector */}
              <div className="space-y-2">
                <label className="text-sm font-medium">市场偏好</label>
                <div className="flex gap-2">
                  {MARKET_OPTIONS.map(opt => (
                    <button
                      key={opt.value}
                      onClick={() => setSingleMarket(opt.value)}
                      className={cn(
                        "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-all border",
                        singleMarket === opt.value
                          ? "bg-primary/10 border-primary/40 text-primary"
                          : "bg-secondary/50 border-border/60 text-muted-foreground hover:text-foreground hover:bg-secondary"
                      )}
                    >
                      {opt.icon}
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Submit */}
              <Button
                onClick={handleSingleAnalyze}
                disabled={!singleCode.trim() || analyzing}
                size="lg"
                className="w-full h-12 gradient-btn text-white font-semibold disabled:opacity-50"
              >
                {analyzing ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    分析中...
                  </>
                ) : (
                  <>
                    <Zap className="mr-2 h-4 w-4" />
                    开始分析
                    {singleCode.trim() && <span className="ml-2 opacity-75">· {singleCode.trim().toUpperCase()}</span>}
                  </>
                )}
              </Button>
            </CardContent>
          </Card>

          {/* Market guide */}
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: 'A股', color: 'text-red-400', examples: '600519、000858', icon: Building2 },
              { label: '港股', color: 'text-blue-400', examples: '00700、09988', icon: Globe },
              { label: '美股', color: 'text-purple-400', examples: 'NVDA、AAPL', icon: Globe },
            ].map(({ label, color, examples, icon: Icon }) => (
              <div key={label} className="p-3 rounded-lg bg-secondary/40 border border-border/40 hover-glow transition-all cursor-default">
                <div className="flex items-center gap-1.5 mb-1">
                  <Icon className={cn("h-3.5 w-3.5", color)} />
                  <span className={cn("text-sm font-semibold", color)}>{label}</span>
                </div>
                <div className="text-xs text-muted-foreground font-mono">{examples}</div>
              </div>
            ))}
          </div>
        </TabsContent>

        {/* Batch Analysis Tab */}
        <TabsContent value="batch" className="mt-6 space-y-4">
          <Card className="border-border/60">
            <CardContent className="p-6 space-y-5">
              {/* Batch textarea */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-sm font-medium">股票代码列表</label>
                  {uniqueBatchCodes.length > 0 && (
                    <Badge variant="outline" className="text-xs bg-primary/10 text-primary border-primary/30">
                      {uniqueBatchCodes.length} 只
                    </Badge>
                  )}
                </div>
                <textarea
                  value={batchText}
                  onChange={(e) => setBatchText(e.target.value.toUpperCase())}
                  placeholder={"输入股票代码，每行一个或逗号分隔\n\n示例:\n600519\n000858\nHK00700\nUSNVDA"}
                  className="flex min-h-[180px] w-full rounded-md border border-border/80 bg-secondary/50 px-3 py-2 text-sm font-mono placeholder:text-muted-foreground/50 focus-visible:outline-none focus-visible:border-primary/50 focus-visible:ring-primary/20 resize-none"
                />
              </div>

              {/* Detected codes preview */}
              {uniqueBatchCodes.length > 0 && (
                <div className="space-y-2">
                  <label className="text-sm font-medium text-muted-foreground">已识别的股票</label>
                  <div className="flex flex-wrap gap-2">
                    {uniqueBatchCodes.map(code => {
                      const market = detectMarket(code);
                      return (
                        <div
                          key={code}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-secondary border border-border/60 text-sm font-mono group"
                        >
                          <span>{code}</span>
                          <span className="text-xs text-muted-foreground">{getMarketLabel(market)}</span>
                          <button
                            onClick={() => setBatchText(prev =>
                              prev.split(/[\n,]+/).filter(c => c.trim().toUpperCase() !== code).join('\n')
                            )}
                            className="ml-1 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-foreground transition-opacity"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Market selector */}
              <div className="space-y-2">
                <label className="text-sm font-medium">市场偏好</label>
                <div className="flex gap-2">
                  {MARKET_OPTIONS.map(opt => (
                    <button
                      key={opt.value}
                      onClick={() => setBatchMarket(opt.value)}
                      className={cn(
                        "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-all border",
                        batchMarket === opt.value
                          ? "bg-primary/10 border-primary/40 text-primary"
                          : "bg-secondary/50 border-border/60 text-muted-foreground hover:text-foreground hover:bg-secondary"
                      )}
                    >
                      {opt.icon}
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Submit */}
              <Button
                onClick={handleBatchAnalyze}
                disabled={uniqueBatchCodes.length === 0 || analyzingBatch}
                size="lg"
                className="w-full h-12 gradient-btn text-white font-semibold disabled:opacity-50"
              >
                {analyzingBatch ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    提交 {uniqueBatchCodes.length} 个任务...
                  </>
                ) : (
                  <>
                    <ListFilter className="mr-2 h-4 w-4" />
                    批量分析
                    {uniqueBatchCodes.length > 0 && (
                      <span className="ml-2 opacity-75">· {uniqueBatchCodes.length} 只股票</span>
                    )}
                  </>
                )}
              </Button>
            </CardContent>
          </Card>

          {/* Batch info card */}
          <Card className="border-border/40 bg-secondary/30">
            <CardContent className="p-4">
              <div className="flex items-start gap-3">
                <AlertCircle className="h-4 w-4 text-muted-foreground mt-0.5 shrink-0" />
                <div className="text-xs text-muted-foreground space-y-1">
                  <p>批量分析支持最多 50 只股票同时提交，系统将自动排队处理。</p>
                  <p>分析完成后可在批量监控页面查看进度和结果。</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Analysis pipeline preview */}
      <Card className="border-border/40 bg-gradient-to-r from-card to-card/50">
        <CardContent className="p-5">
          <div className="text-sm font-medium mb-4 text-muted-foreground">四层量化分析流水线</div>
          <div className="flex items-center gap-2 overflow-x-auto pb-1">
            {[
              { level: 'L1', name: '粗筛', desc: '基本面过滤', color: 'from-blue-500/20 to-blue-500/5', border: 'border-blue-500/20', text: 'text-blue-400', icon: TrendingUp },
              { level: 'L2', name: '技术', desc: '技术面量化', color: 'from-amber-500/20 to-amber-500/5', border: 'border-amber-500/20', text: 'text-amber-400', icon: TrendingUp },
              { level: 'L3', name: '量化', desc: '多因子评分', color: 'from-purple-500/20 to-purple-500/5', border: 'border-purple-500/20', text: 'text-purple-400', icon: TrendingUp },
              { level: 'L4', name: '决策', desc: '综合裁判', color: 'from-primary/20 to-primary/5', border: 'border-primary/20', text: 'text-primary', icon: Zap },
            ].map((step, i) => (
              <div key={step.level} className="flex items-center">
                <div className={cn(
                  "flex flex-col items-center p-3 rounded-lg border bg-gradient-to-b",
                  step.color, step.border
                )}>
                  <div className="flex items-center gap-1.5 mb-1">
                    <step.icon className={cn("h-3.5 w-3.5", step.text)} />
                    <span className={cn("text-sm font-bold", step.text)}>{step.level}</span>
                  </div>
                  <div className="text-xs font-medium">{step.name}</div>
                  <div className="text-xs text-muted-foreground">{step.desc}</div>
                </div>
                {i < 3 && <ArrowRight className="h-4 w-4 text-muted-foreground mx-1 shrink-0" />}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
