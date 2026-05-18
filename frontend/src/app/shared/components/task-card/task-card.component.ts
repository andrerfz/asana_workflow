import { Component, Input, Output, EventEmitter, OnInit } from '@angular/core';
import { ModalController } from '@ionic/angular';
import { Task, AgentRun, CLUSTERS_META } from '../../../core/models/task.model';
import { AgentStateService } from '../../../core/services/agent-state.service';
import { ApiService, Repo } from '../../../core/services/api.service';
import { BranchModalComponent, BranchModalResult } from '../branch-modal/branch-modal.component';
import { ConsoleOverlayComponent } from '../console-overlay/console-overlay.component';
import { firstValueFrom } from 'rxjs';

@Component({
  selector: 'app-task-card',
  templateUrl: './task-card.component.html',
  styleUrls: ['./task-card.component.scss'],
  standalone: false,
})
export class TaskCardComponent implements OnInit {
  @Input() task!: Task;
  @Input() run: AgentRun | undefined;
  @Output() openDetail = new EventEmitter<string>();
  @Output() stopAgent = new EventEmitter<string>();

  availableRepos: Repo[] = [];
  selectedRepoIds: string[] = [];

  constructor(
    private modalCtrl: ModalController,
    private state: AgentStateService,
    private api: ApiService,
  ) {}

  ngOnInit(): void {
    this.api.getRepos().subscribe({
      next: (repos) => {
        this.availableRepos = repos ?? [];
      },
      error: (e) => console.error('[TaskCard] Failed to load repos', e),
    });
    // Pre-fill selected repos from overrides
    const overrides = this.state.taskRepoOverrides();
    this.selectedRepoIds = overrides[this.task.task_gid] ?? [];
  }

  get clusterMeta() {
    return this.task.cluster ? (CLUSTERS_META[this.task.cluster] ?? null) : null;
  }

  get clusterColor(): string {
    return this.clusterMeta?.color ?? 'var(--ion-color-medium)';
  }

  get isRunning(): boolean {
    return !!this.run?.is_active;
  }

  get hasRun(): boolean {
    return !!this.run;
  }

  get phase() {
    return this.run?.phase;
  }

  get needsAttention(): boolean {
    return this.run?.phase === 'awaiting_approval' || this.run?.phase === 'error';
  }

  get lastLog(): string {
    const logs = this.run?.logs;
    return logs?.length ? logs[logs.length - 1].message : '';
  }

  get scopeLabel(): string {
    const s = this.task.scope_score;
    if (!s) return '';
    const labels = ['', 'XS', 'S', 'M', 'L', 'XL'];
    return labels[s] ?? `S${s}`;
  }

  get isDoneOrError(): boolean {
    return this.run?.phase === 'done' || this.run?.phase === 'error';
  }

  onOpen() { this.openDetail.emit(this.task.task_gid); }
  onStop(e: Event) { e.stopPropagation(); this.stopAgent.emit(this.task.task_gid); }

  async onStart(e: Event): Promise<void> {
    e.stopPropagation();
    try {
      const { needsModal, slug, suggestions } = await this.state.startAgentWithBranch(this.task.task_gid);
      if (needsModal) {
        const modal = await this.modalCtrl.create({
          component: BranchModalComponent,
          componentProps: {
            taskGid: this.task.task_gid,
            branchSlug: slug,
            suggestions,
          },
          breakpoints: [0, 0.75, 1],
          initialBreakpoint: 0.75,
        });
        await modal.present();
        const { data } = await modal.onWillDismiss<BranchModalResult>();
        if (!data) return; // cancelled
        await this.state.confirmStart(this.task.task_gid, slug, data.baseBranch);
      } else {
        await this.state.confirmStart(this.task.task_gid, slug, null);
      }
    } catch (err) {
      console.error('[TaskCard] onStart failed', err);
    }
  }

  async onRerun(e: Event): Promise<void> {
    e.stopPropagation();
    try {
      await this.state.startAgent(this.task.task_gid);
    } catch (err) {
      console.error('[TaskCard] onRerun failed', err);
    }
  }

  async onApprove(e: Event): Promise<void> {
    e.stopPropagation();
    try {
      await this.state.answerQuestion(this.task.task_gid, 'Approve');
    } catch (err) {
      console.error('[TaskCard] onApprove failed', err);
    }
  }

  async onReject(e: Event): Promise<void> {
    e.stopPropagation();
    try {
      await this.state.answerQuestion(this.task.task_gid, 'Reject');
    } catch (err) {
      console.error('[TaskCard] onReject failed', err);
    }
  }

  async onOpenConsole(e: Event): Promise<void> {
    e.stopPropagation();
    const modal = await this.modalCtrl.create({
      component: ConsoleOverlayComponent,
      componentProps: { taskGid: this.task.task_gid },
      breakpoints: [0, 0.5, 0.85],
      initialBreakpoint: 0.85,
      handle: true,
    });
    await modal.present();
  }

  onRepoChange(e: CustomEvent): void {
    const ids = e.detail.value as string[];
    this.selectedRepoIds = ids;
    this.state.updateTaskRepos(this.task.task_gid, ids).catch(err =>
      console.error('[TaskCard] onRepoChange failed', err)
    );
  }
}
