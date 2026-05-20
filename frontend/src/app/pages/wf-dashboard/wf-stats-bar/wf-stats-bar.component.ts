import { Component, ChangeDetectionStrategy, input, output, ViewEncapsulation } from '@angular/core';
import { WfStats } from '../wf-header/wf-header.component';

@Component({
  selector: 'app-wf-stats-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `
    <div class="wf-stats">
      <button class="wf-stat" [class.is-on]="statFilter() === 'awaiting'"
              (click)="statFilterChange.emit(statFilter() === 'awaiting' ? null : 'awaiting')">
        <div class="wf-stat-l">Awaiting you</div>
        <div class="wf-stat-row">
          <span class="wf-stat-n" [style.color]="stats().awaiting > 0 ? 'var(--wf-amber)' : 'var(--wf-text-mute)'">{{ stats().awaiting }}</span>
          <span class="wf-stat-trend">{{ stats().awaiting > 0 ? 'review' : 'clear' }}</span>
        </div>
      </button>
      <button class="wf-stat" [class.is-on]="statFilter() === 'flight'"
              (click)="statFilterChange.emit(statFilter() === 'flight' ? null : 'flight')">
        <div class="wf-stat-l">In flight</div>
        <div class="wf-stat-row">
          <span class="wf-stat-n" [style.color]="stats().running > 0 ? 'var(--wf-accent)' : 'var(--wf-text-mute)'">{{ stats().running }}</span>
          <span class="wf-stat-trend">agents</span>
        </div>
      </button>
      <button class="wf-stat" [class.is-on]="statFilter() === 'shipped'"
              (click)="statFilterChange.emit(statFilter() === 'shipped' ? null : 'shipped')">
        <div class="wf-stat-l">Shipped today</div>
        <div class="wf-stat-row">
          <span class="wf-stat-n" [style.color]="stats().shipped > 0 ? 'var(--wf-green)' : 'var(--wf-text-mute)'">{{ stats().shipped }}</span>
          <span class="wf-stat-trend">↑</span>
        </div>
      </button>
    </div>
  `,
})
export class WfStatsBarComponent {
  stats = input.required<WfStats>();
  statFilter = input<string | null>(null);

  statFilterChange = output<string | null>();
}
