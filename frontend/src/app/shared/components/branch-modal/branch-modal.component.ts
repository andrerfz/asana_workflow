import { Component, Input } from '@angular/core';
import { ModalController } from '@ionic/angular';

export interface BranchModalResult {
  action: 'fresh' | 'existing';
  baseBranch: string | null;
}

@Component({
  selector: 'app-branch-modal',
  templateUrl: './branch-modal.component.html',
  styleUrls: ['./branch-modal.component.scss'],
  standalone: false,
})
export class BranchModalComponent {
  @Input() taskGid = '';
  @Input() branchSlug = '';
  @Input() suggestions: Array<{ branch: string; author: string }> = [];

  constructor(private modalCtrl: ModalController) {}

  selectExisting(branch: string): void {
    this.modalCtrl.dismiss({ action: 'existing', baseBranch: branch } as BranchModalResult);
  }

  selectFresh(): void {
    this.modalCtrl.dismiss({ action: 'fresh', baseBranch: null } as BranchModalResult);
  }

  cancel(): void {
    this.modalCtrl.dismiss(null);
  }
}
