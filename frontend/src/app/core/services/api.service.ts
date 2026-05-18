import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface Repo {
  id: string;
  name: string;
  path: string;
  default_branch?: string;
  test_cmd?: string;
  lint_cmd?: string;
}

export interface AgentSettings {
  max_concurrent_agents: number;
  auto_approve_plan: boolean;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  constructor(private http: HttpClient) {}

  getRepos(): Observable<Repo[]> {
    return this.http.get<Repo[]>('/repos');
  }

  getAgentSettings(): Observable<AgentSettings> {
    return this.http.get<AgentSettings>('/agent/settings');
  }

  updateAgentSettings(settings: Partial<AgentSettings>): Observable<AgentSettings> {
    return this.http.put<AgentSettings>('/agent/settings', settings);
  }

  getAgentHistory(): Observable<unknown[]> {
    return this.http.get<unknown[]>('/agent/history');
  }

  getDiff(taskGid: string, repoId: string): Observable<{ diff: string }> {
    return this.http.get<{ diff: string }>(`/agent/diff/${taskGid}/${repoId}`);
  }

  openInIde(path: string, ide: { cli?: string; cliArgs?: string[]; app?: string }): Observable<{ status: string }> {
    return this.http.post<{ status: string }>('/api/ide/open', { path, ...ide });
  }

  getClusters(): Observable<Record<string, unknown>> {
    return this.http.get<Record<string, unknown>>('/clusters');
  }

  classifyAll(): Observable<unknown> {
    return this.http.post('/ai/classify-all', {});
  }
}
