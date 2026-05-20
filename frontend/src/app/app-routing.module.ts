import { NgModule } from '@angular/core';
import { PreloadAllModules, RouterModule, Routes } from '@angular/router';

const routes: Routes = [
  // ── New v2 dashboard is the home ──────────────────────────────────────────
  {
    path: '',
    loadComponent: () => import('./pages/wf-dashboard/wf-dashboard.page').then(m => m.WfDashboardPage),
  },
  // ── Settings and Task detail still use the Ionic pages ───────────────────
  {
    path: 'settings',
    loadChildren: () => import('./pages/settings/settings.module').then(m => m.SettingsModule),
  },
  {
    path: 'task/:gid',
    loadChildren: () => import('./pages/task-detail/task-detail.module').then(m => m.TaskDetailModule),
  },
  {
    path: 'history',
    loadChildren: () => import('./pages/history/history.module').then(m => m.HistoryModule),
  },
  // ── Classic Ionic dashboard kept at /classic ──────────────────────────────
  {
    path: 'classic',
    loadChildren: () => import('./pages/dashboard/dashboard.module').then(m => m.DashboardModule),
  },
  { path: '**', redirectTo: '', pathMatch: 'full' },
];

@NgModule({
  imports: [RouterModule.forRoot(routes, { preloadingStrategy: PreloadAllModules })],
  exports: [RouterModule],
})
export class AppRoutingModule {}
