"""supply_chain — o que o KAM-067 acrescenta ao gate 11 (KAM-002).

O KAM-002 ja entrega SBOM por servico, a allowlist de licencas e o varrimento de
vulnerabilidades (`tools/sbom`), e o KAM-001 a lista de bloqueio
(`tools/lint_arch`). Nada disso se repete aqui. O que este pacote acrescenta e o
que faltava para a cadeia de abastecimento ser fail-closed **no repositorio**:

* `imagens`   toda a imagem referenciada esta fixada por digest e consta do
              inventario `ci/supply-chain/imagens.yaml`, com o estado da
              assinatura cosign;
* `runtime`   nenhuma instalacao em runtime, instalacoes de build so a partir
              do lockfile, contentores com sistema de ficheiros so de leitura;
* `egress`    cada servico declara a sua lista de saidas, negado por omissao;
* `licencas`  o registo de licencas por versao (`ci/supply-chain/licencas.yaml`)
              e coerente com a politica, com a lista de bloqueio e com o que
              esta no repositorio;
* `renovate`  a quarentena de versoes novas nao foi desligada;
* `ci`        os workflows nao usam chaves estaticas;
* `canario`   a prova, **no gate**, de que cada verificacao falha perante o
              defeito: o repositorio e copiado, sofre uma mutacao de cada vez, e
              cada uma tem de dar vermelho pela regra certa.

O que **nao** esta aqui, por depender de infra-estrutura que nao existe: gerar
SBOM por imagem, assinar e publicar imagens, e correr `cosign verify` contra um
registo (KAM-078). A fronteira esta em `docs/supply-chain.md`.

So biblioteca padrao: corre antes de qualquer instalacao, como o `lint_arch`.
"""

__all__ = ["main"]

from .cli import main
