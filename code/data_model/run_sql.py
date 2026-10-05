#!/usr/bin/env python3
"""Execute a .sql file statement-by-statement against a Databricks SQL warehouse.

Uses the SQL Statement Execution API via the Databricks CLI (`databricks api`).
Splits statements with a quote/comment-aware parser so semicolons inside string
literals or `--` comments don't break the split.

Usage:
    python3 run_sql.py --profile <cli_profile> --warehouse <warehouse_id> --file 01_tables.sql

Example (AI Parts Wizard):
    python3 run_sql.py \
      --profile <cli_profile> \
      --warehouse <warehouse_id> \
      --file 01_tables.sql
"""
import argparse, json, re, subprocess, sys, time


def split_statements(text: str) -> list[str]:
    """Split SQL into statements, ignoring ';' inside single-quoted strings and -- comments."""
    stmts, buf = [], []
    i, n, in_str = 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            buf.append(c)
            if c == "'":
                in_str = False
            i += 1
            continue
        if c == "-" and i + 1 < n and text[i + 1] == "-":          # line comment
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "'":
            in_str = True
            buf.append(c)
            i += 1
            continue
        if c == ";":
            s = "".join(buf).strip()
            if s:
                stmts.append(s)
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def api(profile: str, method: str, endpoint: str, body: dict | None = None) -> dict:
    cmd = ["databricks", "api", method, endpoint, "--profile", profile]
    if body is not None:
        cmd += ["--json", json.dumps(body)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return {"_err": r.stderr.strip() or r.stdout.strip()}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"_raw": r.stdout}


def label(stmt: str) -> str:
    m = re.search(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+\S+\.(\w+)", stmt, re.I)
    return m.group(1) if m else stmt[:40].replace("\n", " ")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", required=True)
    p.add_argument("--warehouse", required=True)
    p.add_argument("--file", required=True)
    args = p.parse_args()

    stmts = split_statements(open(args.file).read())
    print(f"Parsed {len(stmts)} statement(s) from {args.file}")
    failures = 0
    for stmt in stmts:
        nm = label(stmt)
        resp = api(args.profile, "post", "/api/2.0/sql/statements",
                   {"warehouse_id": args.warehouse, "statement": stmt,
                    "wait_timeout": "50s", "on_wait_timeout": "CONTINUE"})
        if "_err" in resp:
            print(f"[ERR ] {nm}: {resp['_err'][:200]}"); failures += 1; continue
        sid = resp.get("statement_id")
        state = resp.get("status", {}).get("state")
        while state in ("PENDING", "RUNNING"):
            time.sleep(3)
            resp = api(args.profile, "get", f"/api/2.0/sql/statements/{sid}")
            state = resp.get("status", {}).get("state")
        if state == "SUCCEEDED":
            print(f"[ OK ] {nm}")
        else:
            err = resp.get("status", {}).get("error", {})
            print(f"[FAIL] {nm}: {state} {err.get('message', '')[:200]}"); failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
