"""Coleta: tudo que GRAVA dados no banco.

- importer.py  esquema do SQLite, leitura do CSV/JSON do export de vendas, deduplicação.
- coletor.py   gravação compartilhada do que vem do jogo (vendas, vitrine, nomes de itens) e o
               agendamento (tabela `coleta`); também o servidor local do antigo userscript.
- lojapk.py    tabelas e gravação dos anúncios da loja de Pokémon.
"""
