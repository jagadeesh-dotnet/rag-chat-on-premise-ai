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
  is_active: boolean;
  must_change_password: boolean;
  created: string;
  last_login: string | null;
  roles: string[];
  attributes: Record<string, string[]>; // e.g. { region: ['East'] }, compared by row rules
}

export interface RowRule {
  id: number;
  kind: 'spreadsheet' | 'database';
  source: string; // 'spreadsheets' or a database name
  table_name: string;
  column_name: string;
  attribute: string;
  created: string;
}

/** What can be granted, plus the columns row rules can use. */
export interface Resources extends Grants {
  columns: {
    spreadsheet: Record<string, string[]>; // table -> columns
    database: Record<string, Record<string, string[]>>; // database -> table -> columns
  };
}

export interface Role {
  name: string;
  description: string;
  builtin: number;
  grants: Grants;
  members: number;
}

/** A document file compared with the index. */
export interface DocumentFile {
  source: string; // path under data/docs, e.g. 'hr/hr-handbook-sample.docx'
  size: number | null; // bytes; null when the file is gone
  modified: string | null;
  chunks: number;
  status: 'indexed' | 'changed' | 'new' | 'missing';
}

export interface DocumentsStatus {
  folder: string;
  files: DocumentFile[];
}

/** What one index run did. */
export interface IndexSummary {
  added: string[];
  updated: string[];
  removed: string[];
  unchanged: string[];
  errors: Record<string, string>; // file -> error message
  chunks: number;
  seconds: number;
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

  updateUser(
    id: number,
    change: { display_name?: string; is_active?: boolean; roles?: string[]; attributes?: Record<string, string[]> },
  ) {
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

  resources(): Observable<Resources> {
    return this.http.get<Resources>(`${this.url}/resources`);
  }

  rules(): Observable<RowRule[]> {
    return this.http.get<RowRule[]>(`${this.url}/rules`);
  }

  addRule(rule: { kind: string; source: string; table: string; column: string; attribute: string }) {
    return this.http.post<{ id: number }>(`${this.url}/rules`, rule);
  }

  deleteRule(id: number) {
    return this.http.delete(`${this.url}/rules/${id}`);
  }

  documents(): Observable<DocumentsStatus> {
    return this.http.get<DocumentsStatus>(`${this.url}/documents`);
  }

  /** Index new and changed files (force: every file). Can take a while: the model embeds every chunk. */
  reindex(force = false): Observable<IndexSummary> {
    const params = new HttpParams().set('force', String(force));
    return this.http.post<IndexSummary>(`${environment.apiUrl}/api/documents/index`, null, { params });
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

/** { region: ['East', 'West'], country: ['Germany'] }  <->  'region=East, West; country=Germany' */
export function attributesToText(attributes: Record<string, string[]>): string {
  return Object.entries(attributes)
    .map(([name, values]) => `${name}=${values.join(', ')}`)
    .join('; ');
}

export function textToAttributes(text: string): Record<string, string[]> {
  const result: Record<string, string[]> = {};
  for (const part of text.split(';')) {
    const [name, values] = part.split('=');
    if (!name?.trim() || values === undefined) continue;
    result[name.trim().toLowerCase()] = values.split(',').map((v) => v.trim()).filter(Boolean);
  }
  return result;
}
