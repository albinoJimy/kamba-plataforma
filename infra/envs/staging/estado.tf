# Estado do OpenTofu — cifrado, e NAO CONFIGURADO HOJE.
#
# O DoD do KAM-075 exige «estado de IaC cifrado». Nao ha bloco activo neste
# ficheiro, e a razao e de ordem e nao de esquecimento:
#
#   1. ONDE fica o estado e alojamento, logo ADR-008, logo **D1** — que esta
#      `em branco` (linha A1 do GoLive_Gate.md). Escolher o `backend` aqui era
#      escolher o alojamento.
#   2. NAO EXISTE ESTADO PARA CIFRAR. Nenhum ambiente foi aplicado: zero
#      recursos, zero ficheiros de estado. Ver `infra/README.md` §5.
#
# Quando a D1 fechar, este ficheiro recebe as duas metades:
#
#   terraform {
#     backend "<do fornecedor>" { ... }          # onde
#     encryption {                               # como
#       key_provider "..." "cofre" { ... }       # chave do cofre, nunca daqui
#       method "aes_gcm" "principal" { keys = key_provider....cofre }
#       state    { method = method.aes_gcm.principal }
#       plan     { method = method.aes_gcm.principal }
#     }
#   }
#
# A chave vem do cofre (KAM-010), nao de um ficheiro nem de uma variavel de
# ambiente de longa duracao — e a mesma regra do «sem chave estatica» do
# ADR-L007 §4, aplicada ao estado em vez de ao fornecedor.
#
# Estado desta afirmacao: **NAO VERIFICADO**. A cifra de estado do OpenTofu
# nunca foi exercitada nesta arvore, porque nunca houve estado.
