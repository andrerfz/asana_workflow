import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { IonicModule } from '@ionic/angular';
import { RouterModule } from '@angular/router';

import { SharedModule } from '../../shared/shared.module';
import { HistoryPage } from './history.page';
import { HistoryRoutingModule } from './history-routing.module';

@NgModule({
  declarations: [HistoryPage],
  imports: [CommonModule, IonicModule, RouterModule, SharedModule, HistoryRoutingModule],
})
export class HistoryModule {}
