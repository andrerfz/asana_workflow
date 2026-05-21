import { Component, OnInit, signal } from '@angular/core';
import { ApiService, Repo, AgentSettings, Guide, CliStatus } from '../../core/services/api.service';
import { firstValueFrom } from 'rxjs';

type TabId = 'repos' | 'ide' | 'mapping' | 'agent' | 'guides' | 'workflow';

interface AreaEntry {
  area: string;
  repoIds: string[];
}

const IDE_OPTIONS = [
  { label: 'PhpStorm', value: 'phpstorm' },
  { label: 'VS Code', value: 'vscode' },
  { label: 'Cursor', value: 'cursor' },
  { label: 'WebStorm', value: 'webstorm' },
  { label: 'IntelliJ', value: 'intellij' },
];

@Component({
  selector: 'app-settings',
  templateUrl: './settings.page.html',
  styleUrls: ['./settings.page.scss'],
  standalone: false,
})
export class SettingsPage implements OnInit {
  readonly activeTab = signal<TabId>('repos');
  // Per-tab loading flags — each tab shows its own spinner
  readonly loadingRepos = signal(false);
  readonly loadingMapping = signal(false);
  readonly loadingAgent = signal(false);
  readonly loadingGuides = signal(false);
  readonly loadingWorkflow = signal(false);

  // Repos tab
  readonly repos = signal<Repo[]>([]);
  readonly projectsDir = signal('');
  readonly scannedRepos = signal<Repo[]>([]);
  readonly scanLoading = signal(false);
  readonly showAddForm = signal(false);
  readonly newRepo = signal<Partial<Repo>>({ id: '', path: '', test_cmd: '', lint_cmd: '' });
  readonly editingRepo = signal<Partial<Repo> | null>(null);
  readonly savingRepo = signal<string | null>(null);

  // IDE tab
  readonly selectedIde = signal(localStorage.getItem('ide_selection') ?? 'vscode');
  readonly customIdePath = signal(localStorage.getItem('ide_custom_path') ?? '');
  readonly ideOptions = IDE_OPTIONS;

  // Mapping tab
  readonly areaMap = signal<AreaEntry[]>([]);
  readonly savingArea = signal<string | null>(null);

  // Agent tab
  readonly settings = signal<AgentSettings>({ section_on_start: '', section_on_done: '', section_on_error: '', agent_timeout_minutes: 45, poll_interval_minutes: 5 });
  readonly cliStatus = signal<CliStatus | null>(null);
  readonly savingSettings = signal(false);

  // Guides tab
  readonly guides = signal<Guide[]>([]);
  readonly savingGuide = signal<string | null>(null);

  // Workflow tab
  readonly workflow = signal<unknown>(null);

  constructor(private api: ApiService) {}

  async ngOnInit(): Promise<void> {
    // Fire all fetches in parallel — each tab manages its own loading flag
    this._loadRepos();
    this._loadMapping();
    this._loadAgent();
    this._loadGuides();
    this._loadWorkflow();
  }

  private async _loadRepos(): Promise<void> {
    this.loadingRepos.set(true);
    try {
      const [repos, config] = await Promise.all([
        firstValueFrom(this.api.getRepos()),
        firstValueFrom(this.api.getRepoConfig()),
      ]);
      this.repos.set(repos ?? []);
      this.projectsDir.set(config?.projects_dir ?? '');
    } catch (e) { console.error('[Settings] loadRepos failed', e); }
    finally { this.loadingRepos.set(false); }
  }

  private async _loadMapping(): Promise<void> {
    this.loadingMapping.set(true);
    try { await this.loadMapping(); }
    catch (e) { console.error('[Settings] loadMapping failed', e); }
    finally { this.loadingMapping.set(false); }
  }

  private async _loadAgent(): Promise<void> {
    this.loadingAgent.set(true);
    try {
      const [settings, cli] = await Promise.all([
        firstValueFrom(this.api.getAgentSettings()),
        firstValueFrom(this.api.getCliStatus()),
      ]);
      this.settings.set(settings);
      this.cliStatus.set(cli);
    } catch (e) { console.error('[Settings] loadAgent failed', e); }
    finally { this.loadingAgent.set(false); }
  }

  private async _loadGuides(): Promise<void> {
    this.loadingGuides.set(true);
    try { await this.loadGuides(); }
    catch (e) { console.error('[Settings] loadGuides failed', e); }
    finally { this.loadingGuides.set(false); }
  }

  private async _loadWorkflow(): Promise<void> {
    this.loadingWorkflow.set(true);
    try { await this.loadWorkflow(); }
    catch (e) { console.error('[Settings] loadWorkflow failed', e); }
    finally { this.loadingWorkflow.set(false); }
  }

  setTab(tab: TabId): void { this.activeTab.set(tab); }

  // ---- Repos ----
  async scanRepos(): Promise<void> {
    this.scanLoading.set(true);
    try {
      const repos = await firstValueFrom(this.api.scanRepos());
      this.scannedRepos.set(repos ?? []);
    } catch (e) {
      console.error('[Settings] scanRepos failed', e);
    } finally {
      this.scanLoading.set(false);
    }
  }

  toggleAddForm(): void {
    this.showAddForm.update(v => !v);
    this.newRepo.set({ id: '', path: '', test_cmd: '', lint_cmd: '' });
  }

  onNewRepoField(field: keyof Repo, value: string): void {
    this.newRepo.update(r => ({ ...r, [field]: value }));
  }

  async saveNewRepo(): Promise<void> {
    const repo = this.newRepo();
    if (!repo.id || !repo.path) return;
    this.savingRepo.set('new');
    try {
      const saved = await firstValueFrom(this.api.saveRepo(repo as Repo));
      this.repos.update(r => [...r, saved]);
      this.showAddForm.set(false);
    } catch (e) {
      console.error('[Settings] saveNewRepo failed', e);
    } finally {
      this.savingRepo.set(null);
    }
  }

  startEdit(repo: Repo): void {
    this.editingRepo.set({ ...repo });
  }

  onEditRepoField(field: keyof Repo, value: string): void {
    this.editingRepo.update(r => r ? { ...r, [field]: value } : r);
  }

  async saveEditRepo(): Promise<void> {
    const repo = this.editingRepo();
    if (!repo?.id) return;
    this.savingRepo.set(repo.id);
    try {
      const saved = await firstValueFrom(this.api.saveRepo(repo as Repo));
      this.repos.update(list => list.map(r => r.id === saved.id ? saved : r));
      this.editingRepo.set(null);
    } catch (e) {
      console.error('[Settings] saveEditRepo failed', e);
    } finally {
      this.savingRepo.set(null);
    }
  }

  async deleteRepo(id: string): Promise<void> {
    try {
      await firstValueFrom(this.api.deleteRepo(id));
      this.repos.update(list => list.filter(r => r.id !== id));
    } catch (e) {
      console.error('[Settings] deleteRepo failed', e);
    }
  }

  // ---- IDE ----
  selectIde(value: string): void {
    this.selectedIde.set(value);
    localStorage.setItem('ide_selection', value);
  }

  onCustomPath(e: CustomEvent): void {
    const val = e.detail.value ?? '';
    this.customIdePath.set(val);
    localStorage.setItem('ide_custom_path', val);
  }

  // ---- Mapping ----
  async loadMapping(): Promise<void> {
    try {
      const map = await firstValueFrom(this.api.getAreaMapping());
      this.areaMap.set(
        Object.entries(map ?? {}).map(([area, repoIds]) => ({ area, repoIds }))
      );
    } catch (e) {
      console.error('[Settings] loadMapping failed', e);
    }
  }

  onAreaRepoChange(area: string, e: CustomEvent): void {
    const ids = e.detail.value as string[];
    this.areaMap.update(list =>
      list.map(entry => entry.area === area ? { ...entry, repoIds: ids } : entry)
    );
  }

  async saveAreaMapping(area: string, repoIds: string[]): Promise<void> {
    this.savingArea.set(area);
    try {
      await firstValueFrom(this.api.saveAreaMapping(area, repoIds));
    } catch (e) {
      console.error('[Settings] saveAreaMapping failed', e);
    } finally {
      this.savingArea.set(null);
    }
  }

  // ---- Agent ----
  async loadCliStatus(): Promise<void> {
    try {
      const status = await firstValueFrom(this.api.getCliStatus());
      this.cliStatus.set(status);
    } catch (e) {
      console.error('[Settings] loadCliStatus failed', e);
    }
  }

  onSettingsField(field: keyof AgentSettings, e: CustomEvent): void {
    const val = field === 'agent_timeout_minutes' ? +e.detail.value : (e.detail.value ?? '');
    this.settings.update(s => ({ ...s, [field]: val }));
  }

  async saveSettings(): Promise<void> {
    this.savingSettings.set(true);
    try {
      await firstValueFrom(this.api.updateAgentSettings(this.settings()));
    } catch (e) {
      console.error('[Settings] saveSettings failed', e);
    } finally {
      this.savingSettings.set(false);
    }
  }

  // ---- Guides ----
  async loadGuides(): Promise<void> {
    try {
      const guides = await firstValueFrom(this.api.getGuides());
      this.guides.set(guides ?? []);
    } catch (e) {
      console.error('[Settings] loadGuides failed', e);
    }
  }

  onGuideContent(id: string, e: CustomEvent): void {
    const val = e.detail.value ?? '';
    this.guides.update(list => list.map(g => g.id === id ? { ...g, content: val } : g));
  }

  async saveGuide(guide: Guide): Promise<void> {
    this.savingGuide.set(guide.id);
    try {
      await firstValueFrom(this.api.saveGuide(guide.id, guide.content));
    } catch (e) {
      console.error('[Settings] saveGuide failed', e);
    } finally {
      this.savingGuide.set(null);
    }
  }

  // ---- Workflow ----
  async loadWorkflow(): Promise<void> {
    try {
      const wf = await firstValueFrom(this.api.getAgentWorkflow());
      this.workflow.set(wf);
    } catch (e) {
      console.error('[Settings] loadWorkflow failed', e);
    }
  }

  workflowJson(): string {
    const wf = this.workflow();
    return wf ? JSON.stringify(wf, null, 2) : '';
  }

  trackById(_: number, item: { id: string }): string { return item.id; }
  trackByArea(_: number, entry: AreaEntry): string { return entry.area; }
  trackByIdx(i: number): number { return i; }
}
