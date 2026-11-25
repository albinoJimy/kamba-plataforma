"""Linha de comandos do caminho de *release* (KAM-078).

    python -m release lock gerar --construidos D.json --commit SHA [--saida F]
    python -m release lock verificar F
    python -m release lock diferencas NOVO ANTERIOR
    python -m release imagem --lock F --artefactos DIR (--cosign-chave K | --cosign-identidade I)
    python -m release aprovacao (--pr-json F | --pr N)
    python -m release pipeline
    python -m release smoke-guarda --ambiente A --numero N --projecto P --graph-base U [--producao F]
    python -m release reconciliar --ensaio F
    python -m release tag --tipo T [--anterior vX.Y.Z] --lock F --sboms DIR --verificacao F --destino DIR

Codigo de saida 0 = passa, 1 = recusado ou com achados, 2 = erro de utilizacao
ou de configuracao. **Um 2 nunca e verde**: uma configuracao que nao se le nao
pode parecer uma configuracao conforme.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import aprovacao, imagem, lock, pipeline, rolling, smoke, tag

COMPOSE_DE_PRODUCAO = Path("infra") / "compose" / "docker-compose.prod.yml"


def _json(caminho: str) -> dict:
    return json.loads(Path(caminho).read_text(encoding="utf-8"))


def _lock(args: argparse.Namespace, raiz: Path) -> int:
    if args.accao == "gerar":
        compose = lock.servicos_do_compose(raiz / COMPOSE_DE_PRODUCAO, raiz)
        construidos = _json(args.construidos) if args.construidos else {}
        gerado = lock.gerar(compose, {str(k): str(v) for k, v in construidos.items()}, args.commit)
        texto = gerado.como_json()
        if args.saida:
            Path(args.saida).write_text(texto, encoding="utf-8")
        else:
            sys.stdout.write(texto)
        return 0
    if args.accao == "verificar":
        lido = lock.ler(Path(args.ficheiros[0]))
        print(f"conforme: {len(lido.servicos)} servicos, {len(lido.construidos())} construidos")
        return 0
    novo, anterior = (lock.ler(Path(f)) for f in args.ficheiros[:2])
    for nome, (antes, depois) in novo.diferencas(anterior).items():
        print(f"{nome}: {antes} -> {depois}")
    return 0


def _imagem(args: argparse.Namespace, raiz: Path) -> int:
    lido = lock.ler(Path(args.lock))
    assinatura = imagem.Assinatura(
        chave=args.cosign_chave,
        identidade=args.cosign_identidade,
        emissor=args.cosign_emissor if args.cosign_identidade else None,
    )
    compose = lock.servicos_do_compose(raiz / COMPOSE_DE_PRODUCAO, raiz)
    achados = imagem.verificar(
        lido,
        Path(args.artefactos),
        assinatura,
        imagem.dispensadas_do_gate_14(raiz),
        construidos_no_compose={n for n, i in compose.items() if i is None},
    )
    for achado in achados:
        print(achado)
    print(f"gate 14: {len(achados)} achados em {len(lido.construidos())} imagens nossas")
    return 1 if achados else 0


def _aprovacao(args: argparse.Namespace, raiz: Path) -> int:
    if args.pr_json:
        pr = _json(args.pr_json)
    else:
        campos = "author,headRefOid,labels,reviews,files,changedFiles"
        saida = subprocess.run(
            ["gh", "pr", "view", str(args.pr), "--repo", args.repo, "--json", campos],
            capture_output=True, text=True, check=False,
        )
        if saida.returncode != 0:
            print(f"gh pr view falhou: {saida.stderr.strip()}", file=sys.stderr)
            return 2
        pr = json.loads(saida.stdout)
    decisao = aprovacao.decidir_com_raiz(pr, raiz)
    print(decisao)
    return 0 if decisao.passa else 1


def _pipeline(_args: argparse.Namespace, raiz: Path) -> int:
    achados = pipeline.verificar(raiz)
    for achado in achados:
        print(achado)
    print(f"lint do pipeline: {len(achados)} gates saltados sem registo")
    return 1 if achados else 0


def _smoke_guarda(args: argparse.Namespace, raiz: Path) -> int:
    numeros = ids = None
    if args.producao:
        dados = _json(args.producao)
        numeros = [str(n) for n in dados.get("numeros", [])]
        ids = [str(i) for i in dados.get("phone_number_ids", [])]
    alvo = smoke.Alvo(args.ambiente, args.numero, args.phone_number_id, args.projecto, args.graph_base)
    try:
        smoke.guardar(alvo, smoke.producao_declarada(raiz, numeros, ids or ()), raiz)
    except smoke.SmokeAbortado as excepcao:
        print(f"ABORTADO: {excepcao}")
        return 1
    print(f"guarda: o alvo em {args.ambiente} nao e producao")
    return 0


def _reconciliar(args: argparse.Namespace, _raiz: Path) -> int:
    dados = _json(args.ensaio)
    resultado = rolling.reconciliar(
        [str(i) for i in dados.get("enviados", [])],
        [str(i) for i in dados.get("processados", [])],
        [str(i) for i in dados.get("respostas", [])],
        {str(k): float(v) for k, v in (dados.get("acks_ms") or {}).items()},
        esperadas=int(args.esperadas),
    )
    print(resultado.resumo())
    return 0 if resultado.verde else 1


def _tag(args: argparse.Namespace, _raiz: Path) -> int:
    lido = lock.ler(Path(args.lock))
    versao = tag.proxima_versao(args.anterior, args.tipo)
    verificacao = tag.VerificacaoPosDeploy.de_json(_json(args.verificacao))
    pasta = tag.arquivar(versao, lido, Path(args.lock), Path(args.sboms), verificacao, Path(args.destino))
    print(f"v{versao}: arquivado em {pasta}")
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="release", description="caminho de release (KAM-078)")
    p.add_argument("--root", default=".")
    sub = p.add_subparsers(dest="comando", required=True)

    s = sub.add_parser("lock")
    s.add_argument("accao", choices=("gerar", "verificar", "diferencas"))
    s.add_argument("ficheiros", nargs="*")
    s.add_argument("--construidos")
    s.add_argument("--commit", default="")
    s.add_argument("--saida")

    s = sub.add_parser("imagem")
    s.add_argument("--lock", required=True)
    s.add_argument("--artefactos", required=True)
    s.add_argument("--cosign-chave")
    s.add_argument("--cosign-identidade")
    s.add_argument("--cosign-emissor", default=imagem.EMISSOR_DAS_ACTIONS)

    s = sub.add_parser("aprovacao")
    grupo = s.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--pr-json")
    grupo.add_argument("--pr", type=int)
    s.add_argument("--repo", default="albinoJimy/kamba-plataforma")

    sub.add_parser("pipeline")

    s = sub.add_parser("smoke-guarda")
    s.add_argument("--ambiente", required=True)
    s.add_argument("--numero", required=True)
    s.add_argument("--phone-number-id", default="")
    s.add_argument("--projecto", required=True)
    s.add_argument("--graph-base", required=True)
    s.add_argument("--producao")

    s = sub.add_parser("reconciliar")
    s.add_argument("--ensaio", required=True)
    s.add_argument("--esperadas", default=rolling.MENSAGENS_ESPERADAS)

    s = sub.add_parser("tag")
    s.add_argument("--tipo", required=True, choices=tag.TIPOS)
    s.add_argument("--anterior")
    s.add_argument("--lock", required=True)
    s.add_argument("--sboms", required=True)
    s.add_argument("--verificacao", required=True)
    s.add_argument("--destino", required=True)
    return p


_COMANDOS = {
    "lock": _lock, "imagem": _imagem, "aprovacao": _aprovacao, "pipeline": _pipeline,
    "smoke-guarda": _smoke_guarda, "reconciliar": _reconciliar, "tag": _tag,
}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    raiz = Path(args.root).resolve()
    if args.comando == "lock" and args.accao != "gerar" and len(args.ficheiros) < (
        2 if args.accao == "diferencas" else 1
    ):
        print(f"lock {args.accao}: faltam ficheiros", file=sys.stderr)
        return 2
    try:
        return _COMANDOS[args.comando](args, raiz)
    except (lock.LockInvalido, tag.TagRecusada) as excepcao:
        print(f"RECUSADO: {excepcao}")
        return 1
    except (OSError, ValueError, KeyError) as excepcao:
        print(f"erro: {excepcao}", file=sys.stderr)
        return 2
    except Exception as excepcao:  # noqa: BLE001 — o ci_waivers levanta os seus
        if type(excepcao).__name__ in ("WaiverInvalido", "ConfiguracaoIlegivel", "ConfiguracaoInvalida"):
            print(f"configuracao: {excepcao}", file=sys.stderr)
            return 2
        raise
