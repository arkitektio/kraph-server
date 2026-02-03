-- Initialize Apache AGE extension for testdb
-- This runs after the database is created by POSTGRES_MULTIPLE_DATABASES
\c testdb
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
