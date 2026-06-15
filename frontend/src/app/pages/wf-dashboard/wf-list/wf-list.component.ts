import { Component, ChangeDetectionStrategy, input, output, ViewEncapsulation } from '@angular/core';
import { WfTask, LIVE_PHASES, WF_PHASE_BY_ID } from '../wf-task.model';

export interface WfAction {
  gid: string;
  act: string;
}

@Component({
  selector: 'app-wf-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `
    <div class="wf-cols-h">
      <div>Task</div>
      <div>Phase</div>
      <div>Repo · branch</div>
      <div>Diff</div>
      <div>Cost</div>
      <div style="text-align:right">Actions</div>
    </div>
    <div class="wf-list">
      @if (tasks().length === 0) {
        <div class="wf-empty">No tasks match the current filters</div>
      }
      @for (task of tasks(); track task.gid) {
        <div
          role="button"
          tabIndex="0"
          class="wf-row"
          [class.is-on]="selected() === task.gid"
          [class.is-wait]="task.phase === 'awaiting_approval'"
          (click)="selectedChange.emit(task.gid)"
          (keydown)="onRowKey($event, task.gid)"
        >
          <div class="wf-row-task">
            <span class="wf-row-cdot" [style.background]="task.cluster?.color || '#6b7280'" [title]="task.cluster?.name || ''"></span>
            <div class="wf-row-task-main">
              <div class="wf-row-title">{{ task.name }}</div>
              <div class="wf-row-meta">
                <span class="wf-tag" [class]="tipoCls(task.tipo)">{{ task.tipo }}</span>
                <span class="wf-tag wf-tag-scope">S{{ task.scope }}</span>
                <span class="wf-row-sep">·</span>
                <span [style.color]="task.cluster?.color" style="font-weight:500">{{ task.cluster?.name || '—' }}</span>
              </div>
            </div>
          </div>

          <div class="wf-row-phase">
            <span class="wf-phase-dot" [class.is-live]="isLive(task.phase)" [style.background]="phaseColor(task.phase)"></span>
            <span class="wf-phase-l">{{ phaseLabel(task.phase) }}</span>
          </div>

          <div class="wf-row-repo">
            <span class="wf-row-r1 wf-mono" [title]="reposTitle(task)">
              {{ reposLabel(task) }}
              @if (task.repos.length > 1) {
                <span title="Cross-repo task: {{ reposTitle(task) }}"
                  style="margin-left:4px; padding:0 4px; border-radius:6px; font-size:9px; font-weight:700; background:var(--wf-accent,#5b8cff); color:#fff; vertical-align:middle">×{{ task.repos.length }}</span>
              }
            </span>
            <span class="wf-row-r2 wf-mono">{{ shortBranch(task) }}</span>
          </div>

          <div class="wf-row-diff">
            <span class="wf-mono" style="color:var(--wf-text-dim)">—</span>
          </div>

          <div class="wf-row-cost wf-mono">{{ task.cost ? ('$' + task.cost.toFixed(3)) : '—' }}</div>

          <div class="wf-row-actions">
            @if (task.phase === 'awaiting_approval') {
              <button class="wf-row-mini is-go" aria-label="Approve plan" (click)="emitAction($event, task.gid, 'approve')">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="m5 12 5 5L20 7"/></svg>
              </button>
              <button class="wf-row-mini is-stop" aria-label="Reject" (click)="emitAction($event, task.gid, 'reject')">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18 6 6 18M6 6l12 12"/></svg>
              </button>
            }
            @if (isLive(task.phase)) {
              <button class="wf-row-mini is-stop" aria-label="Stop agent" (click)="emitAction($event, task.gid, 'stop')">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>
              </button>
            }
            @if (task.phase === 'queued' || task.phase === 'cancelled' || task.phase === 'error' || task.phase === 'done') {
              <button class="wf-row-mini is-go" aria-label="Start agent" [disabled]="startingGids().has(task.gid)" (click)="emitAction($event, task.gid, 'start')">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
              </button>
            }
            @if (task.phase === 'done') {
              <button class="wf-row-mini" aria-label="Open PR" (click)="emitAction($event, task.gid, 'open_pr')">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 17 17 7M17 7H8m9 0v9"/></svg>
              </button>
            }
            @if (task.phase === 'done' || task.phase === 'error' || task.phase === 'cancelled') {
              <button class="wf-row-mini" aria-label="Run QA" (click)="emitAction($event, task.gid, 'run_qa')">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
              </button>
            }
            <button class="wf-row-mini" aria-label="Open in IDE" (click)="emitAction($event, task.gid, 'ide')">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
            </button>
          </div>
        </div>
      }
    </div>
  `,
})
export class WfListComponent {
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

  tipoCls(tipo: string | null): string {
    const map: Record<string, string> = {
      Bug: 'wf-tag-tipo-bug',
      Feature: 'wf-tag-tipo-feature',
      Mejora: 'wf-tag-tipo-mejora',
      Performance: 'wf-tag-tipo-perf',
    };
    return tipo ? (map[tipo] ?? '') : '';
  }

  shortBranch(task: WfTask): string {
    if (task.branch === '—') return '—';
    return task.branch.replace(`feature/${task.gid}/`, '…/');
  }

  /** First repo id (compact). Full list is in the tooltip / ×N badge. */
  reposLabel(task: WfTask): string {
    return task.repos.length ? task.repos[0] : task.repo;
  }

  reposTitle(task: WfTask): string {
    return task.repos.length ? task.repos.join(', ') : task.repo;
  }

  emitAction(event: Event, gid: string, act: string): void {
    event.stopPropagation();
    this.action.emit({ gid, act });
  }

  onRowKey(event: KeyboardEvent, gid: string): void {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      this.selectedChange.emit(gid);
    }
  }
}
