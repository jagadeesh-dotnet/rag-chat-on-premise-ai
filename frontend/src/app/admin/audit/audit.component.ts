import { Component, OnInit } from '@angular/core';

import { AdminService, AuditEntry, errorText } from '../admin.service';

const ACTIONS = [
  'login_ok', 'login_failed', 'login_locked', 'logout', 'password_changed', 'password_reset',
  'user_created', 'user_updated', 'role_saved', 'role_deleted',
];

@Component({
  selector: 'app-admin-audit',
  template: `
    <section>
      <div class="bar">
        <h2>Audit log</h2>
        <form class="filters" (ngSubmit)="load()">
          <input name="username" [(ngModel)]="username" placeholder="User" />
          <select name="action" [(ngModel)]="action" (change)="load()">
            <option value="">All actions</option>
            <option *ngFor="let a of actions" [value]="a">{{ a }}</option>
          </select>
          <button type="submit">Filter</button>
        </form>
      </div>
      <p class="error" *ngIf="error" role="alert">{{ error }}</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Time</th><th>User</th><th>Action</th><th>Details</th></tr></thead>
          <tbody>
            <tr *ngFor="let e of entries" [class.warn]="e.action === 'login_failed' || e.action === 'login_locked'">
              <td class="nowrap">{{ e.at | date: 'medium' }}</td>
              <td>{{ e.username }}</td>
              <td><code>{{ e.action }}</code></td>
              <td>{{ e.detail }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="hint" *ngIf="!entries.length && !error">No entries.</p>
    </section>
  `,
  styleUrls: ['../admin.scss'],
})
export class AuditComponent implements OnInit {
  readonly actions = ACTIONS;
  entries: AuditEntry[] = [];
  username = '';
  action = '';
  error = '';

  constructor(private admin: AdminService) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.admin.audit(this.username.trim(), this.action).subscribe({
      next: (entries) => (this.entries = entries),
      error: (err) => (this.error = errorText(err)),
    });
  }
}
