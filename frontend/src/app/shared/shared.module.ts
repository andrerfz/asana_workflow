import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { IonicModule } from '@ionic/angular';
import { FormsModule } from '@angular/forms';

import { TaskCardComponent } from './components/task-card/task-card.component';
import { PhaseBadgeComponent } from './components/phase-badge/phase-badge.component';
import { LogStreamComponent } from './components/log-stream/log-stream.component';
import { BranchModalComponent } from './components/branch-modal/branch-modal.component';
import { ConsoleOverlayComponent } from './components/console-overlay/console-overlay.component';

@NgModule({
  declarations: [TaskCardComponent, PhaseBadgeComponent, LogStreamComponent, BranchModalComponent, ConsoleOverlayComponent],
  imports: [CommonModule, IonicModule, FormsModule],
  exports: [TaskCardComponent, PhaseBadgeComponent, LogStreamComponent, BranchModalComponent, ConsoleOverlayComponent],
})
export class SharedModule {}
