import itertools
import random
import typing

import numpy.random
import simpy
import simpy.resources.resource


class ModeloLavanderia:
    _env: simpy.Environment
    _rnd: numpy.random.Generator
    _resource_maquinas: simpy.Resource
    _resource_cestos: simpy.Resource
    _resource_secadoras: simpy.Resource

    def __init__(self, env: simpy.Environment):
        self._env = env
        self._rnd = numpy.random.default_rng()

        # A lavanderia possui 7 maquinas de lavar
        self._resource_maquinas = simpy.Resource(env, capacity=7)
        # A lavanderia possui 12 cestos
        self._resource_cestos = simpy.Resource(env, capacity=12)
        # A lavanderia possui 2 secadoras
        self._resource_secadoras = simpy.Resource(env, capacity=2)

    def inicia(self) -> typing.Generator[simpy.Event, None, None]:
        # infinitos clientes
        for id_consumidor in itertools.count(start=1):
            print(f'{self._env.now:04.1f}: Consumidor {id_consumidor:02d} chega na lavanderia')
            self._env.process(self._processo_lavagem(id_consumidor))

            # chegada media de 10 minutos com função exponencial
            yield self._env.timeout(self._rnd.exponential(10))

    def _processo_lavagem(self, id_consumidor: int) -> typing.Generator[simpy.Event, None, None]:
        with self._resource_maquinas.request() as request_maquina:
            # (Fila) Aguarda maquina livre
            yield request_maquina

            # (Atividade) Utiliza a maquina livre
            # tempo de lavagem da maquina fixo em 25 minutos
            print(f'{self._env.now:04.1f}: Consumidor {id_consumidor:02d} utiliza a maquina')
            printstats(self._resource_maquinas, 'maquinas utilizadas')
            yield self._env.timeout(25)
            print(f'{self._env.now:04.1f}: Consumidor {id_consumidor:02d} terminou de usar a maquina')
        printstats(self._resource_maquinas, 'maquinas utilizadas')

        with self._resource_cestos.request() as request_cesto:
            # (fila) Aguarda cesto livre
            yield request_cesto

            # (atividade) Descarrega roupas da maquina no cesto livre
            print(f'{self._env.now:04.1f}: Consumidor {id_consumidor:02d} esta descarregando roupa no cesto')
            printstats(self._resource_cestos, 'cestos utilizados')
            yield self._env.timeout(random.uniform(1, 4), 1)
            # (fila) Transporte para a secadora
            print(f'{self._env.now:04.1f}: Consumidor {id_consumidor:02d} esta transportando a roupa para a secadora')
            yield self._env.timeout(random.uniform(3, 5), 1)

        with self._resource_secadoras.request() as request_secadora:
            # Aguarda secadora livre
            yield request_secadora

            # Carrega secadora
            print(f'{self._env.now:04.1f}: Consumidor {id_consumidor:02d} carrega a secadora')
            printstats(self._resource_secadoras, 'secadoras utilizadas')
            yield self._env.timeout(2)
            print(f'{self._env.now:04.1f}: Consumidor {id_consumidor:02d} secadora carregada')

            # Secagem + descarregamento da secadora
            yield self._env.timeout(max(0, self._rnd.normal(10, scale=4)))
            print(f'{self._env.now:04.1f}: Consumidor {id_consumidor:02d} terminou a secagem e o descarregamento')
        printstats(self._resource_secadoras, 'secadoras utilizadas')


def printstats(res, string):
    print(f'{res.count}/{res.capacity} ', string)


def main() -> None:
    env = simpy.Environment()
    modelo = ModeloLavanderia(env)
    env.process(modelo.inicia())
    env.run(until=200)


if __name__ == '__main__':
    main()
