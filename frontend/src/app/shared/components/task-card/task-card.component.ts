import { Component, Input, Output, EventEmitter, computed, signal } from '@angular/core';
import { Task, AgentRun, CLUSTERS_META } from '../../../core/models/task.model';

@Component({
  selector: 'app-task-card',
  templateUrl: './task-card.component.html',
  styleUrls: ['./task-card.component.scss'],
  standalone: false,
})
export class TaskCardComponent {
  @Input() task!: Task;
  @Input() run: AgentRun | undefined;
  @Output() openDetail = new EventEmitter<string>();
  @Output() startAgent = new EventEmitter<string>();
  @Output() stopAgent = new EventEmitter<string>();

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

  onOpen() { this.openDetail.emit(this.task.task_gid); }
  onStart(e: Event) { e.stopPropagation(); this.startAgent.emit(this.task.task_gid); }
  onStop(e: Event) { e.stopPropagation(); this.stopAgent.emit(this.task.task_gid); }
}
