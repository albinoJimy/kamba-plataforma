# Canais de acesso a PMEs: fichas, rondas e decisão por canal

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — fichas dos cinco canais de acesso a PMEs, regra de «repetível» e decisão de distribuição |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-106 (EPIC-10) |
| Estado | NÃO VERIFICADO — nenhum canal foi contactado; as cinco fichas nascem vazias |
| Fonte | `../../../exploracao/14-tese-minima-e-plano-de-validacao.md` §3 (ponto 1), §5, §6; `../../../../specs/EPIC-10_Spikes_Validacao_Gates.md` (bloco KAM-106, critérios 5 a 7) |
| Dono | Responsável de Produto; a decisão de distribuição, se for precisa, é do fundador |
| Documento-fonte | `../../../exploracao/14-tese-minima-e-plano-de-validacao.md` §3, §6; `../../10_Onboarding_Governanca.md` §12 |
| Relacionados | [`Entrevistas_Guiao.md`](Entrevistas_Guiao.md), [`Canais_Rondas.csv`](Canais_Rondas.csv), [`PMEs_Lista_Alvo.csv`](PMEs_Lista_Alvo.csv) |

> **As fichas nascem vazias, e é assim que devem nascer.** Abrir um canal é
> uma reunião, e as reuniões são humanas. Nenhuma associação, banco,
> incubadora ou gabinete foi escolhido aqui: a coluna «quem» é preenchida por
> quem fizer a reunião, e os **contactos não entram neste ficheiro** — vivem no
> arquivo controlado, como os das PMEs
> ([`Entrevistas_Consentimento.md`](Entrevistas_Consentimento.md) §4).
>
> **«Repetível» é proposta** (bloco do KAM-106, critério 5), fixada antes da
> primeira reunião; muda só por emenda registada.

---

## 1. Os cinco canais

Os quatro primeiros são os que `14` §3 (ponto 1) nomeia; o quinto escolhe-o
quem conduzir as reuniões, e regista aqui porquê.

| Id | Tipo | Porque é candidato (`14` §3) |
|---|---|---|
| C1 | Contabilistas e gabinetes de contabilidade | Já falam com PMEs sobre NIF, facturação e AGT — é a hipótese principal |
| C2 | Associações comerciais | Alternativa a testar em paralelo |
| C3 | Programas PME de bancos | Alternativa a testar em paralelo; é também uma das saídas da decisão de distribuição (`14` §6) |
| C4 | Incubadoras | Alternativa a testar em paralelo |
| C5 | Outro (a escolher) | O critério 5 pede «1 outro»; a escolha e a razão escrevem-se na ficha |

O `id` é o que a ficha das entrevistas leva em `canal_origem`, e o que o
[`Canais_Rondas.csv`](Canais_Rondas.csv) leva em `canal`.

## 2. A oferta ao canal

A mesma para os cinco, e escrita antes da primeira reunião:

- **Comissão só por PME que pague** (`14` §5, rubrica «Incentivos a
  parceiros»). Nada por indicação, nada por entrevista. O valor da comissão
  **não está fixado** em nenhum documento do conjunto, e não se inventa aqui:
  fica por decidir antes de se fazer a oferta.
- O que se pede ao canal: indicar PMEs do segmento A (formais ou em
  formalização, com NIF e conta bancária — `../../10_Onboarding_Governanca.md`
  §12) dispostas a uma entrevista de 25 minutos, **sem *pitch***.
- As regras de comunicação do §12 valem também para o canal: nada de «não deixa
  rasto», «escapa à AGT» ou «não regista vendas», e o INAPEM não serve de
  argumento.

## 3. As fichas

Uma por canal. Os campos são os do critério 5, mais o dono e a razão da decisão.

| Campo | C1 | C2 | C3 | C4 | C5 |
|---|---|---|---|---|---|
| Quem (entidade, no arquivo controlado) | | | | | |
| Razão da escolha (obrigatória no C5) | — | — | — | — | |
| Contacto | no arquivo | no arquivo | no arquivo | no arquivo | no arquivo |
| Data da 1.ª reunião | | | | | |
| Oferta feita (§2) | | | | | |
| PMEs-alvo entregues (total, de [`Canais_Rondas.csv`](Canais_Rondas.csv)) | | | | | |
| Rondas com entrega | | | | | |
| Entrevistas obtidas (completas, pelo *script*) | | | | | |
| Estado | | | | | |
| Repetível (§4) | | | | | |
| Decisão até à semana 6: manter / descartar | | | | | |
| Dono e data da decisão | | | | | |

Valores de `Estado`: `a contactar`, `reunião marcada`, `a entregar`,
`descartado`. As três linhas de números não se escrevem à mão: saem do
`scripts/entrevistas_h2.py` (`--rondas`), para que a ficha e a medição não
possam discordar.

### 3.1 As rondas

[`Canais_Rondas.csv`](Canais_Rondas.csv) é o modelo vazio, com uma linha por
entrega de um canal:

| Coluna | Valores |
|---|---|
| `canal` | `C1` … `C5` |
| `ronda` | identificador da ronda (por exemplo `1`, `2`) |
| `data` | `AAAA-MM-DD` |
| `pmes_alvo_entregues` | inteiro ≥ 0 |

Não tem nomes nem contactos — só contagens —, mas preenchido é dado do
terreno: vive ao lado da ficha das entrevistas, no arquivo controlado.

## 4. Repetível, e a decisão de distribuição

**Um canal é repetível se entregou ≥ 6 PMEs-alvo em ≥ 2 rondas** (*proposta*,
critério 5). O *script* lê-o como total ≥ 6 e pelo menos duas rondas com
entrega; uma ronda com 0 PMEs não conta como ronda
([`Entrevistas_Guiao.md`](Entrevistas_Guiao.md) §5, item 6).

A decisão por canal (manter ou descartar) toma-se **até à semana 6**, com dono
e data na ficha.

**Se nenhum canal for repetível à semana 6**, aplica-se a última linha da
tabela de `14` §6: antes de construir mais, resolver a distribuição. A decisão
escreve-se aqui:

| Campo | Valor |
|---|---|
| Canais repetíveis à semana 6 | |
| Via escolhida (parceiro de banco, associação, contratar comercial) | |
| Dono | |
| Data | |
| Assinatura do fundador | |

## 5. A lista de PMEs-alvo

[`PMEs_Lista_Alvo.csv`](PMEs_Lista_Alvo.csv) é o modelo vazio da lista de 30
PMEs-alvo mais suplentes (critério 7):

| Coluna | Valores |
|---|---|
| `id_anonimo` | o mesmo id da ficha das entrevistas, se a PME for entrevistada |
| `categoria` | texto genérico, sem nome de marca |
| `categoria_vedada` | `S`, `N`, pela tabela do [`Entrevistas_Guiao.md`](Entrevistas_Guiao.md) §2 H |
| `canal_origem` | `C1` … `C5` |
| `papel` | `alvo`, `suplente` |

O `--lista` do *script* devolve a % da lista em categoria vedada (entrada do
KAM-088). A correspondência entre o id e a PME vive no arquivo controlado; a
lista que se entrega ao KAM-109 sai de lá, não deste repositório.

## 6. Tabela de aprovação

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Responsável de Produto | | | |
| Fundador (decisão de distribuição, se for precisa) | | | |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Emissão inicial, preparação do KAM-106 (lote 24). Cinco fichas de canal vazias (os quatro tipos de `14` §3 e um quinto a escolher), a oferta com comissão só por PME paga e o valor por fixar, o modelo das rondas e o da lista de PMEs-alvo, a regra de «repetível» como o *script* a lê, e o quadro da decisão de distribuição. Nenhum canal contactado, nenhuma entidade escolhida. | Equipa KAMBÁ |
