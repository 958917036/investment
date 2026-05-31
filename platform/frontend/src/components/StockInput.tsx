import { useState } from 'react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { detectMarket, getMarketColor, getMarketLabel } from '@/lib/utils';

interface StockInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  label?: string;
}

export function StockInput({ value, onChange, placeholder = '600519', label }: StockInputProps) {
  const market = value ? detectMarket(value) : null;

  return (
    <div className="space-y-2">
      {label && <Label>{label}</Label>}
      <div className="relative">
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          placeholder={placeholder}
          className="pr-16"
        />
        {market && (
          <span className={`absolute right-3 top-1/2 -translate-y-1/2 text-xs ${getMarketColor(market)}`}>
            {getMarketLabel(market)}
          </span>
        )}
      </div>
      {value && market && (
        <p className="text-xs text-muted-foreground">
          检测到: {getMarketLabel(market)}股票
          {market === 'CN' && ' (A股)'}
          {market === 'HK' && ' (港股)'}
          {market === 'US' && ' (美股)'}
        </p>
      )}
    </div>
  );
}

interface StockCodeInputProps {
  }

export function StockCodeInput({  }: StockCodeInputProps) {
  const [input, setInput] = useState('');

  const codes = input.split(/[\n,]+/).map(c => c.trim().toUpperCase()).filter(c => c.length > 0);
  const uniqueCodes = [...new Set(codes)];

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label>输入股票代码</Label>
        <TextareaExample value={input} onChange={setInput} />
        <p className="text-xs text-muted-foreground">
          支持多种格式: 600519, HK00700, USNVDA, 或每行一个
        </p>
      </div>

      {uniqueCodes.length > 0 && (
        <div className="space-y-2">
          <Label>已识别的股票 ({uniqueCodes.length})</Label>
          <div className="flex flex-wrap gap-2">
            {uniqueCodes.map((code) => {
              const market = detectMarket(code);
              return (
                <span
                  key={code}
                  className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs ${getMarketColor(market)} bg-muted`}
                >
                  {code}
                  <span className="opacity-60">{getMarketLabel(market)}</span>
                </span>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function TextareaExample({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder="600519&#10;HK00700&#10;USNVDA&#10;或: 600519, 000858, HK00700"
      className="flex min-h-[120px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    />
  );
}
