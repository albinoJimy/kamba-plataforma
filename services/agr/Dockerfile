# AGR — imagem multi-stage (KAM-001).
#
# O que esta imagem ja faz: instala as dependencias exclusivamente a partir de
# `requirements/runtime.txt` com `pip install --require-hashes`, sem resolucao e
# sem compilar nada no arranque, e corre como utilizador sem privilegios
# (`docs/tecnica/08` §4.8, `docs/tecnica/09` §3.2).
#
# A base vem por digest (KAM-067), registado em `ci/supply-chain/imagens.yaml`
# com a data e a fonte de onde se leu. O que esta imagem NAO faz: nao gera SBOM
# por imagem e nao e assinada — nao ha ainda pipeline que a construa e publique
# (KAM-078).
#
# Nota sobre os nossos proprios pacotes (`kamba_core`, `kamba_agr`): entram por
# `PYTHONPATH` e nao por `pip install`. Instala-los exigiria isolamento de
# construcao, que descarregaria `setuptools` **sem hash** e abriria exactamente o
# caminho que o `--require-hashes` fecha. Os `pyproject.toml` ficam como contrato
# de empacotamento para quando houver uma roda construida no CI.
ARG PYTHON_IMAGE=python:3.12-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

FROM ${PYTHON_IMAGE} AS deps
WORKDIR /app
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
COPY services/agr/requirements/runtime.txt ./runtime.txt
# `--no-deps`: o fecho esta completo no ficheiro (ver tools/pip_lock.py), e deixar
# o pip resolver anularia a garantia de que so entra o que foi revisto.
RUN python -m pip install --require-hashes --no-deps \
    --prefix=/install -r runtime.txt

FROM ${PYTHON_IMAGE} AS runtime
WORKDIR /app
ARG KAMBA_COMMIT_SHA=unknown
# HOST=0.0.0.0 e definido aqui, e nunca no codigo: dentro do contentor e preciso
# escutar na interface da rede do compose, mas correr o servico a mao na maquina
# de alguem continua a escutar so em 127.0.0.1 (DoD do KAM-001).
ENV HOST=0.0.0.0 \
    PORT=8000 \
    KAMBA_COMMIT_SHA=${KAMBA_COMMIT_SHA} \
    PYTHONPATH=/app/libs/py-core/src:/app/services/agr/src \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY --from=deps /install /usr/local
COPY libs/py-core libs/py-core
COPY services/agr/pyproject.toml services/agr/pyproject.toml
COPY services/agr/src services/agr/src
# `nobody` existe na imagem base; nao se cria utilizador para nao fixar um UID
# que a infraestrutura do KAM-075 possa querer escolher.
USER nobody
EXPOSE 8000
# O modulo le HOST e PORT do ambiente, como os servicos Node fazem. O 0.0.0.0
# vem do ENV acima e nao do comando: assim o mesmo codigo, corrido a mao,
# escuta so em 127.0.0.1.
CMD ["python", "-m", "kamba_agr"]
