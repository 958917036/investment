import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import { Badge } from '@/components/ui/badge';
import { listBatches, retryBatch, cancelBatch, getQueue, type QueueItem } from '@/lib/api';
import type { BatchTask } from '@/types';
import { RefreshCw, XCircle, Loader2 } from 'lucide-react';

export function Batch() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [batches, setBatches] = useState<BatchTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState<string | null>(null);
  const [expandedBatches, setExpandedBatches] = useState<Set<string>>(new Set());
  const [queueItemsByBatch, setQueueItemsByBatch] = useState<Map<string, QueueItem[]>>(new Map());

  const highlightTaskId = searchParams.get('task_id');

  useEffect(() => {
    loadBatches();
    const interval = setInterval(loadBatches, 5000);
    return () => clearInterval(interval);
  }, []);

  const loadBatches = async () => {
    try {
      const data = await listBatches();
      setBatches(data);
    } catch (error) {
      console.error('Failed to load batches:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleRetry = async (batchId: string) => {
    setRefreshing(batchId);
    try {
      await retryBatch(batchId);
      await loadBatches();
    } catch (error) {
      console.error('Failed to retry batch:', error);
    } finally {
      setRefreshing(null);
    }
  };

  const handleCancel = async (batchId: string) => {
    try {
      await cancelBatch(batchId);
      await loadBatches();
    } catch (error) {
      console.error('Failed to cancel batch:', error);
    }
  };

  const toggleExpand = async (batchId: string) => {
    const newExpanded = new Set(expandedBatches);
    if (newExpanded.has(batchId)) {
      newExpanded.delete(batchId);
    } else {
      newExpanded.add(batchId);
      // Load queue items if not already loaded
      if (!queueItemsByBatch.has(batchId)) {
        try {
          const queue = await getQueue({ batch_id: batchId });
          setQueueItemsByBatch(prev => new Map(prev).set(batchId, queue.items));
        } catch (error) {
          console.error('Failed to load queue items:', error);
        }
      }
    }
    setExpandedBatches(newExpanded);
  };

  const getStatusBadge = (status: string | null) => {
    switch (status) {
      case 'completed':
        return <Badge variant="default" className="bg-buy/20 text-buy border-buy/30">完成</Badge>;
      case 'running':
        return <Badge variant="secondary" className="bg-primary/20 text-primary">进行中</Badge>;
      case 'failed':
        return <Badge variant="destructive" className="bg-sell/20 text-sell border-sell/30">失败</Badge>;
      case 'pending':
        return <Badge variant="outline" className="text-muted-foreground">等待</Badge>;
      default:
        return <Badge variant="outline" className="text-muted-foreground">{status || '未知'}</Badge>;
    }
  };

  const getBatchProgress = (batch: BatchTask) => {
    if (batch.total_count === 0) return 0;
    return (batch.completed_count / batch.total_count) * 100;
  };

  const deriveStatus = (batch: BatchTask): string => {
    if (batch.cancelled_count > 0 && batch.running_count === 0 && batch.pending_count === 0) return 'cancelled';
    if (batch.running_count > 0) return 'running';
    if (batch.pending_count > 0) return 'pending';
    if (batch.failed_count > 0 && batch.completed_count + batch.failed_count >= batch.total_count) return 'failed';
    if (batch.completed_count >= batch.total_count) return 'completed';
    return 'running';
  };

  if (loading) {
    return (
      <div className="space-y-6 animate-slide-up">
        <div className="flex items-center gap-4">
          <Skeleton className="h-8 w-48" />
        </div>
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">批次任务</h1>
          <p className="text-muted-foreground">管理所有批量分析任务</p>
        </div>
        <Button variant="outline" onClick={loadBatches}>
          <RefreshCw className="mr-2 h-4 w-4" />
          刷新
        </Button>
      </div>

      {batches.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            暂无批次任务，
            <button
              onClick={() => navigate('/analyze')}
              className="text-primary hover:underline"
            >
              开始新的分析
            </button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {batches.map((batch) => (
            <Card
              key={batch.task_id}
              className={`transition-all ${batch.task_id === highlightTaskId ? 'border-primary bg-primary/5' : ''}`}
            >
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <CardTitle className="font-mono text-sm">
                      {batch.task_id.slice(0, 8)}...
                    </CardTitle>
                    <Badge
                      variant={
                        deriveStatus(batch) === 'completed'
                          ? 'default'
                          : deriveStatus(batch) === 'running'
                          ? 'secondary'
                          : deriveStatus(batch) === 'failed'
                          ? 'destructive'
                          : deriveStatus(batch) === 'cancelled'
                          ? 'neutral'
                          : 'outline'
                      }
                    >
                      {deriveStatus(batch) === 'pending' && '等待中'}
                      {deriveStatus(batch) === 'running' && '进行中'}
                      {deriveStatus(batch) === 'completed' && '已完成'}
                      {deriveStatus(batch) === 'failed' && '失败'}
                      {deriveStatus(batch) === 'cancelled' && '已取消'}
                    </Badge>
                  </div>
                  <div className="flex gap-2">
                    {batch.failed_count > 0 && deriveStatus(batch) !== 'pending' && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleRetry(batch.task_id)}
                        disabled={!!refreshing}
                      >
                        {refreshing === batch.task_id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <>
                            <RefreshCw className="mr-1 h-3 w-3" />
                            重试 ({batch.failed_count})
                          </>
                        )}
                      </Button>
                    )}
                    {deriveStatus(batch) === 'running' && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleCancel(batch.task_id)}
                      >
                        <XCircle className="mr-1 h-3 w-3" />
                        取消
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => toggleExpand(batch.task_id)}
                    >
                      {expandedBatches.has(batch.task_id) ? '收起' : '展开'}
                    </Button>
                  </div>
                </div>
                <div className="text-sm text-muted-foreground mt-1">
                  {getBatchProgress(batch).toFixed(0)}% · 进度 {batch.completed_count}/{batch.total_count} · 失败 {batch.failed_count}
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <Progress value={getBatchProgress(batch)} className="h-2" />
                <div className="flex justify-between text-sm">
                  <div className="flex gap-4">
                    <span>
                      <span className="text-muted-foreground">完成:</span>{' '}
                      <span className="text-buy font-medium">{batch.completed_count}</span>
                    </span>
                    <span>
                      <span className="text-muted-foreground">失败:</span>{' '}
                      <span className="text-sell font-medium">{batch.failed_count}</span>
                    </span>
                    <span>
                      <span className="text-muted-foreground">总计:</span>{' '}
                      <span className="font-medium">{batch.total_count}</span>
                    </span>
                  </div>
                  <span className="text-muted-foreground">
                    {getBatchProgress(batch).toFixed(0)}%
                  </span>
                </div>

                {expandedBatches.has(batch.task_id) && (
                  <div className="mt-4 pt-4 border-t">
                    <div className="text-sm font-medium mb-2">各股票状态:</div>
                    {queueItemsByBatch.has(batch.task_id) ? (
                      <div className="flex flex-wrap gap-2">
                        {queueItemsByBatch.get(batch.task_id)?.map((item) => (
                          <div key={item.id} className="flex items-center gap-2 px-2 py-1 rounded bg-muted/50">
                            <span className="font-mono text-xs">{item.stock_code}</span>
                            {getStatusBadge(item.status)}
                          </div>
                        )) || <span className="text-sm text-muted-foreground">无数据</span>}
                      </div>
                    ) : (
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        加载中...
                      </div>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
