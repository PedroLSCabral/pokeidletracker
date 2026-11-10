# CLAUDE.md: guia rápido do PokeIdle Tracker

**Antes de mexer, leia [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).** Ele descreve onde está cada
coisa, o que cada módulo faz, o banco, as APIs e as receitas das mudanças comuns. Assim você não precisa
redescobrir o projeto lendo todos os arquivos. Abra só os módulos que a tarefa toca. O
[`docs/PLANO.md`](docs/PLANO.md) é o diário (o porquê das decisões); consulte quando precisar do histórico.

## Em uma frase
Um robô coleta o mercado do pokeidle.io com uma conta separada e grava num SQLite local
(`data/market.db`). Um painel web local (`http://127.0.0.1:8770`) analisa esses dados: preços,
revenda, alertas, botão vender, Pokémon e PvP. A bandeja do Windows mantém os dois rodando.

## Mapa de bolso
| Preciso mexer em… | Arquivo |
|---|---|
| Socket do jogo, agenda, reconexão | `src/robo.py` |
| Gravação de vendas, vitrine, itens, poda, agenda (`coleta`) | `src/coleta/coletor.py` |
| Esquema do banco, CSV/JSON do export, `connect()` | `src/coleta/importer.py` |
| Loja de Pokémon (tabelas e gravação) | `src/coleta/lojapk.py` |
| Revenda e alertas | `src/analise/sinais.py` |
| Botão vender | `src/analise/venda.py` |
| Preço justo e busca de Pokémon | `src/analise/pokemon.py` |
| XP por hora de caça (motor rápido) | `src/analise/caca.py` |
| PvP (Tracker público) | `src/analise/pvp.py` |
| Rotas da API | `src/painel.py` (`Handler.do_GET`/`do_POST`) |
| Página (abas, janelas, estilos) | `src/web/index.html`, `app.js`, `app.css` |
| Ícone da bandeja e supervisão | `src/bandeja.py` |
| Janelinha de status | `src/mini.py` |
| Menu do botão direito da bandeja | `src/menu_bandeja.py` |
| Cores e fontes das janelas Tk | `src/tema.py` (as mesmas do `app.css`) |
| Pastas e arquivos do projeto | `src/caminhos.py` |
| Avisos (Windows, Discord, Telegram) | `src/notificar.py` |

## Regras que não podem ser quebradas
1. **Termos de Uso do jogo:** nada de contornar limites nem sobrecarregar o servidor. Um export por hora, pausas entre páginas, cache e 1,5 s entre pedidos no Tracker.
2. **Nada de VPS ou VM:** a equipe do jogo proibiu. Não proponha rodar em nuvem.
3. **Nunca entre nas contas do dono** (no navegador ou em script). Uma conexão nova derruba a outra (código 4001), e as contas dele rodam no Idle Deck.
4. **O `config.local.json` tem o token da conta coletora:** não imprima, não commite, não mande para fora. `data/` também fica fora do git.
5. **O repositório é público:** nada de nick de terceiros, dados pessoais ou infraestrutura pessoal.

## Convenções
- **Idioma:** código, comentários, interface e commits em **português**. As mensagens de commit seguem o estilo do `git log`: título curto e corpo explicando o porquê.
- **Imports:** os programas (`robo`, `painel`, `bandeja`, `mini`) ficam em `src/`. Os módulos importam por pacote: `from coleta import importer`, `from analise import sinais`, `import caminhos`. Caminho novo entra em `caminhos.py`.
- **Banco:** sempre por `importer.connect()`. As tabelas são criadas por cada módulo com `CREATE TABLE IF NOT EXISTS`.
- **Painel e página sem dependências:** só a biblioteca padrão no Python e JS puro no navegador.
- **Fim de linha:** `.py` com LF e `.bat` com CRLF. No Windows, `Path.write_text` grava CRLF; para `.py`, use `write_bytes` ou `newline="\n"`.
- **Ao mudar estrutura, módulo, rota ou tabela, atualize `docs/ARQUITETURA.md` no mesmo commit.**

## Rodar e testar
- **Tudo:** `iniciar.bat`. A pokébola aparece na bandeja: duplo clique abre o painel, um clique abre o status, o botão direito abre o menu.
- **Religar depois de mudar Python:** use o menu da bandeja ou mate o processo `src\robo.py`/`src\painel.py`; a bandeja religa em ~30 s. Mudou `bandeja.py`, `menu_bandeja.py` ou `tema.py`? Use Sair no menu e ligue de novo. Mudanças em `src/web/` só pedem recarregar a página.
- **Painel de teste sem mexer no que está rodando:** `python src/painel.py --porta 8771` (já está em `.claude/launch.json`).
- **Robô sem tocar no jogo:** `python testes/teste_robo_sessao.py` (jogo falso, banco temporário).
- **Verificação rápida:**
  - `python -m py_compile src/*.py src/coleta/*.py src/analise/*.py`;
  - `node --check src/web/app.js`;
  - `curl` nas rotas `/api/*` da cópia de teste.
- **Experimentos que gravam no banco:** use uma cópia de `data/market.db`.
