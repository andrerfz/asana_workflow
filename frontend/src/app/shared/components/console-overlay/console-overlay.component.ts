import {
  Component, Input, OnInit, OnDestroy, signal, computed,
  ViewChild, ElementRef, AfterViewChecked,
} from '@angular/core';
import { ModalController } from '@ionic/angular';
import { AgentStateService } from '../../../core/services/agent-state.service';
import { ConversationMessage } from '../../../core/models/task.model';

@Component({
  selector: 'app-console-overlay',
  templateUrl: './console-overlay.component.html',
  styleUrls: ['./console-overlay.component.scss'],
  standalone: false,
})
export class ConsoleOverlayComponent implements OnInit, OnDestroy, AfterViewChecked {
  @Input() taskGid!: string;
  @ViewChild('msgContainer') msgContainer?: ElementRef<HTMLElement>;

  message = signal('');
  sending = signal(false);
  private shouldScroll = false;
  private convLength = 0;

  readonly run = computed(() => this.state.agentRuns()[this.taskGid]);
  readonly taskName = computed(() =>
    this.state.tasks().find(t => t.task_gid === this.taskGid)?.name ?? 'Agent Console'
  );
  readonly conversation = computed<ConversationMessage[]>(() =>
    this.run()?.conversation ?? []
  );

  constructor(public state: AgentStateService, private modalCtrl: ModalController) {}

  ngOnInit(): void {}
  ngOnDestroy(): void {}

  ngAfterViewChecked(): void {
    const len = this.conversation().length;
    if (len !== this.convLength) {
      this.convLength = len;
      this.shouldScroll = true;
    }
    if (this.shouldScroll && this.msgContainer) {
      const el = this.msgContainer.nativeElement;
      el.scrollTop = el.scrollHeight;
      this.shouldScroll = false;
    }
  }

  async send(): Promise<void> {
    const msg = this.message().trim();
    if (!msg || this.sending()) return;
    this.sending.set(true);
    try {
      await this.state.sendGuideMessage(this.taskGid, msg);
      this.message.set('');
    } catch (e) {
      console.error('[Console] send failed', e);
    } finally {
      this.sending.set(false);
    }
  }

  async stop(): Promise<void> {
    await this.state.stopAgent(this.taskGid);
  }

  async clearChat(): Promise<void> {
    try {
      await this.state.clearConversation(this.taskGid);
    } catch (e) {
      console.error('[Console] clearChat failed', e);
    }
  }

  close(): void {
    this.modalCtrl.dismiss();
  }

  onInput(e: CustomEvent): void { this.message.set(e.detail.value ?? ''); }

  onKeydown(e: KeyboardEvent): void {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      this.send();
    }
  }

  formatTime(ts: string): string {
    try { return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
    catch { return ''; }
  }

  trackByTs(_: number, m: ConversationMessage): string { return m.timestamp; }
}
