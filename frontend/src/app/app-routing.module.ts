import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';

import { adminGuard, sessionGuard, signedInGuard } from './auth/auth.guards';
import { ChangePasswordComponent } from './auth/change-password/change-password.component';
import { LoginComponent } from './auth/login/login.component';

const routes: Routes = [
  { path: 'login', component: LoginComponent, title: 'Sign in · RAG Chat' },
  { path: 'change-password', component: ChangePasswordComponent, canActivate: [sessionGuard] },
  {
    path: 'admin',
    canActivate: [adminGuard],
    loadChildren: () => import('./admin/admin.module').then((m) => m.AdminModule),
  },
  {
    path: '',
    canActivate: [signedInGuard],
    loadChildren: () => import('./chat/chat.module').then((m) => m.ChatModule),
  },
  { path: '**', redirectTo: '' },
];

@NgModule({
  imports: [RouterModule.forRoot(routes)],
  exports: [RouterModule],
})
export class AppRoutingModule {}
