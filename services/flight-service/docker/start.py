"""Container entry point: configure credentials, migrate, then replace the process."""

import os
import subprocess
import sys

from sqlalchemy.engine import URL

if "FLIGHT_DATABASE_URL" not in os.environ:
    os.environ["FLIGHT_DATABASE_URL"] = URL.create(
        "postgresql+asyncpg",
        username="flight",
        password=os.environ["FLIGHT_DB_PASSWORD"],
        host="postgres",
        port=5432,
        database="flight",
    ).render_as_string(hide_password=False)

subprocess.run(["alembic", "-c", "alembic.ini", "upgrade", "head"], check=True)
os.execv(sys.executable, [sys.executable, "-m", "flight_service.main"])
