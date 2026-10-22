# planta-3d — representação intermediária (planta → 3D)

Esquema do JSON que fica entre a **leitura da planta/corte** (DXF ou IA) e o **renderizador** (SketchUp). A IA produz este JSON, o plugin o desenha, e os ajustes digitados alteram os dados, não o desenho.

## Estrutura

```
schema/projeto.schema.json     esquema (JSON Schema 2020-12)
exemplos/cozinha-simples.json  cozinha 4,00 x 3,00 m com porta, janela, balcão e aéreo
tools/validar.py               valida esquema + coerência geométrica
tools/dxf_para_json.py         converte uma planta DXF simples neste JSON
tools/gerar_dxf_exemplo.py     gera exemplos/cozinha-planta.dxf
tools/gerar_script_sketchup.py JSON -> script para o conector Trimble SketchUp
renderer/sketchup_paredes.py   paredes com vãos de porta/janela (roda no sandbox do conector)
renderer/sketchup_comum.py     funções compartilhadas (extrusão, prisma, validação de sólidos)
renderer/sketchup_esquadrias.py piso, porta (batente + folha), janela (caixilho + vidro)
renderer/sketchup_moveis.py    balcão e aéreo de 2 portas, peça a peça, com lista de corte
renderer/sketchup_vistas.py    estilo técnico + 5 cenas ortográficas + câmera de abertura
renderer/sketchup_validacao.py confere que toda peça-folha é um sólido fechado
tests/                         testes do conversor
requirements.txt               ezdxf, jsonschema
```

## Convenções

- Unidade: **milímetros**. X para a direita, Y para cima na planta, Z para cima no 3D.
- Paredes são segmentos retos; o **lado interno é a esquerda** de `inicio → fim` (contorno anti-horário).
- Aberturas e móveis se posicionam **ao longo de uma parede** (`posicao_mm` / `distancia_do_inicio_mm`, contada a partir de `inicio`), não em coordenadas soltas. Se a parede mudar, eles acompanham.
- Cada valor pode carregar `origem` (`medida`, `usuario`, `inferida`) e `confianca` (0–1). Só `medida` e `usuario` dispensam conferência.
- Biblioteca de blocos e texturas fica **fora** do projeto: o projeto só referencia `{catalogo, id, versao}`.

## Camadas e fases

| Camada | Campo | Fase |
|---|---|---|
| Arquitetura | `paredes`, `aberturas`, `ambientes` | 1 (protótipo) |
| Vistas | `vistas` (planta, frontal, fundos, laterais, corte) | 2 |
| Mobiliário | `mobiliario` (blocos parametrizados) | 4 |
| Acabamentos | `acabamentos` (texturas com escala real e sentido do veio) | 5 |
| Ajustes por texto | `historico_ajustes` (comandos estruturados, nunca código livre) | 3 |

Na fase 1, `mobiliario`, `acabamentos` e `historico_ajustes` podem ficar vazios.

## Validar

```bash
pip install jsonschema
python3 tools/validar.py exemplos/cozinha-simples.json
```

Além do esquema, o validador confere: calibração coerente, ids únicos, aberturas dentro da parede e sem sobreposição, contorno do ambiente fechado, móvel dentro da parede de apoio, área declarada x calculada (aviso se divergir mais de 5%) e corte com plano definido.

## Converter um DXF

```bash
pip install -r requirements.txt
python3 tools/dxf_para_json.py exemplos/cozinha-planta.dxf saida.json --calibracao 0,0,4000,0,4000
python3 -m unittest discover -s tests
```

Convenção de camadas do DXF (sem diferenciar maiúsculas):

| Camada | Conteúdo |
|---|---|
| `PAREDES` | linhas ou polilinhas sobre o **eixo** das paredes |
| `PORTAS` | uma linha por porta, cobrindo o vão, apoiada sobre a parede |
| `JANELAS` | uma linha por janela, cobrindo o vão, apoiada sobre a parede |

O que o conversor faz: ajusta pontos a menos de 2 mm, ordena as paredes num contorno anti-horário, calcula posição e largura de cada abertura ao longo da parede e roda o validador. Unidade vem do cabeçalho do DXF (`$INSUNITS`) ou de `--unidade`. Sem unidade declarada e sem `--unidade`, ele recusa em vez de adivinhar.

O que **não** vem do desenho sai marcado `origem: "inferida"` com confiança 0,5: espessura das paredes (`--espessura`, padrão 150 mm), alturas e peitoril das aberturas, sentido de abertura e a calibração, quando `--calibracao` não é informada.

## Desenhar no SketchUp (conector Trimble)

O conector executa **Python** num sandbox (sem `import`, sem arquivos, unidade em polegadas), então o JSON é embutido no script:

```bash
python3 tools/gerar_script_sketchup.py exemplos/cozinha-simples.json script.py   # valida e monta tudo
```

1. Cole `script.py` em `build_model` com `clean: true`. Ele desenha paredes, piso, porta, janela, móveis, cria as cinco cenas e termina com a validação.
2. Resultado esperado para a cozinha de exemplo: `pecas_verificadas: 24`, `pecas_com_problema: []`, cinco cenas e a `lista_de_corte` dos móveis (15 chapas).
3. `save_model` devolve o `.skp`.

O que é desenhado: paredes com cantos em esquadria; piso (laje de 100 mm); porta com batente e folha **fechada**; janela com caixilho e vidro; balcão e aéreo de 2 portas, uma chapa por subgrupo.

**Medidas que o renderizador assume (não vêm do JSON, confira):** batente 40 mm, caixilho 40 mm, folha 35 mm, vidro 6 mm, piso 100 mm, fundo dos móveis 6 mm, zócalo recuado 50 mm, folga de porta 3 mm, tampo do balcão na mesma chapa do corpo (com 20 mm de avanço). Cores dos MDFs são fixas (as texturas do JSON ainda não são aplicadas).

Testado no conector com a cozinha de exemplo: todas as peças saem como sólidos fechados e as posições conferem com o JSON. **Não** foi conferido visualmente (o ambiente bloqueia o download da miniatura): abra o `.skp` e confira.

Limites: usa só o primeiro pavimento; só os blocos `balcao_2_portas` e `aereo_2_portas` têm desenho; a "Planta" é vista de cima, sem plano de corte (o conector não expõe `SectionPlane`); sem ferragens, puxadores, prateleiras nem furação.

## Limitações conhecidas (versão 0.1.0)

- O conversor aceita um único contorno fechado. Várias peças, paredes que se cruzam em T e paredes desenhadas como duas linhas (as duas faces) ainda não são tratadas.
- Polilinhas com arco são recusadas. Blocos (`INSERT`) de porta/janela e cotas escritas (OCR) não são lidos.

- Só paredes retas; paredes curvas não estão previstas.
- A conferência de área só vale para ambientes retangulares com espessura uniforme.
- Um ambiente por contorno simples; sem pátios internos.
- Os parâmetros dos blocos (`parametros`) são livres; o contrato por bloco virá com o catálogo.
- Medidas de exemplo são ilustrativas, sem validação técnica de projeto.
