/*
  Read-only identity for the chat app.

  The app connects with Windows authentication (often a sysadmin account) and immediately runs
      EXECUTE AS USER = 'chat_reader' WITH NO REVERT;
  so the model's SQL only ever runs with these rights:
    - a user WITHOUT LOGIN: nobody can sign in as it
    - member of db_datareader only: can SELECT, can't change anything

  Run once as an administrator; safe to run again:
      sqlcmd -S localhost -E -i db-scripts\create_chat_reader.sql
*/

SET NOCOUNT ON;

USE Northwind;
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'chat_reader')
    CREATE USER chat_reader WITHOUT LOGIN;
IF IS_ROLEMEMBER('db_datareader', 'chat_reader') = 0
    ALTER ROLE db_datareader ADD MEMBER chat_reader;
PRINT 'Northwind: chat_reader ready';
GO

USE pubs;
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'chat_reader')
    CREATE USER chat_reader WITHOUT LOGIN;
IF IS_ROLEMEMBER('db_datareader', 'chat_reader') = 0
    ALTER ROLE db_datareader ADD MEMBER chat_reader;
PRINT 'pubs: chat_reader ready';
GO
