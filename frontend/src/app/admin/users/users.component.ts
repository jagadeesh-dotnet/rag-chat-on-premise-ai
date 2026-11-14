import { Component, OnInit } from '@angular/core';
import { forkJoin } from 'rxjs';

import { AuthService } from '../../auth/auth.service';
import {
  AdminService,
  AdminUser,
  Role,
  attributesToText,
  errorText,
  temporaryPassword,
  textToAttributes,
} from '../admin.service';

@Component({
  selector: 'app-admin-users',
  templateUrl: './users.component.html',
  styleUrls: ['../admin.scss'],
})
export class UsersComponent implements OnInit {
  users: AdminUser[] = [];
  roles: Role[] = [];
  error = '';
  notice = '';
  me = this.auth.me$.value?.username;

  // new user form
  showNew = false;
  draft = { username: '', display_name: '', temporary_password: '', roles: [] as string[] };

  constructor(
    private admin: AdminService,
    private auth: AuthService,
  ) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    forkJoin({ users: this.admin.users(), roles: this.admin.roles() }).subscribe({
      next: ({ users, roles }) => {
        this.users = users;
        this.roles = roles;
      },
      error: (err) => (this.error = errorText(err)),
    });
  }

  openNew(): void {
    this.showNew = true;
    this.draft = { username: '', display_name: '', temporary_password: temporaryPassword(), roles: [] };
  }

  toggleDraftRole(role: string): void {
    const roles = this.draft.roles;
    this.draft.roles = roles.includes(role) ? roles.filter((r) => r !== role) : [...roles, role];
  }

  create(): void {
    this.run(this.admin.createUser(this.draft), () => {
      this.notice = `User ${this.draft.username} created. Temporary password: ${this.draft.temporary_password}`;
      this.showNew = false;
    });
  }

  toggleRole(user: AdminUser, role: string): void {
    const roles = user.roles.includes(role) ? user.roles.filter((r) => r !== role) : [...user.roles, role];
    this.run(this.admin.updateUser(user.id, { roles }));
  }

  editingAttributes: number | null = null;
  attributeText = '';

  editAttributes(user: AdminUser): void {
    this.editingAttributes = user.id;
    this.attributeText = attributesToText(user.attributes);
  }

  saveAttributes(user: AdminUser): void {
    this.editingAttributes = null;
    this.run(this.admin.updateUser(user.id, { attributes: textToAttributes(this.attributeText) }));
  }

  toggleActive(user: AdminUser): void {
    const verb = user.is_active ? 'Deactivate' : 'Activate';
    if (user.is_active && !confirm(`${verb} ${user.username}? They are signed out immediately.`)) return;
    this.run(this.admin.updateUser(user.id, { is_active: !user.is_active }));
  }

  resetPassword(user: AdminUser): void {
    const password = temporaryPassword();
    if (!confirm(`Reset the password of ${user.username}? They must choose a new one at the next sign-in.`)) return;
    this.run(this.admin.resetPassword(user.id, password), () => {
      this.notice = `Temporary password for ${user.username}: ${password}`;
    });
  }

  /** Run a change, show the server's message on failure, and reload the list either way. */
  private run(request: ReturnType<AdminService['updateUser']>, done?: () => void): void {
    this.error = '';
    this.notice = '';
    request.subscribe({
      next: () => {
        done?.();
        this.load();
      },
      error: (err) => {
        this.error = errorText(err);
        this.load();
      },
    });
  }
}
