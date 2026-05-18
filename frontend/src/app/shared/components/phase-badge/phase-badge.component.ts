import { Component, Input } from '@angular/core';
import { AgentPhase, PHASE_COLORS, PHASE_LABELS } from '../../../core/models/task.model';

@Component({
  selector: 'app-phase-badge',
  templateUrl: './phase-badge.component.html',
  styleUrls: ['./phase-badge.component.scss'],
  standalone: false,
})
export class PhaseBadgeComponent {
  @Input() phase!: AgentPhase;
  @Input() size: 'sm' | 'md' = 'md';

  get color(): string { return PHASE_COLORS[this.phase] ?? '#6b7280'; }
  get label(): string { return PHASE_LABELS[this.phase] ?? this.phase; }

  get isActive(): boolean {
    return ['investigating', 'planning', 'coding', 'testing', 'qa_review', 'init'].includes(this.phase);
  }
}
