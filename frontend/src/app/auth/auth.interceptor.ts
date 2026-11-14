import { HttpErrorResponse, HttpEvent, HttpHandler, HttpInterceptor, HttpRequest } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, catchError, throwError } from 'rxjs';

import { environment } from '../../environments/environment';
import { AuthService } from './auth.service';

/**
 * For every API call: send the session cookie (it's cross-origin: 4200 -> 8000), and react to an ended
 * session (401: back to sign-in) or a temporary password (403 password_change_required).
 */
@Injectable()
export class AuthInterceptor implements HttpInterceptor {
  constructor(
    private auth: AuthService,
    private router: Router,
  ) {}

  intercept(request: HttpRequest<unknown>, next: HttpHandler): Observable<HttpEvent<unknown>> {
    if (!request.url.startsWith(environment.apiUrl)) return next.handle(request);

    return next.handle(request.clone({ withCredentials: true })).pipe(
      catchError((error: unknown) => {
        if (error instanceof HttpErrorResponse && !request.url.includes('/api/auth/')) {
          if (error.status === 401) {
            this.auth.signedOut();
            this.router.navigate(['/login'], { queryParams: { returnUrl: this.router.url } });
          } else if (error.status === 403 && error.error?.detail === 'password_change_required') {
            this.router.navigate(['/change-password']);
          }
        }
        return throwError(() => error);
      }),
    );
  }
}
