import { Component, OnInit, computed, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { AgentStateService } from '../../core/services/agent-state.service';
import { Task, AgentRun } from '../../core/models/task.model';

@Component({
  selector: 'app-task-detail',
  templateUrl: './task-detail.page.html',
  styleUrls: ['./task-detail.page.scss'],
  standalone: false,
})
export class TaskDetailPage implements OnInit {
  taskGid = signal('');
  activeSegment = signal<'logs' | 'plan' | 'qa' | 'console'>('logs');
  guideMessage = signal('');
  sending = signal(false);

  readonly task = computed<Task | undefined>(() =>
    this.state.tasks().find(t => t.task_gid === this.taskGid())
  );

  readonly run = computed<AgentRun | undefined>(() =>
    this.state.agentRuns()[this.taskGid()]
  );

  readonly needsAnswer = computed(() =>
    !!this.run()?.question && !this.run()?.question?.answer
  );

  constructor(private route: ActivatedRoute, public state: AgentStateService) {}

  ngOnInit(): void {
    const gid = this.route.snapshot.paramMap.get('gid') ?? '';
    this.taskGid.set(gid);
    this.state.reloadRun(gid).catch(() => {});
  }

  setSegment(s: 'logs' | 'plan' | 'qa' | 'console'): void {
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

  async start(): Promise<void> { await this.state.startAgent(this.taskGid()); }
  async stop(): Promise<void>  { await this.state.stopAgent(this.taskGid()); }

  onGuideInput(e: CustomEvent): void { this.guideMessage.set(e.detail.value ?? ''); }

  trackByTs(_: number, entry: { timestamp: string }): string { return entry.timestamp; }
}
