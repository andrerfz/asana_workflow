import { Component, ChangeDetectionStrategy, input, output, ViewEncapsulation, computed, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { WfTask, LIVE_PHASES, WF_PHASE_BY_ID } from '../wf-task.model';
import { WfStats } from '../wf-header/wf-header.component';

@Component({
  selector: 'app-wf-sidebar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `
    <aside class="wf-side">
      <!-- WORKSPACE -->
      <div class="wf-side-h">Workspace</div>
      <nav class="wf-side-nav">
        <button class="wf-ws" [class.is-on]="workspace() === 'inbox'" (click)="workspaceChange.emit('inbox')">
          <span class="wf-ws-ico">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>
          </span>
          <span class="wf-ws-l">Inbox · all open</span>
          <span class="wf-ws-c">{{ wsCounts().inbox }}</span>
        </button>
        <button class="wf-ws is-warm" [class.is-on]="workspace() === 'awaiting'" (click)="workspaceChange.emit('awaiting')">
          <span class="wf-ws-ico">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>
          </span>
          <span class="wf-ws-l">Awaiting you</span>
          <span class="wf-ws-c">{{ wsCounts().awaiting }}</span>
        </button>
        <button class="wf-ws is-live" [class.is-on]="workspace() === 'flight'" (click)="workspaceChange.emit('flight')">
          <span class="wf-ws-ico">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m12 2 4 7-4 2-4-2 4-7zM12 11v11M8 22h8"/></svg>
          </span>
          <span class="wf-ws-l">In flight</span>
          <span class="wf-ws-c">{{ wsCounts().flight }}</span>
        </button>
        <button class="wf-ws" [class.is-on]="workspace() === 'queued'" (click)="workspaceChange.emit('queued')">
          <span class="wf-ws-ico">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
          </span>
          <span class="wf-ws-l">Queued</span>
          <span class="wf-ws-c">{{ wsCounts().queued }}</span>
        </button>
        <button class="wf-ws is-good" [class.is-on]="workspace() === 'shipped'" (click)="workspaceChange.emit('shipped')">
          <span class="wf-ws-ico">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m5 12 5 5L20 7"/></svg>
          </span>
          <span class="wf-ws-l">Shipped today</span>
          <span class="wf-ws-c">{{ wsCounts().shipped }}</span>
        </button>
      </nav>

      <!-- LIVE AGENTS -->
      @if (liveTasks().length > 0) {
        <div class="wf-side-h">
          <span>Live agents</span>
          <span class="wf-side-h-act">
            <span class="wf-h-pulse" style="display:inline-block; vertical-align:middle; margin-right:4px"></span>
            {{ liveTasks().length }}
          </span>
        </div>
        <div class="wf-live-stack">
          @for (task of liveTasks(); track task.gid) {
            <button class="wf-live" [class.is-on]="selected() === task.gid" (click)="selectedChange.emit(task.gid)">
              <div class="wf-live-top">
                <span class="wf-live-cdot" [style.background]="task.cluster?.color || '#6b7280'"></span>
                <span class="wf-live-title">{{ task.name }}</span>
              </div>
              <div class="wf-live-meta">
                <span class="wf-live-phase" [style.color]="phaseColor(task.phase)">
                  <span class="wf-live-phase-dot wf-phase-dot is-live" [style.background]="phaseColor(task.phase)"></span>
                  {{ phaseLabel(task.phase) }}
                </span>
                <span class="wf-mono wf-live-pct">{{ Math.round(task.progress * 100) }}%</span>
              </div>
              <div class="wf-live-bar">
                <div class="wf-live-bar-fill" [style.width.%]="task.progress * 100" [style.background]="phaseColor(task.phase)"></div>
              </div>
            </button>
          }
        </div>
      }

      <!-- SECTIONS -->
      <div class="wf-side-h">Section</div>
      <nav class="wf-side-nav">
        <button class="wf-sec" [class.is-on]="section() == null" (click)="sectionChange.emit(null)">
          <span class="wf-sec-l">All</span>
          <span class="wf-sec-c">{{ tasks().length }}</span>
        </button>
        @for (sec of sections(); track sec.name) {
          @if (sec.count > 0) {
            <button class="wf-sec" [class.is-on]="section() === sec.name" (click)="sectionChange.emit(sec.name)">
              <span class="wf-sec-l">{{ sec.name }}</span>
              <span class="wf-sec-c">{{ sec.count }}</span>
            </button>
          }
        }
      </nav>

      <!-- USAGE FOOT -->
      <div class="wf-side-foot">
        <div class="wf-foot-row" title="Real Anthropic API spend today (paid key — AI classification only), from the usage on each call">
          <span>AI classify <span style="opacity:.55">· API</span></span>
          <span class="wf-mono"><b>{{ fmtUsd(apiSpend()) }}</b></span>
        </div>
        <div class="wf-foot-row" style="margin-top:4px" title="Local tally of agent run cost (Claude Code subscription — not account credit)">
          <span>Agent runs <span style="opacity:.55">· sub</span></span>
          <span class="wf-mono">{{ '$' + stats().cost.toFixed(2) }}</span>
        </div>
        @if (quota(); as q) {
          @if (q.available && q.usage) {
            <div class="wf-foot-row" style="margin-top:8px">
              <span>Claude quota <span style="opacity:.55">· real</span></span>
              @if (q.stale) { <span style="font-size:10px;opacity:.5">stale</span> }
            </div>
            @for (g of gauges(q.usage); track g.key) {
              <div class="wf-foot-row" style="margin-top:4px;font-size:11px" [title]="g.title">
                <span style="opacity:.75">{{ g.label }}</span>
                <span class="wf-mono" [style.color]="g.color || 'inherit'">{{ g.pct }}%<span style="opacity:.5"> · {{ g.reset }}</span></span>
              </div>
              <div class="wf-foot-bar" style="margin-top:2px">
                <div class="wf-foot-bar-fill" [style.width.%]="Math.min(100, g.pct)" [style.background]="g.color || null"></div>
              </div>
            }
          }
        }
        @if (claudeUsage(); as cu) {
          @if (cu.insights.length) {
            <div class="wf-foot-row" style="margin-top:10px" [title]="cu.note">
              <span style="opacity:.8">contributing <span style="opacity:.55">· 24h local</span></span>
              <span class="wf-mono" style="opacity:.6">~{{ tokensM(cu.tokens_24h) }}M tok</span>
            </div>
            @for (ins of cu.insights; track ins.key) {
              <div class="wf-foot-row" style="margin-top:3px;font-size:11px" [title]="ins.hint">
                <span style="opacity:.7">{{ ins.label }}</span>
                <span class="wf-mono" style="opacity:.85">{{ ins.pct }}%</span>
              </div>
            }
            <div style="font-size:9px;opacity:.4;margin-top:4px;line-height:1.3">Local estimate, not your real quota</div>
          }
        }
      </div>
    </aside>
  `,
})
export class WfSidebarComponent {
  tasks = input.required<WfTask[]>();
  workspace = input<string>('inbox');
  section = input<string | null>(null);
  selected = input<string | null>(null);
  stats = input.required<WfStats>();

  workspaceChange = output<string>();
  sectionChange = output<string | null>();
  selectedChange = output<string>();

  protected Math = Math;

  /** Real classification API spend today (paid key), fetched from the backend. */
  apiSpend = signal(0);
  /** Local Claude Code usage insights (last 24h) — honest, not a quota %. */
  claudeUsage = signal<{ tokens_24h: number; note: string; insights: { key: string; label: string; pct: number; hint: string }[] } | null>(null);
  /** Real subscription quota (session 5h + weekly), via the Electron host bridge. */
  quota = signal<{ available: boolean; stale: boolean; usage: any } | null>(null);

  constructor(private http: HttpClient) {
    this.refreshUsage();
    // Refresh periodically so the figures stay current.
    setInterval(() => this.refreshUsage(), 60_000);
  }

  private refreshUsage(): void {
    this.http.get<{ today: { cost_usd: number } }>('/api/ai/usage').subscribe({
      next: r => this.apiSpend.set(r?.today?.cost_usd ?? 0),
      error: () => {},
    });
    this.http.get<{ tokens_24h: number; note: string; insights: { key: string; label: string; pct: number; hint: string }[] }>('/api/ai/claude-usage').subscribe({
      next: r => this.claudeUsage.set(r),
      error: () => {},
    });
    this.http.get<{ available: boolean; stale: boolean; usage: any }>('/api/ai/oauth-usage').subscribe({
      next: r => this.quota.set(r),
      error: () => {},
    });
  }

  tokensM(t: number): string {
    return (t / 1_000_000).toFixed(t >= 10_000_000 ? 0 : 1);
  }

  /** Build the displayable quota gauges from the /api/oauth/usage payload. */
  gauges(u: any): { key: string; label: string; pct: number; reset: string; color: string | null; title: string }[] {
    const color = (p: number) => p >= 95 ? '#ef4444' : p >= 80 ? '#fbbf24' : null;
    const g: any[] = [];
    if (u?.five_hour) g.push({ key: 'session', label: 'Session 5h', pct: Math.round(u.five_hour.utilization), reset: this.fmtReset(u.five_hour.resets_at), color: color(u.five_hour.utilization), title: 'Current 5-hour session window' });
    if (u?.seven_day) g.push({ key: 'week', label: 'Week · all', pct: Math.round(u.seven_day.utilization), reset: this.fmtReset(u.seven_day.resets_at), color: color(u.seven_day.utilization), title: 'Current week, all models' });
    if (u?.seven_day_sonnet) g.push({ key: 'week-sonnet', label: 'Week · Sonnet', pct: Math.round(u.seven_day_sonnet.utilization), reset: this.fmtReset(u.seven_day_sonnet.resets_at), color: color(u.seven_day_sonnet.utilization), title: 'Current week, Sonnet only' });
    const ex = u?.extra_usage;
    if (ex?.is_enabled) g.push({ key: 'extra', label: 'Extra usage', pct: Math.round(ex.utilization), reset: `${Math.round(ex.used_credits)}/${ex.monthly_limit}${ex.currency === 'EUR' ? '€' : ''}`, color: color(ex.utilization), title: 'Monthly extra-usage credits' });
    return g;
  }

  fmtReset(iso: string | null): string {
    if (!iso) return '—';
    try {
      const d = new Date(iso);
      const sameDay = d.toDateString() === new Date().toDateString();
      return sameDay
        ? d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
        : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
    } catch {
      return '—';
    }
  }

  liveTasks = computed(() =>
    this.tasks().filter(t => LIVE_PHASES.includes(t.phase))
  );

  wsCounts = computed(() => {
    const ts = this.tasks();
    return {
      inbox:    ts.filter(t => t.phase !== 'done').length,
      awaiting: ts.filter(t => t.phase === 'awaiting_approval').length,
      flight:   ts.filter(t => LIVE_PHASES.includes(t.phase)).length,
      queued:   ts.filter(t => t.phase === 'queued').length,
      shipped:  ts.filter(t => t.phase === 'done').length,
    };
  });

  sections = computed(() => {
    const countMap: Record<string, number> = {};
    for (const t of this.tasks()) {
      countMap[t.section] = (countMap[t.section] ?? 0) + 1;
    }
    return Object.entries(countMap).map(([name, count]) => ({ name, count }));
  });

  /** Show cents with 2 decimals, but keep precision for sub-cent spend. */
  fmtUsd(v: number): string {
    if (v > 0 && v < 0.01) return '$' + v.toFixed(4);
    return '$' + v.toFixed(2);
  }

  phaseColor(phase: string): string {
    return WF_PHASE_BY_ID[phase]?.color ?? '#6b7280';
  }

  phaseLabel(phase: string): string {
    return WF_PHASE_BY_ID[phase]?.label ?? phase;
  }
}
