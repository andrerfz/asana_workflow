import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { IonicModule } from '@ionic/angular';
import { RouterModule } from '@angular/router';

import { SharedModule } from '../../shared/shared.module';
import { TaskDetailPage } from './task-detail.page';
import { TaskDetailRoutingModule } from './task-detail-routing.module';

@NgModule({
  declarations: [TaskDetailPage],
  imports: [CommonModule, IonicModule, RouterModule, SharedModule, TaskDetailRoutingModule],
})
export class TaskDetailModule {}
