import abc
import statistics
import typing

import matplotlib.pyplot as plt
import numpy.random
import simpy

Generator = typing.Generator[simpy.Event, typing.Any, typing.Any]


class Modelo[M](abc.ABC):
    _rnd: numpy.random.Generator
    _deve_exibir_log: bool

    def __init__(self, *, deve_exibir_log: bool, seed: int | None = None) -> None:
        self._deve_exibir_log = deve_exibir_log
        self._rnd = numpy.random.default_rng(seed)

    def _log(self, env: simpy.Environment, *args: str) -> None:
        if self._deve_exibir_log:
            print(f'{env.now:05.2f}', *args, sep=': ')

    @abc.abstractmethod
    def inicia(self, env: simpy.Environment) -> None:
        pass

    @abc.abstractmethod
    def calcula_metrica(self, metrica: M) -> list[float]:
        pass


def plot[M](
        criador_modelo: typing.Callable[[], Modelo[M]],
        metricas: list[M],
        descritor_metrica: typing.Callable[[M], str],
        x_range: tuple[int, int, int],
        y_range: tuple[int, int, int],
) -> None:
    min_x, max_x, step_x = x_range
    min_y, max_y, step_y = y_range

    x = []
    medidas: dict[M, list[float]] = {}
    for until in range(min_x, max_x + 1, step_x):
        env = simpy.Environment()
        modelo = criador_modelo()
        modelo.inicia(env)
        env.run(until=until)

        x.append(until)
        for metrica in metricas:
            valores = modelo.calcula_metrica(metrica)
            medidas.setdefault(metrica, []).append(statistics.mean(valores))

    fig, ax = plt.subplots()
    for metrica in metricas:
        y = medidas[metrica]
        ax.plot(x, y, label=descritor_metrica(metrica))

    ax.set_xlabel('Tempo da simulação')
    ax.set_ylabel('Tempo médio da ação')

    def major_formatter(value: float, _: float) -> str:
        hours, minutes = divmod(value, 60)
        tokens: list[str] = []
        if hours > 0:
            tokens.append(f'{hours}h')
        if minutes > 0:
            tokens.append(f'{minutes}m')
        return ''.join(tokens)

    ax.xaxis.set_major_formatter(major_formatter)
    ax.yaxis.set_major_formatter(major_formatter)
    ax.set_xlim(min_x, max_x)
    ax.set_ylim(min_y, max_y)
    ax.set_xticks(list(range(min_x, max_x + 1, step_x)))
    ax.set_yticks(list(range(min_y, max_y + 1, step_y)))
    ax.grid(axis='y')
    ax.legend()
    plt.show()
