import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface Repo {
  id: string;
  path: string;
  default_branch?: string;
  test_cmd?: string;
  test_worktree_cmd?: string;
  test_worktree_cmd_fast?: string;
  lint_cmd?: string;
  build_cmd?: string | null;
  language?: string;
  context_files?: string[];
  health?: { status: string; details: string };
}

export interface AgentSettings {
  section_on_start: string;
  section_on_done: string;
  section_on_error: string;
  agent_timeout_minutes: number;
}

export interface Guide {
  id: string;
  label: string;
  type: string;
  content: string;
}

export interface CliStatus {
  available: boolean;
  authenticated: boolean;
  version: string;
  path: string;
  error?: string;
}

export interface BranchSuggestion {
  branch: string;
  author: string;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  constructor(private http: HttpClient) {}

  getRepos(): Observable<Repo[]> {
    return new Observable(obs => {
      this.http.get<{ repos: Repo[] }>('/api/repos').subscribe({
        next: r => { obs.next(r.repos ?? []); obs.complete(); },
        error: e => obs.error(e),
      });
    });
  }

  getRepoConfig(): Observable<{ projects_dir: string }> {
    return this.http.get<{ projects_dir: string }>('/api/repos/config');
  }

  scanRepos(): Observable<Repo[]> {
    return this.http.get<Repo[]>('/api/repos/scan');
  }

  saveRepo(repo: Partial<Repo> & { id: string }): Observable<Repo> {
    return this.http.post<Repo>(`/api/repos/${repo.id}`, repo);
  }

  deleteRepo(id: string): Observable<unknown> {
    return this.http.delete(`/api/repos/${id}`);
  }

  getAreaMapping(): Observable<Record<string, string[]>> {
    return new Observable(obs => {
      this.http.get<{ area_repo_map: Record<string, string[]> }>('/api/repos/mapping/areas').subscribe({
        next: r => { obs.next(r.area_repo_map ?? {}); obs.complete(); },
        error: e => obs.error(e),
      });
    });
  }

  saveAreaMapping(area: string, repoIds: string[]): Observable<unknown> {
    return this.http.put(`/api/repos/mapping/areas/${encodeURIComponent(area)}`, { repo_ids: repoIds });
  }

  getAgentSettings(): Observable<AgentSettings> {
    return this.http.get<AgentSettings>('/api/agent/settings');
  }

  updateAgentSettings(settings: Partial<AgentSettings>): Observable<AgentSettings> {
    return this.http.put<AgentSettings>('/api/agent/settings', settings);
  }

  getCliStatus(): Observable<CliStatus> {
    return this.http.get<CliStatus>('/api/agent/cli-status');
  }

  getAgentHistory(): Observable<unknown[]> {
    return this.http.get<unknown[]>('/api/agent/history');
  }

  getTaskRepoOverrides(): Observable<Record<string, string[]>> {
    return this.http.get<Record<string, string[]>>('/api/agent/task-repo-overrides');
  }

  updateTaskRepos(gid: string, repoIds: string[]): Observable<unknown> {
    return this.http.put(`/api/agent/task/${gid}/repos`, { repo_ids: repoIds });
  }

  getDiff(taskGid: string, repoId: string): Observable<{ diff: string }> {
    return this.http.get<{ diff: string }>(`/api/agent/diff/${taskGid}/${repoId}`);
  }

  getBranchName(gid: string): Observable<{ branch: string }> {
    return this.http.post<{ branch: string }>(`/api/ai/branch-name/${gid}`, {});
  }

  getBranchSuggestions(gid: string): Observable<{ branches: BranchSuggestion[] }> {
    return this.http.get<{ branches: BranchSuggestion[] }>(`/api/agent/branch-suggestions/${gid}`);
  }

  runQA(gid: string): Observable<unknown> {
    return this.http.post(`/api/agent/qa/${gid}`, {});
  }

  runTest(gid: string): Observable<{ all_passed: boolean }> {
    return this.http.post<{ all_passed: boolean }>(`/api/agent/test/${gid}`, {});
  }

  syncTasks(): Observable<unknown> {
    return this.http.post('/api/sync', {});
  }

  getGuides(): Observable<Guide[]> {
    return this.http.get<Guide[]>('/api/guides');
  }

  saveGuide(id: string, content: string): Observable<unknown> {
    return this.http.put(`/api/guides/${encodeURIComponent(id)}`, { content });
  }

  getAgentWorkflow(): Observable<unknown> {
    return this.http.get('/api/agent/workflow');
  }

  openInIde(path: string, ide: { cli?: string; cliArgs?: string[]; app?: string }): Observable<{ status: string }> {
    return this.http.post<{ status: string }>('/api/ide/open', { path, ...ide });
  }

  getClusters(): Observable<Record<string, unknown>> {
    return this.http.get<Record<string, unknown>>('/api/clusters');
  }

  classifyAll(): Observable<unknown> {
    return this.http.post('/api/ai/classify-all', {});
  }

  classifyTask(gid: string): Observable<unknown> {
    return this.http.post(`/api/ai/classify/${gid}`, {});
  }
}
