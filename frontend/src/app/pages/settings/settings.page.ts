import { Component, OnInit, signal } from '@angular/core';
import { ApiService, Repo, AgentSettings } from '../../core/services/api.service';
import { firstValueFrom } from 'rxjs';

@Component({
  selector: 'app-settings',
  templateUrl: './settings.page.html',
  styleUrls: ['./settings.page.scss'],
  standalone: false,
})
export class SettingsPage implements OnInit {
  readonly repos = signal<Repo[]>([]);
  readonly settings = signal<AgentSettings>({ max_concurrent_agents: 2, auto_approve_plan: false });
  readonly loading = signal(false);
  readonly activeTab = signal<'repos' | 'workflow'>('repos');

  constructor(private api: ApiService) {}

  async ngOnInit(): Promise<void> {
    this.loading.set(true);
    try {
      const [repos, settings] = await Promise.all([
        firstValueFrom(this.api.getRepos()),
        firstValueFrom(this.api.getAgentSettings()),
      ]);
      this.repos.set(repos ?? []);
      this.settings.set(settings);
    } finally {
      this.loading.set(false);
    }
  }

  setTab(tab: 'repos' | 'workflow'): void { this.activeTab.set(tab); }

  async saveSettings(): Promise<void> {
    await firstValueFrom(this.api.updateAgentSettings(this.settings()));
  }

  onMaxConcurrent(e: CustomEvent): void {
    this.settings.update(s => ({ ...s, max_concurrent_agents: +e.detail.value }));
  }

  onAutoApprove(e: CustomEvent): void {
    this.settings.update(s => ({ ...s, auto_approve_plan: !!e.detail.checked }));
  }
}
