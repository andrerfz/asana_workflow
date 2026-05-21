import {
  Component, ChangeDetectionStrategy, ViewEncapsulation,
  signal, inject, OnInit,
} from '@angular/core';
import { ApiService, Repo, AgentSettings, Guide } from '../../../core/services/api.service';
import { firstValueFrom } from 'rxjs';
import { WF_PHASES } from '../wf-task.model';

type SettingsTab = 'repos' | 'ide' | 'agent' | 'guides' | 'workflow' | 'mapping';

export interface IdeOption {
  id: string;
  label: string;
  sub: string;          // shown in settings radio
  cli?: string;         // binary for /api/ide/open
  cliArgs?: string[];
  app?: string;         // macOS app name for `open -a`
}

export const IDE_OPTIONS: IdeOption[] = [
  { id: 'phpstorm', label: 'PhpStorm', sub: 'JetBrains',  app: 'PhpStorm' },
  { id: 'vscode',   label: 'VS Code',  sub: 'cli: code',  cli: 'code',   cliArgs: ['-r'] },
  { id: 'cursor',   label: 'Cursor',   sub: 'cli: cursor', cli: 'cursor', cliArgs: ['-r'] },
  { id: 'webstorm', label: 'WebStorm', sub: 'JetBrains',  app: 'WebStorm' },
  { id: 'idea',     label: 'IntelliJ', sub: 'JetBrains',  app: 'IntelliJ IDEA' },
  { id: 'custom',   label: 'Custom',   sub: 'set CLI path below' },
];

export function getIdeConfig(id: string, customPath: string): { cli?: string; cliArgs?: string[]; app?: string } {
  if (id === 'custom') return { cli: customPath };
  const opt = IDE_OPTIONS.find(o => o.id === id);
  if (!opt) return { cli: 'code', cliArgs: ['-r'] };
  return { cli: opt.cli, cliArgs: opt.cliArgs, app: opt.app };
}

@Component({
  selector: 'app-wf-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `
<div class="wf-settings">

  <!-- Left nav -->
  <aside class="wf-settings-side">
    <div class="wf-side-h">Settings</div>
    <nav class="wf-side-nav">
      @for (item of tabs; track item.id) {
        <button class="wf-ws" [class.is-on]="tab() === item.id" (click)="tab.set(item.id)">
          <span></span>
          <span style="display:flex;flex-direction:column">
            <span style="font-weight:500">{{ item.label }}</span>
            <span style="font-size:10px;color:var(--wf-text-mute);margin-top:1px">{{ item.sub }}</span>
          </span>
        </button>
      }
    </nav>
  </aside>

  <!-- Content -->
  <div class="wf-settings-body">

    <!-- ── REPOS ── -->
    @if (tab() === 'repos') {
      <div class="wf-page-head">
        <div>
          <h2 class="wf-page-title">Repositories</h2>
          <div class="wf-page-sub">One worktree per task. Branch: feature/&#123;task_gid&#125;/&#123;slug&#125;.</div>
        </div>
        <button class="wf-btn wf-btn-primary" (click)="showAdd.set(!showAdd())">+ Add repo</button>
      </div>

      @if (showAdd()) {
        <div class="wf-form-card" style="margin-bottom:16px">
          <div class="wf-field">
            <div class="wf-field-l"><div class="wf-field-lbl">ID *</div></div>
            <div class="wf-field-c"><input class="wf-input wf-mono" [value]="newRepo().id" (input)="patchNew('id', $any($event.target).value)" placeholder="back-clientes"/></div>
          </div>
          <div class="wf-field">
            <div class="wf-field-l"><div class="wf-field-lbl">Path *</div></div>
            <div class="wf-field-c"><input class="wf-input wf-mono" [value]="newRepo().path" (input)="patchNew('path', $any($event.target).value)" placeholder="/Users/you/Projects/repo"/></div>
          </div>
          <div class="wf-field">
            <div class="wf-field-l"><div class="wf-field-lbl">Test command</div></div>
            <div class="wf-field-c"><input class="wf-input wf-mono" [value]="newRepo().test_cmd || ''" (input)="patchNew('test_cmd', $any($event.target).value)" placeholder="make agent-test"/></div>
          </div>
          <div class="wf-field">
            <div class="wf-field-l"><div class="wf-field-lbl">Fast test command</div></div>
            <div class="wf-field-c"><input class="wf-input wf-mono" [value]="newRepo().test_worktree_cmd_fast || ''" (input)="patchNew('test_worktree_cmd_fast', $any($event.target).value)" placeholder="make agent-test-no-migrations"/></div>
          </div>
          <div style="display:flex;gap:8px;padding:12px 16px;border-top:1px solid var(--wf-border)">
            <button class="wf-btn" (click)="showAdd.set(false)">Cancel</button>
            <button class="wf-btn wf-btn-primary" [disabled]="!newRepo().id || !newRepo().path || saving()" (click)="saveNewRepo()">
              {{ saving() ? 'Saving…' : 'Save' }}
            </button>
          </div>
        </div>
      }

      @if (loadingRepos()) {
        <div class="wf-empty" style="padding:40px">Loading…</div>
      } @else {
        <div class="wf-repo-list">
          @for (repo of repos(); track repo.id) {
            <div class="wf-repo-card">
              @if (editingId() !== repo.id) {
                <div class="wf-repo-card-head">
                  <div style="display:flex;align-items:center;gap:10px">
                    <span class="wf-repo-icon">
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 22V8a2 2 0 0 1 2-2h13l5 5v11a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2z"/><polyline points="17 6 17 11 22 11"/></svg>
                    </span>
                    <div>
                      <div style="font-weight:600;font-size:14px">{{ repo.id }}</div>
                      <div class="wf-mono" style="font-size:11px;color:var(--wf-text-mute)">{{ repo.path }}</div>
                    </div>
                  </div>
                  <div style="display:flex;gap:6px">
                    <button class="wf-btn wf-btn-icon" title="Edit" (click)="startEdit(repo)">
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                    </button>
                    <button class="wf-btn wf-btn-icon" title="Delete" (click)="deleteRepo(repo.id)" style="color:var(--wf-red)">
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
                    </button>
                  </div>
                </div>
                <div class="wf-repo-grid">
                  <div class="wf-kv-row"><div class="wf-kv-k">Default branch</div><div class="wf-kv-v wf-mono">{{ repo.default_branch || 'master' }}</div></div>
                  <div class="wf-kv-row"><div class="wf-kv-k">Test command</div><div class="wf-kv-v wf-mono" style="font-size:11px">{{ repo.test_worktree_cmd || repo.test_cmd || '—' }}</div></div>
                  <div class="wf-kv-row"><div class="wf-kv-k">Fast test</div><div class="wf-kv-v wf-mono" style="font-size:11px">{{ repo.test_worktree_cmd_fast || '—' }}</div></div>
                  <div class="wf-kv-row"><div class="wf-kv-k">Lint</div><div class="wf-kv-v wf-mono" style="font-size:11px">{{ repo.lint_cmd || '—' }}</div></div>
                </div>
              } @else {
                <div class="wf-repo-card-head"><div style="font-weight:600">Edit {{ repo.id }}</div></div>
                <div class="wf-field"><div class="wf-field-l"><div class="wf-field-lbl">Test command</div></div>
                  <div class="wf-field-c"><input class="wf-input wf-mono" [value]="editDraft().test_worktree_cmd || ''" (input)="patchEdit('test_worktree_cmd', $any($event.target).value)"/></div>
                </div>
                <div class="wf-field"><div class="wf-field-l"><div class="wf-field-lbl">Fast test command</div></div>
                  <div class="wf-field-c"><input class="wf-input wf-mono" [value]="editDraft().test_worktree_cmd_fast || ''" (input)="patchEdit('test_worktree_cmd_fast', $any($event.target).value)"/></div>
                </div>
                <div class="wf-field"><div class="wf-field-l"><div class="wf-field-lbl">Lint command</div></div>
                  <div class="wf-field-c"><input class="wf-input wf-mono" [value]="editDraft().lint_cmd || ''" (input)="patchEdit('lint_cmd', $any($event.target).value)"/></div>
                </div>
                <div style="display:flex;gap:8px;padding:12px 16px;border-top:1px solid var(--wf-border)">
                  <button class="wf-btn" (click)="editingId.set(null)">Cancel</button>
                  <button class="wf-btn wf-btn-primary" [disabled]="saving()" (click)="saveEdit()">{{ saving() ? 'Saving…' : 'Save' }}</button>
                </div>
              }
            </div>
          }
        </div>
      }
    }

    <!-- ── IDE ── -->
    @if (tab() === 'ide') {
      <div class="wf-page-head">
        <div>
          <h2 class="wf-page-title">IDE</h2>
          <div class="wf-page-sub">"Open in IDE" buttons launch your editor at the worktree path.</div>
        </div>
      </div>
      <div class="wf-form-card">
        <div class="wf-field">
          <div class="wf-field-l"><div class="wf-field-lbl">Preferred IDE</div></div>
          <div class="wf-field-c">
            <div class="wf-radiogrid">
              @for (i of ideOptions; track i.id) {
                <button class="wf-radio" [class.is-on]="selectedIde() === i.id" (click)="selectIde(i.id)">
                  <span class="wf-radio-dot"></span>
                  <span style="flex:1">{{ i.label }}</span>
                  <span class="wf-mono" style="font-size:10px;color:var(--wf-text-mute)">{{ i.sub }}</span>
                </button>
              }
            </div>
          </div>
        </div>
        <div class="wf-field">
          <div class="wf-field-l">
            <div class="wf-field-lbl">Custom CLI path</div>
            <div class="wf-field-sub">Override for non-standard installs.</div>
          </div>
          <div class="wf-field-c">
            <input class="wf-input wf-mono" placeholder="e.g. /usr/local/bin/my-ide"
              [value]="customIdePath()"
              (input)="customIdePath.set($any($event.target).value); saveIde()"/>
          </div>
        </div>
      </div>
    }

    <!-- ── AGENT ── -->
    @if (tab() === 'agent') {
      <div class="wf-page-head">
        <div>
          <h2 class="wf-page-title">Agent</h2>
          <div class="wf-page-sub">Asana section transitions and run timeout.</div>
        </div>
        <button class="wf-btn wf-btn-primary" [disabled]="saving()" (click)="saveAgentSettings()">
          {{ saving() ? 'Saving…' : 'Save' }}
        </button>
      </div>
      @if (loadingAgent()) {
        <div class="wf-empty" style="padding:40px">Loading…</div>
      } @else {
        <div class="wf-form-card">
          <div class="wf-field">
            <div class="wf-field-l">
              <div class="wf-field-lbl">Move task to section on start</div>
              <div class="wf-field-sub">Task moves here when the agent begins working.</div>
            </div>
            <div class="wf-field-c">
              <input class="wf-input" [value]="agentSettings().section_on_start || ''"
                (input)="patchAgent('section_on_start', $any($event.target).value)"/>
            </div>
          </div>
          <div class="wf-field">
            <div class="wf-field-l">
              <div class="wf-field-lbl">Move task to section on done</div>
              <div class="wf-field-sub">Task moves here when the agent ships a PR.</div>
            </div>
            <div class="wf-field-c">
              <input class="wf-input" [value]="agentSettings().section_on_done || ''"
                (input)="patchAgent('section_on_done', $any($event.target).value)"/>
            </div>
          </div>
          <div class="wf-field">
            <div class="wf-field-l">
              <div class="wf-field-lbl">Move task to section on error</div>
              <div class="wf-field-sub">Task moves here on failure.</div>
            </div>
            <div class="wf-field-c">
              <input class="wf-input" [value]="agentSettings().section_on_error || ''"
                (input)="patchAgent('section_on_error', $any($event.target).value)"/>
            </div>
          </div>
          <div class="wf-field">
            <div class="wf-field-l">
              <div class="wf-field-lbl">Run timeout</div>
              <div class="wf-field-sub">Agent stops and pauses after this many minutes per phase.</div>
            </div>
            <div class="wf-field-c">
              <div class="wf-stepper">
                <button (click)="stepTimeout(-5)">−</button>
                <span class="wf-mono">{{ agentSettings().agent_timeout_minutes }} min</span>
                <button (click)="stepTimeout(5)">+</button>
              </div>
            </div>
          </div>
          <div class="wf-field">
            <div class="wf-field-l">
              <div class="wf-field-lbl">Asana poll interval</div>
              <div class="wf-field-sub">How often to fetch task updates from Asana. Takes effect on next poll cycle — no restart needed.</div>
            </div>
            <div class="wf-field-c">
              <div class="wf-stepper">
                <button (click)="stepPollInterval(-1)">−</button>
                <span class="wf-mono">{{ agentSettings().poll_interval_minutes }} min</span>
                <button (click)="stepPollInterval(1)">+</button>
              </div>
            </div>
          </div>
        </div>
      }
    }

    <!-- ── GUIDES ── -->
    @if (tab() === 'guides') {
      <div class="wf-page-head">
        <div>
          <h2 class="wf-page-title">Guides</h2>
          <div class="wf-page-sub">CLAUDE.md files loaded during the Investigation phase.</div>
        </div>
      </div>
      @if (loadingGuides()) {
        <div class="wf-empty" style="padding:40px">Loading…</div>
      } @else {
        @for (guide of guides(); track guide.id) {
          <div class="wf-form-card" style="margin-bottom:12px">
            <div style="padding:12px 16px;border-bottom:1px solid var(--wf-border);display:flex;align-items:center;justify-content:space-between">
              <div>
                <span style="font-weight:600;font-size:13px">{{ guide.label }}</span>
                <span class="wf-tag" style="margin-left:8px;font-size:10px">{{ guide.type }}</span>
              </div>
              <button class="wf-btn wf-btn-primary" style="font-size:12px" [disabled]="savingGuide() === guide.id" (click)="saveGuide(guide)">
                {{ savingGuide() === guide.id ? 'Saving…' : 'Save' }}
              </button>
            </div>
            <textarea class="wf-input wf-mono"
              style="width:100%;min-height:220px;border:none;border-radius:0;resize:vertical;font-size:11px;line-height:1.6;padding:12px 16px"
              [value]="guide.content || ''"
              (input)="updateGuide(guide.id, $any($event.target).value)">
            </textarea>
          </div>
        }
      }
    }

    <!-- ── WORKFLOW ── -->
    @if (tab() === 'workflow') {
      <div class="wf-page-head">
        <div>
          <h2 class="wf-page-title">Workflow</h2>
          <div class="wf-page-sub">Pipeline phases. ✋ marks human approval gates.</div>
        </div>
      </div>
      <div class="wf-flow-graph">
        @for (ph of phases; track ph.id; let i = $index) {
          <div class="wf-flow-node">
            <div class="wf-flow-node-dot" [style.background]="ph.color"></div>
            <div>
              <div style="font-size:13px;font-weight:600">{{ ph.label }}</div>
              <div style="font-size:11px;color:var(--wf-text-mute)">{{ phaseDesc(ph.id) }}</div>
            </div>
          </div>
          @if (i < phases.length - 1) {
            <div class="wf-flow-arrow">↓</div>
          }
        }
      </div>
    }

    <!-- ── MAPPING ── -->
    @if (tab() === 'mapping') {
      <div class="wf-page-head">
        <div>
          <h2 class="wf-page-title">Area mapping</h2>
          <div class="wf-page-sub">Maps Asana task areas to repositories for automatic repo selection.</div>
        </div>
      </div>
      @if (loadingMapping()) {
        <div class="wf-empty" style="padding:40px">Loading…</div>
      } @else {
        @for (entry of areaMap(); track entry.area) {
          <div class="wf-form-card" style="margin-bottom:12px">
            <div style="padding:12px 16px;border-bottom:1px solid var(--wf-border);display:flex;justify-content:space-between;align-items:center">
              <span style="font-weight:600;font-size:13px;font-family:monospace">{{ entry.area }}</span>
              <button class="wf-btn wf-btn-primary" style="font-size:12px"
                [disabled]="savingArea() === entry.area"
                (click)="saveMapping(entry.area, entry.repoIds)">
                {{ savingArea() === entry.area ? 'Saving…' : 'Save' }}
              </button>
            </div>
            <div style="padding:12px 16px;display:flex;flex-wrap:wrap;gap:8px">
              @for (repo of repos(); track repo.id) {
                <button class="wf-chip"
                  [class.is-on]="entry.repoIds.includes(repo.id)"
                  (click)="toggleAreaRepo(entry.area, repo.id)">
                  {{ repo.id }}
                </button>
              }
            </div>
          </div>
        }
      }
    }

  </div>
</div>
  `,
})
export class WfSettingsComponent implements OnInit {
  private api = inject(ApiService);

  tab = signal<SettingsTab>('repos');

  // Repos
  repos = signal<Repo[]>([]);
  loadingRepos = signal(false);
  showAdd = signal(false);
  newRepo = signal<Partial<Repo>>({ id: '', path: '', test_cmd: '', test_worktree_cmd_fast: '' });
  editingId = signal<string | null>(null);
  editDraft = signal<Partial<Repo>>({});
  saving = signal(false);

  // IDE
  ideOptions = IDE_OPTIONS;
  selectedIde = signal(localStorage.getItem('wf-ide') ?? 'vscode');
  customIdePath = signal(localStorage.getItem('wf-ide-path') ?? '');

  // Agent
  agentSettings = signal<AgentSettings>({ section_on_start: '', section_on_done: '', section_on_error: '', agent_timeout_minutes: 45, poll_interval_minutes: 5 });
  loadingAgent = signal(false);

  // Guides
  guides = signal<Guide[]>([]);
  loadingGuides = signal(false);
  savingGuide = signal<string | null>(null);

  // Mapping
  areaMap = signal<{ area: string; repoIds: string[] }[]>([]);
  loadingMapping = signal(false);
  savingArea = signal<string | null>(null);

  // Workflow
  phases = WF_PHASES.filter(p => p.id !== 'queued');

  tabs: { id: SettingsTab; label: string; sub: string }[] = [
    { id: 'repos',    label: 'Repositories', sub: '' },
    { id: 'ide',      label: 'IDE',          sub: localStorage.getItem('wf-ide') ?? 'vscode' },
    { id: 'agent',    label: 'Agent',        sub: 'sections · timeout' },
    { id: 'guides',   label: 'Guides',       sub: 'CLAUDE.md files' },
    { id: 'mapping',  label: 'Area mapping', sub: 'area → repos' },
    { id: 'workflow', label: 'Workflow',      sub: '8 phases' },
  ];

  async ngOnInit(): Promise<void> {
    this.loadingRepos.set(true);
    this.loadingAgent.set(true);
    this.loadingGuides.set(true);
    this.loadingMapping.set(true);
    await Promise.all([
      firstValueFrom(this.api.getRepos()).then(r => this.repos.set(r ?? [])).catch(() => {}),
      firstValueFrom(this.api.getAgentSettings()).then(s => this.agentSettings.set(s)).catch(() => {}),
      firstValueFrom(this.api.getGuides()).then(g => this.guides.set(g ?? [])).catch(() => {}),
      firstValueFrom(this.api.getAreaMapping()).then(m => {
        this.areaMap.set(Object.entries(m ?? {}).map(([area, repoIds]) => ({ area, repoIds })));
      }).catch(() => {}),
    ]);
    this.loadingRepos.set(false);
    this.loadingAgent.set(false);
    this.loadingGuides.set(false);
    this.loadingMapping.set(false);
  }

  // ── Repos ──
  patchNew(field: string, value: string): void { this.newRepo.update(r => ({ ...r, [field]: value })); }

  async saveNewRepo(): Promise<void> {
    const r = this.newRepo();
    if (!r.id || !r.path) return;
    this.saving.set(true);
    try {
      const saved = await firstValueFrom(this.api.saveRepo(r as Repo));
      this.repos.update(list => [...list, saved]);
      this.newRepo.set({ id: '', path: '', test_cmd: '', test_worktree_cmd_fast: '' });
      this.showAdd.set(false);
    } catch (e) { console.error(e); }
    finally { this.saving.set(false); }
  }

  startEdit(repo: Repo): void { this.editingId.set(repo.id); this.editDraft.set({ ...repo }); }
  patchEdit(field: string, value: string): void { this.editDraft.update(r => ({ ...r, [field]: value })); }

  async saveEdit(): Promise<void> {
    const draft = this.editDraft();
    if (!draft.id) return;
    this.saving.set(true);
    try {
      const saved = await firstValueFrom(this.api.saveRepo(draft as Repo));
      this.repos.update(list => list.map(r => r.id === saved.id ? saved : r));
      this.editingId.set(null);
    } catch (e) { console.error(e); }
    finally { this.saving.set(false); }
  }

  async deleteRepo(id: string): Promise<void> {
    try {
      await firstValueFrom(this.api.deleteRepo(id));
      this.repos.update(list => list.filter(r => r.id !== id));
    } catch (e) { console.error(e); }
  }

  // ── IDE ──
  selectIde(id: string): void {
    this.selectedIde.set(id);
    localStorage.setItem('wf-ide', id);
    this.tabs[1].sub = id;
  }

  saveIde(): void { localStorage.setItem('wf-ide-path', this.customIdePath()); }

  // ── Agent ──
  patchAgent(field: string, value: string | number): void {
    this.agentSettings.update(s => ({ ...s, [field]: value }));
  }

  stepTimeout(delta: number): void {
    this.agentSettings.update(s => ({
      ...s,
      agent_timeout_minutes: Math.max(5, (s.agent_timeout_minutes ?? 45) + delta),
    }));
  }

  stepPollInterval(delta: number): void {
    this.agentSettings.update(s => ({
      ...s,
      poll_interval_minutes: Math.max(1, Math.min(60, (s.poll_interval_minutes ?? 5) + delta)),
    }));
  }

  async saveAgentSettings(): Promise<void> {
    this.saving.set(true);
    try { await firstValueFrom(this.api.updateAgentSettings(this.agentSettings())); }
    catch (e) { console.error(e); }
    finally { this.saving.set(false); }
  }

  // ── Guides ──
  updateGuide(id: string, content: string): void {
    this.guides.update(list => list.map(g => g.id === id ? { ...g, content } : g));
  }

  async saveGuide(guide: Guide): Promise<void> {
    this.savingGuide.set(guide.id);
    try { await firstValueFrom(this.api.saveGuide(guide.id, guide.content)); }
    catch (e) { console.error(e); }
    finally { this.savingGuide.set(null); }
  }

  // ── Mapping ──
  toggleAreaRepo(area: string, repoId: string): void {
    this.areaMap.update(list => list.map(e => {
      if (e.area !== area) return e;
      const ids = e.repoIds.includes(repoId)
        ? e.repoIds.filter(id => id !== repoId)
        : [...e.repoIds, repoId];
      return { ...e, repoIds: ids };
    }));
  }

  async saveMapping(area: string, repoIds: string[]): Promise<void> {
    this.savingArea.set(area);
    try { await firstValueFrom(this.api.saveAreaMapping(area, repoIds)); }
    catch (e) { console.error(e); }
    finally { this.savingArea.set(null); }
  }

  // ── Workflow ──
  phaseDesc(id: string): string {
    const map: Record<string, string> = {
      investigating:     'Reads codebase, produces findings',
      planning:          'Drafts implementation plan',
      awaiting_approval: '✋ human gate — approval required',
      coding:            'Implements plan in worktree',
      testing:           'Runs tests, fix-loop ×3',
      qa_review:         'Self-review · auto-approves on PASS',
      done:              'Push branch + Asana comment',
    };
    return map[id] ?? '';
  }
}
