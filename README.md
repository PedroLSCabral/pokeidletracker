# PokeIdle Tracker

Coleta e análise do mercado do [pokeidle.io](https://pokeidle.io), onde as gemas valem dinheiro de verdade.

Um robô entra no jogo com uma conta só para coleta e grava num banco SQLite local:

- as vendas do mercado (o export de 1 em 1 hora que o próprio jogo oferece);
- a vitrine de itens, a cada 15 minutos;
- a loja de Pokémon inteira, a cada 3 horas.

Um painel web em pixel art mostra preços, sinais de revenda, alertas e um analisador de Pokémon. O analisador estima o preço justo de cada anúncio e procura o melhor Pokémon para um orçamento.

O plano completo, as descobertas sobre o jogo e as decisões estão em [PLANO.md](PLANO.md).

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
   O comando pede o nick e o token, copiados do console do navegador; o passo a passo está no PLANO.md, Fase 2. Eles ficam em `config.local.json`, que **nunca** vai para o git.
3. **Ligue tudo com dois cliques em `iniciar.bat`.** O robô e o painel rodam escondidos, e aparece uma pokébola na bandeja, perto do relógio:
   - o clique esquerdo abre uma janelinha de status (o que o robô está fazendo e quando é a próxima tarefa);
   - o clique direito abre o menu (painel, log, reiniciar, ligar com o Windows, sair).
4. **Abra o painel em http://127.0.0.1:8770.**

Para ligar junto com o Windows, marque a opção no menu da pokébola ou rode `python src/bandeja.py --instalar`.

Numa VM Linux o robô também roda sozinho: `python src/robo.py`, ou como serviço com [deploy/pokeidle-robo.service](deploy/pokeidle-robo.service).

## Estrutura

| Arquivo | O que faz |
|---|---|
| `src/robo.py` | Robô coletor: socket do jogo, export, vitrine, loja de Pokémon e alertas |
| `src/bandeja.py` | Ícone na bandeja: mantém o robô e o painel rodando escondidos e os religa se caírem |
| `src/mini.py` | Janelinha de status, que abre pelo ícone |
| `src/painel.py` + `src/painel/` | Painel web (API em Python e página em HTML/CSS/JS, sem dependências). Os ícones vêm direto do site do jogo |
| `src/importer.py` | Banco SQLite, importação do CSV/JSON do export, deduplicação |
| `src/coletor.py` | Gravação compartilhada (vendas, vitrine, itens) e o servidor do antigo userscript |
| `src/lojapk.py` | Tabelas e gravação dos anúncios da loja de Pokémon |
| `src/sinais.py` | Fase 3: sinais de revenda, regras e histórico de alertas |
| `src/notificar.py` | Avisos pelo Windows, Discord ou Telegram |
| `src/analise_pokemon.py` | Fase 4: preço justo, busca por orçamento e padrões de mercado |
| `src/userscript/`, `extras/` | Primeira tentativa de coleta, por userscript (não funcionou no Idle Deck) |
| `deploy/` | Serviço systemd para rodar o robô numa VM |

Os dados ficam em `data/`, também fora do git: `market.db`, `robo.log` e `robo_agora.json`.

## Regras que o robô respeita

- **1 export por hora,** pelo tempo que o próprio jogo devolve.
- **Pausa de 1 s entre as páginas da loja.**
- **Uma conexão por conta.** Se a conta for aberta em outro lugar, o robô espera em vez de disputar a sessão.
- **Um robô por PC.**
- **Nada de contornar limites do jogo,** conforme os Termos de Uso.
