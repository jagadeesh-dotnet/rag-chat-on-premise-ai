import { HttpErrorResponse } from '@angular/common/http';
import { Component } from '@angular/core';
import { Router } from '@angular/router';

import { AuthService } from '../auth.service';

@Component({
  selector: 'app-change-password',
  templateUrl: './change-password.component.html',
  styleUrls: ['../auth-page.scss'],
})
export class ChangePasswordComponent {
  current = '';
  next = '';
  repeat = '';
  error = '';
  busy = false;
  readonly forced$ = this.auth.me$;

  constructor(
    private auth: AuthService,
    private router: Router,
  ) {}

  get mismatch(): boolean {
    return !!this.repeat && this.next !== this.repeat;
  }

  submit(): void {
    if (this.busy || this.mismatch) return;
    this.busy = true;
    this.error = '';
    this.auth.changePassword(this.current, this.next).subscribe({
      next: () => this.router.navigateByUrl('/'),
      error: (err: HttpErrorResponse) => {
        this.busy = false;
        this.error = err.error?.detail ?? 'The password could not be changed.';
      },
    });
  }

  signOut(): void {
    this.auth.logout().subscribe(() => this.router.navigateByUrl('/login'));
  }
}
