# A INTERFACE que um modulo de fornecedor tem de implementar.
#
# Um `provider-<nome>` futuro copia estas variaveis e estas saidas e preenche o
# meio com os recursos do seu fornecedor. O que nao pode fazer e acrescentar uma
# variavel que so o seu fornecedor entende: a interface e o contrato, e um
# campo proprietario nela era o fornecedor unico a entrar pela janela.

variable "ambiente" {
  description = "`staging` ou `prod`. Vem de `env.yaml`, nao se escreve a mao."
  type        = string

  validation {
    condition     = contains(["staging", "prod"], var.ambiente)
    error_message = "ambiente tem de ser `staging` ou `prod`; `dev` e Compose local e nao passa por aqui."
  }
}

variable "vcpu" {
  description = "Nucleos virtuais do host (doc 09 §6: 4 em staging, 8 em prod)."
  type        = number
}

variable "memoria_gb" {
  description = "Memoria do host em GB (doc 09 §6: 16 em staging, 32 em prod)."
  type        = number
}

variable "disco_gb" {
  description = <<-EOT
    Tamanho do disco NVMe em GB. O perfil P0 do doc 09 §4.4 diz «NVMe >= 200 GB»
    para producao. Nao esta em `env.yaml` de proposito: cresce com a base de
    dados, e o doc 09 §8.2 avisa que acima de 40 GB de BD o RTO de 2 h deixa de
    ser seguro — logo e um parametro de capacidade, nao uma linha da matriz.
  EOT
  type        = number

  validation {
    condition     = var.disco_gb >= 200
    error_message = "o perfil P0 do doc 09 §4.4 pede NVMe >= 200 GB."
  }
}

variable "cloud_init" {
  description = "O documento cloud-init, produzido por `host-base`. Opaco aqui."
  type        = string
  sensitive   = true
}

variable "dns_ttl_segundos" {
  description = "TTL dos registos. *Proposta* de 300 s (bloco do KAM-075)."
  type        = number
}

variable "etiquetas" {
  description = <<-EOT
    Etiquetas de custo por ambiente (ADR-018, criterio 7 do KAM-075).
    `kamba_env` e `kamba_data_class`, vindas de `env.yaml`.
  EOT
  type        = map(string)
}

variable "decisao_d1" {
  description = <<-EOT
    A referencia da decisao D1, vinda de `dados.decisao_d1` do `env.yaml`.
    `null` hoje, nos tres ambientes, porque a D1 esta `em branco` (linha A1 de
    `docs/tecnica/evidencia/validacao/GoLive_Gate.md`).

    E a PRIMEIRA das duas barreiras das saidas: sem referencia de D1 nao se
    escolhe fornecedor, logo nao se cria recurso nenhum. A forma da referencia
    esta em `specs/02_Dicionario_de_Dados_Canonico.md` §3.
  EOT
  type        = string
  default     = null
}

variable "fornecedor_implementado" {
  description = <<-EOT
    A SEGUNDA barreira, e e `false` por omissao porque ESTE modulo e a costura
    e nao um fornecedor: nao implementa nenhum, logo nao cria nada.

    Nenhum modulo de raiz passa esta variavel, pelo que ela e sempre `false`
    aqui. Existe como variavel, e nao como `false` literal nas precondicoes,
    porque o OpenTofu recusa uma condicao que nao olhe para nada — e o
    argumento dele e bom: uma barreira tem de afirmar alguma coisa. Um
    `provider-<nome>` real escreve-a `true`, porque ai e verdade.
  EOT
  type        = bool
  default     = false
}
