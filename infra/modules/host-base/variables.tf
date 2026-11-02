# infra/modules/host-base — o que todo o host da KAMBA tem ao fim do primeiro
# arranque, seja qual for o fornecedor.
#
# O criterio 2 do KAM-075 nomeia quatro coisas: «Docker, utilizador nao-root,
# WireGuard e disco NVMe». Sao estas quatro, e nada mais — o Compose de producao
# e o KAM-076, o TLS e o *edge* sao o KAM-077, e a observabilidade e o KAM-080.
#
# NAO SABE QUE FORNECEDOR EXISTE: produz um documento cloud-init como texto, e
# quem o entrega ao host e o modulo de fornecedor.

terraform {
  required_version = "1.10.6"
}

variable "ambiente" {
  description = "`staging` ou `prod`, de `env.yaml`."
  type        = string
}

variable "utilizador" {
  description = <<-EOT
    O utilizador nao-root que corre os servicos. Nao e o utilizador de
    administracao: ninguem entra por SSH com este (`docs/tecnica/08` §5, linha
    «Acesso humano»: «Sem SSH por palavra-passe», admin so por VPN WireGuard).
  EOT
  type        = string
  default     = "kamba"

  validation {
    condition     = var.utilizador != "root"
    error_message = "o criterio 2 do KAM-075 pede um utilizador nao-root."
  }
}

variable "chaves_ssh_de_administracao" {
  description = <<-EOT
    Chaves PUBLICAS de SSH dos administradores. Publicas: nenhuma chave privada
    passa por aqui, nem por `env.yaml`, nem pelo estado — o gate 9 varre a
    arvore e o DoD do ticket exige «sem segredos em codigo, estado de IaC ou
    logs».

    Vazia por omissao, e a lista vazia e o estado correcto hoje: nao ha host,
    nao ha administrador com acesso, e inventar uma chave aqui era pior do que
    nao ter nenhuma.
  EOT
  type        = list(string)
  default     = []
}

variable "ponto_de_montagem_nvme" {
  description = <<-EOT
    Onde o disco NVMe e montado. `/var/lib/kamba` porque e o que tem de estar no
    disco rapido: o volume do Postgres e o WAL (doc 09 §8.2 conta o restauro em
    minutos sobre este disco).
  EOT
  type        = string
  default     = "/var/lib/kamba"
}

variable "etiqueta_do_disco_nvme" {
  description = <<-EOT
    Etiqueta do sistema de ficheiros, usada em vez do nome do dispositivo.
    O nome (`/dev/nvme0n1`, `/dev/vdb`, `/dev/sdb`) e do FORNECEDOR, e usa-lo
    aqui era trazer o fornecedor para dentro de um modulo que nao o conhece —
    exactamente o que o criterio 6 proibe. A etiqueta sobrevive a troca.
  EOT
  type        = string
  default     = "kamba-dados"
}

variable "porta_wireguard" {
  description = <<-EOT
    Porta UDP do WireGuard. 51820 e a porta por omissao do WireGuard.

    *Proposta*: o `docs/tecnica/09` §3.2 regra 5 diz «sem portas publicas alem
    de 443» e o KAM-077 exige um *scan* externo onde «so 443 e a porta UDP do
    WireGuard» estejam abertas — nenhum dos dois fixa o numero. Quem o fixa para
    valer e o KAM-077, que e quem faz o *scan*.
  EOT
  type        = number
  default     = 51820
}

variable "referencia_do_segredo_wireguard" {
  description = <<-EOT
    A REFERENCIA do segredo, nunca o valor. A forma e
    `<projecto_de_segredos>/<ID_EM_MAIUSCULAS>`, e o `ID` e o do inventario do
    KAM-010 — aqui, `vpn_wireguard_admin` (`ops/secrets-inventory.yaml`).

    O `tools/env_lint` verifica que o projecto desta referencia e o do ambiente
    do modulo de raiz que a passou. Uma referencia de `prod` escrita em
    `staging` faz o gate 2 falhar: e o controlo do criterio 5.
  EOT
  type        = string
}
