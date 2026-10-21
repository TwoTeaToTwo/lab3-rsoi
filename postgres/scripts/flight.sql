-- Tables are managed exclusively by Flight Alembic migrations.
SELECT format('CREATE ROLE flight LOGIN PASSWORD %L', :'flight_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'flight')
\gexec

SELECT 'CREATE DATABASE flight OWNER flight'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'flight')
\gexec
