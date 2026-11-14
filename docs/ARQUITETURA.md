# Arquitetura do PokeIdle Tracker

Este é o mapa técnico do projeto: onde está cada coisa, o que cada módulo faz, como os processos
conversam, o formato do banco e das APIs, e como fazer as mudanças mais comuns. Ele serve para
qualquer pessoa (ou IA) que vá mexer no código, para não ter que redescobrir o projeto do zero.

- **[`docs/PLANO.md`](PLANO.md)** é o diário: o porquê das decisões, as descobertas sobre o jogo, na ordem em que aconteceram.
- **[`CLAUDE.md`](../CLAUDE.md)** é o resumo de bolso, com as regras que não podem ser quebradas.
- **Este arquivo** descreve o **estado atual**. Quem mudar a estrutura, um módulo, uma rota ou uma tabela atualiza este arquivo no mesmo commit.

---

## 1. Visão geral

O pokeidle.io é um jogo idle de Pokémon com mercado de dinheiro real: as **gemas** podem ser sacadas
(a ~US$ 0,009 cada) e os **coins** são a moeda de jogo. O projeto:

1. **coleta** o mercado com uma conta separada (o robô): as vendas, a vitrine de itens e a loja de Pokémon;
2. **guarda** tudo num SQLite local (`data/market.db`);
3. **analisa** esses dados: preços, revenda, alertas, preço justo de Pokémon, quando e por quanto vender e PvP;
4. **mostra** num painel web local com o visual do jogo (`http://127.0.0.1:8770`) e avisa por Windows, Discord ou Telegram.

```
                       ┌─────────────────────── PC (Windows) ────────────────────────┐
 pokeidle.io           │                                                             │
 ┌──────────────┐  WS  │  bandeja.py  (ícone na bandeja; liga e vigia os dois abaixo) │
 │ socket do    │◄────►│   ├─ robo.py    sessão contínua no jogo → grava no banco      │
 │ jogo         │      │   └─ painel.py  servidor HTTP 127.0.0.1:8770 (API + página)   │
 └──────────────┘      │  mini.py     janelinha de status (um clique no ícone)         │
 ┌──────────────┐ HTTP │                                                             │
 │ /tracker/api │◄─────│  analise/pvp.py (pelo painel e pelo robô, sem login)          │
 └──────────────┘      │            data/market.db  ◄── todos leem/gravam aqui        │
                       └─────────────────────────────────────────────────────────────┘
```

Todo o código é Python 3.12+ e só depende de `websockets` (robô) e `pystray` + `pillow` (ícone).
O painel e a página não têm dependências: são HTML, CSS e JS puros, com gráficos em SVG próprio.

---

## 2. Estrutura de pastas

```
pokeidletracker/
├─ iniciar.bat              liga tudo (pythonw src\bandeja.py --abrir), sem janela de console
├─ requirements.txt         websockets, pystray, pillow
├─ README.md                apresentação e como usar
├─ CLAUDE.md                guia rápido para quem vai mexer no código (regras e atalhos)
├─ docs/
│  ├─ ARQUITETURA.md        este arquivo
│  └─ PLANO.md              diário do projeto (decisões e descobertas, em ordem)
├─ src/
│  ├─ bandeja.py            PROGRAMA: ícone na bandeja, supervisor do robô e do painel
│  ├─ robo.py               PROGRAMA: robô coletor (socket do jogo)
│  ├─ painel.py             PROGRAMA: servidor do painel (API JSON + arquivos de web/)
│  ├─ mini.py               PROGRAMA: janelinha de status (tkinter)
│  ├─ menu_bandeja.py       menu do botão direito no visual do jogo (Tk numa thread da bandeja)
│  ├─ tema.py               cores, fontes, moldura e pokébola das janelas Tk e do ícone
│  ├─ caminhos.py           todas as pastas e arquivos do projeto (RAIZ, DADOS, BANCO, CONFIG, WEB…)
│  ├─ notificar.py          avisos: Windows, Discord, Telegram
│  ├─ coleta/               o que GRAVA no banco
│  │  ├─ importer.py        esquema do SQLite, CSV/JSON do export, deduplicação, connect()
│  │  ├─ coletor.py         gravação compartilhada (vendas, vitrine, itens), agenda (tabela coleta), poda
│  │  └─ lojapk.py          tabelas e gravação da loja de Pokémon
│  ├─ analise/              o que LÊ o banco e calcula
│  │  ├─ sinais.py          revenda, barato/caro, liquidez, regras e disparo de alertas
│  │  ├─ venda.py           botão "vender": moeda, preço e momento
│  │  ├─ pokemon.py         preço justo de Pokémon, busca por orçamento, padrões do mercado
│  │  ├─ caca.py            XP por hora de caça de um Pokémon (motor rápido) e os dados do jogo que ele usa
│  │  ├─ evolucao.py        análise de um Pokémon só até a evolução final (nota, XP/h nível a nível, preço)
│  │  ├─ precificar.py      preço de venda de um Pokémon (rápido/normal/paciente) e até que nível vale evoluir/subir
│  │  ├─ arena.py           força no PvP (⚔ do PvP, duelo 1×1 do jogo) e se vale evoluir um Pokémon para o PvP
│  │  └─ pvp.py             aba PvP (Tracker público do jogo)
│  └─ web/                  a página do painel
│     ├─ index.html         estrutura das abas e janelas
│     ├─ app.js             toda a lógica da página (uma seção por aba)
│     └─ app.css            visual do jogo (tokens de cor e fontes em :root)
├─ testes/
│  └─ teste_robo_sessao.py  robô contra um jogo falso (sessão, queda, vitrine, poda)
├─ legado/                  primeira tentativa de coleta: userscript no navegador (não roda no Idle Deck)
│  ├─ userscript/pokeidle-coletor.user.js
│  └─ iniciar-coletor.bat   liga o servidor do userscript (src/coleta/coletor.py, porta 8765)
├─ .claude/launch.json      cópia do painel na porta 8771, para testar sem mexer no que está rodando
├─ config.local.json        (fora do git) nick + token da conta coletora, canais de alerta
└─ data/                    (fora do git) market.db, logs, robo_agora.json, inbox/ do importador e jogo/
                            (catalogo.json e welcome-dados.json, para o XP/h e a evolução)
```

**Como os imports funcionam.** Os quatro programas ficam em `src/` e põem `src/` no `sys.path`. Os
módulos importam por pacote: `from coleta import importer`, `from analise import sinais`,
`import caminhos`. Os módulos de `coleta/` que também rodam como script (`importer.py`, `coletor.py`)
têm uma guarda no topo que põe `src/` no caminho quando são executados direto.

**Por que os programas ficam na raiz de `src/`.** O atalho de inicialização do Windows aponta para
`src\bandeja.py`, e a bandeja liga `src\robo.py` e `src\painel.py` pelo nome. Mover um deles quebra a
inicialização com o Windows. Se for preciso mover, rode `python src/bandeja.py --instalar` de novo.

---

## 3. Processos e ciclo de vida

### `bandeja.py`: o supervisor
- **Como liga:** pelo `iniciar.bat`, pelo atalho em `shell:startup\PokeIdle Tracker.lnk` (que roda `pythonw src\bandeja.py`) ou por `python src/bandeja.py`.
- **Uma bandeja só:** o mutex `Local\PokeIdleTrackerBandeja` garante isso. Uma segunda só abre o navegador, e só se foi chamada com `--abrir`.
- **Liga o robô e o painel antes de importar o `pystray`.** Assim, se a biblioteca do ícone faltar, os dois rodam mesmo assim e aparece um aviso.
- **Os filhos (`class Filho`) rodam como `python.exe` com `CREATE_NO_WINDOW`,** sem janela nem botão na barra de tarefas.
  - O robô escreve o próprio `data/robo.log`; os tracebacks dele vão para `data/robo.erros.log`.
  - O painel escreve em `data/painel.log`.
  - A própria bandeja escreve em `data/bandeja.log`.
  - Um log com mais de 2 MB vira `.old` na próxima vez que o processo liga.
- **Quando um filho cai:**
  - com **código 3** (fatal), não religa e mostra uma notificação. É o caso de sessão recusada, robô duplicado ou porta ocupada;
  - com qualquer outro código, religa depois de 30 s. A espera dobra a cada queda seguida até 10 min e volta a 30 s depois de 10 min de pé.
- **Cliques no ícone, como na Steam** (`classe_icone()`, que estende o `pystray.Icon` e troca o `_on_notify`):
  - **duplo clique** abre o painel no navegador;
  - **um clique** abre o `mini.py`. Ele espera o tempo de duplo clique do Windows (`GetDoubleClickTime`) antes de agir, para um duplo clique não abrir as duas coisas;
  - **botão direito** abre o menu no visual do jogo (`menu_bandeja.py`).
- **Menu do botão direito:**
  - no topo, o estado do robô (com a fase de `robo_agora.json`), do painel e a hora do último registro;
  - Abrir painel e Status agora;
  - Ver log do robô e Abrir pasta de dados;
  - Reiniciar robô e Reiniciar painel;
  - Ligar junto com o Windows (cria ou apaga o atalho);
  - Sair.
- **Menu cinza do Windows:** o mesmo menu também existe como `pystray.Menu`. Ele só aparece se o menu próprio não abrir (sem Tk, ou um erro ao montar). O motivo vai para `data/bandeja.log`.
- **DPI:** a bandeja chama `SetProcessDpiAwareness(1)`, para o menu sair nítido em telas com escala.
- **Linha de comando:** `--instalar` e `--remover` cuidam do atalho de inicialização; `--abrir` abre o painel no navegador.

### `robo.py`: o coletor
- **Um robô por PC:** o mutex `Local\PokeIdleTrackerRobo` impede dois. Dois robôs na mesma conta se derrubam com o código 4001; um robô duplicado sai com código 3.
- **Sessão contínua** (`sessao()`): conecta em `wss://pokeidle.io`, manda `hello`, espera o `welcome` e **fica conectado**. A cada volta do laço:
  1. `tarefas_locais()`: os nomes dos itens (1 vez por dia), a poda da vitrine (1 vez por hora), a pré-carga do PvP (a cada 6 h, numa thread) e o catálogo de espécies do jogo (1 vez por dia, numa thread, `caca.baixar_catalogo`).
  2. Vê o que está na hora (`proximas_tarefas()`): o export (quando o jogo libera), a vitrine (a cada minuto) e a loja de Pokémon (a cada 3 h).
  3. Faz cada uma: `pedir_export()`, `ler_vitrine()`, `varrer_loja_pokemon()`. Depois, `checar_alertas()`.
  4. Dorme até a próxima tarefa (no mínimo 1 s, no máximo 10 min). Um ping a cada 25 s mantém a conexão viva.
- **Welcome:** ao entrar, `caca.guardar_welcome()` tira dele as hunts, as constantes de caça (e quantos fragmentos fazem uma Shiny Stone) e a tabela de tipos e grava em `data/jogo/welcome-dados.json` (o estado da conta não é guardado). Grava também `welcome-esqueleto.json`, só com as chaves, para conferir o formato quando o jogo mudar.
- **`Sessao`:**
  - um leitor em segundo plano filtra as mensagens que interessam e as põe numa fila;
  - `pedir()` descarta o que chegou sem ser pedido, envia e espera a resposta que satisfaz a condição;
  - o prazo estica enquanto o gateway manda `vivo` (fila de login);
  - um `sessao.renovada` com token novo é salvo no `config.local.json`.
- **Reconexão** (`rodar()`):
  - conexão fechada pelo jogo: espera 1 min, dobrando até 10 min, e zera depois de 10 min conectado;
  - **4001** (a conta foi aberta em outro lugar): espera 30 min, sem disputar a sessão;
  - qualquer outro erro: 5 min;
  - recusas fatais (`RECUSAS_FATAIS`: ban, token inválido…) param o robô com código 3.
- **Estado ao vivo:** `agora(**campos)` grava `data/robo_agora.json` de forma atômica. Os campos são fase, detalhe, progresso da loja, erro e `acordar_ms`. É isso que o `mini.py` lê.
- **Linha de comando:**
  - `--configurar` cola o JSON com nick e token;
  - `--uma-vez` faz uma volta só, para teste.

### `painel.py`: o servidor do painel
- **Servidor:** `ThreadingHTTPServer` em `127.0.0.1:8770`. `--porta N` troca a porta (a cópia de teste usa 8771).
- **GET:**
  - `/api/*` devolve JSON (ver a seção 7);
  - o resto serve os arquivos de `src/web/`.
- **POST:** só com `Content-Type: application/json`. Sem a permissão CORS, um site de fora não consegue mandar esse tipo de pedido para 127.0.0.1, então nenhuma página externa mexe nas regras.
- **Uma conexão SQLite por pedido** (`importer.connect()`).
- **Erros:**
  - `pvp.ErroPvP` vira 400 com a mensagem;
  - qualquer outra exceção vira 500 com `repr`.
- **Porta já em uso:** sai com código 3 (`allow_reuse_address = False`). No Windows, sem isso, dois servidores dividiriam a porta.

### `mini.py`: a janelinha de status
- **Janela:** tkinter, `-toolwindow` (sem botão na barra) e `-topmost`, no canto inferior direito da área de trabalho.
- **Uma janela só:** o mutex `Local\PokeIdleTrackerMini`. Uma segunda chamada traz a janela que já existe para a frente (`FindWindowW` pelo título).
- **O que mostra:**
  - um LED do robô (pelo mutex dele) e um do painel (por uma conexão na porta 8770);
  - a fase atual, lida de `robo_agora.json`, com barra de progresso na leitura da loja;
  - os próximos horários, lidos da tabela `coleta` só para leitura, com as mesmas contas do robô;
  - a última linha do `robo.log`.

### `menu_bandeja.py`: o menu do botão direito
- **`MenuBandeja`** sobe um `tk.Tk()` escondido numa thread própria da bandeja. `mostrar(x, y, estado, itens)` pode ser chamado de qualquer thread: o pedido entra numa fila que o Tk lê a cada 60 ms.
- **Itens:** `Item(texto, acao, ativo, marcado, destaque)`; `SEPARADOR` é `None`. Cada ação roda numa thread nova, para o menu não travar enquanto um processo reinicia.
- **Janela:** `Toplevel` sem moldura do Windows (`overrideredirect`) e por cima de tudo, com o canto de baixo à direita no mouse, sem sair da área útil do monitor (`MonitorFromPoint`).
- **Fecha** com Esc, ao perder o foco ou com um clique fora. O clique fora é vigiado com `GetAsyncKeyState`, porque o `FocusOut` nem sempre chega numa janela sem moldura.
- **Visual:** quadro de madeira, título com contorno e dois vãos (estado e ações). A linha sob o mouse fica roxa.

### `tema.py`: o visual das janelas Tk
- As cores do jogo (as mesmas do `app.css`), as fontes (`TEXTO` = Segoe UI, `TITULO` = Tahoma) e `FASES` (texto e cor de cada fase do robô).
- **Peças:** `moldura()` (quadro de madeira), `vao()` (área escura com filete), `titulo_contornado()` (Tahoma negrito branco com contorno, desenhado num `Canvas`) e `desenhar_pokebola()` (o ícone da bandeja, em pixel art 16×16).

---

## 4. Fluxo dos dados

| Origem (no jogo) | Quem pede | Quem grava | Tabela | Frequência |
|---|---|---|---|---|
| `csv.pedir` (export de vendas) | `robo.pedir_export` | `coletor.receber_vendas` → `importer.import_rows` | `trades`, `imports` | quando o jogo libera (1/h) |
| `market.itens` (vitrine) | `robo.ler_vitrine` | `coletor.receber_vitrine` | `vitrine` | a cada minuto |
| `market.listar` (loja de Pokémon) | `robo.varrer_loja_pokemon` | `lojapk.gravar` / `lojapk.finalizar` | `pk_anuncios`, `pk_varreduras` | a cada 3 h |
| `items.json` (público, HTTP) | `robo.baixar_itens` | `coletor.receber_itens` | `itens` | 1/dia |
| Tracker `/tracker/api/*` (HTTP) | `pvp.tracker` | `pvp.tracker` (cache) | `pvp_cache` | sob demanda, com cache; pré-carga a cada 6 h |

Os alertas (`sinais.avaliar`) rodam depois de cada coleta e gravam em `alertas_log`. O painel
consulta `/api/alertas/novos` a cada 30 s para tocar o som.

---

## 5. Banco de dados (`data/market.db`)

Cada módulo cria as suas tabelas com `CREATE TABLE IF NOT EXISTS`. Não há migração separada: as
colunas novas entram com `ALTER TABLE` dentro de `importer.connect()`.

| Tabela | Criada em | Para quê |
|---|---|---|
| `trades` | importer | Cada venda: `ts` ('YYYY-MM-DD HH:MM', horário de Brasília), `ts_ms` (exato, quando vem do robô), `kind` ('item' ou 'pokemon'), `name`, `base_name` (agrupável: "Common House", "Numel"), `serial`, `qty`, `currency` ('gems' ou 'coins'), `total`, `unit_price`, `seller`, `buyer`. Para Pokémon também `level`, `shiny`, `nota`, `iv_total`, `potencia`, `qualidade`. |
| `imports` | importer | Um registro por importação, com `gap_before = 1` quando pode ter faltado venda entre um export e outro. |
| `vitrine` | importer | Retrato da vitrine de itens, chave (`snap_ms`, `item_id`): `anuncios`, `unidades`, `min_gems`, `min_coins`, `media7_*` e `un7_*` (a média de 7 dias calculada pelo jogo). Fica de minuto em minuto por 3 dias e depois 1 a cada 15 min (`coletor.podar_vitrine`). |
| `itens` | importer | id → nome (e `icone`), vindos do `items.json` mais os `ITENS_ESPECIAIS` (fragmentos, casas, bicicletas, tickets). |
| `coleta` | importer | Chave/valor da agenda (ver abaixo). |
| `pk_anuncios` | lojapk | Cada anúncio da loja de Pokémon com a ficha completa: `species_id`, nível, shiny, nota, poder, IVs, stats, qualidade, potência, `tipos` (JSON), preço, moeda, vendedor, `ativo`, `primeiro_ms`, `visto_ms` e `sumiu_ms`. Um anúncio que some de uma varredura completa fica com `ativo = 0`. |
| `pk_varreduras` | lojapk | Uma linha por varredura: `snap_ms`, total de anúncios e se foi completa. |
| `alertas_regras` | sinais | Regras de alerta: `tipo` (oportunidade, abaixo, acima, variacao), `item` (NULL para qualquer item), `moeda`, `valor`, `ativo`. |
| `alertas_log` | sinais | Alertas disparados: `regra_id`, `item`, `moeda`, `valor`, `msg`, `ms`, `canais`. |
| `pvp_cache` | pvp | Respostas do Tracker: `chave` (rota + parâmetros), `ms` e `json`. |

**Chaves da tabela `coleta`** (todas em ms, gravadas por `coletor.put` e lidas por `coletor.get`):

| Chave | Quem grava | Significado |
|---|---|---|
| `export_liberado_em` | receber_vendas / receber_recusa | Quando o próximo export pode ser pedido (`esperaMs`/`restaMs` do jogo + 30 s) |
| `export_trava_ate` | rodar (em erro) / decidir_vez | Não pede export antes disso (um pedido sem resposta não trava para sempre) |
| `ultimo_export_em` | receber_vendas | Último export aceito |
| `vitrine_em` | receber_vitrine | Último retrato da vitrine |
| `vitrine_trava_ate` | decidir_vez (legado) | Trava do userscript |
| `vitrine_poda_em` | robo.tarefas_locais | Última poda da vitrine |
| `itens_em` | receber_itens | Último `items.json` baixado |
| `pokemon_em` / `pokemon_tentativa_em` | varrer_loja_pokemon | Última varredura completa e última tentativa (uma tentativa que falha espera 30 min) |
| `pvp_meta_em` | robo.tarefas_locais | Última pré-carga do PvP |
| `catalogo_jogo_em` | robo.tarefas_locais | Último catálogo de espécies do jogo baixado (para o XP/h) |

---

## 6. Comunicação externa

### 6.1 Socket do jogo (`wss://pokeidle.io`, JSON)
O robô usa só isto; o cliente do jogo tem muito mais.

| Envia | Recebe | Uso |
|---|---|---|
| `{"t":"hello","nick","token","delta":1,"dispositivo"}` | `welcome` (e `vivo` enquanto está na fila) | Login. O `dispositivo` é um UUID guardado no config |
| `{"t":"ping"}` a cada 25 s | — | Manter a sessão |
| `{"t":"csv.pedir","tipo":"mercado","filtros":{}}` | `csv` com `ok` + `mercado.linhas` + `esperaMs`, ou `recusa` {`chave`,`restaMs`} | Export de vendas, no máximo 1 por hora |
| `{"t":"market.itens"}` | `market` com `aba:"itens"`, `resumo` {item_id: {anuncios, unidades, minGold, minOrb}} e `medias` | Vitrine |
| `{"t":"market.listar", ...lojapk.FILTRO_TUDO, "moeda", "ordem", "pagina", "especieId":0}` | `market` com `aba:"vitrine"`, `linhas`, `total`, `pagina` e `porPagina` | Loja de Pokémon: 24 por página, teto na página 200, por isso as passadas do mais barato e do mais caro |
| — | `erro` {`chave`} | `RECUSAS_FATAIS` param o robô; `RECUSAS_ESPERAR` (rede cheia) tenta depois |
| — | `sessao.renovada` {`token`} | O token novo é salvo no config |
| — | fechamento com código **4001** | A conta foi aberta em outro lugar |

As moedas do jogo se chamam `orb` (gemas) e `gold` (coins).

### 6.2 Tracker público (`https://pokeidle.io/tracker/api/<rota>`, GET, JSON, sem login)
É o site do botão "Tracker" do PvP. O jogo avisa quando alguém pede rápido demais, então
`pvp.tracker()` espera 1,5 s entre pedidos e guarda cada resposta em `pvp_cache`.

| Rota | Parâmetros | O que traz | Cache |
|---|---|---|---|
| `jogador` | `nick` | `jogador`, `rank` (pontos, tierId, posição, V/D), `totais`, `pokemons` (por espécie), `counters` (para quem perde), `vitimas`, `golpes` e `partidas` (as 20 últimas, com `eu`/`ele` e `pks` dos dois times) | 5 min (o seu) / 6 h (os do topo) |
| `partidas` | `nick`, `temporada` | Mais partidas | — |
| `meta` | `ordem` (uso…), `limite`, `faixa` | Por espécie: `partidas`, `vitorias`, `winrate`, dano por entrada, sobrevivência, `tipos` | 6 h |
| `pokemon` | `id`, `faixa` | A espécie, os `counters` (de quem ela mais perde; o `winrate` da linha é o DELA), as `vitimas` e quem mais usa | 12 h |
| `ladder` | `pagina`, `limite`, `temporada` | Ranking com nick, pontos, V/D e tier | 6 h |
| `inicio`, `golpes`, `guilds`, `busca` | — | Não usadas hoje | — |

Valores de `faixa`: `todas` (sem parâmetro), `baixo`, `alto`, `bronze`, `prata`, `ouro`, `platina`, `diamante`, `mestre`.
Os ids de espécie do Tracker são os mesmos de `pk_anuncios.species_id` (Mega Sceptile = 3254 nos dois).

### 6.3 Outros
- **`https://pokeidle.io/assets/items.json`:** os nomes e ícones dos itens.
- **Ícones na página:** carregados direto de `pokeidle.io` pelo navegador. Nenhuma imagem do jogo fica no repositório.

---

## 7. API do painel (`painel.py`)

Todas as rotas GET aceitam `moeda=gems|coins` (o padrão é gems).

| Rota | Função | O que devolve |
|---|---|---|
| `GET /api/resumo` | `api_resumo` | Lista do mercado: mediana atual, variação de 24 h e 7 d, vendas de 24 h, menor anúncio e mini gráfico de 7 dias |
| `GET /api/item?nome=&janela=24h\|7d\|30d\|tudo` | `api_item` | Detalhe: estatísticas, série do gráfico (baldes), menor anúncio no tempo, vitrine e últimas vendas |
| `GET /api/item/serie?nome=&janela=&de=&ate=` | `api_item_serie` | Zoom do gráfico: a série de `[de, ate]` (ms) com baldes mais finos (até 5 min), o menor anúncio no trecho e o resumo (mediana, vendas, unidades). As suspeitas seguem a mediana da janela inteira |
| `GET /api/montagem` | `api_montagem` | Fragmentos × casa/bicicleta pronta (valor esperado por raridade) |
| `GET /api/venda?nome=&qtd=` | `api_venda` → `venda.analisar` | Botão vender: moeda, preços, momento e montagem |
| `GET /api/sinais` | `api_sinais` → `sinais.calcular` | Revenda, barato/caro, regras, log de alertas e canais |
| `GET /api/alertas/novos?desde=ms` | `api_alertas_novos` | Alertas gravados depois de `desde` (para o som) |
| `GET /api/pokemon?busca=&shiny=&limite=` | `api_pokemon` | Vendas recentes de Pokémon |
| `GET /api/pk/buscar?orcamento=&objetivo=&especie=&tipo=&pmin=&nivel=&nota=&shiny=&treinador=&pvp_nick=&pvp_faixa=&transferir=` | `pokemon.buscar` (+ `pvp.pesos_especies` se `objetivo` é `pvp` ou `ponte`; + `venda.cambio` se `ponte`) | Anúncios da loja ordenados pelo objetivo, com o XP/h de cada um (`xp_h`, `xp_hunt`) para o nível de treinador `treinador`. Com `objetivo=ponte`, traz `ponte` (piso, teto e, com `transferir` em gemas, a comissão, quanto recebe e o custo total) e `aviso_pvp` se o Tracker falhou |
| `GET /api/pk/padroes?dias=` | `pokemon.padroes` | Padrões do mercado de Pokémon |
| `GET /api/pk/evolucao?anuncio=` ou `?especie=&nivel=&qualidade=&potencia=&shiny=&hp=&atk=&def=&spAtk=&spDef=&speed=` (+ `&treinador=&alvo=&valor_hora=`; da ficha colada também `especie_id`, `st_<stat>`, `nota`, `poder`, `refino`) | `api_evolucao` → `evolucao.analisar` (trilha esticada até `precificar.horizonte`) + `precificar.precificar` | Um Pokémon (anúncio da loja ou ficha digitada) agora e em cada evolução final: nota projetada, stats, ⚔, XP/h, trilha nível a nível com o tempo e o preço justo. Em `precificacao`: os preços de venda de agora e, por evolução final (ou `subir`, se já é a última forma), o valor em cada nível e o melhor ponto para vender |
| `GET /api/pk/evolucao/pvp?` (a mesma ficha de `/api/pk/evolucao`, + `&treinador=&nick=&faixa=&forcar=`) | `api_evolucao_pvp` → `evolucao.analisar` (alvo Nv 150 se o Pokémon está abaixo) + `arena.avaliar` | Vale evoluir para o PvP: a forma de agora e cada evolução final com o ⚔ do PvP, a nota de PvP para o seu time (`pvp._pontuar`), a taxa no meta, os duelos contra as suas ameaças, o tempo até poder levar ao ranqueado, os anúncios dela já pronta e o `veredito` (`vale`, `melhora_fora`, `igual`, `nao`); `melhor` é o índice do melhor caminho. Sem `nick`, só o meta da faixa (padrão `alto`) |
| `GET /api/pk/especies` | `evolucao.especies` | Espécies do catálogo (com arte, sem mega) para o formulário, com `evolui` |
| `GET /api/pvp?nick=&faixa=&orcamento=&moeda=&forcar=` | `pvp.analisar` | Aba PvP inteira. `forcar=1` relê o seu perfil e o meta sem esperar o cache |
| `GET /api/status` | `api_status` → `coletor.status` | Estado da coleta e as últimas linhas do log |
| `POST /api/regras` | `post_regra` | Cria uma regra {tipo, item, moeda, valor} |
| `POST /api/regras/apagar`, `/api/regras/alternar` | `post_regra_acao` | {id} |
| `POST /api/alertas/testar` | `post_testar` | Manda uma notificação de teste |

---

## 8. Módulos, um por um

### `caminhos.py`
Constantes de caminho: `SRC`, `RAIZ`, `CONFIG`, `DADOS`, `BANCO`, `LOG_ROBO`, `AGORA_ROBO`, `WEB`,
`LEGADO` e `USERSCRIPT`. **Toda pasta ou arquivo novo do projeto entra aqui.**

### `notificar.py`
- `config()` lê o bloco `"alertas"` do `config.local.json`.
- `canais_ativos()` lista os canais configurados: `windows` (o padrão no Windows), `discord` e `telegram`.
- `enviar(titulo, texto)` devolve `(canais_ok, erros)`.
  - **Windows:** notificação por PowerShell (`_windows`).
  - **Discord:** webhook.
  - **Telegram:** Bot API.

### `coleta/importer.py`
- **Fuso:** `BRT` fixo em UTC−3, a hora do CSV do jogo.
- **Esquema:** a string `SCHEMA`, com trades, imports, vitrine, itens e coleta.
- **`connect(db_path)`** é o único jeito de abrir o banco. Ele cria as tabelas, migra as colunas novas e grava os `ITENS_ESPECIAIS`.
- **`parse_row`** lê uma linha do CSV.
- **`parse_json_row`** lê uma linha do export JSON, que é o que o robô recebe. A posição 8 traz os atributos do Pokémon.
- **`import_rows(con, rows, fonte)`** faz a deduplicação. O CSV não tem id e vai só até o minuto, então:
  - os minutos completos do arquivo substituem os do banco;
  - no minuto mais antigo, que pode estar cortado, fica a maior contagem de cada linha idêntica.
- **Linha de comando:** `python src/coleta/importer.py [arquivo.csv]` importa os CSVs de `data/inbox/` para `data/processed/`.

### `coleta/coletor.py`
- **Agenda:** `get`/`put` na tabela `coleta`; `agora_ms()`.
- **`receber_vendas` / `receber_recusa` / `receber_falha`** tratam o resultado do export e marcam o próximo horário (`ESPERA_PADRAO_MS` = 1 h, `MARGEM_MS` = 30 s).
- **`receber_vitrine`** grava um retrato. O log ganha uma linha só a cada 15 min (`VITRINE_RESUMO_MS`).
- **`podar_vitrine`** cuida do histórico: depois de `VITRINE_DETALHE_MS` (3 dias), sobra o primeiro retrato de cada faixa de 15 min.
- **`receber_itens`** grava os nomes dos itens.
- **`status`** monta o que a rota `/api/status` mostra.
- **Constantes:** `VITRINE_A_CADA_MS` (1 min) e `ITENS_A_CADA_MS` (1 dia).
- **Legado:** `decidir_vez`, `Handler` e `main()` formam o servidor HTTP do userscript, na porta 8765.

### `coleta/lojapk.py`
- **Constantes:**
  - `INTERVALO_MS`: 3 h entre varreduras;
  - `PAUSA_ENTRE_PAGINAS_S`: 1 s;
  - `ULTIMA_PAGINA`: 200;
  - `PASSADAS`: gemas e coins, do mais barato e do mais caro;
  - `FILTRO_TUDO`: o filtro neutro de `market.listar`;
  - `MOEDA`: orb vira gems e gold vira coins.
- **`preparar(con)`** cria as tabelas.
- **`gravar(con, linhas, t0)`** faz upsert dos anúncios.
- **`finalizar(con, t0, n, completa)`** registra a varredura. Se ela foi completa, marca como inativo o que não foi visto.

### `analise/sinais.py` (Fase 3)
- **`calcular(con, moeda)`** devolve, por item:
  - as medianas de 24 h e 7 d, sem outliers (fora de mediana ×/÷ 4);
  - vendas por dia e liquidez (alta ≥ 20, média ≥ 5);
  - a referência de revenda: a menor entre as medianas de 24 h e 7 d, e só com 10 ou mais vendas em 7 dias;
  - o líquido depois da taxa de 15% (em gemas a taxa é arredondada para cima), o lucro e a margem;
  - o desvio de 24 h contra 7 d e a variação de 7 dias.

  Um anúncio abaixo de referência ÷ 4 fica com `anuncio_fora = True` e não conta como revenda.
- **`TIPOS_REGRA`** tem quatro tipos: oportunidade (margem ≥ X%), abaixo (menor anúncio ≤ X), acima (mediana de 24 h ≥ X) e variacao (variação de 7 d ≥ X%).
- **`avaliar(con)`** confere as regras ativas.
  - O mesmo alerta não se repete por 6 h (`ESPERA_REPETIR_MS`), a menos que melhore 5%.
  - **`registrar`** grava em `alertas_log`.
  - O robô manda no máximo 5 alertas separados; o resto vai junto numa mensagem só.

### `analise/venda.py` (botão vender)
- **`analisar(con, nome, qtd, montagens, raridades)`** é a entrada.
  - **Moeda:** `cambio()` é a mediana ponderada da razão coins/gemas dos itens vendidos nas duas moedas em 48 h. O valor em coins vira gemas descontando mais 15%, a taxa da troca. Coins só ganha se render pelo menos `PREFERENCIA_GEMAS` (5%) a mais. Se o item quase não vende em gemas e vende bem em coins, a indicação é coins.
  - **Preço** (`analisar_moeda`):
    - *rápido:* o menor anúncio menos um passo, mas não abaixo do p10 das vendas;
    - *normal:* a mediana de 12 h;
    - *paciente:* o p75 de 48 h.

    Num mercado fino (menos de 5 vendas em 48 h), o normal vem da média de 7 dias do jogo. O preço rápido some quando ficar em 1º da fila seria dar o item (`anuncio_muito_baixo`).
  - **Momento** (`tendencia` + `_quando`):
    - a tendência é uma reta de Theil-Sen no log das medianas por hora, e a oscilação normal (sigma) sai dos resíduos dessa reta;
    - a tendência é comparada com a inclinação da média de 7 dias do jogo (`_tendencia_jogo`);
    - as saídas são `agora`, `esperar`, `segurar`, `misto`, `tanto_faz` e `sem_dados`;
    - `segurar` tem horizonte de no máximo `SEGURAR_MAX_DIAS` (3).
  - **Confiança e horário:** `_confianca` fica baixa com menos de 3 dias de coleta. `_melhor_hora` só aparece com 3 dias ou mais.
  - **Montagem:** `_montagem` compara vender 10 fragmentos com o valor esperado de montar.

### `analise/pokemon.py` (Fase 4)
- **`Comparaveis`** dá o preço justo de um Pokémon.
  - Com 5 ou mais vendas parecidas (mesma espécie, shiny, moeda, faixa de nível e de nota), usa a mediana delas.
  - As faixas: nível `FX_NIVEL` (<100, 100, 101-200, 201-500, 501-1000, 1000+) e nota `FX_NOTA` (3,5 / 3,7 / 3,9 / 4,1 / 4,3 / 4,5 / 5 / 6). As de nota acima de 4,3 entraram em 11/2026: antes uma nota 4,35 e uma nota 6 caíam na mesma faixa.
  - Senão, usa o modelo de multiplicadores em log: base da espécie × nível × nota × potência, ajustado por backfitting.
  - Uma espécie cujas vendas saem todas como fora da curva no 2º ajuste fica sem preço base: `preco_justo` confere `(especie, shiny) in base` antes de usar o modelo.
- **`taxa_venda`** calcula a comissão progressiva do jogo para Pokémon.
- **`lado_fisico(species_id, nivel, stats)`** diz quanto da força da espécie é física (0 a 1): os golpes do catálogo liberados no nível, cada um pesando poder ÷ recarga. Sem catálogo, o maior entre ATK e SP.ATK do Pokémon. Guarda em cache por (motor, espécie, nível).
- **`indice_caca(nivel, stats, ivs, fisico)`** é o dano na caça, pela fórmula de dano do jogo: `(2·nível/5 + 2) × (ATK·fisico + SP.ATK·(1−fisico)) × cadência / 100`. A cadência vem do IV de SPD (1 no IV 16, ~0,9 no 1, ~1,14 no 32). Ficam de fora o poder do golpe, a DEF do alvo e o STAB, que valem igual para todos. Os stats do anúncio já vêm no nível dele.
- **`nota_ivs(ivs, fisico)`** é a nota de 0 a 10 dos IVs individuais (`PESO_IV`): 40% o IV do ataque da espécie, 30% o de SPD, 10% cada HP, DEF e SP.DEF. Um IV de ataque ou SPD abaixo de `IV_RUIM` (11) tira até `CASTIGO_IV` (40%). Devolve nota, lado, os dois IVs-chave e os horríveis (`ruins`); a busca manda isso em `ivs_nota`.
- **`comparaveis(con)`** guarda o modelo de preço justo em memória e só o refaz quando entra venda nova (`MAX(rowid)` de `trades`) ou a hora vira. Ajustar do zero leva ~3 s; o painel o prepara ao ligar (`painel.aquecer`).
- **`buscar(...)`** procura na loja (`pk_anuncios`) os anúncios ativos dentro do orçamento e ordena pelo objetivo (`OBJETIVOS`):
  - `xp` ordena pelo XP/h (`caca.xp_do_anuncio`) na melhor hunt liberada para `nivel_treinador`. Funil: só os `FUNIL_XP` (200) melhores pelo índice de caça passam pela conta. Medido na loja inteira, o top 20 em XP/h sempre esteve entre os 100 que mais batem;
  - nos outros objetivos o XP/h é calculado só para os itens que aparecem na lista;
  - `caca` ordena pelo índice de caça; `custo`, pelo índice de caça por gema ou coin;
  - `equilibrado` pesa 60% o percentil do índice de caça e 40% o do desconto (só com confiança alta ou média);
  - `forte` ordena pelo ⚔ (`poder`) do jogo; `barganha`, pelo desconto; `nota`, pela nota;
  - `pvp` usa `pesos_pvp` por `species_id` (`PESO_PVP_ESPECIE`, 60%), o percentil do ⚔ (`PESO_PVP_PODER`, 15%) e o da nota dos IVs (`PESO_PVP_IVS`, 25%).
  - `ponte` (levar gemas de uma conta para a outra): só entram os anúncios até `FOLGA_PONTE` (15%) acima do piso, que é a mediana dos `PISO_K` (10) anúncios ativos mais baratos com os mesmos filtros (um anúncio isolado muito barato não vira o piso; os abaixo do piso também entram); se houver poucos, o teto sobe até o `MIN_PONTE`-ésimo (30) mais barato, sem passar de `TETO_PONTE` (1,5) × o piso. O orçamento, se vier, é teto. Ordena como o `pvp`, com o índice de caça e o preço de desempate. `_conta_ponte` faz a conta da transferência: comissão (`taxa_venda` em gemas), quanto a conta que anunciou recebe e o custo total em gemas com o 1º da lista (comissão + Pokémon pelo câmbio + `DIARIA_ANUNCIO_COINS`). No painel, se o Tracker falhar, a ponte segue só pelo ⚔ e devolve `aviso_pvp`.
- **Por que não o ⚔ para caçar:** no jogo (`shared/nota-pokemon.mjs`), `poder = nível × 10 × score`, e o score é a soma dos seis stats de nascimento numa escala de log entre o pior e o melhor nascimento possíveis. HP, DEF e SP.DEF pesam tanto quanto o ataque, e o log achata as diferenças: o dobro de ATK dá ~30% a mais de ⚔. Dividir o ⚔ pelo preço favorecia os baratos fracos.
- **`padroes(...)`** mostra volume, prêmios por atributo, espécies, horários e compradores.

### `analise/caca.py` (XP por hora de caça)
- **O que responde:** quanto XP/h um Pokémon faz hoje, na melhor hunt liberada para um nível de treinador, sem AoE, TM, bike, casa ou bônus. A explicação completa está no topo do arquivo.
- **Dados** (em `data/jogo/`, fora do git):
  - `catalogo.json`, montado por `baixar_catalogo()` como o cliente do jogo monta. Junta os quatro `assets/creatures*.json` e as correções (`creatures-audit-overrides.json`). Troca os golpes pelos das planilhas de balanceamento (`shared/golpes-planilhas.mjs`, lido por expressão regular em `ler_planilhas`). Injeta os golpes de assinatura de poder 600 (`injetar_golpes_600`) e acrescenta as megas com moveset próprio. Também monta a árvore de evolução (`e`, `a` e `pedras`, ver `analise/evolucao.py`);
  - `welcome-dados.json`, gravado pelo robô a cada login (`guardar_welcome`): as 1.043 hunts (nível e espécies com peso) e as constantes de caça.
- **`Motor`** carrega os dois uma vez (`motor()` recarrega quando os arquivos mudam e limpa o cache). `Motor.xp_h(species_id, nivel, stats, ivs, tipos, nivel_treinador)` devolve a melhor hunt com XP/h, abates/h, segundos de luta por abate e se morre às vezes.
- **Como fica rápido (~5 ms por Pokémon, contra segundos numa simulação completa):**
  1. só o nível de agora, sem a trilha nível a nível;
  2. uma estimativa fechada (`_estimar`) em todas as hunts liberadas, da mais alta para a mais baixa, com corte pelo teto de XP/h de cada hunt;
  3. a mini-luta (`_hunt`, 16 rolagens de HP, golpe a golpe, saltando os trechos só de Investida) só nas `CANDIDATAS` (8) melhores estimativas.
- **Medido:** contra a busca que simula todas as hunts, mesma hunt e mesmo número em 300 de 300 casos. Contra a calculadora da comunidade, a mesma hunt em 6 de 6 casos, com XP/h entre −15% e +17%.
- **`xp_do_anuncio(m, id, ...)`** é o atalho da busca: lê os JSON de `pk_anuncios` e guarda o resultado por (anúncio, nível do treinador).

### `analise/evolucao.py` (análise de um Pokémon até a evolução final)
- **Para que serve:** a busca avalia o Pokémon como está; aqui um Pokémon só (capturado, ou um anúncio pelo botão **Evoluir** da busca) é simulado até cada evolução final. A explicação completa está no topo do arquivo.
- **O que a evolução muda:** só as bases da espécie (e os golpes: a última forma ganha os de poder 600). Nível, IVs, qualidade, potência, shiny e refino ficam. Precisa do nível do destino e da pedra do tipo (shiny usa Shiny Stone).
- **Nota projetada:** `nota_pokemon` é o `notaPokemon` do jogo (`shared/nota-pokemon.mjs`) em Python, com o piso dos ancestrais (`Arvore.ancestrais`, o `anotarLinhagemDaNota` de `shared/linhagem-nota.mjs`): a nota nunca cai, sobe pelo menos 0,1 por estágio. É o mesmo número do "Potencial na evolução final" da calculadora do jogo (o servidor não o manda pronto). `poder` e `xp_total` (curva de XP do Pokémon, `⌊50/3·(L³−6L²+17L−12)⌉`) também são do cliente.
- **A árvore:** o `creatures.json` só tem `evolvesToId`/`evolveLevel`. `baixar_catalogo` baixa também `shared/evolucoes-cruzadas.mjs`, `shared/evolucoes-ramificadas.mjs`, `shared/pedras-evolucao.mjs` e `assets/creatures-sprites-lab.json`, lê as tabelas por expressão regular (`ler_tabelas`) e monta a árvore na ordem do cliente (`arvore_antes_dos_golpes`: cadeias truncadas e 600 → 100; `arvore_depois_dos_golpes`: Outland não evolui, elos entre gerações, nível padrão das ramificações, níveis corrigidos). Cada espécie do catálogo ganha `e` = `[[destino, nível, tipo da pedra], ...]` e `a: 0` se não tem arte jogável (`tem_arte`, o `temSpriteJogo`; destino sem arte não conta como evolução final). O catálogo ganha `pedras` (tipo → nome). Se os módulos falharem, o catálogo sai sem `e` e a análise avisa.
- **`analisar(ficha, nivel_treinador, nivel_alvo, comps, m)`:**
  - os stats de cada forma em cada nível saem de `(base + 2·IV) × nível/100 × fator`; num anúncio ou numa ficha colada do jogo o fator vem dos stats reais (já com lendário e refino), numa ficha digitada da fórmula (qualidade^exp × potência × shiny);
  - a trilha tem `PONTOS_TRILHA` (28) pontos em escala de log do nível de agora até o alvo, mais os níveis das evoluções. Em cada ponto, `Motor.xp_h` com a forma daquele nível; o tempo entre dois pontos é o XP que falta ÷ a média harmônica do XP/h nas duas pontas (com a forma do ponto de partida). Supõe evoluir assim que chega ao nível e que o Pokémon leva o XP inteiro do abate;
  - devolve `atual` e `finais` (um por evolução final, a melhor nota primeiro), com `caminho`, `nota`, `mercado_ok`, `na_evolucao`, `no_alvo`, `horas_ate_evoluir`, `horas_ate_alvo`, `trilha` e o preço justo (`Comparaveis.preco_justo` da forma final, no nível e na nota projetada);
  - avisa quando o Pokémon tem refino (a nota projetada usa as bases sem ele) e quando a trilha passa do nível do treinador + 5 (o limite do jogo para lutar).
- **Medido (11/2026):** a nota calculada bate com a do jogo (|dif| < 0,002) em 26.414 de 26.671 anúncios sem refino, todos os que não são mega; o ⚔ também. As megas divergem porque o catálogo guarda nelas as bases da forma base (as próprias estão em `shared/megas.mjs`, que não é baixado), então para uma mega a análise usa a nota do anúncio. Larvitar → Tyranitar com 28 pontos leva ~0,2 s; Eevee (8 finais) até o Nv 500, ~1 s.

### `analise/precificar.py` (preço de venda de um Pokémon e até que nível vale subir)
- **Para que serve:** o "botão vender" dos Pokémon. Junta o preço justo (`Comparaveis`), a loja (`pk_anuncios`), a comissão (`taxa_venda`), o câmbio (`venda.cambio`) e a trilha da evolução. A explicação completa está no topo do arquivo.
- **`precos_agora` / `precos_moeda`:** três preços por moeda (shiny só gemas), cada um com a comissão e o líquido (em gemas, já com 1 diária de anúncio):
  - *rápido:* 1 passo abaixo do anúncio parecido mais barato (mesma espécie, shiny, moeda e faixas de nível e nota), sem passar do justo nem descer do piso (p10 das vendas parecidas; sem elas, 60% do justo);
  - *normal:* o preço justo; *paciente:* o p75 das vendas parecidas, no mínimo justo × 1,15;
  - os anúncios **melhores** (nível, nota − 0,05 e potência pelo menos iguais) mais baratos formam uma fila: o rápido fica abaixo do 1º, o normal do 2º e o paciente do 3º; o anúncio que está sendo analisado não conta como concorrente;
  - a moeda segue a regra dos itens: coins só se render `PREFERENCIA_GEMAS` (5%) a mais depois da troca.
- **`preco_item_gemas`:** custo de uma pedra em gemas, pela rota mais barata (gemas, ou coins pelo câmbio + 15%). A Shiny Stone de um tipo não se negocia (é fabricada no Centro): `preco_pedra` cobra N × o preço do `Shiny Stone Fragment`, com N do `shinyStone.custo` do welcome (`Motor.shiny_stone_custo`, guardado em `consts` por `guardar_welcome`) ou 10, o padrão do cliente.
- **`precificar(con, comps, r, ficha, valor_hora)`:** com o resultado de `evolucao.analisar` (trilha até `horizonte`: treinador + 5, ou o Nv 1001 sem treinador, com pontos em `ENTRADAS_FAIXA`, a entrada de cada faixa de nível do modelo), avalia em cada ponto da trilha já na forma final o ganho = valor líquido pelo justo (o maior visto até ali: subir não barateia) − vender agora pelo preço normal − pedras, e as gemas por hora desde agora. O melhor ponto é o de mais gemas/h, e só "vale" com pelo menos `MIN_GEMAS_H` (1) por hora; com `valor_hora`, o de maior ganho − valor_hora × horas. `pode_vender` aplica a regra do mercado (nível ≥ 50 e nota ≥ 3,5, salvo shiny e P5).
- **Limites:** o preço anda em degraus (faixas de nível e de nota do modelo), então o melhor ponto costuma cair na entrada de uma faixa; não avalia vender numa forma intermediária; o tempo supõe caçar sem parar.

### `analise/arena.py` (força no PvP e se vale evoluir para o PvP)
- **Fórmulas do jogo** (`shared/ginasios.mjs`; o "Poder no PvP" da ficha é o `poderNoGinasio`): `nivel_arena` achata o nível acima do 150 (`150 × (nível/150)^0,45`: Nv 300 → 205, Nv 1000 → 351); `poder_pvp` é `dps × HP de combate × defesa média / 10⁷` com o golpe que mais bate no nível de arena; `duelo` é o `compararDuelo1v1` com tipos (dps do melhor golpe contra o outro × HP de combate, variação de dano de 85% a 100%, 400 amostras). O ranqueado pede Nv 150 (`NIVEL_MIN_PVP`, o `PVP_NIVEL_MIN` de `shared/pvp-rank.mjs`).
- **`lutador(esp, nivel, ivs, fatores)`** monta o Pokémon com os stats do nível de arena (os `fatores` de `evolucao._fatores`) e os golpes liberados do catálogo; **`rival(esp, nivel, shiny)`** é o "típico" do outro lado (IV 16, qualidade 1, P1).
- **`avaliar(con, r, nick, faixa, forcar, m)`**, com o resultado de `evolucao.analisar`: para a forma de agora e cada evolução final (no Nv 150 se ainda não chegou), o ⚔ do PvP, a nota da espécie para o seu time (`pvp._pontuar` sobre o `pvp._contexto` do nick; espécies fora dos 100 mais usados leem a página delas no Tracker, até `MAX_PAGINAS_EXTRA`) e os duelos contra as suas 5 ameaças no nível mediano em que elas aparecem nas suas partidas. O veredito compara a força com a forma de agora (≥ `GANHO_MIN` de ⚔ ou ≥ `LIMIAR_DUELOS` na chance média dos duelos) e a espécie final com o seu time: entra se já está nele, ou se tem nota ≥ `NOTA_MIN_TIME` e não fica abaixo do mais fraco do time (só conta com 5 no time; a própria linha evolutiva não conta). A forma de agora não entra na comparação de nota porque quase nunca está no meta. Também traz os anúncios da forma final já pronta (`_prontos`: mesma condição de shiny, pelo menos o nível com que o seu entraria no PvP, nota até 0,05 abaixo da projetada).
- **Limites:** o duelo é a aproximação 1×1 do próprio jogo, sem o tabuleiro (posição, alcance, 5 contra 5); o rival não tem o indivíduo dele (IV, qualidade, potência) e não conta lendário nem TM.

### `analise/pvp.py` (aba PvP)
- **Tipos:** `TABELA` é a tabela de tipos da série, a mesma de `shared/tipo-efetividade.mjs` do jogo. `mult(atq, defesa)` dá o multiplicador e `melhor_ataque(atacante, defensor)` o melhor golpe de mesmo tipo.
- **`tracker(con, rota, ttl_s, forcar, **params)`:** GET com cache, 1,5 s entre pedidos e a cópia velha guardada se o site falhar. Os erros viram `ErroPvP` com mensagem em português. Com `forcar`, o cache só vale por `TTL_FORCADO_S` (1 min), para cliques seguidos não martelarem o site. A resposta traz `_ms` (quando foi lida do Tracker).
- **`atualizar_meta(con)`:** a pré-carga do robô (meta das faixas todas, alto e mestre, mais o ladder e os 10 primeiros perfis).
- **`analisar(con, nick, faixa, orcamento, moeda, forcar)`:** com `forcar` (botão "Atualizar agora"), o perfil e o meta do rank são lidos de novo; devolve `lido_em` e `meta_lido_em`. A leitura e as ameaças ficam em `_contexto` e a nota de uma espécie em `_pontuar`, que `arena.avaliar` também usa.
  - `_time_atual`: as espécies das últimas 5 partidas;
  - `_ameacas`: os counters da temporada mais os pokémons nos times das derrotas recentes, com peso nas recentes e no dano;
  - `_buracos` e os tipos que castigam;
  - candidatos por três sinais:
    - 45%: quem ganha das ameaças, pelas páginas `pokemon` delas, com pelo menos `MIN_CONFRONTOS` (20) e confiança n/(n+60);
    - 35%: a taxa no meta do rank, encolhida para 50% (`_nota_meta`);
    - 20%: o encaixe de tipos.
  - com orçamento, `_anuncios` acha na loja o melhor (40% percentil do ⚔ e 60% o da `pokemon.nota_ivs`, dentro da espécie) e o mais barato de cada sugestão;
  - `_resumo_meta` traz os mais usados, a melhor taxa e os times do topo.
- **`pesos_especies(con, faixa, nick)`:** uma nota de 0 a 1 por espécie, para o objetivo `pvp` da busca.

---

## 9. A página (`src/web/`)

- **`index.html`:** o cabeçalho tem as abas (Mercado, Sinais, Montagem, Pokémon), o seletor de moeda, o botão de som e o status.
  - Cada aba é uma `<section id="aba-…" class="aba-corpo">`.
  - Na aba Pokémon, as sub-abas são `data-pksub` (buscar, evolucao, pvp, padroes, vendas) e os painéis são `id="pk-…"`.
  - A janela do botão vender é `#venda-fundo`.
- **`app.js`:** um arquivo só, dividido em seções por comentários `// ------ nome`.
  - **ícones:** `IMG`, `CATEGORIAS`, `img()`;
  - **formatação:** `fmtNum`, `htmlPreco`, `htmlVar`, `usd`, `classeRaridade` e `api()`, o fetch que lança erro com a mensagem do servidor;
  - **estado na URL:** `lerHash` e `gravarHash`. Aba, moeda, janela, categoria e item ficam no `#`;
  - **lista e detalhe:** `carregarResumo`, `desenharLista` (cada linha tem um botão `[data-vender]`), `selecionar`, `desenharDetalhe`, `ligarCalculadora`;
  - **gráfico:** `desenharGraficos`, em SVG próprio. O estado fica em `graf` (pilha de zooms, ponto fixado, séries escondidas) e zera ao trocar item, moeda ou janela:
    - arrastar faz zoom (`darZoom`): desenha na hora com os baldes que já tem e troca pelos de `/api/item/serie`; `− zoom`, duplo clique, `-` ou Esc voltam (`voltarZoom`);
    - a mira (`mostrarPonto`) gruda no balde mais perto, com linha vertical e horizontal, anéis na mediana e no menor anúncio e etiquetas nos eixos; o tooltip traz a variação contra o balde anterior e a distância do anúncio para a mediana;
    - clique fixa o ponto, ← → andam de balde em balde (o `.grafico-box` tem foco), Esc solta;
    - a legenda é clicável e esconde séries (lembradas em `graf_ocultas` no `localStorage`); a escala de preço só olha o que está visível;
    - o eixo do tempo marca horas redondas de Brasília (`marcasTempo`), com a meia-noite mais forte; o servidor alinha os baldes do mesmo jeito (`_baldes`);
    - a linha da mediana só quebra depois de 3 h sem venda (ou de um balde vazio, se o balde for maior);
    - com mais de 240 fotos da vitrine, o servidor (`_anuncios`) manda uma por meio balde, a de valor mediano;
  - **montagem:** `carregarMontagem`;
  - **vender:** `abrirVenda`, `desenharVenda`, `ligarVenda` e o estado em `venda`;
  - **sinais:** `carregarSinais`, `desenharSinais`, `ligarSinais`; `postar()` para os POST;
  - **aviso sonoro:** `checarAlertasNovos` (polling), `tocar` (WebAudio), `mostrarAviso`;
  - **PvP:** `analisarPvp(e, forcar)` (o botão `#pvp-forcar` manda `forcar=1`), `desenharPvp`, `ligarPvp`, `haQuanto`. O nick fica no `localStorage` (`pvp_nick`);
  - **pokémon:** `mostrarSubPk`, `buscarPk`, `carregarPadroesPk`, `carregarPokemon`, `ligarPokemon`;
  - **análise com evolução:** `lerFichaJogo` (lê a ficha que o jogo copia, "# Nome — ficha do PokeIdle": espécie com o número, shiny, nível, potência, qualidade, nota, poder e a tabela de stats; um "+N" na coluna da base marca refino) e `colarFicha` (preenche o formulário e analisa, mandando os stats da ficha em `st_*`; mexer no formulário descarta a ficha colada, `fichaColada`), `fichaSimulada` (o botão **Copiar ficha simulada** de cada evolução final, `[data-copiar-ficha]`: a ficha da forma final no nível do campo ao lado, `[data-nivel-ficha]`, montada na página por `formaNoNivel` com os `fatores` e o `score` que a análise devolve, no mesmo modelo que o jogo copia, com `percentilQualidade` do jogo; `lerFichaJogo` lê de volta), `carregarEspeciesPk` (o `datalist` das espécies, carregado ao abrir a sub-aba), `analisarEvolucao(e, anuncio)`, `desenharEvolucao`, `ligarEvolucao`. A precificação (`precificacao` da mesma resposta) entra por `htmlPrecosVenda` (rápido/normal/paciente por moeda, com a concorrência) e `htmlVale` (o veredito e a tabela do valor em cada nível, com a linha do melhor ponto em `.pkv-melhor`); o campo **Sua hora vale** (`#pke-hora`, lembrado em `pk_valor_hora`) manda `valor_hora`. O botão `[data-evoluir]` de cada linha da busca abre a sub-aba com a ficha do anúncio e a copia para o formulário. Depois de desenhar, `carregarPvpEvolucao` pede `/api/pk/evolucao/pvp` com o `pvp_nick` salvo e preenche a caixa `#pke-pvp` ("Vale evoluir para o PvP?", `htmlPvpEvolucao`, com o botão Atualizar que manda `forcar=1`); `pedidoPvpEvol` descarta respostas de uma análise antiga;
  - **status e navegação:** `carregarStatus`, `mostrarAba`, `ligar()` (liga todos os eventos) e `iniciar()` (carga inicial e os timers de 1 e 5 min).
- **Regras da página:**
  - todo texto que vem do servidor passa por `esc()` antes de entrar no HTML;
  - os eventos usam delegação no contêiner (por exemplo, `#lista`, `#venda-corpo`), porque o conteúdo é redesenhado;
  - o `localStorage` só guarda conveniências e fica sempre dentro de `try/catch`.
- **`app.css`:** copia o visual do jogo (as cores saíram do CSS público do pokeidle.io).
  - **Fontes, só do sistema:** texto corrido em `--f-texto` (Segoe UI); títulos, botões, abas, rótulos e números em `--f-titulo` (Tahoma negrito). Os títulos levam contorno de 4 pontos (`--contorno-*`), como no jogo. Nenhuma fonte é baixada.
  - **Tokens em `:root`:** `--xadrez-*` (fundo azul), `--mad-*` (madeira), `--rx-*` (roxo), `--vao*` (áreas escuras), `--tinta*`, `--gema`, `--ouro`, `--sobe`, `--desce` e as raridades (`--r-*`). O `app.js` usa `--linha` (fundo dos quadrinhos e do gráfico), `--grade`, `--serie-1`/`--serie-2` e `--tinta*`. As séries foram validadas contra o `--linha`; se mudar um, valide o outro.
  - **Três peças:** o quadro de madeira (`.janela`, `.topo`), o vão (`.janela-corpo`, `.campo`) e o botão. O botão é de madeira quando apagado e roxo quando ligado (`.ativa`) ou de ação (`.btn-primario`). As abas do topo são o botão grande (moldura de 8 px).
  - **Molduras com `box-shadow: inset` empilhados:** a primeira sombra fica por cima. O padding de um botão nunca pode ser menor que a moldura (5 px nos pequenos, 8 px nas abas).
  - **Outros componentes:** `.caixa`, `.tile`/`.tiles`, `.grafico-box`, `.tabela`, `.tag`, `.tipo-tag`, `.var.sobe`/`.var.desce` e o interruptor que substitui todo `input[type=checkbox]`.
  - **Raridade:** as classes `.r-*` só definem `--rar`. A `.linha-item` desenha a faixa da esquerda com ela, e a `.rar-tag` é a versão em linha (na tabela de montagem).
  - As seções novas vão no fim do arquivo, com um comentário `/* ---------- nome ---------- */`.

---

## 10. Configuração (`config.local.json`, fora do git)

```json
{
  "nick": "conta coletora",
  "token": "token da sessão (copiado do console do navegador; ver PLANO.md, Fase 2)",
  "dispositivo": "uuid gerado na primeira vez",
  "alertas": {
    "windows": true,
    "discord_webhook": "https://discord.com/api/webhooks/...",
    "telegram_token": "123:ABC...", "telegram_chat_id": "123456"
  }
}
```

**O token é uma credencial.** Ele nunca pode ser impresso em log, enviado para fora ou commitado. O
robô atualiza o token sozinho quando o jogo manda `sessao.renovada`.

---

## 11. Tempos e limites

| O quê | Valor | Onde |
|---|---|---|
| Export de vendas | o que o jogo mandar (`esperaMs`), ~1 h + 30 s | coletor |
| Vitrine | a cada 1 min | `coletor.VITRINE_A_CADA_MS` |
| Poda da vitrine | a cada 1 h; detalhe por 3 dias, depois 1 a cada 15 min | robo / coletor |
| Loja de Pokémon | a cada 3 h, 1 s entre páginas, tentativa que falha espera 30 min | lojapk / robo |
| Nomes de itens | 1 vez por dia | `coletor.ITENS_A_CADA_MS` |
| Pré-carga do PvP | a cada 6 h | `robo.PVP_META_A_CADA_MS` |
| Catálogo de espécies do jogo (XP/h) | 1 vez por dia, 1 s entre arquivos; falhou, tenta em 1 h | `robo.CATALOGO_A_CADA_MS` |
| Hunts e constantes de caça | a cada login (vêm no `welcome`) | `caca.guardar_welcome` |
| Ping da sessão | 25 s | `Sessao._pingar` |
| Reconexão | 1 min dobrando até 10 min; 4001 espera 30 min; erro 5 min | robo |
| Cache do Tracker | 5 min (você) / 6 h (meta e topo) / 12 h (espécie) | `pvp.TTL_S` |
| Repetição de alerta | 6 h, ou se melhorar 5% | sinais |
| Status no painel | a cada 1 min; dados a cada 5 min; alertas novos a cada 30 s | app.js `iniciar()` / `ligarSom()` |

---

## 12. Regras que não podem ser quebradas

1. **Termos de Uso do jogo:** nada de contornar limites nem sobrecarregar o servidor. Um export por hora, pausas entre páginas, cache no Tracker.
2. **Nada de VPS ou VM:** a equipe do jogo proibiu. Tudo roda no PC do dono.
3. **Uma conexão por conta:** abrir a conta coletora ou as do dono em outro lugar derruba a sessão que já existe (4001). Nunca entre nas contas do dono para testar.
4. **No máximo 4 contas por pessoa,** somando todas as redes. A coletora fica online o tempo todo e conta nesse limite.
5. **O token e o `config.local.json` nunca saem do PC.** O `data/` também não vai para o git.
6. **O repositório é público:** nada de nick de terceiros, dados pessoais ou infraestrutura pessoal nos arquivos versionados.

---

## 13. Como fazer as mudanças mais comuns

**Uma rota nova na API**
1. Escreva a função em `analise/<modulo>.py`. Ela recebe `con` e devolve um dict serializável.
2. Em `painel.py`, `Handler.do_GET`, adicione `if url.path == "/api/x": return self._json(...)`. Limite o tamanho dos parâmetros vindos de `q`.
3. Documente na seção 7 deste arquivo.

**Uma aba ou sub-aba nova na página**
1. Em `index.html`, adicione a sub-aba (`data-pksub="x"` + `<div class="pk-painel hidden" id="pk-x">`) ou uma aba (`data-aba` + `<section id="aba-x" class="aba-corpo hidden">`. Uma aba nova também precisa entrar em `mostrarAba()`).
2. Em `app.js`, crie uma seção `// ------ x` com `carregarX`/`desenharX`/`ligarX` e chame `ligarX()` a partir de `ligar()` ou `ligarPokemon()`.
3. Os estilos vão no fim do `app.css`, usando os tokens.

**Uma tarefa nova no robô**
1. Se ela usa o socket: escreva `async def fazer_x(s: Sessao)` com `s.pedir(...)`. Adicione o horário em `proximos_horarios()` e chame a tarefa em `sessao()`.
2. Se não usa o jogo: escreva dentro de `tarefas_locais()`, com uma chave nova em `coleta`. Se demorar, rode numa thread, como `_precarregar_pvp`.
3. Publique o progresso com `agora(fase=..., detalhe=...)` e, se for uma fase nova, adicione em `mini.FASES`.

**Uma tabela nova:** crie no `SCHEMA` do módulo dono com `CREATE TABLE IF NOT EXISTS` e documente na seção 5.

**Um alerta novo:** adicione o tipo em `sinais.TIPOS_REGRA` e trate em `_checar()`. O formulário da aba Sinais monta o seletor sozinho.

**Religar depois de mudar o código**
- **Pelo menu da bandeja:** Reiniciar robô ou Reiniciar painel.
- **Pelo terminal:** mate o processo `python … src\robo.py` (ou `painel.py`); a bandeja religa em ~30 s.
- **Arquivos de `src/web/`:** não precisam de religação; basta recarregar a página.

---

## 14. Testes e verificação

- **`python testes/teste_robo_sessao.py`:** o robô contra um jogo falso local, numa pasta temporária. Não toca no jogo nem no banco real.
- **Painel de teste:** `.claude/launch.json` sobe uma cópia na porta 8771 (`python src/painel.py --porta 8771`), com o mesmo banco. Dá para testar rotas e página sem derrubar o painel em uso.
- **Experimentos que gravam:** copie `data/market.db` para uma pasta temporária e aponte `importer.connect` para a cópia.
- **Verificação rápida:**
  - `python -m py_compile src/*.py src/coleta/*.py src/analise/*.py`;
  - `node --check src/web/app.js`;
  - `curl` em cada rota de `/api/`.
- **Inicialização com o Windows:** teste abrindo o atalho pelo Explorer (`explorer.exe "<Startup>\PokeIdle Tracker.lnk"`), não por um terminal. Um processo iniciado pelo Explorer pode não enxergar pacotes instalados por um terminal com ambiente diferente.

---

## 14.1 Fórmulas do jogo (Pokémon)

Os módulos `shared/` do jogo são públicos (por exemplo, `https://pokeidle.io/shared/nota-pokemon.mjs`). Os que importam aqui:
- **Stat:** `arred((base + refino + 2×IV) × nível/100 × qualidade^exp × potência × shiny × lendário)`.
  - O expoente da qualidade é 0,95 para HP e SPD e 0,8 para os outros.
  - A potência multiplica por 1; 1,05; 1,1; 1,25; 2 (P1 a P5). Shiny multiplica por 3; lendário e mítico, por 4.
  - IV vai de 1 a 32 por stat (6 a 192 somados). A qualidade vai de 0,8 a 1,8, e metade dos nascimentos fica abaixo de ~1,08.
- **Nota (N=):** de 0 a 10 **dentro da espécie**, no nível 100. O 0 é o pior nascimento possível (IV 6, Q 0,8, P1) e o 10 o melhor (IV 192, Q 1,8, P5, shiny), em escala de log da soma dos stats. Uma evolução sobe a nota em pelo menos 0,1. O ×4 do lendário fica fora da nota.
- **⚔ (poder):** `nível × 10 × score`, com o score em log (ver `analise/pokemon.py`).
- **Mercado:** só aceita Pokémon de nível ≥ 50 e nota ≥ 3,5. Shiny, P5, lendário e mítico passam livres. **Shiny só se anuncia em gemas** (desde 10/10/2026).
- **Dano na caça:** `((2·nível/5 + 2) × poder do golpe × ATK/DEF) / 50 + 2`, × STAB × efetividade. Na caça, a efetividade é ampliada em 1,5: 2× vira 2,5× e 0,5× vira 0,33×. O golpe usa ATK ou SP.ATK conforme a categoria.
- **Golpes:**
  - os das planilhas de balanceamento valem desde o nível 1, com recarga pela curva do poder (10 s no poder 15, 30 s no 100, 60 s no 600);
  - toda última evolução ganha um golpe de 600 de cada tipo seu (dois se tiver um tipo só), no lado de ataque mais forte, com 60 s de recarga;
  - a Investida (poder 30, 2 s) sai quando nenhum golpe está pronto. O intervalo entre golpes é 0,9 s, e a Investida e o intervalo caem 10 ms por ponto de IV de SPD.
- **Selvagem:** stats `(base + 2×16) × nível/100`; vida de combate `máx(24, HP × 12) × 5`; dano dele × 1,8, um golpe a cada 1,4 s.
- **XP do abate:** uma curva só, pelo nível do selvagem: `⌊0,6·n²⌋ + 8` até 150; acima, `13.500 × (n/150)^1,25`.
- **Hunt liberada:** nível do treinador ≥ nível da hunt.
- **PvP e ginásio** (`shared/ginasios.mjs`, `shared/pvp-rank.mjs`): nível de arena = o nível até 150 e `150 × (nível/150)^0,45` acima; o ranqueado pede Nv 150 e times de até 5; ⚔ do PvP = `dps × máx(24, HP × 12) × (DEF + SP.DEF)/2 / 10⁷`. Ver `analise/arena.py`.

## 15. Armadilhas conhecidas

- **Fim de linha:** `.py` usa LF e `.bat` usa CRLF (`.gitattributes`). No Windows, `Path.write_text` grava CRLF; para `.py`, use `write_bytes` ou `open(..., newline="\n")`.
- **`pythonw` não tem stdout:** os filhos da bandeja têm a saída redirecionada para arquivos. Não use `print` esperando um console.
- **Dois mercados no mesmo item:** pedras são vendidas em lote a 2 gemas por unidade e avulsas a dezenas ou centenas de gemas. Sempre filtre outliers (mediana ×/÷ 4) antes de comparar preços.
- **Coleta curta:** tendências e "melhor horário" ficam pouco confiáveis nos primeiros dias, e a interface mostra a confiança. A média de 7 dias do jogo (`vitrine.media7_*`) ajuda nesse começo.
- **O teto da loja de Pokémon é a página 200:** por isso a varredura faz as passadas do mais barato e do mais caro.
- **O export vem atrasado:** uma venda pode chegar ao banco até ~1 h depois de acontecer. Contagens das últimas horas sobem com o tempo.
- **Idle Deck:** as contas de caça do dono rodam lá (é um app fechado). O projeto não automatiza essas contas; o PvP lê só o Tracker público.
- **Dados do XP/h:** a busca mostra "sem os dados do jogo ainda" até o robô entrar uma vez (hunts) e baixar o catálogo. Se o jogo mudar o formato do `welcome` ou da planilha de golpes, compare com `data/jogo/welcome-esqueleto.json` e com a contagem de `ler_planilhas` (26 tabelas, ~1.100 espécies e ~90 megas em 11/2026).
