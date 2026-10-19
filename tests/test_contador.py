"""Testes do contador de repetições por ângulo do cotovelo."""

from station.contador import ContadorRepeticoes


def alimentar(contador, angulos, passo=0.1):
    reps = []
    for i, angulo in enumerate(angulos):
        r = contador.atualizar(angulo, i * passo)
        if r:
            reps.append(r)
    return reps


def test_ciclo_completo_conta_uma_repeticao():
    c = ContadorRepeticoes(150, 130, 55)
    reps = alimentar(c, [170, 165, 125, 90, 50, 40, 70, 120, 160])
    assert len(reps) == 1
    assert reps[0].completa
    assert reps[0].menor_angulo == 40
    assert reps[0].duracao_s == 0.6  # de 125° (i=2) até 160° (i=8)


def test_amplitude_parcial_vira_repeticao_incompleta():
    c = ContadorRepeticoes(150, 130, 55)
    reps = alimentar(c, [170, 120, 90, 100, 160])
    assert len(reps) == 1
    assert not reps[0].completa


def test_comecando_flexionado_espera_extensao():
    c = ContadorRepeticoes(150, 130, 55)
    assert alimentar(c, [40, 60, 100]) == []
    assert len(alimentar(c, [160, 120, 45, 160])) == 1


def test_ruido_perto_da_extensao_nao_conta_repeticao():
    c = ContadorRepeticoes(150, 130, 55)
    assert alimentar(c, [170, 148, 152, 146, 155, 140, 151]) == []


def test_varias_repeticoes_seguidas():
    c = ContadorRepeticoes(150, 130, 55)
    ciclo = [165, 120, 70, 45, 80, 140, 162]
    assert len(alimentar(c, ciclo * 5)) == 5
