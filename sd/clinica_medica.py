import itertools
import random
import typing

import numpy.random
import simpy
import simpy.resources.resource


class ModeloClinicaMedica:
    _env: simpy.Environment
    _rnd: numpy.random.Generator
    _resource_medicos: simpy.Resource
    _resource_recepcionistas: simpy.Resource

    def __init__(self, env: simpy.Environment):
        self._env = env
        self._rnd = numpy.random.default_rng()

        # A Clinica possui 3 medicos
        self._resource_medicos = simpy.Resource(env, capacity=3)
        # A Clinica possui 2 recepcionistas
        self._resource_recepcionistas = simpy.Resource(env, capacity=2)

    def inicia(self) -> typing.Generator[simpy.Event, None, None]:
        # infinitos pacientes
        for id_paciente in itertools.count(start=1):
            print(f'{self._env.now:04.1f}: Paciente {id_paciente:02d} chega na clinica')
            self._env.process(self._processo_atendimento(id_paciente))

            # chegada media de 3 minutos com função exponencial
            yield self._env.timeout(self._rnd.exponential(3))

    def _processo_atendimento(self, id_paciente: int) -> typing.Generator[simpy.Event, None, None]:
        with self._resource_recepcionistas.request() as request_recepcionista:
            # (Fila) Aguarda recepcionista livre
            yield request_recepcionista

            # Preenche a ficha
            print(f'{self._env.now:04.1f}: Paciente {id_paciente:02d} preenche a ficha')
            yield self._env.timeout(self._rnd.exponential(10))
            print(f'{self._env.now:04.1f}: Paciente {id_paciente:02d} terminou de preencher a ficha')

        # Espera medico livre
        with self._resource_medicos.request() as request_medico:
            yield request_medico

            # Consulta
            print(f'{self._env.now:04.1f}: Paciente {id_paciente:02d} iniciou sua consulta')
            yield self._env.timeout(self._rnd.exponential(20))
            print(f'{self._env.now:04.1f}: Paciente {id_paciente:02d} terminou sua consulta')

        # Retorno a recepcionista
        with self._resource_recepcionistas.request() as request_recepcionista:
            # (Fila) Aguarda recepcionista livre
            yield request_recepcionista

            # Efetua pagamento
            print(f'{self._env.now:04.1f}: Paciente {id_paciente:02d} efetua pagamento e agenda proxima consulta')
            yield self._env.timeout(random.uniform(1, 4), 1)
            print(f'{self._env.now:04.1f}: Paciente {id_paciente:02d} saiu da clinica')


def main() -> None:
    env = simpy.Environment()
    modelo = ModeloClinicaMedica(env)
    env.process(modelo.inicia())
    env.run(until=200)


if __name__ == '__main__':
    main()
