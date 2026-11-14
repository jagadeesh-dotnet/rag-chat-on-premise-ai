import { Component } from '@angular/core';

/** Shell: header with tabs; the tab content comes through the router outlet. */
@Component({
  selector: 'app-admin-page',
  template: `
    <div class="admin">
      <header>
        <a routerLink="/" class="back">← Back to chat</a>
        <h1>Administration</h1>
        <nav>
          <a routerLink="users" routerLinkActive="active">Users</a>
          <a routerLink="roles" routerLinkActive="active">Roles</a>
          <a routerLink="rules" routerLinkActive="active">Row rules</a>
          <a routerLink="audit" routerLinkActive="active">Audit log</a>
        </nav>
      </header>
      <router-outlet></router-outlet>
    </div>
  `,
  styleUrls: ['../admin.scss'],
})
export class AdminPageComponent {}
