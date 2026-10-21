-- Tables are managed exclusively by Bonus Alembic migrations.
SELECT format('CREATE ROLE bonus LOGIN PASSWORD %L', :'bonus_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'bonus')
\gexec

SELECT 'CREATE DATABASE bonus OWNER bonus'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'bonus')
\gexec
