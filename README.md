# PokeIdle Tracker

Coleta e análise do mercado do [pokeidle.io](https://pokeidle.io), onde as gemas valem dinheiro de verdade.

Um robô entra no jogo com uma conta só para coleta e grava num banco SQLite local:

- as vendas do mercado (o export de 1 em 1 hora que o próprio jogo oferece);
- a vitrine de itens (menor anúncio e média de 7 dias de cada item), a cada minuto;
- a loja de Pokémon inteira, a cada 3 horas.

Um painel web em pixel art mostra preços, sinais de revenda, alertas e um analisador de Pokémon. O analisador estima o preço justo de cada anúncio e procura o melhor Pokémon para um orçamento. A aba PvP lê o seu histórico no Tracker público do jogo e sugere o que comprar contra quem você mais perde.

O plano completo, as descobertas sobre o jogo e as decisões estão em [docs/PLANO.md](docs/PLANO.md); o mapa técnico do código, em [docs/ARQUITETURA.md](docs/ARQUITETURA.md).

> **Projeto pessoal e não oficial,** sem relação com a equipe do pokeidle.io. Os Termos de Uso do jogo permitem automação desde que ela não burle limites nem sobrecarregue o servidor; o robô foi feito para ficar dentro disso (veja "Regras que o robô respeita"). Use por sua conta e risco, com uma conta separada, nunca com a sua conta principal.

## Como usar (Windows)

1. **Instale Python 3.12 ou mais novo e as dependências:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Configure a conta coletora:**
   ```bash
   python src/robo.py --configurar
   ```
   O comando pede o nick e o token, copiados do console do navegador; o passo a passo está no [docs/PLANO.md](docs/PLANO.md), Fase 2. Eles ficam em `config.local.json`, que **nunca** vai para o git.
3. **Ligue tudo com dois cliques em `iniciar.bat`.** O robô e o painel rodam escondidos, e aparece uma pokébola na bandeja, perto do relógio:
   - o clique esquerdo abre uma janelinha de status (o que o robô está fazendo e quando é a próxima tarefa);
   - o clique direito abre o menu (painel, log, reiniciar, ligar com o Windows, sair).
4. **Abra o painel em http://127.0.0.1:8770.**

Para ligar junto com o Windows, marque a opção no menu da pokébola ou rode `python src/bandeja.py --instalar`.

> **Rode no seu próprio PC.** A equipe do jogo confirmou que VPS (máquina virtual na nuvem) não é permitido.

## Estrutura

| Pasta / arquivo | O que tem |
|---|---|
| `src/bandeja.py` | Ícone na bandeja: mantém o robô e o painel rodando escondidos e os religa se caírem |
| `src/robo.py` | Robô coletor: fica conectado ao jogo e lê a vitrine, o export e a loja de Pokémon |
| `src/painel.py` | Servidor do painel (API JSON + a página de `src/web/`) |
| `src/mini.py` | Janelinha de status, que abre pelo ícone |
| `src/coleta/` | O que grava no banco: esquema e importação (`importer`), vendas/vitrine/agenda (`coletor`), loja de Pokémon (`lojapk`) |
| `src/analise/` | O que calcula: revenda e alertas (`sinais`), botão vender (`venda`), Pokémon (`pokemon`), PvP (`pvp`) |
| `src/web/` | A página do painel em pixel art (HTML, CSS e JS sem dependências; ícones carregados do site do jogo) |
| `src/caminhos.py`, `src/notificar.py` | Pastas do projeto; avisos pelo Windows, Discord ou Telegram |
| `testes/` | Robô contra um jogo falso, sem tocar no pokeidle.io |
| `legado/` | Primeira tentativa de coleta, por userscript (não funcionou no Idle Deck) |
| `docs/` | [`ARQUITETURA.md`](docs/ARQUITETURA.md) (o mapa técnico) e [`PLANO.md`](docs/PLANO.md) (o diário do projeto) |

Os dados ficam em `data/`, também fora do git: `market.db`, os logs e `robo_agora.json`.

**Vai mexer no código?** Comece pelo [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) e pelo [`CLAUDE.md`](CLAUDE.md).

## Regras que o robô respeita

- **1 export por hora,** pelo tempo que o próprio jogo devolve.
- **Pausa de 1 s entre as páginas da loja.**
- **Uma conexão por conta.** Se a conta for aberta em outro lugar, o robô espera em vez de disputar a sessão.
- **Um robô por PC.**
- **Nada de contornar limites do jogo,** conforme os Termos de Uso.
- **Nada de VPS:** roda só no PC, como a equipe do jogo pediu.
