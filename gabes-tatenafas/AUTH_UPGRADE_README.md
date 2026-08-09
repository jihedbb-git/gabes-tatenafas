# Authentication & Role Management Upgrade

Production-ready, secure, session-based authentication for Gabes Tatenafas.
Scope is strictly limited to authentication, authorization, RBAC, email
verification, password reset, and the database schema they require. No
dashboard, medical, school, or unrelated business logic was touched.

## What changed / was added

### Database (`db/auth_upgrade.sql`) - idempotent migration
- Extends `users.role` enum with `super_admin`.
- Adds to `users`: `first_name`, `last_name`, `phone`, `age`, `status`
  (`pending|active|suspended`), `email_verified_at`, `password_changed_at`,
  `created_by`, `updated_at`, `last_login_at`, `failed_login_attempts`, `locked_until`.
- Adds `UNIQUE(email)` + indexes on `status` and `role`.
- New tables: `auth_otps` (OTP codes), `auth_audit_log` (security events).
- Ensures `rate_limits` exists (reused by the existing rate limiter).
- Migrates existing active accounts to `status='active'` + verified so nothing breaks.
- Does NOT drop or alter any unrelated table.

### Backend
- `backend/config/auth_config.php` - all tunables (OTP TTL, rate limits, lockout,
  password policy, mail transport, super-admin seed).
- `backend/lib/rbac.php` - role constants, hierarchy, capability checks.
- `backend/lib/validation.php` - email / phone / password / name / age validators.
- `backend/lib/mailer.php` - mail sender (log / php / smtp transports).
- `backend/lib/auth.php` - rewritten core (registration, OTP, login by email,
  password reset, CSRF, brute-force lockout, audit logging, RBAC guards).
  Backward-compatible: `auth_user()`, `auth_require()`, `auth_logout()`,
  `role_allowed_routes()` keep their signatures.
- `backend/api/auth.php` - JSON API: me, csrf, login, logout, register,
  verify-email, resend-otp, forgot-password, verify-reset, reset-password.
- `backend/api/admin-users.php` - RBAC-protected user/role management API.
- `backend/scripts/seed_super_admin.php` - creates/resets the single Super Admin.

### Frontend (only the 5 auth pages; existing design language reused)
- `frontend/login.php` (email + password + Forgot Password link)
- `frontend/register.php` (first name, last name, phone, age, email, password, confirm)
- `frontend/verify-email.php` (OTP entry + resend)
- `frontend/forgot-password.php`
- `frontend/reset-password.php`
- `frontend/styles/auth.css` - small additive block for the new flow.

## Role mapping (important)
To preserve all existing modules that key off role strings, roles map as:

| Spec role    | Stored role key | Notes |
|--------------|-----------------|-------|
| Normal User  | `citizen`       | public self-registration |
| Doctor       | `health`        | existing medical role; granted by Admin |
| School       | `school`        | granted by Admin |
| Admin        | `admin`         | created by Super Admin |
| Super Admin  | `super_admin`   | single, seeded manually |

## Install steps
1. Back up your database.
2. Run the migration:
   ```
   mysql -u root gabes_tatenafas -e "source db/auth_upgrade.sql"
   ```
3. Edit `backend/config/auth_config.php`:
   - Set `APP_BASE_URL` to your install path.
   - Set `SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD`.
   - Choose `MAIL_MODE`: keep `log` for local dev (emails saved to
     `backend/logs/mail/*.eml`), or set `smtp` + SMTP creds for real email.
4. Seed the Super Admin (single account):
   ```
   php backend/scripts/seed_super_admin.php
   ```
   (or open http://localhost/gabes-tatenafas/backend/scripts/seed_super_admin.php from localhost)
5. Log in with the Super Admin email + password, then change the password.

## Email in local dev (WAMP/XAMPP)
WAMP/XAMPP cannot usually send real email. With `MAIL_MODE='log'`, every OTP
email is written to `backend/logs/mail/`. Open the latest `.eml` file to read
the 6-digit code during testing. Switch to `MAIL_MODE='smtp'` for production
(drop PHPMailer into `backend/lib/vendor/` or wire your own SMTP).

## User / role management API (for wiring into the existing Admin page)
All POST actions require a `csrf` token (GET `?action=csrf` on `api/auth.php`).

`backend/api/admin-users.php`:
- `GET  ?action=list[&role=&status=&q=]` - view users (Admin/Super).
- `POST ?action=create-admin` - Super Admin only.
- `POST ?action=suspend-admin | restore-admin | delete-admin` - Super Admin only.
- `POST ?action=suspend-user | restore-user` - Admin/Super.
- `POST ?action=set-role` `{user_id, role: citizen|health|school}` - Admin/Super
  (grant Doctor/School, or revert to Normal User).

The backend enforces every rule (only Super Admin manages Admins; Admins cannot
touch Super Admin; Admins can only assign Doctor/School/Normal). Add buttons to
your existing admin UI that call these endpoints - no dashboard redesign needed.

## Security features
- Bcrypt password hashing (`password_hash`).
- OTP codes stored hashed (bcrypt), single-use, expiring, attempt-limited.
- CSRF tokens on all auth + management POSTs.
- Brute-force lockout after repeated failed logins.
- Rate limiting on register / login / OTP send / OTP verify / reset.
- Session fixation protection (`session_regenerate_id`), hardened cookies.
- Full audit trail in `auth_audit_log`.
- User-enumeration-safe forgot-password responses.

## User Management page (now wired into the Admin panel)
A dedicated **User Management** page was added to the existing SPA (no redesign
of other pages):
- Sidebar link "User Management" appears automatically for `admin` and `super_admin`.
- Route `#/users` -> `frontend/pages/users.html` + `frontend/scripts/pages/users.js`
  + `frontend/styles/users.css`.
- Searchable/filterable user table with KPIs.
- **Super Admin** sees a "Create Admin" button and Suspend/Restore/Delete actions
  on Admin rows.
- **Admin** sees Make Doctor / Make School / Revert to Normal, plus Suspend/Restore
  on normal users. The Super Admin row is always shown as "Protected".
- All actions call `backend/api/admin-users.php` with a CSRF token fetched from
  `backend/api/auth.php?action=csrf`; the backend re-enforces every rule.

Files changed to wire it in (auth-scope only, additive):
- `frontend/index.php` - added nav entry, icon, `super_admin` role label,
  users.css link and users.js include.
- `frontend/scripts/router.js` - added the `#/users` route.
- `frontend/scripts/pages/dashboard-admin.js` - guard now also allows `super_admin`
  (so the Super Admin can open the existing Admin panel). No other logic changed.
- `backend/lib/auth.php` - `role_allowed_routes()` now includes `users` for
  admin + super_admin.
