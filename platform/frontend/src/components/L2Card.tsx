import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { AnalysisRecord } from '@/types';

type L2CardData = AnalysisRecord | Record<string, unknown>;

interface L2CardProps {
  data: L2CardData;
}

export function L2Card({ data }: L2CardProps) {
  // Try to extract technical_data from l2_data.stocks[0]
  const l2Data = (data as AnalysisRecord)?.l2_data as Record<string, unknown> | undefined;
  const stocks = l2Data?.stocks as Array<{ _data?: { technical_data?: Record<string, unknown> } }> | undefined;
  const techData = stocks?.[0]?._data?.technical_data as Record<string, unknown> | undefined;

  if (!techData) {
    return (
      <Card className="card-hover-depth">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">L2 技术指标</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-muted-foreground text-sm">暂无技术指标数据</div>
        </CardContent>
      </Card>
    );
  }

  // Extract values with safe defaults
  const currentPrice = techData.price as number | undefined;
  const changePercent = techData.change_pct as number | undefined;
  const rsi = techData.rsi as number | undefined;
  const macdStatus = techData.macd_status as string | undefined;
  const ma5 = techData.ma5 as number | undefined;
  const ma10 = techData.ma10 as number | undefined;
  const ma20 = techData.ma20 as number | undefined;
  const ma60 = techData.ma60 as number | undefined;
  const bollingerUpper = techData.bb_upper as number | undefined;
  const bollingerLower = techData.bb_lower as number | undefined;
  const week52High = techData.year_high as number | undefined;
  const week52Low = techData.year_low as number | undefined;
  const return1m = techData.return_m1 as number | undefined;
  const return3m = techData.return_m3 as number | undefined;
  const returnAnnualized = techData.return_annualized as number | undefined;

  // Determine trend based on MA arrangement
  const getMATrend = () => {
    if (ma5 && ma10 && ma20 && ma60) {
      if (ma5 > ma10 && ma10 > ma20 && ma20 > ma60) return '多头排列';
      if (ma5 < ma10 && ma10 < ma20 && ma20 < ma60) return '空头排列';
      return '纠缠';
    }
    return 'N/A';
  };

  // Determine RSI zone
  const getRSIZone = () => {
    if (rsi === undefined) return 'N/A';
    if (rsi > 70) return '超买';
    if (rsi < 30) return '超卖';
    return '正常';
  };

  // Calculate position in Bollinger Band
  const getBollingerPosition = () => {
    if (!currentPrice || !bollingerUpper || !bollingerLower) return 'N/A';
    const position = ((currentPrice - bollingerLower) / (bollingerUpper - bollingerLower)) * 100;
    return `${position.toFixed(1)}%`;
  };

  // Calculate position in 52-week range
  const getWeek52Position = () => {
    if (!currentPrice || !week52High || !week52Low) return 'N/A';
    const position = ((currentPrice - week52Low) / (week52High - week52Low)) * 100;
    return `${position.toFixed(1)}%`;
  };

  const formatPercent = (v: number | undefined) => v !== undefined ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}%` : 'N/A';
  const formatPrice = (v: number | undefined) => v !== undefined ? `$${v.toFixed(2)}` : 'N/A';

  return (
    <Card className="card-hover-depth">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">L2 技术指标</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          {/* Price and Change */}
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">当前价</div>
            <div className="text-lg font-semibold">{formatPrice(currentPrice)}</div>
            <div className={`text-sm ${(changePercent || 0) >= 0 ? 'text-buy' : 'text-sell'}`}>
              {formatPercent(changePercent)}
            </div>
          </div>

          {/* RSI */}
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">RSI(14)</div>
            <div className="text-lg font-semibold">{rsi?.toFixed(1) || 'N/A'}</div>
            <div className={`text-sm ${
              rsi !== undefined
                ? rsi > 70 ? 'text-sell' : rsi < 30 ? 'text-buy' : 'text-muted-foreground'
                : 'text-muted-foreground'
            }`}>
              {getRSIZone()}
            </div>
          </div>

          {/* MACD */}
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">MACD状态</div>
            <div className="text-lg font-semibold">{macdStatus || 'N/A'}</div>
            <div className="text-sm text-muted-foreground">动量指标</div>
          </div>

          {/* MA Trend */}
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">均线多空</div>
            <div className="text-lg font-semibold">{getMATrend()}</div>
            <div className="text-xs text-muted-foreground">MA5/10/20/60</div>
          </div>

          {/* MA Values */}
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">均线价格</div>
            <div className="text-xs">
              <span className="text-muted-foreground">5:</span> {formatPrice(ma5)} |{' '}
              <span className="text-muted-foreground">10:</span> {formatPrice(ma10)}
            </div>
            <div className="text-xs">
              <span className="text-muted-foreground">20:</span> {formatPrice(ma20)} |{' '}
              <span className="text-muted-foreground">60:</span> {formatPrice(ma60)}
            </div>
          </div>

          {/* Bollinger Band */}
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">布林带位置</div>
            <div className="text-lg font-semibold">{getBollingerPosition()}</div>
            <div className="text-xs text-muted-foreground">
              上:{formatPrice(bollingerUpper)} 下:{formatPrice(bollingerLower)}
            </div>
          </div>

          {/* 52 Week Range */}
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">52周高低</div>
            <div className="text-lg font-semibold">{getWeek52Position()}</div>
            <div className="text-xs text-muted-foreground">
              高:{formatPrice(week52High)} 低:{formatPrice(week52Low)}
            </div>
          </div>

          {/* Returns */}
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">收益率</div>
            <div className="text-xs">
              <span className="text-muted-foreground">1月:</span>{' '}
              <span className={(return1m || 0) >= 0 ? 'text-buy' : 'text-sell'}>
                {formatPercent(return1m)}
              </span>
            </div>
            <div className="text-xs">
              <span className="text-muted-foreground">3月:</span>{' '}
              <span className={(return3m || 0) >= 0 ? 'text-buy' : 'text-sell'}>
                {formatPercent(return3m)}
              </span>
            </div>
            <div className="text-xs">
              <span className="text-muted-foreground">年化:</span>{' '}
              <span className={(returnAnnualized || 0) >= 0 ? 'text-buy' : 'text-sell'}>
                {formatPercent(returnAnnualized)}
              </span>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
