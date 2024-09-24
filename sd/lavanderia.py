import functools
import itertools
import random

import simpy
import simpy.resources.resource

import sd


class ModeloLavanderia(metaclass=sd.ModeloMetaclass):
    # Configuração do modelo
    chave_modelo: str = 'lavanderia'
    unidade_tempo: str = 'minutos'

    _qtd_lavadoras: int = sd.ParametroModelo(chave='qtd-lavadoras')
    _qtd_cestos: int = sd.ParametroModelo(chave='qtd-cestos')
    _qtd_secadoras: int = sd.ParametroModelo(chave='qtd-secadoras')

    _resource_maquinas: simpy.Resource = sd.RecursoModelo(descricao='Máquinas')
    _resource_cestos: simpy.Resource = sd.RecursoModelo(descricao='Cestos')
    _resource_secadoras: simpy.Resource = sd.RecursoModelo(descricao='Secadoras')

    _no_pedidos_consumidos: int = sd.MetricaModelo(descricao='Número de cestos utilizados')
    _tempos_estadia_cliente: list[float] = sd.MetricaModelo(descricao='Tempo estadia')
    _tempos_espera_cesto: list[float] = sd.MetricaModelo(descricao='Tempo espera p/ cesto')
    _tempos_espera_lavadora: list[float] = sd.MetricaModelo(descricao='Tempo espera p/ lavar')
    _tempos_espera_secadora: list[float] = sd.MetricaModelo(descricao='Tempo espera p/ secar')

    def executa(self, env: simpy.Environment) -> None:
        # Recursos
        self._resource_maquinas = simpy.Resource(env, capacity=self._qtd_lavadoras)
        self._resource_cestos = simpy.Resource(env, capacity=self._qtd_cestos)
        self._resource_secadoras = simpy.Resource(env, capacity=self._qtd_secadoras)
        env.process(self._processa_consumidores(env))

    def _processa_consumidores(self, env: simpy.Environment) -> sd.Generator:
        # Processos de clientes
        for id_consumidor in itertools.count(start=1):
            env.process(self._processo_lavagem(env, id_consumidor))

            # Chegada média de 10 minutos
            yield env.timeout(self._rnd.exponential(10))

    @sd.entrypoint
    def _processo_lavagem(self, env: simpy.Environment, id_consumidor: int) -> sd.Generator:
        log = functools.partial(self._log, env, f'consumidor {id_consumidor:02d}')

        log('chega na lavanderia')
        tempo_inicial_estadia_cliente = env.now

        with self._resource_maquinas.request() as request_maquina:
            tempo_inicial_aguarda_maquina = env.now
            # Aguarda máquina livre
            yield request_maquina
            self._tempos_espera_lavadora.append(env.now - tempo_inicial_aguarda_maquina)

            # Utiliza a máquina
            log('utiliza máquina')
            yield env.timeout(25)
            log('termina de usar a máquina')

        with self._resource_cestos.request() as request_cesto:
            tempo_inicial_aguarda_cesto = env.now
            # Aguarda cesto livre
            yield request_cesto
            self._tempos_espera_cesto.append(env.now - tempo_inicial_aguarda_cesto)

            # Descarrega roupas no cesto
            log('descarrega roupas no cesto')
            yield env.timeout(random.uniform(1, 4))
            # Transporte para a secadora
            log('transporta roupa para a secadora')
            yield env.timeout(random.uniform(3, 5))

        with self._resource_secadoras.request() as request_secadora:
            tempo_inicial_aguarda_secadora = env.now
            # Aguarda secadora livre
            yield request_secadora
            self._tempos_espera_secadora.append(env.now - tempo_inicial_aguarda_secadora)

            # Carrega secadora
            log('carrega a secadora')
            yield env.timeout(2)
            log('termina de carregar a secadora')

            # Secagem
            yield env.timeout(abs(self._rnd.normal(10, scale=4)))
            log('termina a secagem')

        self._tempos_estadia_cliente.append(env.now - tempo_inicial_estadia_cliente)


def main() -> None:
    sd.executa_script(ModeloLavanderia, x_range=(60, 360, 30), y_range=(0, 60, 15))


if __name__ == '__main__':
    main()
