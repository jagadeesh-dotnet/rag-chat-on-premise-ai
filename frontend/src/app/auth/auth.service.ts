import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable, catchError, map, of, tap } from 'rxjs';

import { environment } from '../../environments/environment';

/** What /api/auth/me tells the frontend about the signed-in user. */
export interface Me {
  username: string;
  display_name: string;
  is_admin: boolean;
  must_change_password: boolean;
  folders: string[];
  spreadsheets: string[];
  databases: string[];
}

/**
 * Who is signed in. The session itself is an HttpOnly cookie the page can't read: the only way to know
 * is to ask the server (/me). `me$` is undefined until asked, null when signed out.
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly url = `${environment.apiUrl}/api/auth`;
  readonly me$ = new BehaviorSubject<Me | null | undefined>(undefined);

  constructor(private http: HttpClient) {}

  /** The current user, asking the server only the first time. */
  ensureLoaded(): Observable<Me | null> {
    const known = this.me$.value;
    if (known !== undefined) return of(known);
    return this.http.get<Me>(`${this.url}/me`).pipe(
      catchError(() => of(null)),
      tap((me) => this.me$.next(me)),
    );
  }

  login(username: string, password: string): Observable<Me> {
    return this.http.post<Me>(`${this.url}/login`, { username, password }).pipe(tap((me) => this.me$.next(me)));
  }

  logout(): Observable<void> {
    return this.http.post<void>(`${this.url}/logout`, {}).pipe(
      catchError(() => of(undefined)),
      tap(() => this.me$.next(null)),
    );
  }

  changePassword(currentPassword: string, newPassword: string): Observable<void> {
    return this.http
      .post<void>(`${this.url}/change-password`, { current_password: currentPassword, new_password: newPassword })
      .pipe(
        tap(() => {
          const me = this.me$.value;
          if (me) this.me$.next({ ...me, must_change_password: false });
        }),
      );
  }

  /** The session ended on the server (401): forget the user. */
  signedOut(): void {
    this.me$.next(null);
  }

  get isAdmin$(): Observable<boolean> {
    return this.me$.pipe(map((me) => !!me?.is_admin));
  }
}
