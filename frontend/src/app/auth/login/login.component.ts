import { HttpErrorResponse } from '@angular/common/http';
import { Component } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';

import { AuthService } from '../auth.service';

@Component({
  selector: 'app-login',
  templateUrl: './login.component.html',
  styleUrls: ['../auth-page.scss'],
})
export class LoginComponent {
  username = '';
  password = '';
  error = '';
  busy = false;

  constructor(
    private auth: AuthService,
    private router: Router,
    private route: ActivatedRoute,
  ) {}

  submit(): void {
    if (this.busy) return;
    this.busy = true;
    this.error = '';
    this.auth.login(this.username.trim(), this.password).subscribe({
      next: (me) => {
        this.password = '';
        const returnUrl = this.route.snapshot.queryParamMap.get('returnUrl') ?? '/';
        // Only follow local paths: a crafted ?returnUrl=https://evil.example mustn't redirect anywhere else.
        const safe = returnUrl.startsWith('/') && !returnUrl.startsWith('//') ? returnUrl : '/';
        this.router.navigateByUrl(me.must_change_password ? '/change-password' : safe);
      },
      error: (err: HttpErrorResponse) => {
        this.busy = false;
        this.password = '';
        this.error =
          err.status === 429
            ? 'Too many failed attempts. Try again in a few minutes.'
            : err.status === 401
              ? 'Wrong username or password.'
              : 'The server is not reachable.';
      },
    });
  }
}
