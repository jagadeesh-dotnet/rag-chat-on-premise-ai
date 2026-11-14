import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { map } from 'rxjs';

import { AuthService } from './auth.service';

/**
 * Guards only decide what to show; the server checks every request anyway.
 * A page the user can't use simply redirects, instead of loading and then failing.
 */

/** Signed in and the password isn't temporary. */
export const signedInGuard: CanActivateFn = (_route, state) => {
  const router = inject(Router);
  return inject(AuthService)
    .ensureLoaded()
    .pipe(
      map((me) => {
        if (!me) return router.createUrlTree(['/login'], { queryParams: { returnUrl: state.url } });
        if (me.must_change_password) return router.createUrlTree(['/change-password']);
        return true;
      }),
    );
};

export const adminGuard: CanActivateFn = (route, state) => {
  const router = inject(Router);
  return inject(AuthService)
    .ensureLoaded()
    .pipe(
      map((me) => {
        if (!me) return router.createUrlTree(['/login'], { queryParams: { returnUrl: state.url } });
        if (me.must_change_password) return router.createUrlTree(['/change-password']);
        return me.is_admin ? true : router.createUrlTree(['/']);
      }),
    );
};

/** The change-password page needs a session, but works with a temporary password. */
export const sessionGuard: CanActivateFn = () => {
  const router = inject(Router);
  return inject(AuthService)
    .ensureLoaded()
    .pipe(map((me) => (me ? true : router.createUrlTree(['/login']))));
};
