import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { IonicModule } from '@ionic/angular';

import { TaskCardComponent } from './components/task-card/task-card.component';
import { PhaseBadgeComponent } from './components/phase-badge/phase-badge.component';
import { LogStreamComponent } from './components/log-stream/log-stream.component';

@NgModule({
  declarations: [TaskCardComponent, PhaseBadgeComponent, LogStreamComponent],
  imports: [CommonModule, IonicModule],
  exports: [TaskCardComponent, PhaseBadgeComponent, LogStreamComponent],
})
export class SharedModule {}
