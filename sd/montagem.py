import abc
import dataclasses
import enum
import functools
import typing

import simpy
import simpy.resources.resource

import sd
from sd import Modelo


class _Metrica(enum.Enum):
    TEMPO_ESPERA_PECAS = 0
    TEMPO_ESPERA_PARAFUSOS = 1
    TEMPO_ESPERA_MAQUINA_USINAGEM = 2
    TEMPO_ESPERA_PECAS_FIXADAS = 3


class ModeloMontagem(sd.Modelo[_Metrica]):
    @dataclasses.dataclass
    class _Estatisticas:
        tempos_espera_pecas: list[float]
        tempos_espera_parafusos: list[float]
        tempos_espera_maquina_usinagem: list[float]
        tempos_espera_pecas_fixadas: list[float]

    _resource_maquina: simpy.Resource
    _container_pecas: simpy.Container
    _container_parafusos: simpy.Container
    _container_pecas_fixadas: simpy.Container

    _pecas_fixadas: int
    _pecas_unidas: int
    _estatisticas: _Estatisticas

    def __init__(self, *, deve_exibir_log: bool = False, seed: int | None = None) -> None:
        super().__init__(
            deve_exibir_log=deve_exibir_log,
            seed=seed,
        )

    def _monitora(self, env: simpy.Environment) -> sd.Generator:
        while True:
            # A célula é abastecida em média a cada 40 minutos,
            # normalmente distribuído com desvio de 3min...
            yield env.timeout(abs(self._rnd.normal(40, scale=3)))

            # ...por pallets com 60 peças...
            yield self._container_pecas.put(60 - self._container_pecas.level)
            # ...e caixas de parafusos que contêm de 990 a 1.010 unidades
            qtd_parafusos = max(self._rnd.integers(990, 1010), self._container_parafusos.level) - self._container_parafusos.level
            if qtd_parafusos > 0:
                yield self._container_parafusos.put(qtd_parafusos)

    def _fixa_pecas(self, env: simpy.Environment) -> sd.Generator:
        # [Atividade] Fixa peças
        # A fixação das peças antes da usinagem é feita em um tempo médio
        # de 40 segundos, normalmente distribuído, com desvio-padrão de 5
        # segundos
        yield env.timeout(abs(self._rnd.normal(40 / 60, scale=5 / 60)))
        self._pecas_fixadas += 1

    def _une_pecas(self, env: simpy.Environment) -> sd.Generator:
        # [Atividade] Une peças
        # A união das peças por parafusos gasta entre 3,5 e 4 minutos,
        # segundo uma distribuição uniforme
        yield env.timeout(self._rnd.uniform(low=3.5, high=4))
        self._pecas_unidas += 1

    @typing.override
    def inicia(self, env: simpy.Environment) -> None:
        self._pecas_unidas = 0
        self._pecas_fixadas = 0
        self._estatisticas = ModeloMontagem._Estatisticas(
            tempos_espera_pecas=[],
            tempos_espera_parafusos=[],
            tempos_espera_maquina_usinagem=[],
            tempos_espera_pecas_fixadas=[],
        )

        # A máquina de usinagem
        self._resource_maquina = simpy.Resource(env, capacity=1)
        # A célula é abastecida por pallets com 60 peças
        self._container_pecas = simpy.Container(env, init=60, capacity=60)
        # A célula é abastecida por caixas de parafusos que contêm de 990 a 1.010 unidades
        self._container_parafusos = simpy.Container(env, init=1010)
        # As peças fixadas aguardando serem unidas
        self._container_pecas_fixadas = simpy.Container(env, init=0)

        env.process(self._monitora(env))
        self._executa(env)

    @typing.override
    def calcula_metrica(self, metrica: _Metrica) -> list[float]:
        match metrica:
            case _Metrica.TEMPO_ESPERA_PECAS:
                return self._estatisticas.tempos_espera_pecas
            case _Metrica.TEMPO_ESPERA_PARAFUSOS:
                return self._estatisticas.tempos_espera_parafusos
            case _Metrica.TEMPO_ESPERA_MAQUINA_USINAGEM:
                return self._estatisticas.tempos_espera_maquina_usinagem
            case _Metrica.TEMPO_ESPERA_PECAS_FIXADAS:
                return self._estatisticas.tempos_espera_pecas_fixadas
            case _:
                typing.assert_never(metrica)

    @abc.abstractmethod
    def _executa(self, env: simpy.Environment) -> None:
        pass


class ModeloMontagem1(ModeloMontagem):
    @typing.override
    def _executa(self, env: simpy.Environment) -> None:
        for _ in range(10):
            env.process(self._executa_funcionario_1(env))
            env.process(self._executa_funcionario_2(env))

    def _executa_funcionario_1(self, env: simpy.Environment) -> typing.Generator[simpy.Event, None, None]:
        log = functools.partial(self._log, env, 'funcionário 1')
        while True:
            # (Fila) Aguarda ao menos 2 peças
            tempo_inicial_espera_pecas = env.now
            yield self._container_pecas.get(2)
            log('obtém pares de peças')
            self._estatisticas.tempos_espera_pecas.append(env.now - tempo_inicial_espera_pecas)

            yield env.process(self._fixa_pecas(env))
            log('fixa peças')

            with self._resource_maquina.request() as request_maquina:
                tempo_inicial_espera_maquina = env.now
                # (Fila) Aguarda máquina
                yield request_maquina
                self._estatisticas.tempos_espera_maquina_usinagem.append(env.now - tempo_inicial_espera_maquina)

                log('inicia usinagem')
                # [Atividade] Executa usinagem
                yield env.timeout(3)
                log('termina usinagem')

            yield self._container_pecas_fixadas.put(2)

    def _executa_funcionario_2(self, env: simpy.Environment) -> typing.Generator[simpy.Event, None, None]:
        log = functools.partial(self._log, env, 'funcionário 2')
        while True:
            # Aguarda peças fixadas
            tempo_inicial_espera_pecas_fixadas = env.now
            yield self._container_pecas_fixadas.get(2)
            log('recebe peças fixadas')
            self._estatisticas.tempos_espera_pecas_fixadas.append(env.now - tempo_inicial_espera_pecas_fixadas)

            # (Fila) Aguarda ao menos 4 parafusos
            # Outro empregado une os pares de peças com 4 parafusos
            tempo_inicial_espera_parafusos = env.now
            yield self._container_parafusos.get(4)
            log('recebe parafusos')
            self._estatisticas.tempos_espera_parafusos.append(env.now - tempo_inicial_espera_parafusos)

            yield env.process(self._une_pecas(env))
            log('une peças')


class ModeloMontagem2(ModeloMontagem):
    _evento_usinagem: simpy.Event

    @typing.override
    def _executa(self, env: simpy.Environment) -> None:
        self._evento_usinagem = env.event()
        for _ in range(100):
            env.process(self._executa_fixacao(env))
            env.process(self._executa_uniao(env))

    def _executa_fixacao(self, env: simpy.Environment) -> typing.Generator[simpy.Event, None, None]:
        log = functools.partial(self._log, env, 'funcionário')
        while True:
            # (Fila) Aguarda ao menos 2 peças
            yield self._container_pecas.get(2)
            log('obtém pares de peças')

            yield env.process(self._fixa_pecas(env))
            log('fixa peças')

            with self._resource_maquina.request() as request_maquina:
                # (Fila) Aguarda máquina
                yield request_maquina

                log('inicia usinagem')
                self._evento_usinagem.succeed()
                self._evento_usinagem = env.event()

                # [Atividade] Executa usinagem
                yield env.timeout(3)
                self._log(env, 'termina usinagem')

            yield self._container_pecas_fixadas.put(2)

    def _executa_uniao(self, env: simpy.Environment) -> typing.Generator[simpy.Event, None, None]:
        while True:
            # Apenas durante usinagem
            yield self._evento_usinagem

            # (Fila) Aguarda ao menos 4 parafusos
            yield self._container_parafusos.get(4)
            self._log(env, 'F1 obtém peças fixadas')

            yield env.process(self._une_pecas(env))
            self._log(env, 'F1 une peças')


class ExecutorModeloMontagem(sd.ExecutorModelo[_Metrica]):
    def inicializa_modelo(
            self,
            dados_modelos: dict[str, dict[str, typing.Any]],
            seed: int | None,
            deve_exibir_log: bool,
    ) -> Modelo[_Metrica]:
        return ModeloMontagem1(deve_exibir_log=deve_exibir_log, seed=seed)

    def lista_metricas(self) -> typing.Sequence[_Metrica]:
        return list(_Metrica)

    def exibe_modelo_executado(self, modelo: Modelo[_Metrica]) -> None:
        for metrica in self.lista_metricas():
            valores = modelo.calcula_metrica(metrica)
            label = self.descreve_metrica(metrica)
            self._log_stats(label, valores, time_unit='minutes')

    def descreve_metrica(self, metrica: _Metrica) -> str:
        match metrica:
            case _Metrica.TEMPO_ESPERA_PECAS:
                return 'Espera p/ receber peças'
            case _Metrica.TEMPO_ESPERA_PARAFUSOS:
                return 'Espera p/ receber parafusos'
            case _Metrica.TEMPO_ESPERA_MAQUINA_USINAGEM:
                return 'Espera p/ liberar máquina'
            case _Metrica.TEMPO_ESPERA_PECAS_FIXADAS:
                return 'Espera p/ receber peças unidas'
            case _:
                typing.assert_never(metrica)

    modelo: ModeloMontagem


def main() -> None:
    executor = ExecutorModeloMontagem()
    sd.executa_script(executor, x_range=(30, 8 * 60 + 30, 60), y_range=(0, 30, 5))


if __name__ == '__main__':
    main()
