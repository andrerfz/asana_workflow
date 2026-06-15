import { Component, ChangeDetectionStrategy, input, output, ViewEncapsulation } from '@angular/core';
import { WfTask, LIVE_PHASES, WF_PHASE_BY_ID } from '../wf-task.model';
import { WfAction } from '../wf-list/wf-list.component';

@Component({
  selector: 'app-wf-cards',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `
    @if (tasks().length === 0) {
      <div class="wf-empty">No tasks match the current filters</div>
    } @else {
      <div class="wf-cards">
        @for (task of tasks(); track task.gid) {
          <div
            role="button"
            tabIndex="0"
            class="wf-card-tile"
            [class.is-on]="selected() === task.gid"
            [class.is-wait]="task.phase === 'awaiting_approval'"
            (click)="selectedChange.emit(task.gid)"
            (keydown)="onKey($event, task.gid)"
          >
            <div class="wf-card-stripe" [style.background]="task.cluster?.color || '#6b7280'"></div>

            <div class="wf-card-head">
              <span [style.color]="task.cluster?.color" style="font-size:11px; font-weight:600">{{ task.cluster?.name || '—' }}</span>
              <span class="wf-mono" style="color:var(--wf-text-dim); font-size:10px">#{{ task.gid.slice(-5) }}</span>
            </div>

            <h4 class="wf-card-title">{{ task.name }}</h4>

            <div class="wf-card-tags">
              <span class="wf-tag" [class]="tipoCls(task.tipo)">{{ task.tipo }}</span>
              <span class="wf-tag wf-tag-scope">S{{ task.scope }}</span>
              <span class="wf-tag" [class]="priCls(task.priority)">P{{ task.priority }}</span>
            </div>

            <div class="wf-card-phase">
              <span class="wf-phase-dot" [class.is-live]="isLive(task.phase)" [style.background]="phaseColor(task.phase)"></span>
              <span [style.color]="phaseColor(task.phase)" style="font-size:12px; font-weight:500">{{ phaseLabel(task.phase) }}</span>
              @if (isLive(task.phase)) {
                <span class="wf-mono" style="color:var(--wf-text-mute); margin-left:auto; font-size:11px">{{ pct(task) }}%</span>
              }
              @if (task.phase === 'done') {
                <span style="color:var(--wf-green); margin-left:auto; font-size:11px">shipped</span>
              }
            </div>

            @if (isLive(task.phase)) {
              <div class="wf-card-bar">
                <div class="wf-card-bar-fill" [style.width.%]="task.progress * 100" [style.background]="phaseColor(task.phase)"></div>
              </div>
            }

            @if (task.branch !== '—') {
              <div class="wf-card-branch wf-mono">
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M6 9v6M6 18a9 9 0 0 0 9-9v3"/></svg>
                @if (task.repos.length > 1) {
                  <span title="Cross-repo task: {{ task.repos.join(', ') }}"
                    style="margin-right:5px; padding:0 4px; border-radius:6px; font-size:9px; font-weight:700; background:var(--wf-accent,#5b8cff); color:#fff">{{ task.repos.length }} repos</span>
                }
                <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap">{{ shortBranch(task) }}</span>
              </div>
            }

            <div class="wf-card-foot">
              <div class="wf-card-foot-l">
                <span class="wf-mono" style="color:var(--wf-text-mute); font-size:11px">
                  {{ task.cost ? ('$' + task.cost.toFixed(3)) : '—' }}
                </span>
              </div>

              <div class="wf-card-actions">
                @if (task.phase === 'awaiting_approval') {
                  <button class="wf-btn wf-btn-warn" style="padding:4px 10px; font-size:11px" (click)="emitAction($event, task.gid, 'approve')">Approve</button>
                }
                @if (isLive(task.phase)) {
                  <button class="wf-btn wf-btn-danger" style="padding:4px 10px; font-size:11px" (click)="emitAction($event, task.gid, 'stop')">Stop</button>
                }
                @if (task.phase === 'queued') {
                  <button class="wf-btn wf-btn-primary" style="padding:4px 10px; font-size:11px" (click)="emitAction($event, task.gid, 'start')">Run agent</button>
                }
                @if (task.phase === 'done') {
                  <button class="wf-btn" style="padding:4px 10px; font-size:11px" (click)="emitAction($event, task.gid, 'open_pr')">Open PR ↗</button>
                }
                @if (task.phase === 'done' || task.phase === 'error' || task.phase === 'cancelled') {
                  <button class="wf-btn" style="padding:4px 10px; font-size:11px" (click)="emitAction($event, task.gid, 'run_qa')">Run QA</button>
                }
                <button class="wf-row-mini" aria-label="Open in IDE" (click)="emitAction($event, task.gid, 'ide')">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
                </button>
              </div>
            </div>
          </div>
        }
      </div>
    }
  `,
})
export class WfCardsComponent {
  tasks = input<WfTask[]>([]);
  selected = input<string | null>(null);
  startingGids = input<Set<string>>(new Set());

  selectedChange = output<string>();
  action = output<WfAction>();

  isLive(phase: string): boolean {
    return LIVE_PHASES.includes(phase);
  }

  phaseColor(phase: string): string {
    return WF_PHASE_BY_ID[phase]?.color ?? '#6b7280';
  }

  phaseLabel(phase: string): string {
    return WF_PHASE_BY_ID[phase]?.label ?? phase;
  }

  pct(task: WfTask): number {
    return Math.round((task.progress || 0) * 100);
  }

  tipoCls(tipo: string | null): string {
    const map: Record<string, string> = {
      Bug: 'wf-tag-tipo-bug',
      Feature: 'wf-tag-tipo-feature',
      Mejora: 'wf-tag-tipo-mejora',
      Performance: 'wf-tag-tipo-perf',
    };
    return tipo ? (map[tipo] ?? '') : '';
  }

  priCls(priority: number): string {
    return `wf-tag-pri-${Math.min(4, priority)}`;
  }

  shortBranch(task: WfTask): string {
    if (task.branch === '—') return '—';
    return task.branch.replace(`feature/${task.gid}/`, '…/');
  }

  emitAction(event: Event, gid: string, act: string): void {
    event.stopPropagation();
    this.action.emit({ gid, act });
  }

  onKey(event: KeyboardEvent, gid: string): void {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      this.selectedChange.emit(gid);
    }
  }
}
