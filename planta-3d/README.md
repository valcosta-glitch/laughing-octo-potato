# planta-3d — representação intermediária (planta → 3D)

Esquema do JSON que fica entre a **leitura da planta/corte** (DXF ou IA) e o **renderizador** (SketchUp). A IA produz este JSON, o plugin o desenha, e os ajustes digitados alteram os dados, não o desenho.

## Estrutura

```
schema/projeto.schema.json     esquema (JSON Schema 2020-12)
exemplos/cozinha-simples.json  cozinha 4,00 x 3,00 m com porta, janela, balcão, gaveteiro e aéreo
exemplos/*.dxf                 cozinha-planta, cozinha-corte (separado) e sala-L-planta (corte no mesmo arquivo)
tools/validar.py               valida esquema + coerência geométrica
tools/planta_para_skp.py       DA PLANTA DXF AO SCRIPT DO SKETCHUP, num comando (começa por aqui)
tools/imagem_extrair.py        IMAGEM da planta -> paredes e vãos em pixels (visão computacional clássica)
tools/imagem_classificar_claude.py  etapa de I.A.: classifica os vãos e lê a escala (API NÃO executada)
tools/imagem_para_json.py      extração + classificação -> JSON intermediário e script do SketchUp
tools/imagem_gerar_teste.py    gera plantas sintéticas (imagem + gabarito) para testar a leitura
tools/dxf_para_json.py         converte uma planta DXF simples neste JSON
tools/gerar_dxf_exemplo.py     gera exemplos/cozinha-planta.dxf e exemplos/sala-L-planta.dxf
tools/gerar_script_sketchup.py JSON -> script para o conector Trimble SketchUp
renderer/sketchup_paredes.py   paredes com vãos de porta/janela (roda no sandbox do conector)
renderer/sketchup_comum.py     funções compartilhadas (extrusão, prisma, validação de sólidos)
renderer/sketchup_esquadrias.py piso, porta (batente + folha), janela (caixilho + vidro)
renderer/sketchup_moveis.py    balcão, aéreo e gaveteiro, peça a peça, com lista de corte
renderer/sketchup_vistas.py    estilo técnico + 5 cenas ortográficas + cena Interior de cima (perspectiva)
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

## Da planta DXF ao SketchUp, num comando

```bash
pip install -r requirements.txt
python3 tools/planta_para_skp.py exemplos/sala-L-planta.dxf --saida-dir saida --calibracao 0,0,600,0,6000
# com o corte em outro arquivo:
python3 tools/planta_para_skp.py exemplos/cozinha-planta.dxf --corte exemplos/cozinha-corte.dxf --saida-dir saida --calibracao 0,0,4000,0,4000
```

Escreve `saida/projeto.json` (confira os valores marcados `inferida`) e `saida/script_sketchup.py`. Cole o script em `build_model` (com `clean: true`) do conector Trimble SketchUp e depois use `save_model`. O comando para com erro, sem escrever nada, se a conversão ou a validação falhar.

Convenção de camadas do DXF (sem diferenciar maiúsculas):

| Camada | Conteúdo |
|---|---|
| `PAREDES` | linhas ou polilinhas sobre o **eixo** das paredes (um contorno fechado) |
| `PORTAS` / `JANELAS` | uma linha por vão, apoiada sobre a parede |
| `MOVEIS_<BLOCO>` | um **retângulo fechado** por móvel, com a face de trás junto à parede (até 150 mm) e alinhado a ela |
| `CORTE_PISO`, `CORTE_TETO` | **corte 1:1** (no mesmo DXF, em qualquer lugar, ou em outro arquivo com `--corte`): uma linha horizontal cada; o pé-direito é a distância entre elas |
| `CORTE_PORTAS`, `CORTE_JANELAS` | um **retângulo fechado** alinhado aos eixos por tipo de vão, na vista do corte |

**Como o corte é lido.** O pé-direito vem da distância entre as linhas de piso e teto (e tem prioridade sobre `--pe-direito`). A altura de cada abertura é a altura do retângulo e o peitoril é a distância dele ao piso; o retângulo vale para as aberturas da planta do **mesmo tipo e da mesma largura** (±5 mm). Os valores lidos saem com `origem: "medida"` e confiança 0,9. O conversor **não chuta**: avisa e mantém o padrão quando (a) uma abertura não tem retângulo de mesma largura, (b) há retângulos de mesma largura com alturas ou peitoris diferentes (ambíguo), (c) falta a linha de piso (sem ela não há peitoril) ou há linhas repetidas, (d) um retângulo do corte não corresponde a nenhuma abertura (sinal de escala ou unidade diferente no corte). Porta com peitoril no corte é forçada a 0. Uma abertura mais alta que o pé-direito é erro de validação.

Blocos: `MOVEIS_BALCAO_2_PORTAS`, `MOVEIS_AEREO_2_PORTAS`, `MOVEIS_GAVETEIRO_3_GAVETAS`. Largura e profundidade vêm do retângulo; altura (870 / 700 / 870 mm), chapa (18 / 15 / 18 mm), zócalo e elevação (aéreo a 1400 mm) são **padrões do bloco** (`BLOCOS_PADRAO` em `tools/dxf_para_json.py`), não vêm do desenho. A parede de apoio é descoberta pela geometria.

Testado de ponta a ponta com a cozinha (mm, com corte em arquivo separado: pé-direito 2800, porta 2200, janela 1200 a 1000 do piso, e as alturas conferidas de volta no SketchUp) e com `sala-L-planta.dxf` (em **cm**, desenhada no sentido **horário**, com parede reentrante, 3 aberturas e 5 móveis): o conversor reorienta o contorno, converte a unidade e ancora os móveis; o script rodou no conector com 68 peças sólidas verificadas e sem problemas. O que não é validado: se as medidas desenhadas estão certas (isso é do projeto), e a aparência das cenas (ver abaixo).

O validador recusa móveis sobrepostos na mesma parede e avisa quando um móvel cruza uma porta ou janela.

## Da imagem da planta ao SketchUp

Para foto, scan ou PDF rasterizado de uma planta. O desenho é dividido de propósito: **a geometria não vem da I.A.**, porque modelos de linguagem estimam coordenadas em pixels com erro de dezenas de pixels. A I.A. entra só no que ela faz bem (semântica).

```
imagem ──► imagem_extrair.py ──► extracao.json + overlay.png      (paredes e vãos em pixels; visão computacional clássica)
                                        │
overlay.png + extracao.json ──► I.A. (ou pessoa) ──► classificacao.json   (porta/janela de cada vão numerado; a cota escrita → escala)
                                        │
extracao.json + classificacao.json ──► imagem_para_json.py ──► projeto.json + script_sketchup.py   (mesmo conversor e validador do DXF)
```

```bash
python3 tools/imagem_extrair.py planta.png --saida-dir saida            # gera saida/extracao.json e saida/overlay.png
# classificação: pela I.A. (tools/imagem_classificar_claude.py) ou à mão, num classificacao.json:
#   {"calibracao": {"parede": 1, "referencia": "externa", "medida_mm": 5400, "origem": "cota lida: 5,40 m"},
#    "aberturas": {"1": "janela", "2": "janela", "3": "porta"}, "ambiente": "SALA"}
python3 tools/imagem_para_json.py saida/extracao.json classificacao.json --saida-dir saida2
```

**O que a extração faz.** Separa o que é parede (faixa escura sólida, grossa e longa, na horizontal ou vertical) do traço fino (arco e folha de porta, cota, texto, móveis). Os vãos são as interrupções de uma parede; os cantos viram o cruzamento dos eixos. A imagem é desinclinada automaticamente (até ±4°). O comprimento mínimo de parede acompanha a espessura estimada.

**Precisão medida** (plantas sintéticas com gabarito, 24 por linha, paredes de 15 px a 100 px/m):

| Condição | Plantas lidas certo | Erro máx. de parede | Erro máx. de posição do vão | Erro máx. de largura do vão |
|---|---|---|---|---|
| limpa | 24/24 | 0 mm | 10 mm | 0 mm |
| ruído + desfoque + JPEG | 24/24 | 0 mm | 10 mm | 0 mm |
| girada 1,5° | 24/24 | 0 mm | 10 mm | 10 mm |
| girada −2° + ruído/JPEG | 24/24 | 0 mm | 10 mm | 0 mm |
| meia resolução (50 px/m) | 24/24 | 20 mm | 22 mm | 20 mm |
| 1/3 da resolução (33 px/m) | **10/24** | 30 mm | 45 mm | 40 mm |

O erro de 10 mm é 1 pixel nessa escala. **Em 33 px/m a leitura falha em mais da metade, e parte das falhas é silenciosa (um vão some)**: por isso há avisos explícitos de resolução (parede com menos de 10 px; "RESOLUÇÃO MUITO BAIXA" com menos de 6 px; escala a partir de 15 mm/px). Use imagem com a parede de **pelo menos 8 a 10 px** de espessura e confira o `overlay.png`.

**Avaliação "cega" da etapa de I.A.** Três plantas novas (sementes nunca vistas, uma em L com ruído e JPEG); a classificação foi feita só olhando as imagens, antes de abrir o gabarito: 9 de 9 vãos com tipo, largura e posição certos (≤ 10 mm), escala lida da cota certa. Quem classificou foi o próprio Claude desta sessão, não a chamada de API do repositório, que **não foi executada** (usaria a `ANTHROPIC_API_KEY` do ambiente, sem autorização); só a parte offline dela (montar o prompt, interpretar e validar a resposta) é testada. Rode `tools/imagem_classificar_claude.py` uma vez numa planta conhecida antes de confiar.

**Onde quebra (testado):** paredes desenhadas em linha dupla (contorno oco) ou hachuradas dão **erro claro**, não resultado errado; o traço claro em cinza funciona. Ainda não suporta: paredes inclinadas (só horizontais/verticais), mais de um contorno, espessuras diferentes entre paredes, paredes que se encontram em T, móveis (não são lidos da imagem), cota que não esteja escrita na imagem (a escala vem só de uma cota lida ou de uma medida informada).

**O que as imagens deste teste NÃO provam.** São sintéticas e limpas: traço preto sólido, símbolos padronizados. Plantas reais têm legendas sobre as paredes, hachuras, vários estilos de porta e janela, escalas gráficas e carimbos. Os números acima mostram que o algoritmo faz o que se propõe nesse caso, não que lê qualquer planta.

## Converter um DXF (só até o JSON)

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

O que **não** vem do desenho sai marcado `origem: "inferida"` com confiança 0,5: espessura das paredes (`--espessura`, padrão 150 mm), alturas e peitoril das aberturas **sem corte**, sentido de abertura e a calibração, quando `--calibracao` não é informada.

## Desenhar no SketchUp (conector Trimble)

O conector executa **Python** num sandbox (sem `import`, sem arquivos, unidade em polegadas), então o JSON é embutido no script:

```bash
python3 tools/gerar_script_sketchup.py exemplos/cozinha-simples.json script.py   # valida e monta tudo
```

1. Cole `script.py` em `build_model` com `clean: true`. Ele desenha paredes, piso, porta, janela, móveis, cria as seis cenas e termina com a validação.
2. Resultado esperado para a cozinha de exemplo: `pecas_verificadas: 48`, `pecas_com_problema: []`, seis cenas e `pecas_por_movel` (balcão 8, gaveteiro 24, aéreo 7 = 39 chapas na lista de corte).
3. `save_model` devolve o `.skp`.

O que é desenhado: paredes com cantos em esquadria; piso (laje de 100 mm); porta com batente e folha **fechada**; janela com caixilho e vidro; balcão e aéreo de 2 portas e gaveteiro de 3 gavetas, uma chapa por subgrupo.

**Medidas que o renderizador assume (não vêm do JSON, confira):** batente 40 mm, caixilho 40 mm, folha 35 mm, vidro 6 mm, piso 100 mm, fundo dos móveis 6 mm, zócalo recuado 50 mm, folga de porta 3 mm, tampo do balcão na mesma chapa do corpo (com 20 mm de avanço). Cores dos MDFs são fixas (as texturas do JSON ainda não são aplicadas).

Testado no conector com a cozinha de exemplo: todas as peças saem como sólidos fechados e as posições conferem com o JSON. A miniatura do `save_model` vem em base64 (`thumbnail_base64`) e pode ser decodificada para uma imagem; ela mostrou porta, janela com vidro, piso e, por dentro da janela, os móveis. A miniatura é uma vista fixa e **não** reflete as cenas nem a câmera do modelo, então as seis cenas não foram vistas. Para a cena "Interior de cima" conferi só por leitura de volta: a etiqueta contém a parede da frente e a porta, e só essa cena a oculta. Abra o `.skp` para ver as cenas. O link de download não é acessível a partir do ambiente de nuvem (política de rede).

Cenas: Planta, Frontal, Fundos, Lateral esquerda, Lateral direita (ortográficas) e **Interior de cima** (perspectiva a 40° de altura e 10° de azimute, olhando para dentro). Essa cena **oculta a parede da frente e a porta** dela, por meio da etiqueta `Parede_da_frente`; as outras cenas gravam a etiqueta visível. A parede da frente é a que fica entre a câmera e o ambiente. O arquivo abre em "Interior de cima".

**Blocos da biblioteca (catálogo `demo`):** `balcao_2_portas`, `aereo_2_portas` e `gaveteiro_3_gavetas`. O gaveteiro usa o parâmetro `gavetas` (o nome do bloco diz 3, mas o desenho aceita 2 a 4; testado sem sobreposição). Cada gaveta: frente de 18 mm + caixa (duas laterais, traseira e frente interna de 15 mm, fundo de 6 mm), folga de 13 mm de cada lado para a corrediça e comprimento da caixa em múltiplos de 50 mm, até 550. Sem corrediças, puxadores nem furação desenhados.

Limites: usa só o primeiro pavimento; só os três blocos acima têm desenho; a "Planta" é vista de cima, sem plano de corte (o conector não expõe `SectionPlane`); sem ferragens, puxadores, prateleiras nem furação.

## Limitações conhecidas (versão 0.1.0)

- O conversor aceita um único contorno fechado. Móveis só encostados numa parede e alinhados a ela (sem canto em L de móveis, ilhas nem móveis girados). Várias peças, paredes que se cruzam em T e paredes desenhadas como duas linhas (as duas faces) ainda não são tratadas.
- Imagem: ver a seção própria (só paredes ortogonais, um contorno, sem móveis).
- Polilinhas com arco são recusadas. Blocos (`INSERT`) de porta/janela e cotas escritas (OCR) não são lidos.

- Só paredes retas; paredes curvas não estão previstas.
- A conferência de área só vale para ambientes retangulares com espessura uniforme.
- Um ambiente por contorno simples; sem pátios internos.
- Os parâmetros dos blocos (`parametros`) são livres; o contrato por bloco virá com o catálogo.
- Medidas de exemplo são ilustrativas, sem validação técnica de projeto.
