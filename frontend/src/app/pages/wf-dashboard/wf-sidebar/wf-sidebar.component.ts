import { Component, ChangeDetectionStrategy, input, output, ViewEncapsulation, computed } from '@angular/core';
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

      <!-- BUDGET FOOT -->
      <div class="wf-side-foot">
        <div class="wf-foot-row">
          <span>Spend today</span>
          <span class="wf-mono"><b>{{ '$' + stats().cost.toFixed(2) }}</b> / $10.00</span>
        </div>
        <div class="wf-foot-bar">
          <div class="wf-foot-bar-fill" [style.width.%]="Math.min(100, (stats().cost / 10) * 100)"></div>
        </div>
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

  phaseColor(phase: string): string {
    return WF_PHASE_BY_ID[phase]?.color ?? '#6b7280';
  }

  phaseLabel(phase: string): string {
    return WF_PHASE_BY_ID[phase]?.label ?? phase;
  }
}
