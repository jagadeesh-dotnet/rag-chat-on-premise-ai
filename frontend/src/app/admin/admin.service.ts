import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';

export type GrantKind = 'folder' | 'spreadsheet' | 'database';
export type Grants = Record<GrantKind, string[]>;

export interface AdminUser {
  id: number;
  username: string;
  display_name: string;
  is_active: number;
  must_change_password: number;
  created: string;
  last_login: string | null;
  roles: string[];
}

export interface Role {
  name: string;
  description: string;
  builtin: number;
  grants: Grants;
  members: number;
}

export interface AuditEntry {
  at: string;
  username: string;
  action: string;
  detail: string;
}

/** /api/admin: every call is checked for the admin role on the server. */
@Injectable({ providedIn: 'root' })
export class AdminService {
  private readonly url = `${environment.apiUrl}/api/admin`;

  constructor(private http: HttpClient) {}

  users(): Observable<AdminUser[]> {
    return this.http.get<AdminUser[]>(`${this.url}/users`);
  }

  createUser(user: { username: string; display_name: string; temporary_password: string; roles: string[] }) {
    return this.http.post<{ id: number }>(`${this.url}/users`, user);
  }

  updateUser(id: number, change: { display_name?: string; is_active?: boolean; roles?: string[] }) {
    return this.http.patch(`${this.url}/users/${id}`, change);
  }

  resetPassword(id: number, temporaryPassword: string) {
    return this.http.post(`${this.url}/users/${id}/password`, { temporary_password: temporaryPassword });
  }

  roles(): Observable<Role[]> {
    return this.http.get<Role[]>(`${this.url}/roles`);
  }

  saveRole(name: string, description: string, grants: Grants) {
    return this.http.put(`${this.url}/roles/${encodeURIComponent(name)}`, { description, grants });
  }

  deleteRole(name: string) {
    return this.http.delete(`${this.url}/roles/${encodeURIComponent(name)}`);
  }

  resources(): Observable<Grants> {
    return this.http.get<Grants>(`${this.url}/resources`);
  }

  audit(username = '', action = ''): Observable<AuditEntry[]> {
    let params = new HttpParams();
    if (username) params = params.set('username', username);
    if (action) params = params.set('action', action);
    return this.http.get<AuditEntry[]>(`${this.url}/audit`, { params });
  }
}

/** A readable temporary password, e.g. "maple-river-4821-cloud". */
export function temporaryPassword(): string {
  const words = ['maple', 'river', 'cloud', 'stone', 'amber', 'cedar', 'delta', 'ember', 'frost', 'harbor'];
  const pick = () => words[crypto.getRandomValues(new Uint32Array(1))[0] % words.length];
  const digits = String(crypto.getRandomValues(new Uint32Array(1))[0] % 10000).padStart(4, '0');
  return `${pick()}-${pick()}-${digits}-${pick()}`;
}

/** The server's error message, or a fallback. */
export function errorText(err: { error?: { detail?: unknown } }): string {
  const detail = err.error?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d) => d?.msg ?? '').join('; ');
  return 'Something went wrong.';
}
