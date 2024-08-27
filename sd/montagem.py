import abc
import dataclasses
import typing

import matplotlib.lines
import matplotlib.patches
import matplotlib.pyplot as plt
import numpy.random
import simpy
import simpy.resources.resource


@dataclasses.dataclass
class EstadoModeloMontagem:
    rnd: numpy.random.Generator
    resource_maquina: simpy.Resource
    container_pecas: simpy.Container
    container_parafusos: simpy.Container
    container_pecas_fixadas: simpy.Container


class ModeloMontagem(abc.ABC):
    _should_log: bool
    _estado: EstadoModeloMontagem
    _pecas_fixadas: int
    _pecas_unidas: int

    def __init__(self, should_log: bool = False) -> None:
        self._should_log = should_log

    def _log(self, env: simpy.Environment, message: str) -> None:
        if self._should_log:
            print(f'{env.now:04.1f}: {message}')

    @property
    def pecas_unidas(self):
        return self._pecas_unidas

    @property
    def pecas_fixadas(self):
        return self._pecas_fixadas

    def _monitora(self, env: simpy.Environment) -> typing.Generator[simpy.Event, None, None]:
        rnd = self._estado.rnd
        container_pecas = self._estado.container_pecas
        container_parafusos = self._estado.container_parafusos
        while True:
            # A célula é abastecida em média a cada 40 minutos,
            # normalmente distribuído com desvio de 3min...
            yield env.timeout(rnd.normal(40, scale=3))

            # ...por pallets com 60 peças...
            yield container_pecas.put(60 - container_pecas.level)
            # ...e caixas de parafusos que contêm de 990 a 1.010 unidades
            yield container_parafusos.put(rnd.integers(low=990, high=1010) - container_parafusos.level)

    def _fixa_pecas(self, env: simpy.Environment) -> typing.Generator[simpy.Event, None, None]:
        rnd = self._estado.rnd

        # [Atividade] Fixa peças
        # A fixação das peças antes da usinagem é feita em um tempo médio
        # de 40 segundos, normalmente distribuído, com desvio-padrão de 5
        # segundos
        yield env.timeout(rnd.normal(40 / 60, scale=5 / 60))
        self._pecas_fixadas += 1

    def _une_pecas(self, env: simpy.Environment) -> typing.Generator[simpy.Event, None, None]:
        rnd = self._estado.rnd

        # [Atividade] Une peças
        # A união das peças por parafusos gasta entre 3,5 e 4 minutos,
        # segundo uma distribuição uniforme
        yield env.timeout(rnd.uniform(low=3.5, high=4))
        self._pecas_unidas += 1

    def executa(self, env: simpy.Environment) -> None:
        self._pecas_unidas = 0
        self._pecas_fixadas = 0
        self._estado = EstadoModeloMontagem(
            rnd=numpy.random.default_rng(0),

            # A máquina de usinagem
            resource_maquina=simpy.Resource(env, capacity=1),

            # A célula é abastecida por pallets com 60 peças
            container_pecas=simpy.Container(env, init=60),
            # A célula é abastecida por caixas de parafusos que contêm de 990 a 1.010 unidades
            container_parafusos=simpy.Container(env, init=1010),

            # As peças fixadas aguardando serem unidas
            container_pecas_fixadas=simpy.Container(env, init=0),
        )

        env.process(self._monitora(env))
        self._executa(env)

    @abc.abstractmethod
    def _executa(self, env: simpy.Environment) -> None:
        pass


class ModeloMontagem1(ModeloMontagem):
    @typing.override
    def _executa(self, env: simpy.Environment) -> None:
        env.process(self._executa_funcionario_1(env))
        env.process(self._executa_funcionario_2(env))

    def _executa_funcionario_1(self, env: simpy.Environment) -> typing.Generator[simpy.Event, None, None]:
        estado = self._estado
        resource_maquina = estado.resource_maquina
        container_pecas = estado.container_pecas
        container_pecas_fixadas = estado.container_pecas_fixadas
        while True:
            # (Fila) Aguarda ao menos 2 peças
            yield container_pecas.get(2)
            self._log(env, 'F1 obtém pares de peças')

            yield env.process(self._fixa_pecas(env))
            self._log(env, 'F1 fixa peças')

            with resource_maquina.request() as request_maquina:
                # (Fila) Aguarda máquina
                yield request_maquina

                self._log(env, 'F1 inicia usinagem')

                # [Atividade] Executa usinagem
                yield env.timeout(3)
                self._log(env, 'F1 termina usinagem')

            yield container_pecas_fixadas.put(2)

    def _executa_funcionario_2(self, env: simpy.Environment) -> typing.Generator[simpy.Event, None, None]:
        estado = self._estado
        container_parafusos = estado.container_parafusos
        container_pecas_fixadas = estado.container_pecas_fixadas
        while True:
            # Apenas após peças fixadas
            yield container_pecas_fixadas.get(2)

            # (Fila) Aguarda ao menos 4 parafusos
            # Outro empregado une os pares de peças com 4 parafusos
            yield container_parafusos.get(4)
            self._log(env, 'F2 recebe peças fixadas')

            yield env.process(self._une_pecas(env))
            self._log(env, 'F2 une peças')


class ModeloMontagem2(ModeloMontagem):
    _evento_usinagem: simpy.Event

    @typing.override
    def _executa(self, env: simpy.Environment) -> None:
        self._evento_usinagem = env.event()
        env.process(self._executa_fixacao(env))
        env.process(self._executa_uniao(env))

    def _executa_fixacao(self, env: simpy.Environment) -> typing.Generator[simpy.Event, None, None]:
        estado = self._estado
        resource_maquina = estado.resource_maquina
        container_pecas = estado.container_pecas
        container_pecas_fixadas = estado.container_pecas_fixadas
        while True:
            # (Fila) Aguarda ao menos 2 peças
            yield container_pecas.get(2)
            self._log(env, 'F1 obtém pares de peças')

            yield env.process(self._fixa_pecas(env))
            self._log(env, 'F1 fixa peças')

            with resource_maquina.request() as request_maquina:
                # (Fila) Aguarda máquina
                yield request_maquina

                self._log(env, 'F1 inicia usinagem')

                self._evento_usinagem.succeed()
                self._evento_usinagem = env.event()

                # [Atividade] Executa usinagem
                yield env.timeout(3)
                self._log(env, 'F1 termina usinagem')

            yield container_pecas_fixadas.put(2)

    def _executa_uniao(self, env: simpy.Environment) -> typing.Generator[simpy.Event, None, None]:
        estado = self._estado
        container_parafusos = estado.container_parafusos
        while True:
            # Apenas durante usinagem
            yield self._evento_usinagem

            # (Fila) Aguarda ao menos 4 parafusos
            yield container_parafusos.get(4)
            self._log(env, 'F1 obtém peças fixadas')

            yield env.process(self._une_pecas(env))
            self._log(env, 'F1 une peças')


def main() -> None:
    # deve_mostrar_logs = '--no-logs' not in sys.argv
    # deve_mostrar_grafico = '--graph' in sys.argv
    deve_mostrar_logs = True
    deve_mostrar_grafico = False
    if not deve_mostrar_grafico:
        modelo = ModeloMontagem1(should_log=deve_mostrar_logs)
        env = simpy.Environment()
        modelo.executa(env)
        env.run(until=60)
        return

    modelos = [
        ModeloMontagem1(should_log=deve_mostrar_logs),
        ModeloMontagem2(should_log=deve_mostrar_logs),
    ]

    fig, ax = plt.subplots()
    for i, modelo in enumerate(modelos):
        plt_color = ['red', 'green'][i]

        x = []
        y_unidas = []
        y_fixadas = []
        for until in range(30, 180, 10):
            env = simpy.Environment()
            modelo.executa(env)
            env.run(until=until)

            x.append(until)
            y_unidas.append(modelo.pecas_unidas)
            y_fixadas.append(modelo.pecas_fixadas)

        ax.plot(x, y_unidas, '-', color=plt_color)
        ax.plot(x, y_fixadas, '--', color=plt_color)

    ax.legend(handles=[
        matplotlib.patches.Patch(color='red', label='Modelo 1'),
        matplotlib.patches.Patch(color='green', label='Modelo 2'),
        matplotlib.lines.Line2D([0, 1], [0, 1], linestyle='-', color='black', label='Peças unidas'),
        matplotlib.lines.Line2D([0, 1], [0, 1], linestyle='--', color='black', label='Peças fixadas'),
    ])
    ax.set_xlabel('Minutos de execução')
    ax.set_ylabel('Qtd de peças produzidas')

    plt.show()


if __name__ == '__main__':
    main()
