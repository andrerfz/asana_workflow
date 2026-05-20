import { Component, ChangeDetectionStrategy, input, output, ViewEncapsulation } from '@angular/core';

export interface WfStats {
  total: number;
  awaiting: number;
  running: number;
  shipped: number;
  cost: number;
}

@Component({
  selector: 'app-wf-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `
    <header class="wf-header">
      <div class="wf-h-brand">
        <div class="wf-h-mark">A</div>
        <div>
          <div class="wf-h-title">Asana Workflow</div>
          <div class="wf-h-sub">back-clientes · agent control</div>
        </div>
      </div>

      <div class="wf-view-switch">
        <button class="wf-vs-b" [class.is-on]="mode() === 'tasks'" (click)="modeChange.emit('tasks')">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
          Tasks
        </button>
        <button class="wf-vs-b" [class.is-on]="mode() === 'history'" (click)="modeChange.emit('history')">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><path d="M12 7v5l4 2"/></svg>
          History
        </button>
        <button class="wf-vs-b" [class.is-on]="mode() === 'settings'" (click)="modeChange.emit('settings')">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h0a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          Settings
        </button>
      </div>

      <div class="wf-h-status">
        <span class="wf-h-pulse" [class.wf-h-pulse-off]="!connected()"></span>
        <span>{{ stats().total }} tasks</span>
      </div>

      <div class="wf-h-search">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3-3"/></svg>
        <input
          [value]="search()"
          (input)="searchChange.emit($any($event.target).value)"
          placeholder="Search tasks, branches, clusters…"
        />
        <span class="wf-h-search-kbd">⌘K</span>
      </div>

      <div class="wf-h-actions">
        <button class="wf-btn wf-btn-icon" aria-label="Toggle theme" (click)="darkModeToggle.emit()">
          @if (darkMode()) {
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>
          } @else {
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
          }
        </button>
        <button class="wf-btn wf-btn-ai" (click)="classify.emit()">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3l1.9 5.8 5.8 1.9-5.8 1.9L12 18.4l-1.9-5.8-5.8-1.9 5.8-1.9L12 3z"/></svg>
          AI Classify
        </button>
        <button class="wf-btn wf-btn-go" (click)="sync.emit()">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5"/></svg>
          Sync
        </button>
      </div>
    </header>
  `,
})
export class WfHeaderComponent {
  stats = input.required<WfStats>();
  search = input<string>('');
  mode = input<string>('tasks');
  connected = input<boolean>(false);
  darkMode = input<boolean>(false);

  searchChange = output<string>();
  modeChange = output<string>();
  darkModeToggle = output<void>();
  classify = output<void>();
  sync = output<void>();
}
