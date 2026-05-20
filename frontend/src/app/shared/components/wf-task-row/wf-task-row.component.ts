/**
 * <wf-task-row> — standalone pattern reference
 *
 * HOW TO USE IN A MODULE-BASED PAGE:
 *   // In your page's NgModule imports array:
 *   imports: [..., WfTaskRowComponent]
 *
 * HOW TO USE IN ANOTHER STANDALONE COMPONENT:
 *   @Component({ imports: [..., WfTaskRowComponent] })
 *
 * TEMPLATE:
 *   <wf-task-row
 *     [task]="task"
 *     [run]="state.getRunForTask(task.task_gid)"
 *     (approve)="onApprove($event)"
 *     (reject)="onReject($event)"
 *     (run)="onRun($event)"
 *     (stop)="onStop($event)"
 *     (open)="onOpen($event)" />
 */
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  output,
} from '@angular/core';
import { IonicModule } from '@ionic/angular';

import { AgentRun, AgentPhase, PHASE_COLORS, PHASE_LABELS, Task } from '../../core/models/task.model';
import { AgentStateService } from '../../core/services/agent-state.service';

// ─── Re-exported so callers can import from one place ─────────────────────────
export type { Task, AgentRun };

@Component({
  selector: 'wf-task-row',
  standalone: true,
  imports: [IonicModule],
  templateUrl: './wf-task-row.component.html',
  styleUrl: './wf-task-row.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class WfTaskRowComponent {
  // ── Inputs (signal-based, readonly) ────────────────────────────────────────
  readonly task = input.required<Task>();
  readonly run  = input<AgentRun | undefined>(undefined);

  // ── Outputs ────────────────────────────────────────────────────────────────
  readonly approve = output<string>(); // emits task_gid
  readonly reject  = output<string>();
  readonly run$    = output<string>(); // $ suffix avoids collision with input() name
  readonly stop    = output<string>();
  readonly open    = output<string>();

  // ── Injected service (no constructor boilerplate needed) ───────────────────
  private state = inject(AgentStateService);

  // ── Derived state via computed() ───────────────────────────────────────────

  readonly phase = computed<AgentPhase | undefined>(() => this.run()?.phase);

  readonly isActive = computed(() => !!this.run()?.is_active);

  readonly needsApproval = computed(
    () => this.run()?.phase === 'awaiting_approval' && !this.run()?.question?.answer,
  );

  readonly phaseColor = computed(() => {
    const p = this.phase();
    return p ? PHASE_COLORS[p] : 'transparent';
  });

  readonly phaseLabel = computed(() => {
    const p = this.phase();
    return p ? PHASE_LABELS[p] : '';
  });

  readonly clusterColor = computed(() => this.task().cluster?.color ?? '#888');
  readonly clusterName  = computed(() => this.task().cluster?.name ?? null);

  readonly scopeLabel = computed(() => {
    const s = this.task().scope_score;
    return s ? (['', 'XS', 'S', 'M', 'L', 'XL'][s] ?? `S${s}`) : '';
  });

  readonly lastLog = computed(() => {
    const logs = this.run()?.logs;
    return logs?.length ? logs[logs.length - 1].message : '';
  });

  // ── Pulse animation flag (active phases) ──────────────────────────────────
  readonly isPulsing = computed(() =>
    ['investigating', 'planning', 'coding', 'testing', 'qa_review', 'init'].includes(
      this.phase() ?? '',
    ),
  );

  // ── Event handlers — emit gid upward, parent decides the action ───────────

  onApprove(e: Event): void {
    e.stopPropagation();
    this.approve.emit(this.task().task_gid);
  }

  onReject(e: Event): void {
    e.stopPropagation();
    this.reject.emit(this.task().task_gid);
  }

  onRun(e: Event): void {
    e.stopPropagation();
    this.run$.emit(this.task().task_gid);
  }

  onStop(e: Event): void {
    e.stopPropagation();
    this.stop.emit(this.task().task_gid);
  }

  onOpen(): void {
    this.open.emit(this.task().task_gid);
  }
}
