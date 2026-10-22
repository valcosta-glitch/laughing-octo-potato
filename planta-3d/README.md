# planta-3d — representação intermediária (planta → 3D)

Esquema do JSON que fica entre a **leitura da planta/corte** (DXF ou IA) e o **renderizador** (SketchUp). A IA produz este JSON, o plugin o desenha, e os ajustes digitados alteram os dados, não o desenho.

## Estrutura

```
schema/projeto.schema.json     esquema (JSON Schema 2020-12)
exemplos/cozinha-simples.json  cozinha 4,00 x 3,00 m com porta, janela, balcão, gaveteiro e aéreo
exemplos/*.dxf                 cozinha-planta, cozinha-corte (separado) e sala-L-planta (corte no mesmo arquivo)
tools/validar.py               valida esquema + coerência geométrica
tools/planta_para_skp.py       DA PLANTA DXF AO SCRIPT DO SKETCHUP, num comando (começa por aqui)
tools/pdf_extrair.py           PDF VETORIAL (AutoCAD plotado) -> paredes, pilares e vãos, com porta x janela pelos vetores
tools/pdf_para_json.py         PDF vetorial -> JSON intermediário (topologia livre) + script do SketchUp + overlay.png
tools/ajustes.py               AJUSTES DIGITADOS: frase em português -> comandos estruturados -> projeto, com histórico e desfazer
tools/pdf_gerar_teste.py       gera PDFs vetoriais sintéticos (com e sem giro de página) e gabarito
tools/imagem_extrair.py        IMAGEM da planta -> paredes e vãos em pixels (visão computacional clássica)
tools/imagem_classificar_claude.py  etapa de I.A.: classifica os vãos e lê a escala (API NÃO executada)
tools/imagem_para_json.py      extração + classificação -> JSON intermediário e script do SketchUp
tools/imagem_gerar_teste.py    gera plantas sintéticas (imagem + gabarito) para testar a leitura
tools/dxf_para_json.py         converte uma planta DXF simples neste JSON
tools/gerar_dxf_exemplo.py     gera exemplos/cozinha-planta.dxf e exemplos/sala-L-planta.dxf
tools/gerar_script_sketchup.py JSON -> script para o conector Trimble SketchUp
renderer/sketchup_base.py      unidade, material, orientação de faces, GeometryInput
renderer/sketchup_paredes.py   modo "contorno": paredes com vãos de porta/janela, cantos em esquadro
renderer/sketchup_livre_ctx.py + sketchup_livre.py  modo "livre": paredes como caixas, vão = verga + peitoril + esquadria
renderer/sketchup_comum.py     funções compartilhadas (extrusão, prisma, validação de sólidos)
renderer/sketchup_esquadrias.py piso, porta (batente + folha), janela (caixilho + vidro)
renderer/sketchup_moveis.py    balcão, aéreo e gaveteiro, peça a peça, com lista de corte
renderer/sketchup_vistas.py    estilo técnico + 5 cenas ortográficas + cena Interior de cima (perspectiva)
renderer/sketchup_validacao.py confere que toda peça-folha é um sólido fechado
tests/                         testes do conversor
requirements.txt               ezdxf, jsonschema, numpy, Pillow, PyMuPDF
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

## Do PDF vetorial ao SketchUp (planta com vários cômodos)

Para o PDF que sai do AutoCAD/Revit (não escaneado): as paredes estão no arquivo como polígonos (cheios ou em contorno), então a geometria é **lida, não estimada** — sem visão computacional sobre pixels e sem I.A. na medição. O modo de saída é o `topologia: "livre"` do esquema: cada parede é uma caixa, cada vão (`vaos`) vira verga acima da porta/janela, peitoril abaixo da janela e a esquadria. Isso aceita T, vários cômodos e porta na ponta de parede, o que o modo "contorno" (um contorno fechado) não aceita.

```bash
python3 tools/pdf_para_json.py planta.pdf --saida-dir saida --cor-pilar 1,0.5,0     # --escala 50 se o PDF não trouxer "1:50" no texto
#   saida/projeto.json  saida/script_sketchup.py (colar em build_model, clean=true)  saida/overlay.png (CONFIRA)
```

Etapas: (1) escolhe a cor de preenchimento cujas faixas têm 80–350 mm; (2) rasteriza só esse preenchimento numa máscara exata (0,25 pt/px) e decompõe em peças retas, com a orientação de cada pixel decidida pela maior corrida (T fica com a parede mais longa, sem sobreposição) e tampas de ponta absorvidas pela peça vizinha; (3) cola as bordas nos vértices vetoriais do desenho; (4) o vão é o **trecho livre** na faixa da parede, a partir da ponta de uma peça longa (a lacuna entre peças não serve: um T esconde parte dela); (5) **porta** = folha (retângulo fino perpendicular, ou paralelo e aberto a 90° contra a parede) com comprimento ≈ largura do vão; **janela** = 3+ linhas paralelas na faixa; vão sem símbolo = espaço aberto (não vira parede); (6) páginas giradas são lidas na orientação em que a folha é vista. Sem preenchimento de parede, o **modo contorno** descrito abaixo.

### Alturas informadas por você (`--altura-porta`, `--topo-janela`, `--peitoril-janela`)

Quando a pessoa que fez o projeto diz a regra (ex.: "porta 2,10 m; o topo das janelas fica alinhado com o topo das portas"), ela entra direto, sem corte:

```bash
python3 tools/pdf_para_json.py planta.pdf --escala 50 --altura-porta 2100 --topo-janela 2100 [--peitoril-janela 1000]
#   ou no arquivo de ajustes:  {"padroes": {"altura_porta_mm": 2100, "topo_janela_mm": 2100, "peitoril_janela_mm": 1000}}
```

Portas ficam `origem: "usuario"` (confiança 1,0). Janela só vira `usuario` se você informar o topo **e** o peitoril; com só o topo, a altura é `topo − peitoril` (peitoril padrão 1000 mm), a janela continua `inferida` (confiança 0,5) e o aviso diz que o peitoril não foi informado. Ordem de precedência: ajuste por vão > corte > padrões informados > padrão do programa. Topo abaixo do peitoril é recusado. Com os três informados (portas 2100; janelas de 1000 a 2100 mm), tudo vira `usuario` com confiança 1,0. Valores confirmados pelo usuário: peitoril 1,00 m e topo das janelas = topo das portas = 2,10 m nas duas casas; pé-direito 2,60 m na casa de 3 quartos (Planta 1); Guarajuba 2,55 m (térreo) e 2,62 m (superior), lidos das pranchas de marcenaria. Verificado no SketchUp: topo de todas as portas e janelas = 2100 mm.

### Altura e peitoril pelo corte (`--corte`)

A planta baixa não traz pé-direito, altura de porta/janela nem peitoril; sem corte, saem valores padrão `inferida`. Com o corte em DXF 1:1 (as mesmas camadas do fluxo DXF: `CORTE_PISO` e `CORTE_TETO`, uma linha horizontal cada; `CORTE_PORTAS` e `CORTE_JANELAS`, um retângulo fechado por tipo de vão), o conversor lê o pé-direito (teto − piso) e casa cada vão da planta com um retângulo **de mesma largura** (±5 mm): altura = altura do retângulo, peitoril = base − piso, `origem: "medida"`.

```bash
python3 tools/pdf_para_json.py planta.pdf --escala 50 --cor-pilar 1,0.5,0 --corte corte.dxf --saida-dir saida
#   --unidade-corte mm|cm|m      se o DXF não declarar a unidade
#   --tolerancia-largura 85      o vão de alvenaria (planta) costuma ser a folha + batente (ex.: 880 x 800 mm)
```

Sem guesswork: largura sem retângulo correspondente, ou dois retângulos de mesma largura com alturas diferentes, mantém o padrão e **avisa**; retângulo do corte sem vão correspondente também avisa (escala ou unidade diferente?). Um `--ajustes` manual tem a última palavra sobre o corte. Testado com cortes sintéticos (pé-direito, altura, peitoril, sem correspondência, tolerância e ajuste manual; a mutação "ignorar o corte" é detectada). **Não foi testado com um corte real** (as duas plantas enviadas não têm corte) e só lê DXF, não PDF de corte.

### Teste com uma planta real (casa de 3 quartos, 1:50, A4)

Paredes cinza preenchidas, pilares laranja, cotas desenhadas como curvas (o texto não é legível pelo PDF). Resultado, conferido contra as **cotas impressas** lidas da imagem:

| Cota impressa | Modelo | Erro |
|---|---|---|
| Quarto 01 (profundidade) 3,62 m | 3625 mm | +5 |
| parede 0,15 m | 150 mm | 0 |
| Banho 1 · Banho 2 (1,40 m) | 1400 · 1395 mm | 0 · −5 |
| Suíte casal (profundidade) 4,00 m | 4000 mm | 0 |
| Suíte 02 · Quarto 02 · Banho 3 (3,67 · 4,54 · 0,83 m) | 3670 · 4540 · 825 mm | 0 · 0 · −5 |
| Suíte casal (largura) 2,82 m | 2835 mm | **+15** |

Erro médio 3,3 mm; o maior (+15) vem do próprio desenho (paredes de 155–159 mm ali, normalizadas para 150 mm). Vãos: 15 detectados (7 janelas, 8 portas), todos conferidos no overlay contra a planta; nas portas etiquetadas (0,80/0,70/0,60 × 2,10) o vão de alvenaria medido é a folha + ~8 cm de batente (0,88/0,78/0,68), e o renderizador, com batente de 40 mm, devolve folhas de ≈0,80/0,70/0,60. **Fechado no SketchUp:** 103 peças-folha, todas sólidos fechados, 0 problemas.

**Não vem da planta (valores padrão, marcados `inferida` com confiança 0,3 e avisados):** pé-direito 2700 mm; altura da porta 2100 mm (bate com as etiquetas "x2.10", mas foi suposta); janelas 1200 mm de altura a 1000 mm do piso. Informe pelo corte ou por `--ajustes ajustes.json`. O piso é uma laje retangular sob a caixa envolvente.

### Teste com a segunda planta real (layout de interiores, 2 pavimentos, 1:50, A3 girada 270°)

Aqui as paredes **não têm preenchimento**: cada parede é a região entre duas polilinhas aninhadas (face externa e interna, traço de 1,08 pt). O **modo contorno** (`--estilo contorno`, automático quando nenhuma cor de preenchimento parece parede) preenche cada polilinha como polígono e fica com a **paridade** (par/ímpar): o anel entre os contornos sobra, e as interrupções dos contornos são os vãos. Os fios diagonais que o fechamento implícito de polilinhas abertas deixa são removidos por espessura. A folha tem dois pavimentos: cada um sai com `--regiao` (em pontos, na orientação em que a folha é vista).

```bash
python3 tools/pdf_para_json.py layout.pdf --escala 50 --regiao 30,250,420,1040  --saida-dir terreo      # pavimento térreo
python3 tools/pdf_para_json.py layout.pdf --escala 50 --regiao 440,250,820,1040 --saida-dir superior    # pavimento superior
```

Cotas impressas do térreo conferidas com o modelo (as cotas "2.53", "3.03", "3.08" são larguras de cômodo, não de janela):

| Cota impressa | Modelo | Erro |
|---|---|---|
| Garden (largura) 5,76 m | 5750 mm | −10 |
| Garden (profundidade) 2,50 m | 2500 mm | 0 |
| Cozinha/serviço 2,51 m | 2505 mm | −5 |
| Suíte 04 (profundidade) 3,63 m | 3625 mm | −5 |
| Depósito 1,41 m | 1405 mm | −5 |

Paredes: espessuras 190 mm (externas), 130 mm (divisórias) e 240 mm (parede hachurada), lidas do desenho. Fechado no SketchUp: térreo 43 peças-folha e superior 50, todas sólidos fechados, 0 problemas.

**Pranchas de marcenaria da mesma casa (5 PDFs "DET", 1:25).** Não são cortes de parede, mas trazem cotas que valem como segunda fonte, lidas por mim nas imagens (as cotas são desenhadas como curva, então não saem como texto do PDF):
- **Pé-direito (confirma que o padrão de 2,70 m estava errado):** térreo **2,55 m** (suíte 04, sala/TV, roupeiro, gourmet) e **2,60 m** (cozinha e área de serviço); 2º pavimento **2,62 m** (suítes). Um único `--pe-direito` por pavimento não representa as duas alturas do térreo: usei 2550 no térreo e 2620 no superior e deixei o aviso. Modelos regenerados com esses valores.
- **Conferência extra da extração de paredes** (cotas de cômodo das pranchas e da planta): Suíte 04 2,53 m → 2525 mm (−5); Circ./Roup. 0,93 m → 920 mm (−10); Suíte 02 2,53 m → 2515 mm (−15); Suíte máster 4,18 m → 4170 mm (−10). Com as 5 anteriores, as 9 cotas do Guarajuba ficam todas dentro de 15 mm.
- **Medidas de marcenaria candidatas a blocos da biblioteca** (não usadas ainda; leitura de imagem, sem conferência): armários de piso a teto com profundidade 0,55 m e larguras 1,58 m (suítes 04/02) e 4,18 m (máster); bancada de apoio/península a 1,05 m de altura; bancada de banheiro a 1,05 m com espelho de 1,00 m acima; parede de tijolo de vidro 19×19 com 2,38 m de altura sobre base de 0,15 m. As pranchas **não trazem altura de porta nem de janela**.

**Os vãos neste estilo são candidatos, não resultado.** Regras que funcionaram aqui: arco de giro ⇒ porta (e, quando o desenho usa arcos, folha sem arco deixa de bastar: sem isso a escada e a cozinha geravam 6 portas falsas); janela = 3+ linhas paralelas, ou 2 linhas com batente nas duas pontas. Resultado conferido no `overlay.png`: térreo 6 vãos (2 janelas, 4 portas), superior 10 (3 janelas, 7 portas), dos quais **1 era falso** (uma "janela" de 2,53 m que um humano removeu com `--ajustes '{"vaos": {"9": {"remover": true}}}'`). **Não entra**: a escada (as paredes ao redor dela entram como parede, mas a escada não é modelada). Os muros do garden e a parede do terreno entram como paredes de 2,70 m de altura: confira o overlay e use `--ajustes` ou `--regiao`.

**Outros limites.** Só paredes ortogonais; escada, curvas, varanda e hachura não são modeladas; vão sem folha/linhas reconhecíveis é tratado como aberto (a "passagem" com batente e sem folha aparece como aviso, sem esquadria); uma porta de correr sem os painéis desenhados seria perdida (ver a seção de portas de correr); a escolha automática da cor das paredes pode errar com escala errada (use `--cor-parede`).

**Testes** (`tests/test_pdf.py`, PDFs sintéticos com gabarito, 8 sementes, com giro 90/180/270): centros e larguras dos vãos ≤ 10 mm, extensão da planta ≤ 10 mm, tipos certos; os dois estilos (preenchido e contorno) são testados; um terceiro, linhas soltas sem polígono, tem de ser recusado com erro claro; mutações (regra de janela quebrada, 1% de erro na escala) são detectadas. Os PDFs reais não estão no repositório.

### Portas de vidro de correr

Tipo de vão `porta_correr` (no JSON: `tipo`, `folhas` de 2 a 6, padrão 3; vai do piso até a altura de porta, sem peitoril).

**Como o PDF é lido.** Nas plantas de interiores a porta de correr não tem arco nem folha: é um vão entre dois **tocos de parede** curtos (menores que 2× a espessura) com painéis finos escalonados em trilhos. O extrator agora aceita um vão entre tocos **somente se** achar nele pelo menos 6 segmentos de painel (0,18 a 0,6 da largura) em 3 ou mais posições e a largura for de 2 m ou mais; senão o vão segue tratado como espaço aberto. O número de folhas é o número de painéis desenhados, e o vão vai de onde começam os painéis até onde terminam (o trecho livre pode se estender para um espaço aberto ao lado). Janelas de 2 folhas têm o mesmo desenho que uma porta de correr de 2 folhas: a dúvida fica com a **janela** (`transformar janela 3 em porta de correr` resolve).

**Teste real (Guarajuba).** Térreo: sala 2,63 m com 3 folhas e garden 2,57 m com 4 folhas. Superior: varanda da suíte máster 2,63 m com 3 folhas. A medida é **entre os tocos**: as cotas impressas (3,03 m e 3,08 m) são maiores porque contam também os tocos, então confirme no detalhamento antes de fabricar. No SketchUp, 63 peças fechadas, 0 problema; cada porta é batente em U e trilho de alumínio, mais as folhas (moldura de 35 × 40 mm e vidro de 6 mm) em dois trilhos alternados com 50 mm de sobreposição (medidas padrão do renderizador, não vêm do projeto).

| Frase (exemplos) | O que faz |
|---|---|
| `transformar janela 3 em porta de correr` · `... em porta de correr, 4 folhas` | troca o tipo (vai até o topo da janela, sem peitoril) |
| `porta de correr 4: 4 folhas` · `porta 4: altura 2,20 m` · `largura do vão 4: 2,70 m` | altera |
| `adicionar porta de correr de 2,6 m na parede p5 a 1 m do início, 3 folhas` | abre o vão |
| `transformar vão 4 em porta` | volta a porta de abrir (tira as folhas); tudo tem desfazer exato |

## Ajustes digitados (`tools/ajustes.py`)

O cliente corrige o que a leitura automática errou **digitando frases**, sem arquivo de configuração e sem mexer em código:

```bash
python3 tools/ajustes.py projeto.json "remover vão 9" "pé-direito 2,62 m" "todas as janelas: peitoril 1 m, topo 2,10 m" --saida projeto2.json --script script_sketchup.py
python3 tools/ajustes.py projeto2.json --desfazer --saida projeto3.json      # desfaz a última frase
python3 tools/ajustes.py projeto2.json --historico
```

| Frase (exemplos) | O que faz |
|---|---|
| `remover vão 9` · `remover janela 3` · `apagar a porta v4` | tira o vão (verga, peitoril e esquadria) e **deixa o espaço aberto** |
| `fechar vão 9` | troca o vão por um trecho de parede |
| `janela 3: peitoril 1,10 m` · `altura da porta 2 para 2,20 m` · `topo da janela 3 2,10 m` · `largura do vão 5: 0,90 m` | altera um vão (a largura é centrada) |
| `transformar vão 4 em janela, peitoril 1 m, altura 1,1 m` · `transformar a janela 3 em porta` | troca o tipo (janela exige peitoril e altura; porta mantém o topo) |
| `mover janela 3 20 cm para leste` | desloca o vão **ao longo da parede** (norte = +Y, sul = −Y, leste = +X, oeste = −X) |
| `todas as janelas: peitoril 1 m, topo 2,10 m` · `todas as portas: altura 2,10 m` | em lote |
| `pé-direito 2,60 m` | pé-direito do pavimento |
| `parede p5 espessura 15 cm` · `remover parede p5` · `mover parede p5 10 cm para o norte` | paredes (mover leva os vãos da parede junto, e avisa que as junções não são esticadas) |
| `adicionar janela de 1,20 m na parede p5 a 2 m do início, peitoril 1 m, altura 1,1 m` | divide a parede em duas peças e abre o vão (início = ponta de menor coordenada) |

Regras de projeto, todas testadas:
- **Nunca código livre.** A frase vira **comandos estruturados** (`acao`, `alvo`, `alvo_id`, `parametros`, em mm), que o programa valida e executa. A tradução frase → comando é por regras e **offline**; uma camada de I.A. pode, no futuro, traduzir frase livre para essas mesmas frases/comandos sem mudar o resto.
- **Nunca adivinha.** Frase que não casa, número sem unidade ambíguo (`peitoril 90`: cm ou m?), vão inexistente, tipo que não confere (`janela 9` quando v9 é porta), direção impossível (mover para o norte um vão numa parede que corre em Y) ou porta com peitoril ≠ 0 dão **erro explicado** e nada muda.
- **Atômico.** Um lote só é aplicado se todas as frases forem válidas **e** o projeto resultante passar no esquema e na validação geométrica (ex.: `pé-direito 2 m` com porta de 2,10 m é recusado). Frase redundante (o projeto já está assim) vira aviso e o resto do lote segue; dizer o valor de um vão que estava `inferida` o confirma (`usuario`, confiança 1,0).
- **Auditável e reversível.** Cada frase é um grupo no `historico_ajustes` (texto original, comando e **comando inverso**); `--desfazer` restaura o estado **exato** anterior, inclusive origem, confiança e evidência.

**Prova com a planta real (Guarajuba, superior).** As correções que eu tinha feito à mão e por arquivo (remover a janela falsa, pé-direito, altura de porta e janela) foram refeitas **só com 4 frases** a partir da extração bruta (valores padrão): geometria, origem e confiança ficaram **idênticas** ao modelo já salvo no SketchUp.

**Limites:** só frases nas formas acima (frase livre ainda não); no modo "contorno" (DXF) valem só as frases de vão (remover, altura/peitoril, tipo em lote, pé-direito) e móveis por frase não existem; adicionar parede por frase não existe (só pelo comando estruturado); mover parede não ajusta as paredes vizinhas.

### Marcenaria por frase (modo livre)

Móveis se apoiam **numa parede e num lado dela** (`apoio.parede_id` + `apoio.lado` = norte/sul para parede horizontal, leste/oeste para vertical; a distância é medida da ponta de menor coordenada). O validador confere que o móvel **cabe** na parede, **não passa do pé-direito**, **não bate** em outra parede (erro), **não se sobrepõe** a outro móvel (erro) e avisa quando **cobre um vão**.

| Frase (exemplos) | O que faz |
|---|---|
| `adicionar armário de 1,58 m na parede p5 lado norte a 2 m do início` | roupeiro piso-teto (também `a 1 m do fim` e `encostado no início/fim`, que respeita a parede que fecha o canto) |
| `adicionar gabinete de 1,20 m na parede p3 lado leste a 0,5 m do início, profundidade 55 cm, frente nogueira` | gabinete suspenso (elevação padrão 20 cm) |
| `adicionar rack de 2,20 m ...` · `adicionar painel de 2,44 m ...` · `adicionar espelho de 1,2 m ...` · `adicionar balcão de 1 m ..., altura 90 cm, profundidade 60 cm` | rack suspenso (24 cm do piso), painel, espelho, balcão, aéreo, gaveteiro |
| `remover móvel m2` · `mover armário m2 20 cm para leste` (só ao longo da parede) | |
| `móvel m1: largura 1,60 m, altura 2,40 m, frente freijó, portas 4` · `móvel m1: piso ao teto` | altera; piso-teto acompanha o pé-direito |

As medidas que a frase não traz usam o **padrão do bloco** (`tools/blocos.py`, lido das pranchas de detalhe **a olho**, sem conferir cota): roupeiro profundidade 55 cm e zócalo 10 cm; gabinete 85 cm de altura, 48 cm de profundidade, 20 cm do piso; rack 36 × 40 cm, 24 cm do piso; painel 1,20 m; espelho 1,00 m a 1,05 m do piso; chapa 15 mm; portas ≈ 60 cm cada. Cada uso de padrão vira **AVISO** para você conferir. Frentes: branco, marula, titânio, freijó, nogueira, verde, espelho (**cores aproximadas**; texturas reais virão do catálogo de acabamentos). Caixaria sempre branca. O SketchUp recebe cada chapa como grupo nomeado e a **lista de corte** sai no resultado.

**Prova com a planta real (Guarajuba, superior).** Com duas frases (`adicionar roupeiro de 4,18 m na parede p20 lado oeste a 5,9 m do início, frente freijó` e `adicionar roupeiro de 1,58 m na parede p5 lado norte encostado no início, frente marula`) o modelo saiu no SketchUp com 77 peças fechadas e **0 problemas** (27 chapas na lista de corte). As caixas conferem com o previsto em planta: roupeiro da suíte máster de x 5400–5950 mm e y 5900–10080 mm (4,18 m, encostado na face da parede p20); roupeiro da suíte 02 de x 240–1820 mm e y 6830–7380 mm (1,58 m, do canto até o fim da parede p5, que mede 1,59 m).

### Acabamentos e texturas (`tools/acabamentos.py`)

Catálogo versionado (`acabamentos`, versão 1) com pinturas lisas (branco, areia, cinza claro/grafite, verde, verde sálvia, azul petróleo, terracota, espelho), madeiras (marula, freijó, nogueira véneto, carvalho), titânio trama, granito branco itaúnas, porcelanato cinza/areia 60×60 e cimento queimado. `python3 tools/acabamentos.py` lista os itens, com o tipo e onde servem (parede, piso, móvel).

| Frase (exemplos) | O que faz |
|---|---|
| `pintar parede p5 de verde sálvia` · `revestir parede p5 com marula` · `acabamento da parede p5: nogueira véneto` | acabamento na parede inteira |
| `pintar parede p5 lado norte de terracota` | só as faces voltadas para o norte (o lado tem de existir na parede) |
| `piso porcelanato cinza` · `acabamento do piso: cimento queimado` | piso (troca o anterior, não acumula) |
| `remover acabamento a1` · `remover acabamento da parede p5` · `remover acabamento do piso` | volta ao padrão |
| `adicionar armário de 1,58 m ..., frente titânio trama` · `móvel m1: frente granito branco itaúnas` | a frente do móvel usa os mesmos nomes do catálogo |

No JSON cada acabamento é `{"id": "a1", "alvo": {"tipo": "parede" | "piso", "id": ..., "lado": ...}, "textura": {"catalogo": "acabamentos", "id": "marula", "versao": 1}}`. O validador recusa item fora do catálogo, uso errado (porcelanato em parede), parede/lado inexistente, pilar e dois acabamentos no mesmo alvo. Tudo tem desfazer exato, como as outras frases.

**Como a textura aparece no SketchUp.** O conector não lê arquivos de imagem, então as texturas são **procedurais**: uma amostra de 64×64 pixels (veio de madeira, pontilhado de granito, trama, juntas de porcelanato) que se repete no tamanho real do material (`escala_mm`). Elas lembram o material, **não são a foto do fabricante**; os tons vieram das pranchas a olho. Medi no conector que `set_dimensions` espera **pixels por polegada** (o inverso deixa a textura gigante e lisa). Se a textura falhar, cai na cor média sólida. Só os itens usados entram no script. Limites: a verga e o peitoril dos vãos junto da parede pintada não mudam de cor; no modo contorno (DXF) só vale a `frente` do móvel; não há ainda orientação do veio por peça nem acabamento por face interna/externa (só por lado geográfico).

**Prova (Guarajuba, superior, com frases).** `pintar parede p15 lado leste de verde sálvia`, `pintar parede p17 lado oeste de terracota` e `piso porcelanato cinza`, mais as frentes freijó (roupeiro máster) e marula (roupeiro da suíte 02): o SketchUp aceitou os 5 materiais (2 lisos e 3 texturizados: freijó, marula e porcelanato), aplicou cada um só nas faces pedidas (1 face por alvo) e as 77 peças continuaram fechadas, sem problema. Na miniatura aparece a parede verde-sálvia; a miniatura do conector é sempre a vista externa padrão, então a madeira nas portas dos roupeiros não aparece nela. Num teste à parte (caixas e planos) vi a madeira, o granito, a trama e o porcelanato desenhados com o tamanho de amostra correto.

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

- O conversor aceita um único contorno fechado. Móveis só encostados numa parede e alinhados a ela (sem canto em L de móveis, ilhas nem móveis girados). Várias peças e T só existem pelo caminho PDF vetorial (topologia livre; móveis por parede e lado); paredes desenhadas como duas linhas (as duas faces) ainda não são tratadas.
- Imagem: ver a seção própria (só paredes ortogonais, um contorno, sem móveis). PDF vetorial: ver a seção própria (vários cômodos, paredes cheias ou em contornos aninhados; linhas soltas sem polígono não).
- Polilinhas com arco são recusadas. Blocos (`INSERT`) de porta/janela e cotas escritas (OCR) não são lidos.

- Só paredes retas; paredes curvas não estão previstas.
- A conferência de área só vale para ambientes retangulares com espessura uniforme.
- Um ambiente por contorno simples; sem pátios internos.
- Os parâmetros dos blocos (`parametros`) são livres; o contrato por bloco virá com o catálogo.
- Medidas de exemplo são ilustrativas, sem validação técnica de projeto.
