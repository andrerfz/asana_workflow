import { Component, ChangeDetectionStrategy, input, output, signal, ViewEncapsulation, computed } from '@angular/core';
import { WfTask, WF_PHASES, WF_PHASE_BY_ID, LIVE_PHASES } from '../wf-task.model';

// Actions that show a timed loading state and block re-click.
// 'classify' is NOT here — its loading state is real (isClassifying input,
// driven by the actual HTTP request in the dashboard page).
const BUSY_ACTIONS: Record<string, number> = {
  branch: 3000,    // API call + clipboard — ~2s
  ide: 1500,       // open command — ~1s
  asana: 1000,     // open link — instant
};

@Component({
  selector: 'app-wf-drawer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `
    <aside class="wf-drawer">
      <div class="wf-drawer-resize" (mousedown)="onResizeStart($event)"></div>
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
              <button class="wf-d-abtn" [disabled]="busy('ide')" (click)="trigger('ide')">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
                IDE
              </button>
              <button class="wf-d-abtn" [disabled]="busy('branch')" (click)="trigger('branch')">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M6 9v6M6 18a9 9 0 0 0 9-9v3"/></svg>
                {{ busy('branch') ? 'Copying…' : 'Branch' }}
              </button>
              <button class="wf-d-abtn" [disabled]="busy('asana')" (click)="trigger('asana')">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 17 17 7M17 7H8m9 0v9"/></svg>
                Asana
              </button>
              <button class="wf-d-abtn" [class.is-classified]="isClassified() && !isClassifying()" [disabled]="isClassifying()" (click)="trigger('classify')">
                @if (isClassifying()) {
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation:wf-spin .8s linear infinite"><path d="M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5"/></svg>
                  Classifying…
                } @else if (isClassified()) {
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m5 12 5 5L20 7"/></svg>
                  Classified
                } @else {
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3l1.9 5.8 5.8 1.9-5.8 1.9L12 18.4l-1.9-5.8-5.8-1.9 5.8-1.9L12 3z"/></svg>
                  Classify
                }
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

          <!-- Classification block -->
          <div class="wf-d-card wf-d-classif" style="margin-top:12px">
            <div class="wf-d-card-h" style="display:flex;align-items:center;justify-content:space-between">
              <span>Classification</span>
              @if (isClassifying()) {
                <span class="wf-classif-badge is-loading">
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="animation:wf-spin .8s linear infinite"><path d="M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5"/></svg>
                  classifying…
                </span>
              } @else if (isClassified()) {
                <span class="wf-classif-badge">✓ classified</span>
              } @else {
                <span class="wf-classif-badge is-missing">not classified</span>
              }
            </div>
            @if (task()!.ai_summary) {
              <p class="wf-classif-summary">{{ task()!.ai_summary }}</p>
            }
            @if (task()!.ai_reasoning) {
              <p class="wf-classif-reasoning">{{ task()!.ai_reasoning }}</p>
            }
            <div class="wf-classif-grid">
              <div class="wf-kv-row">
                <div class="wf-kv-k">Cluster</div>
                <div class="wf-kv-v">
                  @if (task()!.cluster) {
                    <span class="wf-d-tag" [style.background]="task()!.cluster!.color + '22'" [style.color]="task()!.cluster!.color" style="font-size:11px;padding:2px 7px">
                      {{ task()!.cluster!.name }}
                    </span>
                  } @else { <span style="color:var(--wf-text-dim)">—</span> }
                </div>
              </div>
              <div class="wf-kv-row">
                <div class="wf-kv-k">Type</div>
                <div class="wf-kv-v">
                  @if (task()!.tipo) {
                    <span class="wf-tag">{{ task()!.tipo }}</span>
                  } @else { <span style="color:var(--wf-text-dim)">—</span> }
                </div>
              </div>
              <div class="wf-kv-row">
                <div class="wf-kv-k">Canal</div>
                <div class="wf-kv-v">{{ task()!.canal || '—' }}</div>
              </div>
              <div class="wf-kv-row">
                <div class="wf-kv-k">Area</div>
                <div class="wf-kv-v wf-mono" style="font-size:11px">{{ task()!.area || '—' }}</div>
              </div>
              <div class="wf-kv-row">
                <div class="wf-kv-k">Scope</div>
                <div class="wf-kv-v"><span class="wf-tag wf-tag-scope">S{{ task()!.scope }}</span></div>
              </div>
              <div class="wf-kv-row">
                <div class="wf-kv-k">Priority</div>
                <div class="wf-kv-v wf-mono">P{{ task()!.priority }}</div>
              </div>
              @if (task()!.projects.length) {
                <div class="wf-kv-row">
                  <div class="wf-kv-k">Projects</div>
                  <div class="wf-kv-v" style="display:flex;gap:4px;flex-wrap:wrap">
                    @for (p of task()!.projects!; track p) {
                      <span class="wf-tag">{{ p }}</span>
                    }
                  </div>
                </div>
              }
            </div>
          </div>

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
                            <pre class="wf-plan-text">{{ task()!.plan }}</pre>
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
                          @if (qaPass(task()!.qa_report)) {
                            <div class="wf-d-card is-ok">
                              <div class="wf-d-card-h" style="color:var(--wf-green)">QA · PASS</div>
                              <p>{{ task()!.qa_report }}</p>
                            </div>
                            <div class="wf-d-acts">
                              <button class="wf-btn wf-btn-go" (click)="action.emit('qa_approve')">Ship it ↗</button>
                              <button class="wf-btn" (click)="action.emit('rerun')">Re-run anyway</button>
                            </div>
                          } @else {
                            <div class="wf-d-card is-warn">
                              <div class="wf-d-card-h" style="color:var(--wf-red)">QA · FAIL</div>
                              <p>{{ task()!.qa_report }}</p>
                            </div>
                            <div class="wf-d-acts">
                              <button class="wf-btn wf-btn-warn" (click)="action.emit('rerun')">Re-run</button>
                              <button class="wf-btn wf-btn-danger" (click)="action.emit('reject')">Reject</button>
                            </div>
                          }
                        }

                        @if (ph.id === 'done') {
                          <div class="wf-d-card is-ok">
                            <div class="wf-d-card-h" style="color:var(--wf-green)">Shipped</div>
                            <p>Branch: <span class="wf-mono">{{ task()!.branch }}</span></p>
                            <div class="wf-d-acts">
                              <button class="wf-btn wf-btn-go" [disabled]="!task()!.mr_url" (click)="action.emit('open_pr')">{{ task()!.mr_url ? "Open MR ↗" : "MR not created yet" }}</button>
                              <button class="wf-btn" (click)="action.emit('run_qa')">Run QA</button>
                              <button class="wf-btn" (click)="action.emit('rerun')">Re-run</button>
                            </div>
                          </div>
                        }

                        @if (ph.id === 'queued') {
                          <div class="wf-d-card" style="margin-top:14px">
                            <div class="wf-d-card-h">{{ task()!.phase === 'done' ? 'Shipped' : task()!.phase === 'cancelled' ? 'Cancelled' : task()!.phase === 'error' ? 'Failed' : 'Queued' }}</div>
                            <div class="wf-d-acts">
                              <button class="wf-btn wf-btn-primary" (click)="action.emit('start')" [disabled]="isStarting()">{{ isStarting() ? 'Starting…' : task()!.phase === 'queued' ? 'Start now' : 'Re-run' }}</button>
                              @if (['done','error','cancelled'].includes(task()!.phase)) {
                                <button class="wf-btn" (click)="action.emit('run_qa')">Run QA</button>
                              }
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

          @if (task()!.phase === 'queued' || task()!.phase === 'cancelled' || task()!.phase === 'error' || task()!.phase === 'done') {
            <div class="wf-d-card" style="margin-top:14px">
              <div class="wf-d-card-h">{{ task()!.phase === 'done' ? 'Shipped' : task()!.phase === 'cancelled' ? 'Cancelled' : task()!.phase === 'error' ? 'Failed' : 'Queued' }}</div>
              <div class="wf-d-acts">
                <button class="wf-btn wf-btn-primary" (click)="action.emit('start')" [disabled]="isStarting()">{{ isStarting() ? 'Starting…' : task()!.phase === 'queued' ? 'Start now' : 'Re-run' }}</button>
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
  isStarting = input<boolean>(false);
  isClassifying = input<boolean>(false);
  action = output<string>();

  phases = WF_PHASES;

  onResizeStart(e: MouseEvent): void {
    e.preventDefault();
    const startX = e.clientX;
    const root = document.querySelector('.wf-root') as HTMLElement;
    const startW = parseInt(getComputedStyle(root).getPropertyValue('--wf-drawer') || '380', 10);
    const maxW = Math.round(window.innerWidth * 0.70);
    const minW = 320;

    const onMove = (mv: MouseEvent) => {
      const delta = startX - mv.clientX; // drag left = wider
      const newW = Math.min(maxW, Math.max(minW, startW + delta));
      root.style.setProperty('--wf-drawer', `${newW}px`);
    };
    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }

  readonly isClassified = computed(() => {
    const t = this.task();
    return !!(t?.ai_summary || t?.ai_reasoning);
  });

  private _busy = signal<Set<string>>(new Set());

  busy(act: string): boolean {
    return this._busy().has(act);
  }

  trigger(act: string): void {
    if (this.busy(act)) return;
    const ms = BUSY_ACTIONS[act];
    if (ms) {
      this._busy.update(s => new Set([...s, act]));
      setTimeout(() => this._busy.update(s => { const n = new Set(s); n.delete(act); return n; }), ms);
    }
    this.action.emit(act);
  }

  isLive(phase: string): boolean {
    return LIVE_PHASES.includes(phase);
  }

  qaPass(report: string | undefined): boolean {
    if (!report) return false;
    return /PASS/i.test(report) && !/FAIL/i.test(report);
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
