Clean customer data using PostgreSQL. A raw CSV lives at /app/data/customers.csv.
Import it into PostgreSQL, clean the data inside the database, and export the
cleaned result to /app/data/cleaned_customers.csv.

Environment:
- A PostgreSQL server is reachable at 127.0.0.1:5432 (database `customers_db`,
  user `postgres`, trust auth — no password needed) whenever your script runs.
  During development you can (re)start it yourself with
  `bash /usr/local/bin/pg-up.sh`.

Steps and rules:
1. Create table: customers (id INTEGER, name VARCHAR, email VARCHAR, phone VARCHAR, city VARCHAR).
2. Import /app/data/customers.csv using client-side \COPY (the file has NO header row).
3. Clean the data IN postgres: remove duplicate rows, lowercase all emails, strip every
   non-digit character from phone numbers, and delete rows missing BOTH email AND phone.
4. Export to /app/data/cleaned_customers.csv WITH a header row, ordered by id ascending.

You MUST perform the transformations inside PostgreSQL. The verifier inspects
pg_stat_statements for evidence of the UPDATE/DELETE cleaning statements AND of
client-side \COPY (which the server records as COPY ... FROM STDIN and
COPY ... TO STDOUT) — so use psql's \COPY, not server-side COPY and not an
external tool. A solution that edits the CSV with sed/pandas/awk and never
touches postgres will fail the database and pg_stat_statements checks.

Your deliverable is the single file /app/clean.sh: a shell script containing the
psql commands that create the table, \COPY-import the data, clean it in the
database, and \COPY-export /app/data/cleaned_customers.csv. The verifier extracts
/app/clean.sh into a fresh container, starts its own PostgreSQL, runs your script
against it, and then grades the resulting database and CSV. Assume the server is
already running at 127.0.0.1:5432 when clean.sh executes; do not start postgres
from within clean.sh.
