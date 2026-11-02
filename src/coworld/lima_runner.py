"""Run two native NetLogo worlds, JaCaMo and the original SQL/HTTP router offline."""

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import mysql.connector
import requests

runtime = Path(os.environ["COWORLD_LIMA"])
output = Path(sys.argv[1]).resolve()
output.mkdir(exist_ok=False)
source = runtime / "source"
qualification = json.loads((runtime / "qualification.json").read_bytes())
for name, digest in qualification["files_sha256"].items():
    assert hashlib.sha256((runtime / name).read_bytes()).hexdigest() == digest, name
for name, digest in qualification["source"]["files_sha256"].items():
    assert hashlib.sha256((source / name).read_bytes()).hexdigest() == digest, name
shared = Path("/shared_volume")
shutil.copytree(source / "original/shared_volume", shared)
with Path("/etc/hosts").open("a") as hosts:
    hosts.write("\n127.0.0.1 api db modelo_1 modelo_2\n")
socket = output / "mysql.sock"
(output / "mysql-files").mkdir()
environment = {
    **os.environ,
    "PYTHONPATH": str(shared),
    "host": "api",
    "PYTHONUNBUFFERED": "1",
    "PATH": str(Path(sys.executable).parent) + ":" + os.environ["PATH"],
}
database = [
    str(runtime / "mysql/lib/ld-linux-x86-64.so.2"),
    "--library-path",
    str(runtime / "mysql/lib"),
    str(runtime / "mysql/bin/mysqld"),
    "--no-defaults",
    "--user=root",
    "--basedir=" + str(runtime / "mysql"),
    "--datadir=" + str(output / "database"),
    "--lc-messages-dir=" + str(runtime / "mysql/share"),
    "--secure-file-priv=" + str(output / "mysql-files"),
]
subprocess.run([*database, "--initialize-insecure"], check=True, timeout=120)
children = []
deadline = time.monotonic() + 3000
with ExitStack() as logs:
    try:
        db_log = logs.enter_context((output / "database.log").open("x"))
        db = subprocess.Popen(
            [
                *database,
                "--bind-address=127.0.0.1",
                "--socket=" + str(socket),
                "--pid-file=" + str(output / "mysql.pid"),
                "--innodb-buffer-pool-size=128M",
            ],
            stdout=db_log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        children.append(db)
        while "ready for connections" not in (output / "database.log").read_text():
            assert db.poll() is None, "native database exited before readiness"
            assert time.monotonic() < deadline, "database readiness deadline"
            time.sleep(0.1)
        connection = mysql.connector.connect(user="root", unix_socket=str(socket))
        cursor = connection.cursor()
        cursor.execute((shared / "db_file/MYSQL_DATABASE.sql").read_text())
        while cursor.nextset():
            pass
        cursor.execute("ALTER USER 'root'@'localhost' IDENTIFIED BY 'root'")
        connection.commit()
        cursor.close()
        connection.close()
        subprocess.run(
            [sys.executable, str(shared / "clean_simulation_files.py")],
            env=environment,
            check=True,
            timeout=30,
        )
        api_log = logs.enter_context((output / "api.log").open("x"))
        api = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("lima_api.py"))],
            cwd=shared,
            env=environment,
            stdout=api_log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        children.append(api)
        # TCP readiness without swallowing native startup exceptions.
        import socket as network

        ready = False
        while not ready:
            assert api.poll() is None, "native API exited before readiness"
            assert time.monotonic() < deadline, "API readiness deadline"
            with network.socket() as probe:
                ready = probe.connect_ex(("127.0.0.1", 5000)) == 0
            if not ready:
                time.sleep(0.1)
        assert (
            requests.get("http://127.0.0.1:5000/coworld-healthz", timeout=5).status_code
            == 200
        )
        listeners = [
            row.split() for row in Path("/proc/net/tcp").read_text().splitlines()[1:]
        ]
        native_listeners = {
            row[1]
            for row in listeners
            if row[3] == "0A" and int(row[1].split(":")[1], 16) in {3306, 5000}
        }
        assert native_listeners == {"0100007F:0CEA", "0100007F:1388"}
        (output / "transport-qualified.json").write_text(
            json.dumps(
                {
                    "private_loopback_services": [3306, 5000],
                    "all_native_listeners_bound_to_loopback": True,
                }
            )
            + "\n"
        )
        for name, command, cwd, extra in [
            ("router", [sys.executable, str(shared / "router.py")], shared, {}),
            (
                "jacamo",
                [
                    str(runtime / "java15/bin/java"),
                    "-Xmx512m",
                    "-cp",
                    str(runtime / "jacamo/classes")
                    + ":"
                    + str(runtime / "jacamo/lib/*"),
                    "jacamo.infra.JaCaMoLauncher",
                    "gold_miners.jcm",
                ],
                shared / "jacamo/jacamo_model",
                {},
            ),
            *[
                (
                    model,
                    [
                        str(runtime / "netlogo/netlogo-headless.sh"),
                        "--model",
                        str(shared / ("open_sugarscape_" + model + ".nlogo")),
                        "--experiment",
                        "experiment1",
                    ],
                    shared,
                    {"JAVA_HOME": str(runtime / "java8")},
                )
                for model in ["m1", "m2"]
            ],
        ]:
            path = (
                shared / "netlogo_output" / (name + "_output.txt")
                if name in ["m1", "m2"]
                else output / (name + ".log")
            )
            log = logs.enter_context(path.open("x"))
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env={**environment, **extra},
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            children.append(process)
        models = children[-2:]
        while any(model.poll() is None for model in models):
            assert all(child.poll() is None for child in children[:-2]), (
                "native supporting service exited"
            )
            assert time.monotonic() < deadline, "native Lima execution deadline"
            time.sleep(0.2)
        assert all(model.returncode == 0 for model in models), (
            "native NetLogo process failed"
        )
        # Quiesce every producer before the consistent database snapshot.
        for process in children[1:-2]:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=30)
        connection = mysql.connector.connect(
            user="root",
            password="root",
            unix_socket=str(socket),
            database="MYSQL_DATABASE",
        )
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
        with (output / "snapshot-final.jsonl").open("x") as snapshot:
            for table in ["m1", "m2", "m3", "router"]:
                cursor.execute("SELECT * FROM " + table + " ORDER BY id")
                for row in cursor:
                    snapshot.write(
                        json.dumps({"table": table, **row}, default=str) + "\n"
                    )
        connection.commit()
        cursor.close()
        connection.close()
    finally:
        for process in reversed(children):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=30)
shutil.copytree(shared, output / "shared_volume")
for script, arguments in [
    (
        "audit_snapshot.py",
        [str(output / "snapshot-final.jsonl"), str(output / "snapshot-audit.json")],
    ),
    (
        "audit_native.py",
        [str(output), str(output / "native-audit.json"), "--jacamo-log", "jacamo.log"],
    ),
]:
    subprocess.run(
        [sys.executable, str(source / script), *arguments], check=True, timeout=30
    )
(output / "complete.json").write_text(
    json.dumps(
        {
            "native_model_steps": {"m1": 1000, "m2": 1000},
            "historical_dependency_equivalence": False,
            "deployment": "colocated native processes; HTTP and SQL bind to private game-pod loopback",
        }
    )
    + "\n"
)
