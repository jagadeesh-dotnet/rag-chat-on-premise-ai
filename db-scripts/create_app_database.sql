/*
  RagChatApp: the chat app's own data - accounts, roles, permissions, row rules, sessions, audit log.

  Run once as an administrator; safe to run again (creates only what is missing):
      sqlcmd -S localhost -E -i db-scripts\create_app_database.sql

  The app connects with Windows authentication and immediately runs
      EXECUTE AS USER = 'chat_app' WITH NO REVERT;
  so it can only read and write rows here: no schema changes, no other databases, and the audit log is
  append-only (UPDATE and DELETE denied).
*/

SET NOCOUNT ON;

IF DB_ID('RagChatApp') IS NULL
    CREATE DATABASE RagChatApp;
GO

USE RagChatApp;
GO

IF OBJECT_ID('dbo.users') IS NULL
CREATE TABLE dbo.users (
    id                   INT IDENTITY(1, 1) NOT NULL CONSTRAINT pk_users PRIMARY KEY,
    username             NVARCHAR(50)  NOT NULL CONSTRAINT uq_users_username UNIQUE,  -- case-insensitive collation
    display_name         NVARCHAR(100) NOT NULL,
    password_hash        VARCHAR(100)  NOT NULL,                -- bcrypt, never the password itself
    is_active            BIT           NOT NULL CONSTRAINT df_users_active DEFAULT 1,
    must_change_password BIT           NOT NULL CONSTRAINT df_users_must_change DEFAULT 1,
    created              DATETIME2(3)  NOT NULL,                -- all times are UTC
    last_login           DATETIME2(3)  NULL
);

IF OBJECT_ID('dbo.roles') IS NULL
CREATE TABLE dbo.roles (
    name        NVARCHAR(50)  NOT NULL CONSTRAINT pk_roles PRIMARY KEY,
    description NVARCHAR(200) NOT NULL CONSTRAINT df_roles_description DEFAULT '',
    builtin     BIT           NOT NULL CONSTRAINT df_roles_builtin DEFAULT 0
);

IF OBJECT_ID('dbo.user_roles') IS NULL
CREATE TABLE dbo.user_roles (
    user_id   INT          NOT NULL CONSTRAINT fk_user_roles_user REFERENCES dbo.users (id) ON DELETE CASCADE,
    role_name NVARCHAR(50) NOT NULL CONSTRAINT fk_user_roles_role REFERENCES dbo.roles (name) ON DELETE CASCADE,
    CONSTRAINT pk_user_roles PRIMARY KEY (user_id, role_name)
);

IF OBJECT_ID('dbo.role_grants') IS NULL
CREATE TABLE dbo.role_grants (
    role_name NVARCHAR(50)  NOT NULL CONSTRAINT fk_role_grants_role REFERENCES dbo.roles (name) ON DELETE CASCADE,
    kind      VARCHAR(20)   NOT NULL CONSTRAINT ck_role_grants_kind CHECK (kind IN ('folder', 'spreadsheet', 'database')),
    value     NVARCHAR(200) NOT NULL,      -- 'hr', '/' (top-level files), a table or database name, or '*'
    CONSTRAINT pk_role_grants PRIMARY KEY (role_name, kind, value)
);

-- Attributes of a user that row rules compare against, e.g. region = East (a user can have several values).
IF OBJECT_ID('dbo.user_attributes') IS NULL
CREATE TABLE dbo.user_attributes (
    user_id INT           NOT NULL CONSTRAINT fk_user_attributes_user REFERENCES dbo.users (id) ON DELETE CASCADE,
    name    NVARCHAR(50)  NOT NULL,
    value   NVARCHAR(200) NOT NULL,
    CONSTRAINT pk_user_attributes PRIMARY KEY (user_id, name, value)
);

-- Row-level rules: in <source>.<table_name>, <column_name> must match the user's <attribute>.
-- kind 'spreadsheet' (source = 'spreadsheets') or 'database' (source = database name from databases.json).
IF OBJECT_ID('dbo.row_rules') IS NULL
CREATE TABLE dbo.row_rules (
    id          INT IDENTITY(1, 1) NOT NULL CONSTRAINT pk_row_rules PRIMARY KEY,
    kind        VARCHAR(20)   NOT NULL CONSTRAINT ck_row_rules_kind CHECK (kind IN ('spreadsheet', 'database')),
    source      NVARCHAR(100) NOT NULL,
    table_name  NVARCHAR(128) NOT NULL,
    column_name NVARCHAR(128) NOT NULL,
    attribute   NVARCHAR(50)  NOT NULL,
    created     DATETIME2(3)  NOT NULL,
    CONSTRAINT uq_row_rules UNIQUE (kind, source, table_name, column_name)
);

IF OBJECT_ID('dbo.sessions') IS NULL
CREATE TABLE dbo.sessions (
    token_hash CHAR(64)     NOT NULL CONSTRAINT pk_sessions PRIMARY KEY,  -- SHA-256 of the cookie value
    user_id    INT          NOT NULL CONSTRAINT fk_sessions_user REFERENCES dbo.users (id) ON DELETE CASCADE,
    created    DATETIME2(3) NOT NULL,
    expires    DATETIME2(3) NOT NULL
);

IF OBJECT_ID('dbo.audit') IS NULL
CREATE TABLE dbo.audit (
    id       BIGINT IDENTITY(1, 1) NOT NULL CONSTRAINT pk_audit PRIMARY KEY,
    at       DATETIME2(3)   NOT NULL,
    user_id  INT            NULL,           -- who did it (NULL for failed logins of unknown users); no FK: kept forever
    username NVARCHAR(50)   NOT NULL,
    action   VARCHAR(40)    NOT NULL,       -- login_ok, login_failed, user_created, rule_added, ...
    detail   NVARCHAR(1000) NOT NULL CONSTRAINT df_audit_detail DEFAULT ''  -- never passwords
);

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_audit_user_action')
    CREATE INDEX ix_audit_user_action ON dbo.audit (username, action, at);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_sessions_expires')
    CREATE INDEX ix_sessions_expires ON dbo.sessions (expires);

IF NOT EXISTS (SELECT 1 FROM dbo.roles WHERE name = 'admin')
    INSERT INTO dbo.roles (name, description, builtin) VALUES ('admin', 'Full access and user management', 1);
GO

-- The identity the app runs as: rows only.
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'chat_app')
    CREATE USER chat_app WITHOUT LOGIN;
IF IS_ROLEMEMBER('db_datareader', 'chat_app') = 0
    ALTER ROLE db_datareader ADD MEMBER chat_app;
IF IS_ROLEMEMBER('db_datawriter', 'chat_app') = 0
    ALTER ROLE db_datawriter ADD MEMBER chat_app;
DENY UPDATE, DELETE ON dbo.audit TO chat_app;   -- the app can add audit entries, never change or remove them
PRINT 'RagChatApp ready';
GO
