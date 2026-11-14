import { CommonModule } from '@angular/common';
import { NgModule } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterModule, Routes } from '@angular/router';

import { AdminPageComponent } from './admin-page/admin-page.component';
import { AuditComponent } from './audit/audit.component';
import { RolesComponent } from './roles/roles.component';
import { UsersComponent } from './users/users.component';

const routes: Routes = [
  {
    path: '',
    component: AdminPageComponent,
    children: [
      { path: 'users', component: UsersComponent, title: 'Users · Admin' },
      { path: 'roles', component: RolesComponent, title: 'Roles · Admin' },
      { path: 'audit', component: AuditComponent, title: 'Audit log · Admin' },
      { path: '', redirectTo: 'users', pathMatch: 'full' },
    ],
  },
];

/** Lazy-loaded at /admin, behind adminGuard (the server checks the admin role on every call too). */
@NgModule({
  declarations: [AdminPageComponent, UsersComponent, RolesComponent, AuditComponent],
  imports: [CommonModule, FormsModule, RouterModule.forChild(routes)],
})
export class AdminModule {}
