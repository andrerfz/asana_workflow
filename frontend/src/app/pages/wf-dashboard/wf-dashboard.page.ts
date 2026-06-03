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
import { HttpClient } from '@angular/common/http';
import { WfSettingsComponent, getIdeConfig } from './wf-settings/wf-settings.component';
import { WfHistoryComponent } from './wf-history/wf-history.component';

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
    WfHistoryComponent,
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
              [startingGids]="startingGids()"
              (selectedChange)="selected.set($event)"
              (action)="onAction($event)"
            />
          } @else {
            <app-wf-cards
              [tasks]="filteredTasks()"
              [selected]="selected()"
              [startingGids]="startingGids()"
              (selectedChange)="selected.set($event)"
              (action)="onAction($event)"
            />
          }
        </main>
        <app-wf-drawer
          [task]="selectedTask()"
          [isStarting]="startingGids().has(selected() ?? '')"
          (action)="onDrawerAction($event)"
        />
      }

      <!-- ── HISTORY ── -->
      @if (mode() === 'history') {
        <main class="wf-main wf-full-col">
          <app-wf-history/>
        </main>
      }

      <!-- ── SETTINGS ── (inline, no page navigation) -->
      @if (mode() === 'settings') {
        <main class="wf-main wf-full-col">
          <app-wf-settings/>
        </main>
      }

      <!-- ── BRANCH SELECTION OVERLAY ── -->
      @if (branchModal()) {
        <div class="wf-branch-overlay" (click)="branchCancel()">
          <div class="wf-branch-panel" (click)="$event.stopPropagation()">
            <div class="wf-branch-head">
              <span>Start Agent</span>
              <button class="wf-btn wf-btn-icon" (click)="branchCancel()">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg>
              </button>
            </div>

            @if (branchModal()!.slug) {
              <div class="wf-branch-section">
                <div class="wf-branch-section-lbl">Suggested branch</div>
                <button class="wf-branch-slug-btn" (click)="branchPickFresh()">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M6 9v6M6 18a9 9 0 0 0 9-9v3"/></svg>
                  <code>{{ branchModal()!.slug }}</code>
                  <span class="wf-branch-slug-hint">click to use</span>
                </button>
              </div>
            }

            @if (branchModal()!.suggestions.length > 0) {
              <div class="wf-branch-section">
                <div class="wf-branch-section-lbl">Continue on existing branch</div>
                @for (s of branchModal()!.suggestions; track s.branch) {
                  <button class="wf-branch-item" (click)="branchPickExisting(s.branch)">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M6 9v6M6 18a9 9 0 0 0 9-9v3"/></svg>
                    <div>
                      <div class="wf-mono" style="font-size:12px">{{ s.branch.replace('feature/' + branchModal()!.gid + '/', '…/') }}</div>
                      <div style="font-size:11px;color:var(--wf-text-mute)">{{ s.author }}</div>
                    </div>
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-left:auto;flex-shrink:0"><path d="m9 18 6-6-6-6"/></svg>
                  </button>
                }
              </div>
            }

            <div class="wf-branch-section">
              <button class="wf-btn" style="width:100%" (click)="branchPickFresh()">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>
                Fresh branch
              </button>
            </div>
          </div>
        </div>
      }

      <!-- ── REVISE OVERLAY ── -->
      @if (reviseOverlay()) {
        <div class="wf-branch-overlay" (click)="reviseClose()">
          <div class="wf-branch-panel" (click)="$event.stopPropagation()">
            <div class="wf-branch-head">
              <span>Revise plan</span>
              <button class="wf-btn wf-btn-icon" (click)="reviseClose()">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg>
              </button>
            </div>
            <div class="wf-branch-section">
              <div class="wf-branch-section-lbl">Describe what needs to change in the plan</div>
              <textarea
                #reviseInput
                class="wf-guide-textarea"
                placeholder="e.g. The plan should also update the tests. Don't touch the Provider model."
                rows="4"
                (input)="reviseMessage.set($any($event.target).value)"
                (keydown.meta.enter)="reviseSendFrom(reviseInput)">
              </textarea>
              <div style="display:flex;gap:8px;margin-top:8px">
                <button class="wf-btn" style="flex:1" [disabled]="reviseSending()" (click)="reviseClose()">Cancel</button>
                <button class="wf-btn wf-btn-warn" style="flex:2"
                  [disabled]="reviseSending()"
                  (click)="reviseSendFrom(reviseInput)">
                  {{ reviseSending() ? 'Sending…' : 'Request revision ⌘↵' }}
                </button>
              </div>
            </div>
          </div>
        </div>
      }

      <!-- ── IDE REPO SELECTOR ── -->
      @if (ideRepoOverlay()) {
        <div class="wf-branch-overlay" (click)="ideRepoOverlay.set(null)">
          <div class="wf-branch-panel" (click)="$event.stopPropagation()">
            <div class="wf-branch-head">
              <span>Open in IDE</span>
              <button class="wf-btn wf-btn-icon" (click)="ideRepoOverlay.set(null)">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg>
              </button>
            </div>
            <div class="wf-branch-section">
              <div class="wf-branch-section-lbl">Select repository</div>
              @for (repo of ideRepoOverlay()!.repos; track repo.id) {
                <button class="wf-branch-slug-btn" (click)="openIdeRepo(repo.path)">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                  <span>{{ repo.id }}</span>
                  <code style="font-size:10px;opacity:0.6;margin-left:auto">{{ repo.branch }}</code>
                </button>
              }
            </div>
          </div>
        </div>
      }

      <!-- ── GUIDE OVERLAY ── -->
      @if (guideOverlay()) {
        <div class="wf-branch-overlay" (click)="guideClose()">
          <div class="wf-branch-panel" (click)="$event.stopPropagation()">
            <div class="wf-branch-head">
              <span>Guide agent</span>
              <button class="wf-btn wf-btn-icon" (click)="guideClose()">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg>
              </button>
            </div>
            <div class="wf-branch-section">
              <div class="wf-branch-section-lbl">Send a steering message to the running agent</div>
              <textarea
                #guideInput
                class="wf-guide-textarea"
                placeholder="e.g. Focus on the test failure in InvoiceTest.php, ignore the other errors for now"
                rows="4"
                (input)="guideMessage.set($any($event.target).value)"
                (keydown.meta.enter)="guideSendFrom(guideInput)">
              </textarea>
              <div style="display:flex;gap:8px;margin-top:8px">
                <button class="wf-btn" style="flex:1" [disabled]="guideSending()" (click)="guideClose()">Cancel</button>
                <button class="wf-btn wf-btn-primary" style="flex:2"
                  [disabled]="guideSending()"
                  (click)="guideSendFrom(guideInput)">
                  {{ guideSending() ? 'Sending…' : 'Send ⌘↵' }}
                </button>
              </div>
            </div>
          </div>
        </div>
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
  private http = inject(HttpClient);

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

  // Per-task start loading state
  startingGids = signal<Set<string>>(new Set());

  // Inline branch selection overlay
  branchModal = signal<{ gid: string; slug: string; suggestions: { branch: string; author: string }[] } | null>(null);
  private _branchResolve: ((base: string | null | 'cancel') => void) | null = null;

  // IDE repo selector (shown when task has multiple repos)
  ideRepoOverlay = signal<{ gid: string; repos: { id: string; path: string; branch: string }[] } | null>(null);

  // Inline guide overlay
  guideOverlay = signal<{ gid: string } | null>(null);
  guideMessage = signal('');
  guideSending = signal(false);

  // Inline revise overlay
  reviseOverlay = signal<{ gid: string } | null>(null);
  reviseMessage = signal('');
  reviseSending = signal(false);


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

  guideClose(): void {
    this.guideOverlay.set(null);
    this.guideMessage.set('');
  }

  async guideSendFrom(input: HTMLTextAreaElement): Promise<void> {
    const msg = input.value.trim();
    const gid = this.guideOverlay()?.gid;
    if (!msg || !gid || this.guideSending()) return;
    this.guideSending.set(true);
    input.disabled = true;
    try {
      await this.stateService.sendGuideMessage(gid, msg);
      this.flash('Guide message sent to agent');
      this.guideClose();
    } catch (e: any) {
      console.error('[Guide] send failed', e);
      this.flash(e?.error?.detail || e?.message || 'Failed to send message', 'var(--wf-red)');
      input.disabled = false;
    } finally {
      this.guideSending.set(false);
    }
  }

  reviseClose(): void {
    this.reviseOverlay.set(null);
    this.reviseMessage.set('');
  }

  async reviseSendFrom(input: HTMLTextAreaElement): Promise<void> {
    const msg = input.value.trim();
    const gid = this.reviseOverlay()?.gid;
    if (!msg || !gid || this.reviseSending()) return;
    this.reviseSending.set(true);
    input.disabled = true;
    try {
      await this.stateService.answerQuestion(gid, `revise:${msg}`);
      this.flash('Revision feedback sent — agent will adjust the plan');
      this.reviseClose();
    } catch (e: any) {
      console.error('[Revise] send failed', e);
      this.flash(e?.error?.detail || e?.message || 'Failed to send revision', 'var(--wf-red)');
      input.disabled = false;
    } finally {
      this.reviseSending.set(false);
    }
  }

  private _showBranchModal(gid: string, slug: string, suggestions: { branch: string; author: string }[]): Promise<string | null | 'cancel'> {
    return new Promise(resolve => {
      this._branchResolve = resolve;
      this.branchModal.set({ gid, slug, suggestions });
    });
  }

  branchPickFresh(): void {
    this._branchResolve?.(null);
    this._branchResolve = null;
    this.branchModal.set(null);
  }

  branchPickExisting(branch: string): void {
    this._branchResolve?.(branch);
    this._branchResolve = null;
    this.branchModal.set(null);
  }

  branchCancel(): void {
    this._branchResolve?.('cancel');
    this._branchResolve = null;
    this.branchModal.set(null);
  }

  onModeChange(mode: string): void {
    this.mode.set(mode);
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
      case 'qa_approve':
        this.stateService.answerQuestion(gid, 'Approve');
        this.flash('QA approved — shipping');
        break;
      case 'rerun': {
        const rerunTask = this.allWfTasks().find(t => t.gid === gid);
        this.stateService.startAgent(gid, rerunTask?.branch_slug || undefined)
          .then(() => this.flash('Re-run started'))
          .catch((e: any) => this.flash(e?.error?.detail || e?.message || 'Failed to start agent', 'var(--wf-red)'));
        break;
      }
      case 'reject':
        this.stateService.answerQuestion(gid, 'Reject');
        this.flash('Plan rejected', 'var(--wf-red)');
        break;
      case 'start':
        this._startWithBranch(gid);
        break;
      case 'stop':
        this.stateService.stopAgent(gid);
        this.flash('Agent stopped', 'var(--wf-amber)');
        break;
      case 'guide':
        this.guideMessage.set('');
        this.guideOverlay.set({ gid });
        break;
      case 'revise':
        this.reviseMessage.set('');
        this.reviseOverlay.set({ gid });
        break;
      case 'classify':
        this.flash('Classifying…');
        this.api.classifyTask(gid, true).subscribe({
          complete: () => { this.stateService.refreshTasks(); this.flash('Classification updated'); },
          error: () => this.flash('Classification failed', 'var(--wf-red)'),
        });
        break;
      case 'branch':
        this.api.getBranchName(gid).subscribe(r => {
          if (r?.branch) {
            navigator.clipboard.writeText(r.branch);
            this.flash(`Copied: ${r.branch}`);
          }
        });
        break;
      case 'asana':
        window.open(`https://app.asana.com/0/0/${gid}`, '_blank');
        break;
      case 'ide':
        this._openIde(gid);
        break;
      case 'open_pr': {
        const task = this.allWfTasks().find(t => t.gid === gid);
        const url = task?.mr_url;
        if (url) {
          window.open(url, '_blank');
        } else {
          this.flash('No MR link available yet', 'var(--wf-amber)');
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

  private async _openIde(gid: string): Promise<void> {
    const ideId = localStorage.getItem('wf-ide') ?? 'vscode';
    const ideCustomPath = localStorage.getItem('wf-ide-path') ?? '';

    // URL-scheme IDEs open directly from the browser — no server needed.
    // This bypasses Docker's missing `open` command entirely.
    const urlSchemes: Record<string, string> = {
      phpstorm: `phpstorm://open?file=`,
      webstorm: `webstorm://open?file=`,
      idea:     `idea://open?file=`,
      vscode:   `vscode://file/`,
      cursor:   `cursor://file/`,
    };

    // Multi-repo: show selector if more than one repo has a worktree
    const run = this.stateService.getRunForTask(gid);
    const allRepos = (run?.repos ?? []).filter(r => r.worktree_path);
    if (allRepos.length > 1) {
      this.ideRepoOverlay.set({
        gid,
        repos: allRepos.map(r => ({ id: r.id ?? '', path: r.worktree_path ?? '', branch: r.branch ?? '' })),
      });
      return;
    }

    // Find worktree path — check in-memory signal first, then API
    let path = run?.repos?.[0]?.worktree_path;

    if (!path) {
      // Signal may not be populated yet — check API directly
      try {
        const wts = await firstValueFrom(
          this.http.get<{ worktrees: { path: string; repo_id: string; branch: string }[] }>(`/api/worktrees/${gid}`)
        );
        // Only use the path if the worktree has a valid branch (not broken/empty)
        const validWt = wts?.worktrees?.find(w => w.branch && w.branch !== 'unknown');
        path = validWt?.path;
      } catch { /* no worktrees exist yet */ }
    }

    if (!path) {
      this.flash('No worktree — creating one…');
      try {
        // Get task to find repos
        const task = this.stateService.tasks().find((t: any) => t.task_gid === gid);
        if (!task) { this.flash('Task not found', 'var(--wf-red)'); return; }

        // Generate branch name
        const branchRes = await firstValueFrom(this.api.getBranchName(gid));
        const slug = branchRes?.branch?.split('/').pop() ?? gid.slice(-8);

        // Find first repo for this task (from area mapping or default)
        const reposRes = await firstValueFrom(this.api.getRepos());
        const repo = reposRes?.[0];
        if (!repo) { this.flash('No repos configured', 'var(--wf-red)'); return; }

        // Create worktree from latest master
        const wt = await firstValueFrom(
          this.http.post<{ path: string }>(`/api/worktrees/${gid}`, {
            repo_id: repo.id,
            branch_slug: slug,
          })
        );
        path = wt.path;
        this.flash(`Worktree created: ${slug}`);
      } catch (e: any) {
        this.flash(e?.error?.detail || 'Failed to create worktree', 'var(--wf-red)');
        return;
      }
    }

    // Open using URL scheme (works from browser on host regardless of Docker)
    const scheme = urlSchemes[ideId];
    if (scheme) {
      window.open(scheme + encodeURIComponent(path));
      this.flash(`Opening in ${ideId}…`);
      return;
    }

    // Custom IDE path fallback — try server-side open
    if (ideCustomPath) {
      this.api.openInIde(path, { cli: ideCustomPath }).subscribe({
        error: (e: any) => this.flash(e?.error?.detail || 'Failed to open IDE', 'var(--wf-red)'),
      });
      this.flash(`Opening in custom IDE…`);
    } else {
      this.flash(`No IDE configured — set one in Settings → IDE`, 'var(--wf-amber)');
    }
  }

  openIdeRepo(path: string): void {
    this.ideRepoOverlay.set(null);
    const ideId = localStorage.getItem('wf-ide') ?? 'vscode';
    const urlSchemes: Record<string, string> = {
      phpstorm: `phpstorm://open?file=`,
      webstorm: `webstorm://open?file=`,
      idea:     `idea://open?file=`,
      vscode:   `vscode://file/`,
      cursor:   `cursor://file/`,
    };
    const scheme = urlSchemes[ideId];
    if (scheme) {
      window.open(scheme + encodeURIComponent(path));
      this.flash(`Opening in ${ideId}…`);
    }
  }

  private async _startWithBranch(gid: string): Promise<void> {
    if (this.startingGids().has(gid)) return;
    this.startingGids.update(s => new Set([...s, gid]));
    try {
      const { slug, suggestions } = await this.stateService.startAgentWithBranch(gid);

      if (suggestions.length > 0 || slug) {
        const baseBranch = await this._showBranchModal(gid, slug, suggestions);
        if (baseBranch === 'cancel') return;
        await this.stateService.confirmStart(gid, slug, baseBranch);
      } else {
        // No slug and no suggestions — start with gid suffix as fallback slug
        await this.stateService.confirmStart(gid, gid.slice(-8), null);
      }

      this.flash('Agent started');
    } catch (e: any) {
      console.error('[Dashboard] startWithBranch failed', e);
      const detail = e?.error?.detail || e?.message || 'Failed to start agent';
      this.flash(detail, 'var(--wf-red)');
    } finally {
      this.startingGids.update(s => { const n = new Set(s); n.delete(gid); return n; });
    }
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
