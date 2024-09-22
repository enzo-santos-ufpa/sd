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

    # Variáveis para rastreamento de tempos
    _tempo_total_lavagem = 0
    _tempo_total_secagem = 0
    _tempo_total_chegada = 0
    _tempo_total_cesto = 0
    _num_eventos = 0
    _num_cestos_usados = 0
    _ultimo_tempo_chegada = 0

    def __init__(self, env: simpy.Environment):
        self._env = env
        self._rnd = numpy.random.default_rng()

        # Recursos
        self._resource_maquinas = simpy.Resource(env, capacity=7)
        self._resource_cestos = simpy.Resource(env, capacity=12)
        self._resource_secadoras = simpy.Resource(env, capacity=2)

    def inicia(self) -> typing.Generator[simpy.Event, None, None]:
        # Processos de clientes
        for id_consumidor in itertools.count(start=1):
            chegada = self._env.now
            if self._num_eventos > 0:
                tempo_entre_chegadas = chegada - self._ultimo_tempo_chegada
                self._tempo_total_chegada += tempo_entre_chegadas
            self._ultimo_tempo_chegada = chegada

            print(f'{chegada:04.1f}: Consumidor {id_consumidor:02d} chega na lavanderia')
            self._env.process(self._processo_lavagem(id_consumidor))

            # Chegada média de 10 minutos
            yield self._env.timeout(self._rnd.exponential(10))

    def _processo_lavagem(self, id_consumidor: int) -> typing.Generator[simpy.Event, None, None]:
        tempo_inicio = self._env.now

        with self._resource_maquinas.request() as request_maquina:
            # Aguarda máquina livre
            yield request_maquina
            # Utiliza a máquina
            print(f'{self._env.now:04.1f}: Consumidor {id_consumidor:02d} utiliza a máquina')
            printstats(self._resource_maquinas, 'máquinas utilizadas')
            yield self._env.timeout(25)
            print(f'{self._env.now:04.1f}: Consumidor {id_consumidor:02d} terminou de usar a máquina')
        printstats(self._resource_maquinas, 'máquinas utilizadas')

        tempo_cesto_inicio = self._env.now
        with self._resource_cestos.request() as request_cesto:
            # Aguarda cesto livre
            yield request_cesto
            # Descarrega roupas no cesto
            print(f'{self._env.now:04.1f}: Consumidor {id_consumidor:02d} está descarregando roupa no cesto')
            printstats(self._resource_cestos, 'cestos utilizados')
            yield self._env.timeout(random.uniform(1, 4))
            # Transporte para a secadora
            print(f'{self._env.now:04.1f}: Consumidor {id_consumidor:02d} está transportando a roupa para a secadora')
            yield self._env.timeout(random.uniform(3, 5))
        tempo_cesto_fim = self._env.now
        self._tempo_total_cesto += (tempo_cesto_fim - tempo_cesto_inicio)
        self._num_cestos_usados += 1

        with self._resource_secadoras.request() as request_secadora:
            # Aguarda secadora livre
            yield request_secadora
            # Carrega secadora
            print(f'{self._env.now:04.1f}: Consumidor {id_consumidor:02d} carrega a secadora')
            printstats(self._resource_secadoras, 'secadoras utilizadas')
            yield self._env.timeout(2)
            print(f'{self._env.now:04.1f}: Consumidor {id_consumidor:02d} secadora carregada')

            # Secagem
            tempo_secagem_inicio = self._env.now
            yield self._env.timeout(max(0, self._rnd.normal(10, scale=4)))
            tempo_secagem_fim = self._env.now
            print(f'{self._env.now:04.1f}: Consumidor {id_consumidor:02d} terminou a secagem e o descarregamento')

            # Atualiza o tempo total
            tempo_fim = self._env.now
            self._tempo_total_lavagem += 25
            self._tempo_total_secagem += (tempo_secagem_fim - tempo_secagem_inicio)
            self._num_eventos += 1

        printstats(self._resource_secadoras, 'secadoras utilizadas')

    def obter_estatisticas(self):
        if self._num_eventos == 0:
            return 0, 0, 0, 0
        media_lavagem = self._tempo_total_lavagem / self._num_eventos
        media_secagem = self._tempo_total_secagem / self._num_eventos
        media_chegada = self._tempo_total_chegada / self._num_eventos if self._num_eventos > 1 else 0
        media_cesto = self._tempo_total_cesto / self._num_cestos_usados if self._num_cestos_usados > 0 else 0
        return media_lavagem, media_secagem, media_chegada, media_cesto


def printstats(res, string):
    print(f'{res.count}/{res.capacity} ', string)


def main() -> None:
    env = simpy.Environment()
    modelo = ModeloLavanderia(env)
    env.process(modelo.inicia())
    env.run(until=200)
    media_lavagem, media_secagem, media_chegada, media_cesto = modelo.obter_estatisticas()
    print(f'Tempo médio de lavagem: {media_lavagem:.2f} minutos')
    print(f'Tempo médio de secagem: {media_secagem:.2f} minutos')
    print(f'Tempo médio de chegada dos consumidores: {media_chegada:.2f} minutos')
    print(f'Tempo médio de uso dos cestos: {media_cesto:.2f} minutos')


if __name__ == '__main__':
    main()
