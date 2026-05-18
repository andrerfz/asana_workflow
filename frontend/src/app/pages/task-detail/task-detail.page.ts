import { Component, OnInit, computed, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { ToastController } from '@ionic/angular';
import { AgentStateService } from '../../core/services/agent-state.service';
import { ApiService } from '../../core/services/api.service';
import { Task, AgentRun, RepoEntry } from '../../core/models/task.model';
import { firstValueFrom } from 'rxjs';

type Segment = 'logs' | 'plan' | 'qa' | 'console' | 'diff';

@Component({
  selector: 'app-task-detail',
  templateUrl: './task-detail.page.html',
  styleUrls: ['./task-detail.page.scss'],
  standalone: false,
})
export class TaskDetailPage implements OnInit {
  taskGid = signal('');
  activeSegment = signal<Segment>('logs');
  guideMessage = signal('');
  sending = signal(false);
  reviseFeedback = signal('');
  revising = signal(false);
  runningQA = signal(false);
  runningTests = signal(false);
  diffMap = signal<Record<string, string>>({});
  loadingDiffs = signal<Record<string, boolean>>({});

  readonly task = computed<Task | undefined>(() =>
    this.state.tasks().find(t => t.task_gid === this.taskGid())
  );

  readonly run = computed<AgentRun | undefined>(() =>
    this.state.agentRuns()[this.taskGid()]
  );

  readonly needsAnswer = computed(() =>
    !!this.run()?.question && !this.run()?.question?.answer
  );

  constructor(
    private route: ActivatedRoute,
    public state: AgentStateService,
    private api: ApiService,
    private toastCtrl: ToastController,
  ) {}

  ngOnInit(): void {
    const gid = this.route.snapshot.paramMap.get('gid') ?? '';
    this.taskGid.set(gid);
    this.state.reloadRun(gid).catch(() => {});
  }

  setSegment(s: Segment): void {
    this.activeSegment.set(s);
  }

  async approve(): Promise<void> {
    await this.state.answerQuestion(this.taskGid(), 'Approve');
  }

  async reject(): Promise<void> {
    await this.state.answerQuestion(this.taskGid(), 'Reject');
  }

  async resume(feedback?: string): Promise<void> {
    await this.state.resumeAgent(this.taskGid(), feedback);
  }

  async sendGuide(): Promise<void> {
    const msg = this.guideMessage().trim();
    if (!msg) return;
    this.sending.set(true);
    try {
      await this.state.sendGuideMessage(this.taskGid(), msg);
      this.guideMessage.set('');
    } finally {
      this.sending.set(false);
    }
  }

  async revisePlan(): Promise<void> {
    const feedback = this.reviseFeedback().trim();
    if (!feedback) return;
    this.revising.set(true);
    try {
      await this.state.revisePlan(this.taskGid(), feedback);
      this.reviseFeedback.set('');
    } catch (e) {
      console.error('[TaskDetail] revisePlan failed', e);
    } finally {
      this.revising.set(false);
    }
  }

  async runQA(): Promise<void> {
    this.runningQA.set(true);
    try {
      await this.state.runManualQA(this.taskGid());
      await this.showToast('QA triggered successfully', 'success');
    } catch (e) {
      console.error('[TaskDetail] runQA failed', e);
    } finally {
      this.runningQA.set(false);
    }
  }

  async runTests(): Promise<void> {
    this.runningTests.set(true);
    try {
      const result = await this.state.runManualTest(this.taskGid());
      const color = result.all_passed ? 'success' : 'danger';
      const msg = result.all_passed ? 'All tests passed!' : 'Some tests failed';
      await this.showToast(msg, color);
    } catch (e) {
      console.error('[TaskDetail] runTests failed', e);
    } finally {
      this.runningTests.set(false);
    }
  }

  async loadDiff(repoId: string): Promise<void> {
    this.loadingDiffs.update(m => ({ ...m, [repoId]: true }));
    try {
      const res = await firstValueFrom(this.api.getDiff(this.taskGid(), repoId));
      this.diffMap.update(m => ({ ...m, [repoId]: res?.diff ?? '' }));
    } catch (e) {
      console.error('[TaskDetail] loadDiff failed', e);
      this.diffMap.update(m => ({ ...m, [repoId]: 'Error loading diff' }));
    } finally {
      this.loadingDiffs.update(m => ({ ...m, [repoId]: false }));
    }
  }

  getDiffLines(diff: string): Array<{ text: string; type: 'add' | 'remove' | 'meta' | 'normal' }> {
    return diff.split('\n').map(line => {
      if (line.startsWith('+')) return { text: line, type: 'add' };
      if (line.startsWith('-')) return { text: line, type: 'remove' };
      if (line.startsWith('@@') || line.startsWith('diff ') || line.startsWith('index ')) return { text: line, type: 'meta' };
      return { text: line, type: 'normal' };
    });
  }

  async start(): Promise<void> { await this.state.startAgent(this.taskGid()); }
  async stop(): Promise<void>  { await this.state.stopAgent(this.taskGid()); }

  onGuideInput(e: CustomEvent): void { this.guideMessage.set(e.detail.value ?? ''); }
  onReviseInput(e: CustomEvent): void { this.reviseFeedback.set(e.detail.value ?? ''); }

  trackByTs(_: number, entry: { timestamp: string }): string { return entry.timestamp; }
  trackByRepo(_: number, repo: RepoEntry): string { return repo.id; }

  private async showToast(message: string, color: string): Promise<void> {
    const toast = await this.toastCtrl.create({ message, color, duration: 2500, position: 'bottom' });
    await toast.present();
  }
}
