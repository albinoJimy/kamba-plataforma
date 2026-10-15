"""sbom — gate 11: SCA, licencas e SBOM (KAM-002).

Gera SBOM CycloneDX por alvo e verifica as licencas dos componentes instalados
contra `ci/licenses.yaml`.

**Fronteira com o KAM-067**, que o ticket manda nao duplicar: aqui e por **PR**,
sobre o codigo-fonte e os lockfiles; la e por **imagem** e por **release**, com
digests, cosign e quarentena. O gerador e o mesmo, e e por isso que vive em
`tools/` e nao em `ci/supply-chain/`.

A lista de bloqueio nao se reimplementa: o gate 11 chama `lint_arch deps`.
"""

__all__ = ["main"]

from .cli import main
