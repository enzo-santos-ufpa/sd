# Trabalho 1 - Simulação Discreta

Este repositório contém as simulações do trabalho 1
da disciplina de Simulação Discreta.

## Instalando

Defina o diretório de trabalho atual para a pasta raiz do projeto:

```shell
cd ufpa_simulacao_discreta
dir
```

```none
Mode                 LastWriteTime         Length Name
----                 -------------         ------ ----
d-----        19/08/2024     12:01                sd
-a----        19/08/2024     11:55           8636 poetry.lock                                                                                                                      
-a----        19/08/2024     11:59            293 pyproject.toml
-a----        19/08/2024     12:02            227 README.md
```

_(opcional)_ Crie um ambiente virtual e o ative:

```shell
python -m venv venv
venv\Scripts\activate
# ou, no Linux,
# source venv/bin/activate
```

Instale as dependências do projeto:

```shell
python -m pip install .
```

Crie um arquivo _config.toml_ no diretório raiz do projeto com base no arquivo _default.config.toml_ já existente:

```shell
cp default.config.toml config.toml
```

## Uso

Execute as simulações de cada exercício:

```shell
python -m sd.bar_expresso
python -m sd.centro_distribuicao
python -m sd.clinica_medica
python -m sd.lavanderia
python -m sd.montagem
```

Utilize o arquivo *config.toml* para alterar os parâmetros de cada simulação de modo centralizado.

## Implementando o modelo

> Como exemplo de implementação, consulte o arquivo [bar_expresso.py](sd/bar_expresso.py).

Para implementar um modelo com suporte a gráficos e configurações adicionais, crie um arquivo Python na pasta *sd/*:

```shell
echo '' > sd/<nome_modelo>.py
```

Neste arquivo, insira o seguinte conteúdo:

```python
import simpy

import sd


class MeuModelo(metaclass=sd.ModeloMetaclass):
    # Configuração do modelo
    chave_modelo: str = ...
    unidade_tempo: str = ...

    # [1] TODO Inserir parâmetros

    # [2] TODO Inserir métricas

    # [3] TODO Inserir campos do `simpy`, como `simpy.Resource`s

    def executa(self, env: simpy.Environment) -> None:
        # [4] TODO Implementar o modelo
        ...


def main() -> None:
    sd.executa_script(MeuModelo)


if __name__ == '__main__':
    main()
```

### Campo `chave_modelo`

Ao criar um arquivo _config.toml_ na raiz do projeto, ele será usado para centralizar a customização dos modelos. É
possível ver um exemplo de seu formato por meio do arquivo _default.config.toml_. Note que, para cada simulação, existe
uma
seção `[modelos.<nome-modelo>]` respectiva no arquivo (por exemplo, para a simulação do bar
expresso, `[modelos.bar-expresso]`). Este sufixo é definido pelo campo `chave_modelo`, conforme exibido no código acima.

Dessa forma, definir para um novo modelo

```python
import sd


class MeuModelo(metaclass=sd.ModeloMetaclass):
    ...

    chave_modelo: str = 'meu-modelo'

    ...
```

significa que seus parâmetros no arquivo de configuração poderão ser fornecidos na seção `[modelos.meu-modelo]` deste
arquivo.

### Campo `unidade_tempo`

Cada modelo do SimPy utiliza um `env.timeout` com um valor numérico. Este valor numérico pode estar em horas ou minutos.

Desta forma, definir para um novo modelo

```python
import sd


class MeuModelo(metaclass=sd.ModeloMetaclass):
    ...

    unidade_tempo: str = 'horas'

    ...
```

significa que a unidade de tempo utilizada pelo modelo é de horas. Caso seja de minutos, o valor a ser definido deve
ser `'minutos'`.

### 1. Parâmetros

Os parâmetros do modelo devem ser declarados no seguinte formato:

```python
import sd


class MeuModelo(metaclass=sd.ModeloMetaclass):
    ...

    nome_parametro: tipo_parametro = sd.ParametroModelo(chave='chave-parametro')

    ...
```

onde

- `nome_parametro` deve ser o nome do campo da classe `MeuModelo` que irá armazenar o valor concreto deste campo (por
  exemplo, **`qtd_funcionarios`** para armazenar a quantidade de funcionários atendendo em um bar)
- `tipo_parametro` deve ser o tipo da variável deste campo (por exemplo, **`int`** para representar o número de
  funcionários
  atendendo no bar)
- `chave-parametro` deve ser o nome do campo do tipo `str` a ser lido do arquivo de configuração para customizar essa
  classe (por exemplo, **`qtd-funcionarios`**)

### 2. Métricas

As métricas do modelo devem ser declarados no seguinte formato:

```python
import sd


class MeuModelo(metaclass=sd.ModeloMetaclass):
    ...

    nome_metrica: tipo_metrica = sd.MetricaModelo(descricao='<descricao_metrica>')

    ...
```

onde

- `nome_metrica` deve ser o nome do campo da classe `MeuModelo` que irá armazenar o valor concreto desta métrica (por
  exemplo, **`tempos_estadia_cliente`** para armazenar os tempos que o cliente ficou no bar)
- `tipo_metrica` deve ser o tipo da variável deste campo (por exemplo, **`list[float]`**, já que mais de um cliente pode
  entrar no bar durante a execução e uma lista deve ser usada para armazenar o tempo de estadia de cada um)
- `<descricao_metrica>` deve ser uma descrição da métrica do tipo `str` a ser exibido para o usuário final (por
  exemplo, **`Tempo estadia cliente`**)

### 3. Componentes do SimPy

Adicione os componentes do SimPy (`simpy.Resource`, `simpy.Container`, `simpy.Store`) como campos aqui, inicializando-os
posteriormente no passo 4:

```python
import simpy

import sd


class MeuModelo(metaclass=sd.ModeloMetaclass):
    ...

    _resource_funcionarios: simpy.Resource
    _resource_copos: simpy.Store
    _resource_cadeiras: simpy.Resource
    _resource_lavagem: simpy.Resource

    ...
```

### 4. Código da simulação

Implemente o código da simulação dentro no método `executa` do modelo.

As seguintes ações podem ser realizadas:

- gerar valores aleatórios, acessando o campo `self._rnd`, do tipo `numpy.random.Generator`:
  ```python
  yield env.timeout(self._rnd.exponential(4))
  ```
- exibir logs no console com o tempo atual, utilizando o método `self._log`:
  ```python
  self._log(env, 'funcionário 1', 'coloca copo no freezer')
  # Equivalente a
  # print('184.83: funcionário 1: coloca copo no freezer')
  ```
- acessar os valores dos parâmetros por meio dos campos `self.nome_parametro` definidos no passo 1:
  ```python
  self._resource_cadeiras = simpy.Resource(env, capacity=self.qtd_cadeiras)
  ```
- registrar os valores das métricas por meio dos campos `self.nome_metrica` definidos no passo 2:
  ```python
  tempo_inicio_espera_sentar = env.now
            
  # (Fila) Aguarda cadeira
  yield request_cadeira

  # [Atividade] Ocupa cadeira
  self.tempos_espera_sentar_cliente.append(env.now - tempo_inicio_espera_sentar)
  ```
- chamar qualquer método adicional no parâmetro `env` do método:
  ```python
  env.process(...)
  env.event()
  ```
  > _Nota:_ não é necessário chamar `env.run` dentro deste método.

