import type {
  AnalysisRecord,
  BatchTask,
  DashboardStats,
  StockProfile,
  CompareData,
  Reflection,
  PortfolioItem,
  WatchlistItem,
} from '@/types';

const API_BASE = '/api';

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    headers: {
      'Content-Type': 'application/json',
    },
    ...options,
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Request failed' }));
    throw new Error(error.detail || `HTTP ${res.status}`);
  }

  return res.json();
}

// Dashboard
export async function getDashboardStats(): Promise<DashboardStats> {
  return fetchJSON<DashboardStats>('/dashboard/stats');
}

// Analyze
export async function analyzeStocks(
  stockCodes: string[]
): Promise<{ batch_id: string; tasks: Record<string, string> }> {
  return fetchJSON('/analyze', {
    method: 'POST',
    body: JSON.stringify({ stock_codes: stockCodes }),
  });
}

// Results
export async function getResult(id: string): Promise<AnalysisRecord> {
  return fetchJSON<AnalysisRecord>(`/result/${encodeURIComponent(id)}`);
}

export async function getHistory(stockCode: string): Promise<{ records: AnalysisRecord[] }> {
  return fetchJSON<{ records: AnalysisRecord[] }>(`/history/${stockCode}`);
}

export async function compareResults(
  stockCode: string,
  idA: string,
  idB: string
): Promise<CompareData> {
  return fetchJSON<CompareData>(`/compare/${stockCode}?ids=${idA},${idB}`);
}

// Batch
export async function getBatch(batchId: string): Promise<BatchTask> {
  return fetchJSON<BatchTask>(`/batch/${batchId}`);
}

export async function listBatches(): Promise<BatchTask[]> {
  return fetchJSON<BatchTask[]>('/batches');
}

export async function retryBatch(batchId: string): Promise<{ message: string; count: number }> {
  return fetchJSON(`/batch/${batchId}/retry`, { method: 'POST' });
}

export async function cancelBatch(batchId: string): Promise<{ message: string }> {
  return fetchJSON(`/batch/${batchId}`, { method: 'DELETE' });
}

// Stocks
export async function listStocks(): Promise<StockProfile[]> {
  return fetchJSON<StockProfile[]>('/stocks');
}

export async function searchStocks(q: string): Promise<StockProfile[]> {
  return fetchJSON<StockProfile[]>(`/stocks/search?q=${encodeURIComponent(q)}`);
}

export async function getStock(stockCode: string): Promise<StockProfile> {
  return fetchJSON<StockProfile>(`/stocks/${stockCode}`);
}

// Reflections
export async function submitReflection(data: {
  analysis_id: string;
  wrong_analysis: 'A' | 'B';
  reflection_text: string;
  error_tags: string[];
  correct_analysis_id?: string;
}): Promise<{ success: boolean; reflection_id: string }> {
  return fetchJSON('/reflection', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function getReflections(stockCode: string): Promise<Reflection[]> {
  return fetchJSON<Reflection[]>(`/reflections/${stockCode}`);
}

// Portfolio
export async function getPortfolio(): Promise<PortfolioItem[]> {
  return fetchJSON<PortfolioItem[]>('/portfolio');
}

export async function addToPortfolio(data: {
  stock_code: string;
  market?: string;
  quantity: number;
  avg_cost: number;
}): Promise<{ success: boolean; message: string }> {
  return fetchJSON('/portfolio', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function updatePortfolioPosition(
  stockCode: string,
  data: { quantity?: number; avg_cost?: number }
): Promise<{ success: boolean; message: string }> {
  return fetchJSON(`/portfolio/${stockCode}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function removeFromPortfolio(stockCode: string): Promise<{ success: boolean; message: string }> {
  return fetchJSON(`/portfolio/${stockCode}`, { method: 'DELETE' });
}

// Watchlist
export async function getWatchlist(): Promise<WatchlistItem[]> {
  return fetchJSON<WatchlistItem[]>('/watchlist');
}

export async function addToWatchlist(data: {
  stock_code: string;
  market?: string;
  reason?: string;
}): Promise<{ success: boolean; message: string }> {
  return fetchJSON('/watchlist', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function removeFromWatchlist(stockCode: string): Promise<{ success: boolean; message: string }> {
  return fetchJSON(`/watchlist/${stockCode}`, { method: 'DELETE' });
}

// Price history
export interface PriceHistoryItem {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export async function getStockPrice(stockCode: string): Promise<{ stock_code: string; price_history: PriceHistoryItem[] }> {
  return fetchJSON('/price/' + encodeURIComponent(stockCode));
}

// Queue
export interface QueueItem {
  id: string;
  stock_code: string;
  stock_name: string | null;
  market: string | null;
  timestamp: string | null;
  status: string | null;
  batch_id: string | null;
  final_decision: string | null;
}

export interface QueueResponse {
  total: number;
  offset: number;
  limit: number;
  items: QueueItem[];
}

export async function getQueue(params?: {
  status?: string;
  stock_code?: string;
  batch_id?: string;
  limit?: number;
  offset?: number;
}): Promise<QueueResponse> {
  const searchParams = new URLSearchParams();
  if (params?.status) searchParams.set('status', params.status);
  if (params?.stock_code) searchParams.set('stock_code', params.stock_code);
  if (params?.batch_id) searchParams.set('batch_id', params.batch_id);
  if (params?.limit) searchParams.set('limit', String(params.limit));
  if (params?.offset) searchParams.set('offset', String(params.offset));
  const qs = searchParams.toString();
  return fetchJSON<QueueResponse>(`/queue${qs ? `?${qs}` : ''}`);
}

export async function cancelFromQueue(analysisId: string): Promise<{ message: string; id: string }> {
  return fetchJSON(`/queue/${analysisId}`, { method: 'DELETE' });
}

export async function cancelBatchQueue(batchId: string): Promise<{ message: string; batch_id: string }> {
  return fetchJSON(`/queue/batch/${batchId}`, { method: 'DELETE' });
}

// L1 Analyze
export async function runL1Analyze(
  stockCodes: string[]
): Promise<{ batch_id: string; tasks: Record<string, string> }> {
  return fetchJSON('/l1/analyze', {
    method: 'POST',
    body: JSON.stringify({ stock_codes: stockCodes }),
  });
}

// Records
export interface RecordDetail {
  id: string;
  stock_code: string;
  stock_name: string | null;
  market: string | null;
  timestamp: string | null;
  status: string | null;
  task_id?: string;
  step?: string;
  l1_data: Record<string, unknown> | null;
  l2_data: Record<string, unknown> | null;
  l3_data: Record<string, unknown> | null;
  l4_data: Record<string, unknown> | null;
  final_decision: string | null;
  score: Record<string, number> | null;
  raw_data: Record<string, unknown> | null;
  batch_id: string | null;
}

export interface RecordsResponse {
  total: number;
  offset: number;
  limit: number;
  items: RecordDetail[];
}

export async function getRecords(params?: {
  stock_code?: string;
  market?: string;
  status?: string;
  decision?: string;
  start_date?: string;
  end_date?: string;
  batch_id?: string;
  limit?: number;
  offset?: number;
}): Promise<RecordsResponse> {
  const searchParams = new URLSearchParams();
  if (params?.stock_code) searchParams.set('stock_code', params.stock_code);
  if (params?.market) searchParams.set('market', params.market);
  if (params?.status) searchParams.set('status', params.status);
  if (params?.decision) searchParams.set('decision', params.decision);
  if (params?.start_date) searchParams.set('start_date', params.start_date);
  if (params?.end_date) searchParams.set('end_date', params.end_date);
  if (params?.batch_id) searchParams.set('batch_id', params.batch_id);
  if (params?.limit) searchParams.set('limit', String(params.limit));
  if (params?.offset) searchParams.set('offset', String(params.offset));
  const qs = searchParams.toString();
  return fetchJSON<RecordsResponse>(`/records${qs ? `?${qs}` : ''}`);
}

export async function getRecordDetail(recordId: string): Promise<RecordDetail> {
  return fetchJSON<RecordDetail>(`/records/${recordId}`);
}

export async function getStockRecords(
  stockCode: string,
  limit: number = 20
): Promise<{ stock_code: string; total: number; items: RecordDetail[] }> {
  return fetchJSON(`/records/stock/${encodeURIComponent(stockCode)}?limit=${limit}`);
}

// === Price Cache (session-level, 60s TTL) ===
const _priceCache = new Map<string, { data: { stock_code: string; price_history: PriceHistoryItem[] }; ts: number }>();
const _CACHE_TTL = 60000;

export async function getCachedStockPrice(stockCode: string): Promise<{ stock_code: string; price_history: PriceHistoryItem[] }> {
  const cached = _priceCache.get(stockCode);
  if (cached && Date.now() - cached.ts < _CACHE_TTL) {
    return cached.data;
  }
  const data = await getStockPrice(stockCode);
  _priceCache.set(stockCode, { data, ts: Date.now() });
  return data;
}

export async function getCachedStockPrices(stockCodes: string[]): Promise<Map<string, { stock_code: string; price_history: PriceHistoryItem[] }>> {
  const results = new Map<string, { stock_code: string; price_history: PriceHistoryItem[] }>();
  const uncached = stockCodes.filter(code => {
    const cached = _priceCache.get(code);
    return !cached || Date.now() - cached.ts >= _CACHE_TTL;
  });

  // Fetch uncached in parallel
  if (uncached.length > 0) {
    const fetched = await Promise.all(uncached.map(code => getStockPrice(code)));
    fetched.forEach(data => {
      _priceCache.set(data.stock_code, { data, ts: Date.now() });
    });
  }

  // Add all to results (cached + just-fetched)
  stockCodes.forEach(code => {
    const cached = _priceCache.get(code);
    if (cached) results.set(code, cached.data);
  });

  return results;
}
