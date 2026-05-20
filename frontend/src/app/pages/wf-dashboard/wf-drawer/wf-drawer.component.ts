import { Component, ChangeDetectionStrategy, input, output, ViewEncapsulation, computed } from '@angular/core';
import { WfTask, WF_PHASES, WF_PHASE_BY_ID, LIVE_PHASES } from '../wf-task.model';

@Component({
  selector: 'app-wf-drawer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `
    <aside class="wf-drawer">
      @if (!task()) {
        <div class="wf-d-head">
          <div class="wf-d-tag-row">
            <div style="color:var(--wf-text-mute); font-size:12px">No task selected</div>
          </div>
        </div>
      } @else {
        <div class="wf-d-head">
          <div class="wf-d-tag-row">
            @if (task()!.cluster) {
              <span class="wf-d-tag" [style.background]="task()!.cluster!.color + '22'" [style.color]="task()!.cluster!.color">
                <span class="wf-d-tag-dot" [style.background]="task()!.cluster!.color"></span>
                {{ task()!.cluster!.name }}
              </span>
            }
            <div class="wf-d-actions">
              <button class="wf-d-ibtn" aria-label="Open in IDE" (click)="action.emit('ide')">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
              </button>
              <button class="wf-d-ibtn" aria-label="Generate branch name" (click)="action.emit('branch')">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M6 9v6M6 18a9 9 0 0 0 9-9v3"/></svg>
              </button>
              <button class="wf-d-ibtn" aria-label="Open in Asana" (click)="action.emit('asana')">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 17 17 7M17 7H8m9 0v9"/></svg>
              </button>
              <button class="wf-d-ibtn" aria-label="Classify" (click)="action.emit('classify')">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3l1.9 5.8 5.8 1.9-5.8 1.9L12 18.4l-1.9-5.8-5.8-1.9 5.8-1.9L12 3z"/></svg>
              </button>
            </div>
          </div>
          <h3 class="wf-d-title">{{ task()!.name }}</h3>
          <div class="wf-d-meta">
            <span class="wf-mono">#{{ task()!.gid }}</span>
            <span class="wf-row-sep">·</span>
            <span>{{ task()!.tipo || '—' }}</span>
            <span class="wf-row-sep">·</span>
            <span>P{{ task()!.priority }} · S{{ task()!.scope }}</span>
            <span class="wf-row-sep">·</span>
            <span>{{ task()!.section }}</span>
          </div>
        </div>

        <div class="wf-d-body">
          @if (task()!.notes) {
            <div class="wf-d-card" style="margin-top:12px">
              <div class="wf-d-card-h">Notes from Asana</div>
              <p>{{ task()!.notes }}</p>
            </div>
          }

          <div class="wf-d-card-h" style="margin-top:14px; padding-left:0">Workflow</div>
          <div class="wf-trail">
            @for (ph of phases; track ph.id; let i = $index) {
              @if (ph.id !== 'queued') {
                <div class="wf-trail-row"
                     [class.is-cur]="task()!.phase === ph.id"
                     [class.is-done]="phaseIndex(ph.id) < currentPhaseIndex()"
                     [style.--wf-cur-color]="task()!.phase === ph.id ? ph.color : ''"
                     [style.--wf-cur-color-soft]="task()!.phase === ph.id ? 'rgba(91,140,255,.25)' : ''">
                  <div class="wf-trail-rail">
                    <div class="wf-trail-dot"
                         [style.background]="phaseIndex(ph.id) < currentPhaseIndex() ? ph.color : ''"
                         [style.border-color]="phaseIndex(ph.id) < currentPhaseIndex() ? ph.color : ''"></div>
                  </div>
                  <div>
                    <div class="wf-trail-lbl">
                      <span [style.color]="task()!.phase === ph.id ? ph.color : ''">{{ ph.label }}</span>
                    </div>

                    @if (task()!.phase === ph.id) {
                      <div class="wf-trail-detail">
                        @if (ph.id === 'awaiting_approval' && task()!.plan) {
                          <div class="wf-d-card is-warn">
                            <div class="wf-d-card-h" style="color:var(--wf-amber)">Plan · awaiting approval</div>
                            <p>{{ task()!.plan }}</p>
                          </div>
                          <div class="wf-d-acts">
                            <button class="wf-btn wf-btn-warn" (click)="action.emit('approve')">Approve · proceed to coding</button>
                            <button class="wf-btn" (click)="action.emit('revise')">Revise…</button>
                            <button class="wf-btn wf-btn-danger" (click)="action.emit('reject')">Reject</button>
                          </div>
                        }

                        @if (isLive(ph.id) && task()!.log.length > 0) {
                          @if (task()!.progress > 0) {
                            <div style="height:4px; background:var(--wf-bg); border-radius:2px; overflow:hidden; margin-bottom:8px">
                              <div [style.height.%]="100" [style.width.%]="task()!.progress * 100" [style.background]="ph.color" style="transition:width .3s"></div>
                            </div>
                          }
                          <div class="wf-d-log">
                            @for (row of task()!.log.slice(-5); track $index) {
                              <div class="wf-d-log-row">
                                <span class="wf-d-log-t">{{ row[0] }}</span>
                                <span class="wf-d-log-lvl" [class]="row[1].toLowerCase()">{{ row[1] }}</span>
                                <span class="wf-d-log-m">{{ row[2] }}</span>
                              </div>
                            }
                            <div class="wf-d-log-row">
                              <span class="wf-d-log-t">▌</span>
                              <span class="wf-d-log-lvl info">···</span>
                              <span class="wf-d-log-m" style="color:var(--wf-text-mute)"><span class="wf-d-log-caret">▎</span> awaiting next token</span>
                            </div>
                          </div>
                          <div class="wf-d-acts">
                            <button class="wf-btn" (click)="action.emit('guide')">Guide…</button>
                            <button class="wf-btn wf-btn-danger" (click)="action.emit('stop')">Stop agent</button>
                          </div>
                        }

                        @if (ph.id === 'qa_review' && task()!.qa_report) {
                          <div class="wf-d-card is-ok">
                            <div class="wf-d-card-h" style="color:var(--wf-green)">QA · PASS</div>
                            <p>{{ task()!.qa_report }}</p>
                          </div>
                        }

                        @if (ph.id === 'done') {
                          <div class="wf-d-card is-ok">
                            <div class="wf-d-card-h" style="color:var(--wf-green)">Shipped</div>
                            <p>Branch: <span class="wf-mono">{{ task()!.branch }}</span></p>
                            <div class="wf-d-acts">
                              <button class="wf-btn wf-btn-go" (click)="action.emit('open_pr')">Open PR ↗</button>
                              <button class="wf-btn" (click)="action.emit('rerun')">Re-run</button>
                            </div>
                          </div>
                        }

                        @if (ph.id === 'queued') {
                          <div class="wf-d-card" style="margin-top:14px">
                            <div class="wf-d-card-h">Queued</div>
                            <div class="wf-d-acts">
                              <button class="wf-btn wf-btn-primary" (click)="action.emit('start')">Start now</button>
                            </div>
                          </div>
                        }
                      </div>
                    }
                  </div>
                </div>
              }
            }
          </div>

          @if (task()!.phase !== 'queued') {
            <div class="wf-d-card-h" style="margin-top:14px; padding-left:0">Run state</div>
            <div class="wf-d-kv">
              <span class="wf-d-kv-k">Repo</span>
              <span class="wf-d-kv-v wf-mono">{{ task()!.repo }}</span>
              <span class="wf-d-kv-k">Branch</span>
              <span class="wf-d-kv-v wf-mono" style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap">{{ task()!.branch }}</span>
              <span class="wf-d-kv-k">Cost</span>
              <span class="wf-d-kv-v wf-mono">{{ '$' + task()!.cost.toFixed(3) }}</span>
            </div>
          }

          @if (task()!.phase === 'queued') {
            <div class="wf-d-card" style="margin-top:14px">
              <div class="wf-d-card-h">Queued</div>
              <div class="wf-d-acts">
                <button class="wf-btn wf-btn-primary" (click)="action.emit('start')">Start now</button>
              </div>
            </div>
          }
        </div>

        <div class="wf-d-foot">
          <div class="wf-d-foot-stat">
            <div class="wf-d-foot-l">Cost</div>
            <div class="wf-d-foot-v wf-mono">{{ '$' + task()!.cost.toFixed(3) }}</div>
          </div>
          <div class="wf-d-foot-stat">
            <div class="wf-d-foot-l">Scope</div>
            <div class="wf-d-foot-v wf-mono">S{{ task()!.scope }}</div>
          </div>
          <div class="wf-d-foot-stat">
            <div class="wf-d-foot-l">Priority</div>
            <div class="wf-d-foot-v wf-mono">P{{ task()!.priority }}</div>
          </div>
        </div>
      }
    </aside>
  `,
})
export class WfDrawerComponent {
  task = input<WfTask | null>(null);

  action = output<string>();

  phases = WF_PHASES;

  isLive(phase: string): boolean {
    return LIVE_PHASES.includes(phase);
  }

  phaseIndex(phaseId: string): number {
    return WF_PHASES.findIndex(p => p.id === phaseId);
  }

  currentPhaseIndex = computed(() => {
    const t = this.task();
    if (!t) return -1;
    return WF_PHASES.findIndex(p => p.id === t.phase);
  });

  phaseColor(phaseId: string): string {
    return WF_PHASE_BY_ID[phaseId]?.color ?? '#6b7280';
  }
}
