import { Component, OnInit, signal } from '@angular/core';
import { Router } from '@angular/router';
import { ApiService } from '../../core/services/api.service';
import { AgentStateService } from '../../core/services/agent-state.service';
import { firstValueFrom } from 'rxjs';

@Component({
  selector: 'app-history',
  templateUrl: './history.page.html',
  styleUrls: ['./history.page.scss'],
  standalone: false,
})
export class HistoryPage implements OnInit {
  readonly items = signal<Record<string, unknown>[]>([]);
  readonly loading = signal(false);
  readonly clearing = signal<string | null>(null);

  constructor(
    private api: ApiService,
    private state: AgentStateService,
    private router: Router,
  ) {}

  async ngOnInit(): Promise<void> {
    this.loading.set(true);
    try {
      const res = await firstValueFrom(this.api.getAgentHistory());
      this.items.set((res?.runs ?? []) as Record<string, unknown>[]);
    } catch (e) {
      console.error('[History] load failed', e);
    } finally {
      this.loading.set(false);
    }
  }

  openTask(gid: string): void {
    if (gid) this.router.navigate(['/task', gid]);
  }

  async clearItem(gid: string): Promise<void> {
    this.clearing.set(gid);
    try {
      await this.state.clearRun(gid);
      this.items.update(list => list.filter(i => (i['task_gid'] as string) !== gid));
    } catch (e) {
      console.error('[History] clearItem failed', e);
    } finally {
      this.clearing.set(null);
    }
  }

  getPhase(item: Record<string, unknown>): string {
    return (item['phase'] as string) ?? '';
  }

  trackByGid(_: number, item: Record<string, unknown>): string {
    return (item['task_gid'] as string) ?? String(_);
  }
}
