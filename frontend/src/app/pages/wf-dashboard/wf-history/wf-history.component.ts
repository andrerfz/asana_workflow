import {
  Component, ChangeDetectionStrategy, ViewEncapsulation,
  signal, inject, OnInit, computed,
} from '@angular/core';
import { DatePipe } from '@angular/common';
import { ApiService } from '../../../core/services/api.service';
import { firstValueFrom } from 'rxjs';

interface HistoryRun {
  task_gid: string;
  task_name: string;
  phase: string;
  created_at: string;
  completed_at: string | null;
  duration_seconds: number | null;
  cost_usd: number | null;
  tokens: { input: number; output: number } | null;
  retries: number;
  error: string | null;
  repos?: { id: string }[];
}

interface HistoryStats {
  total_runs: number;
  completed: number;
  failed: number;
  success_rate: number;
  total_cost_usd: number;
  avg_duration_seconds: number;
}

interface DayBucket {
  day: string;
  success: number;
  failed: number;
  cost: number;
}

@Component({
  selector: 'app-wf-history',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  imports: [DatePipe],
  template: `
<div class="wf-hist">

  <!-- ── Stat cards ── -->
  <div class="wf-hist-stats">
    <div class="wf-stat">
      <div class="wf-stat-l">Runs · all time</div>
      <div class="wf-stat-row">
        <span class="wf-stat-n" style="color:var(--wf-accent)">{{ stats()?.total_runs ?? '—' }}</span>
      </div>
      <div class="wf-hist-trend">{{ stats()?.completed }} done / {{ stats()?.failed }} failed</div>
    </div>
    <div class="wf-stat">
      <div class="wf-stat-l">Success rate</div>
      <div class="wf-stat-row">
        <span class="wf-stat-n" style="color:var(--wf-green)">{{ stats() ? stats()!.success_rate.toFixed(0) + '%' : '—' }}</span>
      </div>
      <div class="wf-hist-trend">{{ stats()?.completed }} ✓ / {{ stats()?.failed }} ✗</div>
    </div>
    <div class="wf-stat">
      <div class="wf-stat-l">Total cost</div>
      <div class="wf-stat-row">
        <span class="wf-stat-n" style="color:var(--wf-amber)">{{ stats() ? ('$' + stats()!.total_cost_usd.toFixed(2)) : '—' }}</span>
      </div>
      <div class="wf-hist-trend">{{ totalTokensK() }}K tokens</div>
    </div>
    <div class="wf-stat">
      <div class="wf-stat-l">Avg cycle</div>
      <div class="wf-stat-row">
        <span class="wf-stat-n" style="color:var(--wf-violet)">{{ avgDuration() }}</span>
      </div>
      <div class="wf-hist-trend">incl. queue + tests</div>
    </div>
  </div>

  <!-- ── Bar chart ── -->
  @if (chartData().length > 0) {
    <div class="wf-hist-chart">
      <div class="wf-hist-chart-head">
        <div class="wf-d-card-h" style="padding:0">Daily activity</div>
        <div class="wf-hist-chart-legend">
          <span><span class="wf-legend-dot" style="background:var(--wf-green)"></span>Success</span>
          <span><span class="wf-legend-dot" style="background:var(--wf-red)"></span>Failed</span>
          <span><span class="wf-legend-dot" style="background:var(--wf-amber);opacity:.5"></span>Cost</span>
        </div>
      </div>
      <div class="wf-barchart">
        @for (d of chartData(); track d.day) {
          <div class="wf-bar-col">
            <div class="wf-bar-wrap">
              <div class="wf-bar-stack">
                @if (d.failed > 0) {
                  <div [style.height.%]="barPct(d.failed, maxRuns())" style="background:var(--wf-red)"></div>
                }
                @if (d.success > 0) {
                  <div [style.height.%]="barPct(d.success, maxRuns())" style="background:var(--wf-green)"></div>
                }
              </div>
              <div class="wf-bar-cost" [style.height.%]="barPct(d.cost, maxCost())"></div>
            </div>
            <div class="wf-bar-lbl">{{ d.day }}</div>
          </div>
        }
      </div>
    </div>
  }

  <!-- ── Table ── -->
  <div class="wf-hist-table">
    <div class="wf-hist-toolbar">
      <div class="wf-d-card-h" style="padding:0">Run history · {{ runs().length }}</div>
    </div>

    @if (loading()) {
      <div class="wf-empty" style="padding:40px">Loading history…</div>
    } @else if (runs().length === 0) {
      <div class="wf-empty" style="padding:40px">No completed runs yet</div>
    } @else {
      <div class="wf-hist-head">
        <div>Task</div>
        <div>Started</div>
        <div>Duration</div>
        <div>Outcome</div>
        <div>Tokens</div>
        <div style="text-align:right">Cost</div>
      </div>
      <div class="wf-hist-rows">
        @for (run of runs(); track run.task_gid) {
          <div class="wf-hist-row">
            <div class="wf-hist-task">
              <span class="wf-row-cdot" style="background:var(--wf-accent);flex-shrink:0"></span>
              <div style="min-width:0">
                <div style="font-size:13px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
                  {{ run.task_name || run.task_gid }}
                </div>
                <div style="font-size:11px;color:var(--wf-text-mute);display:flex;gap:6px">
                  <span class="wf-mono">#{{ run.task_gid.slice(-5) }}</span>
                  @if (run.repos?.[0]?.id) {
                    <span class="wf-row-sep">·</span>
                    <span>{{ run.repos![0].id }}</span>
                  }
                  @if (run.retries > 0) {
                    <span class="wf-row-sep">·</span>
                    <span style="color:var(--wf-amber)">{{ run.retries }} retries</span>
                  }
                </div>
              </div>
            </div>
            <div class="wf-hist-cell wf-mono">{{ fmtDate(run.created_at) }}</div>
            <div class="wf-hist-cell wf-mono">{{ fmtDur(run.duration_seconds) }}</div>
            <div class="wf-hist-cell">
              <span class="wf-hist-outcome" [class.is-ok]="run.phase === 'done'" [class.is-err]="run.phase === 'error'">
                {{ run.phase === 'done' ? '✓ shipped' : run.phase === 'error' ? '✗ failed' : run.phase }}
              </span>
            </div>
            <div class="wf-hist-cell wf-mono" style="color:var(--wf-text-soft)">
              {{ run.tokens ? ((run.tokens.input + run.tokens.output) / 1000).toFixed(1) + 'K' : '—' }}
            </div>
            <div class="wf-hist-cell wf-mono" style="text-align:right">
              {{ run.cost_usd ? ('$' + run.cost_usd.toFixed(3)) : '—' }}
            </div>
          </div>
        }
      </div>
    }
  </div>

</div>
  `,
})
export class WfHistoryComponent implements OnInit {
  private api = inject(ApiService);

  loading = signal(true);
  runs = signal<HistoryRun[]>([]);
  stats = signal<HistoryStats | null>(null);

  readonly chartData = computed<DayBucket[]>(() => {
    const buckets = new Map<string, DayBucket>();
    for (const r of this.runs()) {
      if (!r.created_at) continue;
      const d = new Date(r.created_at);
      const key = d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
      if (!buckets.has(key)) buckets.set(key, { day: key, success: 0, failed: 0, cost: 0 });
      const b = buckets.get(key)!;
      if (r.phase === 'done') b.success++; else b.failed++;
      b.cost += r.cost_usd ?? 0;
    }
    return Array.from(buckets.values()).slice(-14).reverse();
  });

  readonly maxRuns = computed(() => Math.max(...this.chartData().map(d => d.success + d.failed), 1));
  readonly maxCost = computed(() => Math.max(...this.chartData().map(d => d.cost), 0.01));

  readonly totalTokensK = computed(() => {
    const total = this.runs().reduce((sum, r) =>
      sum + (r.tokens ? r.tokens.input + r.tokens.output : 0), 0);
    return (total / 1000).toFixed(0);
  });

  readonly avgDuration = computed(() => {
    const s = this.stats();
    if (!s?.avg_duration_seconds) return '—';
    const m = Math.floor(s.avg_duration_seconds / 60);
    return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h ${m % 60}m`;
  });

  async ngOnInit(): Promise<void> {
    try {
      const res = await firstValueFrom(this.api.getAgentHistory());
      this.runs.set((res?.runs ?? []) as HistoryRun[]);
      this.stats.set((res?.stats ?? null) as HistoryStats | null);
    } catch (e) {
      console.error('[WfHistory] load failed', e);
    } finally {
      this.loading.set(false);
    }
  }

  barPct(value: number, max: number): number {
    return max > 0 ? Math.round((value / max) * 100) : 0;
  }

  fmtDate(iso: string): string {
    if (!iso) return '—';
    try {
      const d = new Date(iso);
      const diff = (Date.now() - d.getTime()) / 1000;
      if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
      if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
      return `${Math.floor(diff / 86400)}d ago`;
    } catch { return '—'; }
  }

  fmtDur(seconds: number | null): string {
    if (!seconds) return '—';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return m < 60
      ? `${m}m ${String(s).padStart(2, '0')}s`
      : `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m`;
  }
}
