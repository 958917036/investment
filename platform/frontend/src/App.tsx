import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import { Dashboard } from '@/pages/Dashboard';
import { Analyze } from '@/pages/Analyze';
import { L1Screening } from '@/pages/L1Screening';
import { ResultDetail } from '@/pages/ResultDetail';
import { History } from '@/pages/History';
import { Compare } from '@/pages/Compare';
import { Batch } from '@/pages/Batch';
import { Stocks } from '@/pages/Stocks';
import { Portfolio } from '@/pages/Portfolio';
import { Watchlist } from '@/pages/Watchlist';
import { BarChart3, Search, List, Package, PieChart, Eye, Zap } from 'lucide-react';
import { cn } from '@/lib/utils';

function Navigation() {
  const location = useLocation();

  const navItems = [
    { path: '/', label: '首页', icon: BarChart3 },
    { path: '/analyze', label: '分析', icon: Search },
    { path: '/l1', label: 'L1专线', icon: Zap },
    { path: '/batch', label: '批次', icon: List },
    { path: '/stocks', label: '股票库', icon: Package },
    { path: '/portfolio', label: '持仓', icon: PieChart },
    { path: '/watchlist', label: '关注', icon: Eye },
  ];

  return (
    <nav className="border-b border-border bg-card/50 backdrop-blur supports-[backdrop-filter]:bg-card/50 sticky top-0 z-50">
      <div className="container mx-auto px-4">
        <div className="flex h-14 items-center justify-between">
          <div className="flex items-center gap-6">
            <Link to="/" className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                <BarChart3 className="h-5 w-5 text-primary" />
              </div>
              <span className="font-bold text-lg hidden sm:inline">神农</span>
            </Link>
            <div className="flex gap-1">
              {navItems.map((item) => {
                const Icon = item.icon;
                const isActive = location.pathname === item.path;
                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    className={cn(
                      'flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium transition-colors',
                      isActive
                        ? 'bg-primary/10 text-primary'
                        : 'text-muted-foreground hover:text-foreground hover:bg-muted'
                    )}
                  >
                    <Icon className="h-4 w-4" />
                    <span className="hidden sm:inline">{item.label}</span>
                  </Link>
                );
              })}
            </div>
          </div>
          <div className="text-xs text-muted-foreground">
            AI Stock Analysis Platform
          </div>
        </div>
      </div>
    </nav>
  );
}

function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-background">
        <Navigation />
        <main className="container mx-auto px-4 py-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/analyze" element={<Analyze />} />
            <Route path="/l1" element={<L1Screening />} />
            <Route path="/result/:id" element={<ResultDetail />} />
            <Route path="/history/:code?" element={<History />} />
            <Route path="/compare/:code?" element={<Compare />} />
            
            <Route path="/batch" element={<Batch />} />
            <Route path="/stocks" element={<Stocks />} />
            <Route path="/portfolio" element={<Portfolio />} />
            <Route path="/watchlist" element={<Watchlist />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;
