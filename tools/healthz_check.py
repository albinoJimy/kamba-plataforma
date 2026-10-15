#!/usr/bin/env python3
"""Sonda `/healthz` de cada servico, validada contra o contrato.

E o teste de integracao que o KAM-001 exige: depois de `make up`, cada servico
responde 200 e a carga util conforma-se a
`packages/contracts/schemas/healthz.response.v1.json`.

Valida com `jsonschema` e nao com asercoes escritas a mao: o esquema e a fonte
unica das duas implementacoes (`packages/core-ts` e `libs/py-core`), e um
validador escrito a mao seria uma terceira definicao a divergir das outras duas.

    python tools/healthz_check.py gwy=3000 agr=8000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "packages" / "contracts" / "schemas" / "healthz.response.v1.json"


def _validator():
    try:
        from jsonschema import Draft202012Validator
    except ModuleNotFoundError:
        print(
            "healthz_check: falta 'jsonschema'. Corra 'make bootstrap' "
            "(instala tools/requirements/tools.txt com --require-hashes).",
            file=sys.stderr,
        )
        raise SystemExit(2) from None

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def probe(host: str, port: int, timeout: float) -> tuple[int, dict | None, str | None]:
    url = f"http://{host}:{port}/healthz"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            try:
                return response.status, json.loads(raw), None
            except json.JSONDecodeError as exc:
                return response.status, None, f"resposta nao e JSON: {exc}"
    except urllib.error.HTTPError as exc:
        return exc.code, None, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, None, str(exc)


def check(
    service: str, port: int, host: str, validator, retries: int, delay: float
) -> list[str]:
    """Tenta algumas vezes antes de desistir: `make up` acaba de levantar tudo."""
    problems: list[str] = []
    for attempt in range(1, retries + 1):
        status, body, error = probe(host, port, timeout=5.0)
        if status == 200 and body is not None:
            problems = [
                f"{service}: {e.json_path} — {e.message}"
                for e in validator.iter_errors(body)
            ]
            # O contrato nao sabe que servico devia responder nesta porta; so
            # este ficheiro sabe, e e por isso que se verifica aqui.
            if body.get("service") != service:
                problems.append(
                    f"{service}: a porta {port} respondeu como "
                    f"{body.get('service')!r}; portas trocadas no compose?"
                )
            if not problems:
                print(
                    f"    {service:<15} 200  versao {body['version']}  "
                    f"commit {body['commit']}"
                )
            return problems

        if attempt < retries:
            time.sleep(delay)

    return [f"{service}: nao respondeu em http://{host}:{port}/healthz — {error}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "targets",
        nargs="+",
        metavar="SERVICO=PORTA",
        help="por exemplo gwy=3000 agr=8000",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--retries", type=int, default=15)
    parser.add_argument("--delay", type=float, default=2.0)
    args = parser.parse_args(argv)

    validator = _validator()
    findings: list[str] = []
    for target in args.targets:
        if "=" not in target:
            parser.error(f"esperava SERVICO=PORTA, recebi {target!r}")
        service, _, raw_port = target.partition("=")
        findings += check(
            service, int(raw_port), args.host, validator, args.retries, args.delay
        )

    if findings:
        print(f"healthz_check: {len(findings)} achado(s)", file=sys.stderr)
        for finding in findings:
            print(f"  - {finding}", file=sys.stderr)
        return 1

    print(f"healthz_check: {len(args.targets)} servico(s) conformes ao contrato")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
