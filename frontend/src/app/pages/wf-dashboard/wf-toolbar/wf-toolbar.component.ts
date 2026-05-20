import { Component, ChangeDetectionStrategy, input, output, ViewEncapsulation, computed, signal } from '@angular/core';
import { WfTask } from '../wf-task.model';

@Component({
  selector: 'app-wf-toolbar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `
    <div class="wf-bar">
      <div class="wf-seg">
        <button class="wf-seg-b" [class.is-on]="view() === 'list'" (click)="viewChange.emit('list')">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg>
          List
        </button>
        <button class="wf-seg-b" [class.is-on]="view() === 'cards'" (click)="viewChange.emit('cards')">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
          Cards
        </button>
      </div>

      <div class="wf-chips">
        <button class="wf-chip" [class.is-on]="typeFilter() == null" (click)="typeFilterChange.emit(null)">
          All <span style="opacity:.5; margin-left:4px">{{ filteredCount() }}</span>
        </button>
        @for (type of typeOptions(); track type.k) {
          <button class="wf-chip" [class.is-on]="typeFilter() === type.k" (click)="typeFilterChange.emit(type.k)">
            {{ type.l }} <span style="opacity:.5; margin-left:4px">{{ type.n }}</span>
          </button>
        }
      </div>

      <div style="flex-shrink:0; display:flex; gap:6px; margin-left:auto; align-items:center;">
        @if (filtersActive()) {
          <button class="wf-clear-filters" (click)="resetFilters.emit()">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18 6 6 18M6 6l12 12"/></svg>
            Clear filters
          </button>
        }

        <!-- Cluster dropdown -->
        <div class="wf-dd" (clickOutside)="clusterOpen.set(false)">
          <button class="wf-chip" [class.is-on]="cluster() != null" (click)="clusterOpen.set(!clusterOpen())">
            @if (cluster() != null) {
              <span [style.display]="'inline-block'" [style.width.px]="6" [style.height.px]="6"
                    [style.border-radius]="'50%'" [style.background]="clusterColor()" [style.margin-right.px]="6"></span>
              {{ clusterName() }}
            } @else {
              Cluster
            }
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="margin-left:4px"><path d="m6 9 6 6 6-6"/></svg>
          </button>
          @if (clusterOpen()) {
            <div class="wf-dd-menu">
              <button class="wf-dd-item" (click)="clusterChange.emit(null); clusterOpen.set(false)">
                <span style="flex:1">Any cluster</span>
              </button>
              @for (opt of clusterOptions(); track opt.k) {
                <button class="wf-dd-item" [class.is-on]="cluster() === opt.k"
                        (click)="clusterChange.emit(opt.k); clusterOpen.set(false)">
                  <span [style.display]="'inline-block'" [style.width.px]="8" [style.height.px]="8"
                        [style.border-radius]="'50%'" [style.background]="opt.color"></span>
                  <span style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap">{{ opt.l }}</span>
                  <span class="wf-mono" style="color:var(--wf-text-mute); font-size:10px">{{ opt.n }}</span>
                </button>
              }
            </div>
          }
        </div>
      </div>
    </div>
  `,
})
export class WfToolbarComponent {
  view = input<string>('list');
  typeFilter = input<string | null>(null);
  cluster = input<string | null>(null);
  filteredCount = input<number>(0);
  tasks = input<WfTask[]>([]);
  filtersActive = input<boolean>(false);

  viewChange = output<string>();
  typeFilterChange = output<string | null>();
  clusterChange = output<string | null>();
  resetFilters = output<void>();

  clusterOpen = signal(false);

  typeOptions = computed(() => {
    const ts = this.tasks();
    return [
      { k: 'Bug',         l: 'Bug',     n: ts.filter(t => t.tipo === 'Bug').length },
      { k: 'Mejora',      l: 'Mejora',  n: ts.filter(t => t.tipo === 'Mejora').length },
      { k: 'Feature',     l: 'Feature', n: ts.filter(t => t.tipo === 'Feature').length },
      { k: 'Performance', l: 'Perf',    n: ts.filter(t => t.tipo === 'Performance').length },
    ];
  });

  clusterOptions = computed(() => {
    const countMap: Record<string, { name: string; color: string; count: number }> = {};
    for (const t of this.tasks()) {
      if (t.cluster) {
        const c = countMap[t.cluster.id] ?? { name: t.cluster.name, color: t.cluster.color, count: 0 };
        c.count++;
        countMap[t.cluster.id] = c;
      }
    }
    return Object.entries(countMap)
      .filter(([, v]) => v.count > 0)
      .map(([k, v]) => ({ k, l: v.name, color: v.color, n: v.count }));
  });

  clusterColor = computed(() => {
    const id = this.cluster();
    if (!id) return '';
    return this.clusterOptions().find(o => o.k === id)?.color ?? '';
  });

  clusterName = computed(() => {
    const id = this.cluster();
    if (!id) return '';
    return this.clusterOptions().find(o => o.k === id)?.l ?? id;
  });
}
