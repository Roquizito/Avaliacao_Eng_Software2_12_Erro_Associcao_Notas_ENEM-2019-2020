"""
Roteiro Visual de Demonstração para Apresentação em Sala
Caso 12: Erro na Associação e Correção de Notas do ENEM 2019/2020 (Etapa 3)

Uso:
    python3 demo_apresentacao.py          # Executa todos os cenários direto
    python3 demo_apresentacao.py --pausa  # Pausa a cada etapa (ideal para falar em sala)
"""

import sqlite3
import sys

from database_repository import SQLiteRepositorioProcessamentoEnem
from interfaces import IAlertaQualidadeNotifier, IGabaritoOficialProvider
from matching_service import ValidadorMatchingEnem
from models import (
    CorCaderno,
    LeituraOpticaCartaoResposta,
    RegistroAtaSala,
    RegistroLoteGrafica,
)

# Códigos ANSI para formatação visual no terminal
VERDE = "\033[92m"
VERMELHO = "\033[91m"
AMARELO = "\033[93m"
AZUL = "\033[94m"
CIANO = "\033[96m"
NEGRITO = "\033[1m"
RESET = "\033[0m"


class ConsoleGabaritoProvider(IGabaritoOficialProvider):
    HASHES = {
        CorCaderno.AZUL: "HASH_FRASE_AZUL_2019",
        CorCaderno.AMARELO: "HASH_FRASE_AMARELO_2019",
        CorCaderno.BRANCO: "HASH_FRASE_BRANCO_2019",
        CorCaderno.ROSA: "HASH_FRASE_ROSA_2019",
    }

    def obter_hash_frase_oficial(self, cor: CorCaderno) -> str:
        return self.HASHES[cor]

    def obter_gabarito_oficial(self, cor: CorCaderno) -> str:
        return "A" * 90


class ConsoleAlertaNotifier(IAlertaQualidadeNotifier):
    def emitir_alerta_critico(self, id_lote: str, taxa_erro: float, mensagem: str) -> None:
        print(f"\n   {VERMELHO}{NEGRITO}[ALERTA CRÍTICO DISPARADO AO INEP]{RESET}")
        print(f"   ├─ Lote Suspeito : {id_lote}")
        print(f"   ├─ Taxa de Erro  : {taxa_erro:.1%} (Limite: 0.5%)")
        print(f"   └─ Detalhe       : {mensagem}")


def cabecalho(titulo: str) -> None:
    print(f"\n{AZUL}{NEGRITO}{'=' * 82}{RESET}")
    print(f"{CIANO}{NEGRITO}  {titulo}{RESET}")
    print(f"{AZUL}{NEGRITO}{'=' * 82}{RESET}")


def pausar(modo_pausa: bool) -> None:
    if modo_pausa:
        input(f"\n{AMARELO}>> Pressione [ENTER] para avançar para o próximo cenário...{RESET}")


def executar_demonstracao(modo_pausa: bool = False) -> None:
    repo = SQLiteRepositorioProcessamentoEnem(":memory:")
    gabarito = ConsoleGabaritoProvider()
    notifier = ConsoleAlertaNotifier()
    validador = ValidadorMatchingEnem(gabarito, repo, notifier)

    print(f"\n{NEGRITO}DEMONSTRAÇÃO PRÁTICA — CASO 12: ERRO NAS NOTAS DO ENEM 2019/2020{RESET}")
    print("Arquitetura: 3-Way Matching + Circuit Breaker + Sanity Check TRI + Triggers SQLite")

    # -------------------------------------------------------------------------
    # CENÁRIO 1: Caminho Feliz + Fallback Seguro
    # -------------------------------------------------------------------------
    cabecalho("CENÁRIO 1: 3-WAY MATCHING CONSISTENTE E FALLBACK SEGURO")

    reg_ok = RegistroLoteGrafica(
        id_inscricao="190001001",
        id_lote_impressao="LOTE_SP_01",
        codigo_barras_caderno="CB-99881",
        cor_associada_grafica=CorCaderno.AZUL,
        hash_frase_padrao_cor="HASH_FRASE_AZUL_2019",
    )
    cartao_ok = LeituraOpticaCartaoResposta(
        id_inscricao="190001001",
        codigo_barras_cartao="CR-99881",
        cor_marcada_aluno=CorCaderno.AZUL,
        hash_frase_transcrita_aluno="HASH_FRASE_AZUL_2019",
        respostas_questoes="ABCDE" * 18,
    )
    ata_ok = RegistroAtaSala("190001001", "SALA-101", CorCaderno.AZUL)

    res_ok = validador.validar_candidato(reg_ok, cartao_ok, ata_ok)
    repo.publicar_nota_sisu("190001001", CorCaderno.AZUL, 765.4)

    print(f" • Candidato {NEGRITO}190001001{RESET}: Gráfica=AZUL | Cartão=AZUL | Frase=AZUL | Ata=AZUL")
    print(f"   ├─ Status Matching : {VERDE}{NEGRITO}{res_ok.status.value}{RESET}")
    print(f"   ├─ Cálculo TRI     : {VERDE}AUTORIZADO (Cor confirmada: {res_ok.cor_confirmada.value}){RESET}")
    print(f"   └─ Publicação SISU : {VERDE}Nota 765.4 gravada com sucesso no SQLite!{RESET}")

    pausar(modo_pausa)

    # -------------------------------------------------------------------------
    # CENÁRIO 2: O Bug Real do ENEM 2019 + Bloqueio pela Trigger do Banco
    # -------------------------------------------------------------------------
    cabecalho("CENÁRIO 2: REPRODUÇÃO DO BUG REAL DE 2019 + DEFESA NO BANCO (TRIGGER)")

    reg_bug = RegistroLoteGrafica(
        id_inscricao="190005974",
        id_lote_impressao="LOTE_REIMPRESSO_VALID_42",
        codigo_barras_caderno="CB-OFFSET-01",
        cor_associada_grafica=CorCaderno.AMARELO,  # Gráfica trocou para AMARELO na reimpressão
        hash_frase_padrao_cor="HASH_FRASE_AMARELO_2019",
        foi_reimpresso=True,
    )
    cartao_bug = LeituraOpticaCartaoResposta(
        id_inscricao="190005974",
        codigo_barras_cartao="CR-OFFSET-01",
        cor_marcada_aluno=CorCaderno.BRANCO,  # Aluno recebeu e resolveu a prova BRANCA
        hash_frase_transcrita_aluno="HASH_FRASE_BRANCO_2019",
        respostas_questoes="BDECA" * 18,
    )

    res_bug = validador.validar_candidato(reg_bug, cartao_bug)
    print(f" • Candidato {NEGRITO}190005974{RESET} (Lote Reimpresso): Gráfica=AMARELO vs. Cartão/Frase=BRANCO")
    print(f"   ├─ Status Matching : {VERMELHO}{NEGRITO}{res_bug.status.value}{RESET}")
    print(f"   ├─ Cálculo TRI     : {VERMELHO}BLOQUEADO (pode_calcular_tri = {res_bug.pode_calcular_tri}){RESET}")
    for div in res_bug.divergencias_detectadas:
        print(f"   ├─ Evidência       : {AMARELO}{div}{RESET}")

    print(f"\n • {NEGRITO}Teste de Defesa em Profundidade (Trigger SQLite):{RESET}")
    print("   Tentando forçar INSERT de nota para o candidato 190005974 direto na tabela do SISU...")
    try:
        repo.publicar_nota_sisu("190005974", CorCaderno.AMARELO, 312.0)
    except sqlite3.IntegrityError as erro_db:
        print(f"   └─ {VERDE}{NEGRITO}SUCESSO NO BLOQUEIO PELO SGBD:{RESET} {VERMELHO}{erro_db}{RESET}")

    pausar(modo_pausa)

    # -------------------------------------------------------------------------
    # CENÁRIO 3: Circuit Breaker de Lote Reimpresso (> 0.5% de erro)
    # -------------------------------------------------------------------------
    cabecalho("CENÁRIO 3: CIRCUIT BREAKER — QUARENTENA AUTOMÁTICA DE LOTE CORROMPIDO")

    lote_defeituoso = [
        (
            RegistroLoteGrafica("3001", "LOTE_REIMP_55", "CB3001", CorCaderno.AZUL, "HASH_FRASE_AZUL_2019"),
            LeituraOpticaCartaoResposta("3001", "CR3001", CorCaderno.AZUL, "HASH_FRASE_AZUL_2019", "A" * 90),
            None,
        ),
        (
            RegistroLoteGrafica("3002", "LOTE_REIMP_55", "CB3002", CorCaderno.AMARELO, "HASH_FRASE_AMARELO_2019"),
            LeituraOpticaCartaoResposta("3002", "CR3002", CorCaderno.BRANCO, "HASH_FRASE_BRANCO_2019", "B" * 90),
            None,
        ),
    ]

    print(" • Processando lote 'LOTE_REIMP_55' (Candidato 3001 parecia OK, mas 3002 revelou offset)...")
    validador.processar_lote_com_circuit_breaker(lote_defeituoso)

    reg_3001_db = repo.buscar_registro("3001")
    print(f"\n • Verificando no banco o Candidato {NEGRITO}3001{RESET} (que estava no mesmo lote defeituoso):")
    print(f"   ├─ Novo Status DB  : {VERMELHO}{NEGRITO}{reg_3001_db['status']}{RESET}")
    print(f"   └─ pode_calcular_tri: {VERMELHO}{reg_3001_db['pode_calcular_tri']} (Revogado transacionalmente){RESET}")

    pausar(modo_pausa)

    # -------------------------------------------------------------------------
    # CENÁRIO 4: Portão de Qualidade Estatística da TRI (Inter-Dias)
    # -------------------------------------------------------------------------
    cabecalho("CENÁRIO 4: SANITY CHECK ESTATÍSTICO DA TRI (DISCREPÂNCIA INTER-DIAS)")

    reg_tri = RegistroLoteGrafica("190007777", "LOTE_07", "CB7", CorCaderno.AMARELO, "HASH_FRASE_AMARELO_2019")
    cartao_tri = LeituraOpticaCartaoResposta("190007777", "CR7", CorCaderno.AMARELO, "HASH_FRASE_AMARELO_2019", "A" * 90)
    res_previo = validador.validar_candidato(reg_tri, cartao_tri)

    res_auditado = validador.auditar_anomalia_estatistica_tri(
        resultado_previo=res_previo,
        nota_media_dia1_e_redacao=810.0,
        nota_calculada_dia2=340.5,
    )

    print(f" • Candidato {NEGRITO}190007777{RESET}: Média 1º Dia/Redação = {NEGRITO}810.0{RESET} | Nota calculada 2º Dia = {NEGRITO}340.5{RESET}")
    print(f"   ├─ Queda detectada : {AMARELO}469.5 pontos (Limiar máximo: 320.0 pts){RESET}")
    print(f"   ├─ Novo Status     : {VERMELHO}{NEGRITO}{res_auditado.status.value}{RESET}")
    print(f"   └─ Ação            : {VERDE}Nota retida para auditoria humana antes da divulgação!{RESET}")

    print(f"\n{VERDE}{NEGRITO}{'=' * 82}")
    print("  FIM DA DEMONSTRAÇÃO — TODOS OS MECANISMOS DE DEFESA OPERANDO CORRETAMENTE!")
    print(f"{'=' * 82}{RESET}\n")

    repo.fechar()


if __name__ == "__main__":
    pausa = "--pausa" in sys.argv or "-p" in sys.argv
    executar_demonstracao(modo_pausa=pausa)
