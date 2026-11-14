import { Component, OnInit } from '@angular/core';
import { forkJoin } from 'rxjs';

import { AdminService, GrantKind, Grants, Role, errorText } from '../admin.service';

const KINDS: { kind: GrantKind; label: string; hint: string }[] = [
  { kind: 'folder', label: 'Document folders', hint: '"/" = files directly in data/docs; a folder includes its subfolders' },
  { kind: 'spreadsheet', label: 'Spreadsheets', hint: 'tables loaded from Excel/CSV files' },
  { kind: 'database', label: 'Databases', hint: 'SQL Server databases from databases.json' },
];

@Component({
  selector: 'app-admin-roles',
  templateUrl: './roles.component.html',
  styleUrls: ['../admin.scss'],
})
export class RolesComponent implements OnInit {
  readonly kinds = KINDS;
  roles: Role[] = [];
  resources: Grants = { folder: [], spreadsheet: [], database: [] };
  error = '';

  editing: { name: string; description: string; grants: Grants; isNew: boolean } | null = null;

  constructor(private admin: AdminService) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    forkJoin({ roles: this.admin.roles(), resources: this.admin.resources() }).subscribe({
      next: ({ roles, resources }) => {
        this.roles = roles;
        this.resources = resources;
      },
      error: (err) => (this.error = errorText(err)),
    });
  }

  edit(role?: Role): void {
    const empty: Grants = { folder: [], spreadsheet: [], database: [] };
    this.editing = role
      ? { name: role.name, description: role.description, grants: structuredClone(role.grants), isNew: false }
      : { name: '', description: '', grants: empty, isNew: true };
  }

  options(kind: GrantKind): string[] {
    return ['*', ...this.resources[kind]];
  }

  has(kind: GrantKind, value: string): boolean {
    return !!this.editing?.grants[kind].includes(value);
  }

  toggle(kind: GrantKind, value: string): void {
    if (!this.editing) return;
    const list = this.editing.grants[kind];
    this.editing.grants[kind] = list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
  }

  save(): void {
    if (!this.editing) return;
    const { name, description, grants } = this.editing;
    this.error = '';
    this.admin.saveRole(name, description, grants).subscribe({
      next: () => {
        this.editing = null;
        this.load();
      },
      error: (err) => (this.error = errorText(err)),
    });
  }

  remove(role: Role): void {
    const members = role.members ? ` It is assigned to ${role.members} user(s), who lose its access.` : '';
    if (!confirm(`Delete role ${role.name}?${members}`)) return;
    this.admin.deleteRole(role.name).subscribe({
      next: () => this.load(),
      error: (err) => (this.error = errorText(err)),
    });
  }

  summary(role: Role, kind: GrantKind): string {
    if (role.builtin) return 'everything';
    const values = role.grants[kind];
    return values.length ? values.map((v) => (v === '*' ? 'all' : v)).join(', ') : '—';
  }
}
