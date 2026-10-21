-- Tables are managed exclusively by Ticket Alembic migrations.
SELECT format('CREATE ROLE ticket LOGIN PASSWORD %L', :'ticket_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ticket')
\gexec

SELECT 'CREATE DATABASE ticket OWNER ticket'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'ticket')
\gexec
