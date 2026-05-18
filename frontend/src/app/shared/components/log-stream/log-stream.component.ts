import { Component, Input, OnChanges, ViewChild, ElementRef, AfterViewChecked } from '@angular/core';
import { LogEntry } from '../../../core/models/task.model';

@Component({
  selector: 'app-log-stream',
  templateUrl: './log-stream.component.html',
  styleUrls: ['./log-stream.component.scss'],
  standalone: false,
})
export class LogStreamComponent implements OnChanges, AfterViewChecked {
  @Input() logs: LogEntry[] = [];
  @Input() maxVisible = 100;
  @ViewChild('logContainer') container?: ElementRef<HTMLElement>;

  private shouldScroll = false;

  get visibleLogs(): LogEntry[] {
    return this.logs.slice(-this.maxVisible);
  }

  ngOnChanges(): void {
    this.shouldScroll = true;
  }

  ngAfterViewChecked(): void {
    if (this.shouldScroll && this.container) {
      this.container.nativeElement.scrollTop = this.container.nativeElement.scrollHeight;
      this.shouldScroll = false;
    }
  }

  levelClass(level: string): string {
    const map: Record<string, string> = {
      debug: 'log-debug',
      info: 'log-info',
      warning: 'log-warn',
      error: 'log-error',
    };
    return map[level] ?? 'log-info';
  }

  trackByTs(_: number, entry: LogEntry): string { return entry.timestamp; }

  formatTime(ts: string): string {
    try {
      return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch { return ts; }
  }
}
