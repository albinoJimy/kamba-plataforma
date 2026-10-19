"""Um conjunto documental minimo, em memoria, que se escreve num directorio.

**Porque e que as *fixtures* se constroem e nao se escrevem a mao.** Cada teste
negativo deste gate e «o conjunto, com **uma** coisa errada». Escrever um
`INDICE.md` inteiro por caso dava quinze ficheiros quase iguais, e a diferenca
que importa — o campo mutado — ficava escondida no meio deles. Aqui o teste
muda um campo e manda escrever; o que nao se ve no teste e igual ao caso bom.

**Os identificadores constroem-se em tempo de execucao** (`kam(4)` e nao
`'KAM-004'`). O gate 3 (`lint_refs`) le o conteudo de todos os ficheiros
seguidos pelo git e recusa qualquer `KAM-NNN` que nao exista no backlog mestre:
uma *fixture* com um identificador inventado escrito por extenso punha o gate 3
vermelho, e seria este ficheiro a fazer o repositorio falhar.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from pathlib import Path


def kam(numero: int) -> str:
    """O identificador de um ticket, construido e nunca escrito por extenso."""
    return f'KAM-{numero:03d}'


def epic_de(numero: int) -> str:
    return f'EPIC-{numero:02d}'


#: Nome por extenso de cada epic da *fixture*, como o §4 e os blocos o escrevem.
NOMES = {1: 'Fundações e Dados', 2: 'Canais WhatsApp e Handoff'}
#: Nome do ficheiro de cada epic.
FICHEIROS = {1: 'specs/EPIC-01_Fundacoes_Dados.md',
             2: 'specs/EPIC-02_Canais_WhatsApp_Handoff.md'}


@dataclass
class Ticket:
    numero: int
    epic: int
    titulo: str
    tipo: str = 'chore'
    estimativa: str = 'M'
    prioridade: str = 'P0'
    fase: str = '0'
    #: Dependencias, como texto ja formado (`'KAM-001, ext:D6'`) ou `None` para
    #: derivar de `depende_de`.
    dependencias: str | None = None
    depende_de: tuple[int, ...] = ()
    bloqueia: tuple[int, ...] = ()
    #: Quando verdadeiro, o bloco sai sem tabela de campos (caso de codigo 2).
    sem_campos: bool = False
    #: Sobreposicoes do bloco, para divergir de proposito de um campo do §4.
    no_bloco: dict = field(default_factory=dict)
    #: Sobreposicoes da linha da «Tabela Resumo» do §3.
    no_resumo: dict = field(default_factory=dict)
    #: Quando falso, o ticket nao tem linha no §4 (bloco orfao).
    no_indice: bool = True
    #: Quando falso, o ticket nao tem bloco (linha orfa).
    tem_bloco: bool = True
    #: Quando falso, o ticket nao tem linha no §3 do seu epic.
    no_resumo_do_epic: bool = True

    @property
    def id(self) -> str:
        return kam(self.numero)

    @property
    def deps(self) -> str:
        if self.dependencias is not None:
            return self.dependencias
        return ', '.join(kam(x) for x in self.depende_de) or '—'

    @property
    def bloqueia_texto(self) -> str:
        return ', '.join(kam(x) for x in self.bloqueia) or '—'

    def campo(self, nome: str, omissao: str) -> str:
        return self.no_bloco.get(nome, omissao)

    def no_resumo_campo(self, nome: str, omissao: str) -> str:
        return self.no_resumo.get(nome, omissao)


def tickets_por_omissao() -> list[Ticket]:
    """Cinco tickets coerentes: tres no EPIC-01, dois no EPIC-02.

    O EPIC-01 tem os blocos em `specs/tickets/` (convencao do KAM-155) e o
    EPIC-02 tem-nos dentro do proprio ficheiro: as *fixtures* cobrem as duas
    formas, porque e nas duas que o gate le.
    """
    return [
        Ticket(1, 1, 'Monorepo, estrutura de serviços e toolchain',
               bloqueia=(2, 3)),
        Ticket(2, 1, 'Pipeline de CI base', depende_de=(1,), bloqueia=(4,)),
        Ticket(3, 1, 'Schema `platform` e migrações reversíveis',
               tipo='feature', estimativa='L', depende_de=(1,)),
        Ticket(4, 2, 'GWY: webhook Meta', tipo='feature', estimativa='L',
               prioridade='P1', fase='1', depende_de=(2,)),
        Ticket(5, 2, 'CHR: ChannelResolver por `phone_number_id`',
               tipo='feature', prioridade='P1', fase='1'),
    ]


@dataclass
class Conjunto:
    """O conjunto inteiro, mutavel, que se escreve num directorio."""

    tickets: list[Ticket] = field(default_factory=tickets_por_omissao)
    #: `{numero do epic: numero declarado no §3.1}`; `None` = o real.
    quantos_no_inventario: dict[int, int] = field(default_factory=dict)
    #: `{numero do epic: intervalo declarado no §3.1}`; ausente = o derivado.
    intervalo_no_inventario: dict[int, str] = field(default_factory=dict)
    total_declarado: int | None = None
    intervalo_total: str | None = None
    quantos_no_proposito: int | None = None
    epics_no_proposito: int | None = None
    #: `{caminho relativo: [versoes]}` do «Controlo de versoes» de cada epic.
    versoes: dict[str, list[str]] = field(default_factory=dict)
    #: `{caminho relativo: versao do cabecalho}`.
    cabecalhos: dict[str, str] = field(default_factory=dict)
    #: Texto a acrescentar ao fim do ficheiro de um epic (para o tornar ilegivel).
    extra_no_epic: dict[int, str] = field(default_factory=dict)
    #: Conteudo bruto de `ci/backlog-allow.yaml`, ou `None` para nao o escrever.
    allow: str | None = None

    def clonar(self) -> 'Conjunto':
        return copy.deepcopy(self)

    def ticket(self, numero: int) -> Ticket:
        for t in self.tickets:
            if t.numero == numero:
                return t
        raise KeyError(numero)

    def substituir(self, numero: int, **campos) -> None:
        for indice, t in enumerate(self.tickets):
            if t.numero == numero:
                self.tickets[indice] = replace(t, **campos)
                return
        raise KeyError(numero)

    # -- renderizacao -------------------------------------------------------

    @property
    def epics(self) -> list[int]:
        return sorted({t.epic for t in self.tickets if t.no_indice})

    def do_epic(self, epic: int) -> list[Ticket]:
        return [t for t in self.tickets if t.epic == epic and t.no_indice]

    def _intervalo(self, numeros: list[int]) -> str:
        if not numeros:
            return '—'
        return f'{kam(min(numeros))} – {kam(max(numeros))}'

    def _controlo(self, caminho: str) -> str:
        linhas = self.versoes.get(caminho, ['1.0'])
        corpo = '\n'.join(
            f'| {v} | Outubro 2026 | Emenda de teste. | Equipa KAMBÁ |'
            for v in linhas)
        return ('\n## Controlo de versões\n\n'
                '| Versão | Data | Descrição | Autor |\n|---|---|---|---|\n'
                f'{corpo}\n')

    def _indice(self) -> str:
        linhas = [
            '# Backlog Executável — KAMBÁ',
            '',
            f'**Versão do conjunto:** {self.cabecalhos.get("specs/INDICE.md", "1.0")}',
            '',
            '## 1. Propósito',
            '',
        ]
        presentes = sorted(t.numero for t in self.tickets if t.no_indice)
        quantos = (self.quantos_no_proposito if self.quantos_no_proposito
                   is not None else len(presentes))
        quantos_epics = (self.epics_no_proposito if self.epics_no_proposito
                         is not None else len(self.epics))
        linhas += [
            f'Decompõe o trabalho em **{quantos} tickets atómicos '
            f'({kam(min(presentes))} a {kam(max(presentes))})** distribuídos por '
            f'**{quantos_epics} epics**.',
            '',
            '## 2. Estrutura do conjunto',
            '',
            'Nada a dizer aqui.',
            '',
            '## 3. Inventário de tickets',
            '',
            '### 3.1 Por epic',
            '',
            '| Epic | Range | N.º tickets | Fase |',
            '|------|-------|-------------|------|',
        ]
        soma = 0
        for epic in self.epics:
            numeros = [t.numero for t in self.do_epic(epic)]
            quantos_epic = self.quantos_no_inventario.get(epic, len(numeros))
            soma += quantos_epic
            intervalo = self.intervalo_no_inventario.get(
                epic, self._intervalo(numeros))
            linhas.append(f'| {epic_de(epic)} {NOMES[epic]} | {intervalo} | '
                          f'{quantos_epic} | 0–1 |')
        total = self.total_declarado if self.total_declarado is not None else soma
        intervalo_total = (self.intervalo_total if self.intervalo_total is not None
                           else self._intervalo(presentes))
        linhas += [
            f'| **TOTAL** | **{intervalo_total}** | **{total}** | — |',
            '',
            '### 3.2 Fases',
            '',
            'Nada a dizer aqui.',
            '',
            '## 4. Backlog mestre (contrato entre epics)',
            '',
        ]
        for epic in self.epics:
            linhas += [
                f'### {epic_de(epic)} — {NOMES[epic]}',
                '',
                '| ID | Título | Tipo | Est. | Prio | Fase | Dependências |',
                '|---|---|---|---|---|---|---|',
            ]
            for t in self.do_epic(epic):
                linhas.append(
                    f'| {t.id} | {t.titulo} | {t.tipo} | {t.estimativa} | '
                    f'{t.prioridade} | {t.fase} | {t.deps} |')
            linhas.append('')
        linhas += ['## 5. Como usar o backlog', '', 'Nada a dizer aqui.', '']
        return '\n'.join(linhas) + self._controlo('specs/INDICE.md')

    def _bloco(self, t: Ticket, ligacao: bool = False) -> str:
        if t.sem_campos:
            return (f'## {t.id} — {t.titulo}\n\n### Contexto\n\n'
                    'Sem tabela de campos.\n')
        campos = [
            ('Epic', t.campo('epic', f'{epic_de(t.epic)} — {NOMES[t.epic]}')),
            ('Fase', t.campo('fase', t.fase)),
            ('Tipo', t.campo('tipo', t.tipo)),
            ('Prioridade', t.campo('prioridade', t.prioridade)),
            ('Estimativa', t.campo('estimativa', t.estimativa)),
            ('Dependências', t.campo('dependencias', t.deps)),
            ('Bloqueia', t.campo('bloqueia', t.bloqueia_texto)),
            ('Responsável sugerido', 'Engenheiro de Plataforma'),
        ]
        tabela = '\n'.join(f'| {nome} | {valor} |' for nome, valor in campos)
        titulo = t.campo('titulo', t.titulo)
        return (f'## {t.id} — {titulo}\n\n| Campo | Valor |\n|---|---|\n'
                f'{tabela}\n\n### Contexto\n\nNada a dizer aqui.\n')

    def _epic(self, epic: int) -> str:
        caminho = FICHEIROS[epic]
        linhas = [
            f'# {epic_de(epic)} — {NOMES[epic]}',
            '',
            '| Campo | Valor |',
            '|---|---|',
            f'| Versão | {self.cabecalhos.get(caminho, "1.0")} |',
            '| Data | Outubro de 2026 |',
            '',
            '## 1. Visão do Epic',
            '',
            'Nada a dizer aqui.',
            '',
            '## 3. Tabela Resumo de Tickets',
            '',
            '| ID | Título | Tipo | Estimativa | Prioridade | Dependências |',
            '|---|---|---|---|---|---|',
        ]
        for t in self.do_epic(epic):
            if not t.no_resumo_do_epic:
                continue
            celula = (f'[{t.id}](tickets/{t.id}.md)' if epic == 1 else t.id)
            linhas.append(
                f'| {celula} | {t.no_resumo_campo("titulo", t.titulo)} | '
                f'{t.no_resumo_campo("tipo", t.tipo)} | '
                f'{t.no_resumo_campo("estimativa", t.estimativa)} | '
                f'{t.no_resumo_campo("prioridade", t.prioridade)} | '
                f'{t.no_resumo_campo("dependencias", t.deps)} |')
        linhas.append('')
        texto = '\n'.join(linhas)
        if epic != 1:
            # Os dez epics que nao sao o EPIC-01 tem os blocos dentro.
            for t in self.tickets:
                if t.epic == epic and t.tem_bloco:
                    texto += '\n' + self._bloco(t)
        texto += self.extra_no_epic.get(epic, '')
        return texto + self._controlo(caminho)

    def escrever(self, raiz: Path) -> Path:
        (raiz / 'specs' / 'tickets').mkdir(parents=True, exist_ok=True)
        (raiz / 'ci').mkdir(parents=True, exist_ok=True)
        (raiz / 'specs' / 'INDICE.md').write_text(self._indice(), encoding='utf-8')
        for epic in sorted(NOMES):
            (raiz / FICHEIROS[epic]).write_text(self._epic(epic), encoding='utf-8')
        for t in self.tickets:
            if t.epic == 1 and t.tem_bloco:
                (raiz / 'specs' / 'tickets' / f'{t.id}.md').write_text(
                    self._bloco(t), encoding='utf-8')
        if self.allow is not None:
            (raiz / 'ci' / 'backlog-allow.yaml').write_text(
                self.allow, encoding='utf-8')
        return raiz
