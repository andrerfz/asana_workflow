import {
  Component,
  ChangeDetectionStrategy,
  ViewEncapsulation,
  signal,
  computed,
  inject,
  HostListener,
  OnInit,
} from '@angular/core';
import { Router } from '@angular/router';
import { DatePipe } from '@angular/common';
import { AgentStateService } from '../../core/services/agent-state.service';
import { ApiService } from '../../core/services/api.service';
import { toWfTask, WfTask, LIVE_PHASES, WF_PHASE_BY_ID } from './wf-task.model';
import { WfStats, WfHeaderComponent } from './wf-header/wf-header.component';
import { WfSidebarComponent } from './wf-sidebar/wf-sidebar.component';
import { WfStatsBarComponent } from './wf-stats-bar/wf-stats-bar.component';
import { WfToolbarComponent } from './wf-toolbar/wf-toolbar.component';
import { WfListComponent } from './wf-list/wf-list.component';
import { WfCardsComponent } from './wf-cards/wf-cards.component';
import { WfDrawerComponent } from './wf-drawer/wf-drawer.component';
import { WfAction } from './wf-list/wf-list.component';
import { firstValueFrom } from 'rxjs';
import { WfSettingsComponent, getIdeConfig } from './wf-settings/wf-settings.component';

@Component({
  selector: 'app-wf-dashboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  imports: [
    WfHeaderComponent,
    WfSidebarComponent,
    WfStatsBarComponent,
    WfToolbarComponent,
    WfListComponent,
    WfCardsComponent,
    WfDrawerComponent,
    WfSettingsComponent,
    DatePipe,
  ],
  template: `
    <div class="wf-root" [class.wf-theme-light]="darkMode()">

      <app-wf-header
        [stats]="stats()"
        [search]="search()"
        [mode]="mode()"
        [connected]="stateService.connected()"
        [darkMode]="darkMode()"
        (searchChange)="search.set($event)"
        (modeChange)="onModeChange($event)"
        (darkModeToggle)="toggleDarkMode()"
        (classify)="onClassify()"
        (sync)="onSync()"
      />

      <!-- ── TASKS ── -->
      @if (mode() === 'tasks') {
        <app-wf-sidebar
          [tasks]="allWfTasks()"
          [workspace]="workspace()"
          [section]="section()"
          [selected]="selected()"
          [stats]="stats()"
          (workspaceChange)="onWorkspaceChange($event)"
          (sectionChange)="section.set($event)"
          (selectedChange)="selected.set($event)"
        />
        <main class="wf-main">
          <app-wf-stats-bar
            [stats]="stats()"
            [statFilter]="statFilter()"
            (statFilterChange)="onStatFilterChange($event)"
          />
          <app-wf-toolbar
            [view]="view()"
            [typeFilter]="typeFilter()"
            [cluster]="cluster()"
            [filteredCount]="filteredTasks().length"
            [tasks]="allWfTasks()"
            [filtersActive]="filtersActive()"
            (viewChange)="view.set($event)"
            (typeFilterChange)="typeFilter.set($event)"
            (clusterChange)="cluster.set($event)"
            (resetFilters)="resetFilters()"
          />
          @if (view() === 'list') {
            <app-wf-list
              [tasks]="filteredTasks()"
              [selected]="selected()"
              (selectedChange)="selected.set($event)"
              (action)="onAction($event)"
            />
          } @else {
            <app-wf-cards
              [tasks]="filteredTasks()"
              [selected]="selected()"
              (selectedChange)="selected.set($event)"
              (action)="onAction($event)"
            />
          }
        </main>
        <app-wf-drawer
          [task]="selectedTask()"
          (action)="onDrawerAction($event)"
        />
      }

      <!-- ── HISTORY ── -->
      @if (mode() === 'history') {
        <main class="wf-main wf-full-col">
          @if (historyLoading()) {
            <div class="wf-empty" style="padding:40px">Loading history…</div>
          } @else {
            <div class="wf-cols-h">
              <div>Task</div><div>Phase</div><div>Cost</div><div>Started</div><div>Duration</div>
            </div>
            <div class="wf-list">
              @if (historyItems().length === 0) {
                <div class="wf-empty">No completed runs yet</div>
              }
              @for (run of historyItems(); track run['task_gid']) {
                <div class="wf-row" (click)="selected.set($any(run['task_gid'])); mode.set('tasks')">
                  <div class="wf-row-task">
                    <span class="wf-row-cdot" style="background:var(--wf-accent)"></span>
                    <div class="wf-row-task-main">
                      <div class="wf-row-title">{{ run['task_name'] || run['task_gid'] }}</div>
                    </div>
                  </div>
                  <div class="wf-row-phase">
                    <span class="wf-phase-dot" [style.background]="phaseColor(run['phase'])"></span>
                    <span class="wf-phase-l">{{ phaseLabel(run['phase']) }}</span>
                  </div>
                  <div class="wf-row-cost wf-mono">{{ run['cost_usd'] ? ('$' + (+run['cost_usd']).toFixed(3)) : '—' }}</div>
                  <div class="wf-row-repo wf-mono" style="font-size:11px">{{ run['started_at'] ? ($any(run['started_at']) | date:'short') : '—' }}</div>
                  <div class="wf-row-repo wf-mono" style="font-size:11px">{{ run['duration_seconds'] ? (run['duration_seconds'] + 's') : '—' }}</div>
                </div>
              }
            </div>
          }
        </main>
      }

      <!-- ── SETTINGS ── (inline, no page navigation) -->
      @if (mode() === 'settings') {
        <main class="wf-main wf-full-col">
          <app-wf-settings/>
        </main>
      }

      <!-- ── TOAST ── -->
      @if (toast()) {
        <div class="wf-toast">
          <span class="wf-toast-dot" [style.background]="toast()!.color"></span>
          {{ toast()!.text }}
        </div>
      }

    </div>
  `,
})
export class WfDashboardPage implements OnInit {
  protected stateService = inject(AgentStateService);
  private api = inject(ApiService);
  private router = inject(Router);

  // UI state signals
  mode = signal<string>('tasks');
  selected = signal<string | null>(null);
  workspace = signal<string>('inbox');
  section = signal<string | null>(null);
  cluster = signal<string | null>(null);
  typeFilter = signal<string | null>(null);
  statFilter = signal<string | null>(null);
  view = signal<string>('list');
  search = signal('');
  darkMode = signal(
    localStorage.getItem('wf-dark') !== null
      ? localStorage.getItem('wf-dark') === 'true'
      : window.matchMedia('(prefers-color-scheme: dark)').matches
  );

  // Toast
  toast = signal<{ text: string; color: string } | null>(null);
  private _toastTimer: ReturnType<typeof setTimeout> | null = null;

  // History
  historyItems = signal<Record<string, unknown>[]>([]);
  historyLoading = signal(false);

  // All tasks merged with run data
  allWfTasks = computed<WfTask[]>(() => {
    const tasks = this.stateService.tasks();
    const runs = this.stateService.agentRuns();
    return tasks.map(t => toWfTask(t, runs[t.task_gid]));
  });

  // Workspace filter
  private workspaceFilter = computed(() => {
    const ws = this.workspace();
    return (task: WfTask): boolean => {
      switch (ws) {
        case 'inbox':    return task.phase !== 'done';
        case 'awaiting': return task.phase === 'awaiting_approval';
        case 'flight':   return LIVE_PHASES.includes(task.phase);
        case 'queued':   return task.phase === 'queued';
        case 'shipped':  return task.phase === 'done';
        default: return true;
      }
    };
  });

  filteredTasks = computed<WfTask[]>(() => {
    const wsFilter = this.workspaceFilter();
    const q = this.search().toLowerCase();
    const sec = this.section();
    const clus = this.cluster();
    const tipo = this.typeFilter();
    const stat = this.statFilter();

    let list = this.allWfTasks().filter(wsFilter);

    if (q) {
      list = list.filter(t =>
        t.name.toLowerCase().includes(q) ||
        t.gid.includes(q) ||
        (t.branch !== '—' && t.branch.toLowerCase().includes(q)) ||
        (t.cluster?.name.toLowerCase().includes(q) ?? false)
      );
    }
    if (sec) list = list.filter(t => t.section === sec);
    if (clus) list = list.filter(t => t.cluster?.id === clus);
    if (tipo) list = list.filter(t => t.tipo === tipo);
    if (stat === 'awaiting') list = list.filter(t => t.phase === 'awaiting_approval');
    if (stat === 'flight')   list = list.filter(t => LIVE_PHASES.includes(t.phase));
    if (stat === 'shipped')  list = list.filter(t => t.phase === 'done');

    return list;
  });

  stats = computed<WfStats>(() => {
    const all = this.allWfTasks();
    return {
      total: all.length,
      awaiting: all.filter(t => t.phase === 'awaiting_approval').length,
      running: all.filter(t => LIVE_PHASES.includes(t.phase)).length,
      shipped: all.filter(t => t.phase === 'done').length,
      cost: all.reduce((sum, t) => sum + t.cost, 0),
    };
  });

  selectedTask = computed<WfTask | null>(() => {
    const id = this.selected();
    if (!id) return null;
    return this.allWfTasks().find(t => t.gid === id) ?? null;
  });

  filtersActive = computed(() =>
    this.workspace() !== 'inbox' ||
    !!this.section() ||
    !!this.cluster() ||
    !!this.typeFilter() ||
    !!this.statFilter() ||
    !!this.search()
  );

  ngOnInit(): void {
    // Apply persisted dark mode to Ionic palette too
    document.documentElement.classList.toggle('ion-palette-dark', this.darkMode());
  }

  flash(text: string, color = 'var(--wf-green)'): void {
    if (this._toastTimer) clearTimeout(this._toastTimer);
    this.toast.set({ text, color });
    this._toastTimer = setTimeout(() => this.toast.set(null), 2200);
  }

  phaseColor(phase: unknown): string {
    return WF_PHASE_BY_ID[phase as string]?.color ?? '#6b7280';
  }

  phaseLabel(phase: unknown): string {
    return WF_PHASE_BY_ID[phase as string]?.label ?? String(phase ?? '—');
  }

  async onModeChange(mode: string): Promise<void> {
    this.mode.set(mode);
    if (mode === 'history' && this.historyItems().length === 0) {
      this.historyLoading.set(true);
      try {
        const res = await firstValueFrom(this.api.getAgentHistory());
        this.historyItems.set((res?.runs ?? []) as Record<string, unknown>[]);
      } catch { /* ignore */ }
      finally { this.historyLoading.set(false); }
    }
  }

  onWorkspaceChange(ws: string): void {
    this.workspace.set(ws);
    this.statFilter.set(null);
  }

  onStatFilterChange(v: string | null): void {
    this.statFilter.set(v);
    if (v) this.workspace.set('inbox');
  }

  resetFilters(): void {
    this.workspace.set('inbox');
    this.section.set(null);
    this.cluster.set(null);
    this.typeFilter.set(null);
    this.statFilter.set(null);
    this.search.set('');
  }

  onAction(event: WfAction): void {
    this.handleAction(event.gid, event.act);
  }

  onDrawerAction(act: string): void {
    const id = this.selected();
    if (id) this.handleAction(id, act);
  }

  private handleAction(gid: string, act: string): void {
    switch (act) {
      case 'approve':
        this.stateService.answerQuestion(gid, 'Approve');
        this.flash('Plan approved — agent moving to coding');
        break;
      case 'reject':
        this.stateService.answerQuestion(gid, 'Reject');
        this.flash('Plan rejected', 'var(--wf-red)');
        break;
      case 'start':
        this.stateService.startAgent(gid);
        this.flash('Agent started');
        break;
      case 'stop':
        this.stateService.stopAgent(gid);
        this.flash('Agent stopped', 'var(--wf-amber)');
        break;
      case 'classify':
        this.api.classifyTask(gid).subscribe();
        this.flash('Classifying…');
        break;
      case 'branch':
        this.api.getBranchName(gid).subscribe(r => {
          if (r?.branch) {
            navigator.clipboard.writeText(r.branch);
            this.flash(`Copied: ${r.branch}`);
          }
        });
        break;
      case 'ide': {
        const run = this.stateService.getRunForTask(gid);
        const path = run?.repos?.[0]?.worktree_path;
        if (path) {
          const ideId = localStorage.getItem('wf-ide') ?? 'vscode';
          const idePath = localStorage.getItem('wf-ide-path') ?? '';
          const ideConfig = getIdeConfig(ideId, idePath);
          this.api.openInIde(path, ideConfig).subscribe();
          this.flash(`Opening in ${ideId}…`);
        }
        break;
      }
    }
  }

  toggleDarkMode(): void {
    const next = !this.darkMode();
    this.darkMode.set(next);
    localStorage.setItem('wf-dark', String(next));
    document.documentElement.classList.toggle('ion-palette-dark', next);
  }

  onClassify(): void {
    this.api.classifyAll().subscribe();
    this.flash('AI classification started…');
  }

  onSync(): void {
    this.stateService.refreshTasks();
    this.flash('Synced from Asana');
  }

  // Keyboard navigation: j/k or arrow down/up
  @HostListener('window:keydown', ['$event'])
  onKeyDown(event: KeyboardEvent): void {
    const target = event.target as HTMLElement;
    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return;

    const filtered = this.filteredTasks();
    const currentId = this.selected();
    const currentIdx = filtered.findIndex(t => t.gid === currentId);

    if (event.key === 'j' || event.key === 'ArrowDown') {
      event.preventDefault();
      const next = filtered[Math.min(filtered.length - 1, currentIdx + 1)];
      if (next) this.selected.set(next.gid);
    } else if (event.key === 'k' || event.key === 'ArrowUp') {
      event.preventDefault();
      const prev = filtered[Math.max(0, currentIdx - 1)];
      if (prev) this.selected.set(prev.gid);
    }
  }
}
