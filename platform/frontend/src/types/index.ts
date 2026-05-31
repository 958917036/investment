export type Market = 'CN' | 'HK' | 'US';
export type Status = 'pending' | 'running' | 'completed' | 'failed';
export type Decision = 'BUY' | 'SELL' | 'WATCH' | 'NO';

export interface Score {
  growth?: number;
  value?: number;
  momentum?: number;
  quality?: number;
  risk?: number;
  [key: string]: number | undefined;
}

export interface AnalysisRecord {
  id: string;
  stock_code: string;
  stock_name?: string;
  market: Market;
  timestamp: string;
  status: Status;
  task_id?: string;
  step?: string;
  l1_data?: Record<string, unknown>;
  l2_data?: Record<string, unknown>;
  l3_data?: Record<string, unknown>;
  l4_data?: Record<string, unknown>;
  final_decision?: Decision;
  score?: Score;
  judge_score?: number;
  raw_data?: Record<string, unknown>;
  batch_id?: string;
}

export interface BatchTask {
  task_id: string;
  status?: Status;
  total_count: number;
  completed_count: number;
  failed_count: number;
  pending_count: number;
  running_count: number;
  cancelled_count: number;
  buy_count: number;
  watch_count: number;
  progress: number;
}

export interface StockProfile {
  stock_code: string;
  stock_name?: string;
  market: Market;
  analysis_count: number;
  last_analysis_date?: string;
  latest_result_id?: string;
  latest_decision?: Decision;
}

export interface DashboardStats {
  total_analyses: number;
  stocks_analyzed: number;
  buy_count: number;
  watch_count: number;
  sell_count: number;
  no_count: number;
  window_analyses: number;
  completed_count: number;
  active_tasks: number;
  decision_distribution: Record<Decision, number>;
  market_distribution: Record<Market, number>;
  status_distribution: Record<Status, number>;
  recent_analyses: Array<{
    id: string;
    stock_code: string;
    stock_name?: string;
    market?: Market;
    timestamp: string;
    status: Status;
    final_decision?: Decision;
  }>;
}

export interface CompareData {
  stock_code: string;
  analysis_a: AnalysisRecord;
  analysis_b: AnalysisRecord;
  comparison: {
    decision_changed: boolean;
    decision_a?: Decision;
    decision_b?: Decision;
    score_a: Score;
    score_b: Score;
    timestamp_a?: string;
    timestamp_b?: string;
  };
}

export interface Reflection {
  id: string;
  analysis_id: string;
  wrong_analysis: 'A' | 'B';
  reflection_text: string;
  error_tags: string[];
  correct_analysis_id?: string;
  created_at: string;
}

export interface PortfolioItem {
  stock_code: string;
  stock_name?: string;
  market: Market;
  quantity?: number;
  cost?: number;
  current_price?: number;
  current_value?: number;
  latest_analysis?: {
    id: string;
    timestamp: string;
    final_decision?: Decision;
    score?: Score;
  };
}

export interface WatchlistItem {
  stock_code: string;
  stock_name?: string;
  market: Market;
  added_at: string;
  latest_analysis?: {
    id: string;
    timestamp: string;
    final_decision?: Decision;
    score?: Score;
  };
}

export interface HistoryResponse {
  records: AnalysisRecord[];
}
