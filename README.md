# Trabalho 1 - Simulação Discreta

Este repositório contém os códigos para os exercícios "Bar expresso" e "Montagem" da lista de exercícios do trabalho 1
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

## Uso

Execute as simulações de cada exercício:

```shell
python -m sd.bar_expresso
python -m sd.centro_distribuicao
python -m sd.clinica_medica
python -m sd.lavanderia
python -m sd.montagem
```

Para alterar os parâmetros de cada simulação de modo centralizado, crie um arquivo local *config.toml*. Os argumentos
que podem ser configurados neste arquivo estão especificados em *default.config.toml*.
