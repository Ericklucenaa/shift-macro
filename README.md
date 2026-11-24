# Shift Macro Recorder

[![Apoie no Ko-fi](https://img.shields.io/badge/Ko--fi-apoiar%20o%20projeto-F2A93B?logo=ko-fi&logoColor=white)](https://ko-fi.com/ericklucena)
[![Última versão](https://img.shields.io/github/v/release/Ericklucenaa/shift-macro?label=vers%C3%A3o)](https://github.com/Ericklucenaa/shift-macro/releases/latest)

Aplicativo para Windows 10 e 11 que grava, edita e executa macros de mouse e teclado, com reconhecimento de imagem (Smart Click), condições, loops, variáveis e funções. Funciona offline, sem conta e sem assinatura.

## Instalar

**Para usar:** baixe `ShiftMacro-x.y.z-win64.zip` na [página de versões](https://github.com/Ericklucenaa/shift-macro/releases/latest), extraia e rode `ShiftMacro.exe`. Para instalar no Menu Iniciar e abrir arquivos `.shiftmacro` com duplo clique, rode, de dentro da pasta extraída:

```powershell
powershell -ExecutionPolicy Bypass -File instalar.ps1            # opção: -AtalhoAreaDeTrabalho
```

O instalador não pede administrador: copia para `%LOCALAPPDATA%\Programs\Shift Macro` e aparece em *Configurações > Aplicativos*, de onde também desinstala. Com o Inno Setup 6 instalado, `scripts\compilar.ps1` também gera um `ShiftMacro-1.0.0-setup.exe`.

**Para desenvolver** (Python 3.12):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\instalar-dependencias.ps1
.venv\Scripts\python.exe main.py [arquivo.shiftmacro]
```

### Atualizações

Ao abrir, no máximo uma vez por dia, o app consulta as releases públicas do GitHub. É a única conexão que ele faz, e não envia nada. Quando há versão nova, mostra o que mudou e oferece *Baixar e instalar*.

**Como a instalação funciona:**
1. O app baixa o pacote e confere o SHA-256 publicado junto com a release. Se não bater, recusa.
2. Fecha.
3. Troca os arquivos da pasta do aplicativo.
4. Abre de novo.

Também dá para procurar à mão em *Ajuda > Verificar atualizações* e desligar a consulta automática em *Configurações > Preferências*. Suas macros e configurações não são tocadas.

## Uso rápido

1. **Gravar:** *Gravar* (F9), faça a tarefa e pressione F9 de novo. Cliques, cliques duplos, arrastes, rolagem, textos, combinações de teclas, teclas seguradas e os tempos entre ações viram etapas editáveis. A seta ao lado de *Gravar* escolhe *mouse e teclado*, *somente cliques* ou *somente teclado* e se os movimentos do mouse entram.
2. **Smart Click:** Shift+F11, em qualquer momento, congela a tela para você recortar a imagem de um botão. A etapa procura essa imagem durante a execução e clica onde ela estiver, mesmo que tenha mudado de lugar. *Testar agora* mostra onde ela foi encontrada e com que similaridade.
3. **Editar:** duplo clique abre a etapa. O painel *Propriedades* edita a etapa selecionada. Arraste linhas para reordenar e use a caixa da coluna *Etapa* para desativar sem apagar. Ctrl+Z desfaz. Selecione várias etapas e insira um Loop ou If para envolvê-las no bloco.
4. **Executar:** no painel inferior escolha uma vez, N vezes, por um tempo ou sem parar, e a velocidade. F6 executa, F7 pausa ou continua e F8 para na hora. A seta ao lado de *Executar* tem *a partir da etapa selecionada*, *somente as selecionadas* e *passo a passo* (F10).

### Atalhos globais

Funcionam com o app minimizado e podem ser trocados em *Configurações > Atalhos globais*. Cada macro também pode ter atalhos próprios, em *Arquivo > Propriedades da macro*.

| Atalho | Ação |
|---|---|
| F6 | Iniciar execução |
| F7 | Pausar ou continuar |
| F8 | Parar imediatamente, inclusive dentro de delays, loops e buscas de imagem sem limite |
| F9 | Iniciar ou finalizar gravação |
| Shift+F11 | Capturar imagem e criar Smart Click |

## Comandos

- **Mouse:** Mover mouse, Clique esquerdo, Clique direito, Clique duplo, Clique do meio, Pressionar botão, Soltar botão, Arrastar e soltar, Rolar (vertical e horizontal).
- **Teclado:** Pressionar tecla, Manter tecla pressionada, Soltar tecla, Digitar texto (com acentos e `{variáveis}`), Combinação de teclas, Segurar tecla por um tempo.
- **Imagem e tela:** Smart Click, Procurar imagem, Aguardar imagem aparecer, Clicar em imagem, Aguardar imagem desaparecer, Verificar cor de pixel, Procurar cor, Capturar screenshot.
- **Controle de fluxo:** Delay (fixo ou aleatório), If, Else If, Else, End If, Loop (0 = infinito), While, Break, Continue, Go To (rótulo ou número da etapa), Label, Encerrar execução, Comentário.
- **Variáveis e funções:** Definir variável (=, +=, −=, ×=, ÷=), Função, Chamar função, Retornar, Executar outra macro.
- **Sistema:** Abrir programa, Abrir arquivo, Abrir pasta, Abrir URL, Aguardar janela, Ativar janela, Minimizar/maximizar janela, Exibir notificação, Alerta sonoro.

### Smart Click e busca de imagem

- **Similaridade:** de 1% a 100%. Usa OpenCV Template Matching (`TM_CCOEFF_NORMED`) e fica sempre com o resultado de maior confiança.
- **Tolerar mudança de tamanho:** procura de 75% a 150% do tamanho original. Serve para quando a escala do Windows ou o zoom mudou depois do recorte.
- **Diferenciar cores:** desligado, compara em tons de cinza, que é mais rápido. Ligue quando só a cor muda, por exemplo um botão verde ou cinza.
- **Onde procurar:** tela inteira (todos os monitores), monitor específico, região personalizada (selecionada na tela), janela específica (pelo título) ou área por coordenadas.
- **Quando encontrar:** mover o mouse, clique esquerdo, direito ou duplo, clique com deslocamento X/Y, apenas validar, executar o bloco até o End If, ir para uma etapa, ou guardar as coordenadas em `<prefixo>_x` e `<prefixo>_y`.
- **Quando não encontrar:** continuar, tentar novamente (N vezes, depois para), parar, pausar, ir para uma etapa ou executar o bloco Else.
- **Tempo:** tempo limite, procura sem limite e intervalo entre tentativas. Esses tempos não mudam com a velocidade, porque são espera pela tela.

### Variáveis e expressões

Campos de posição, repetições e valores aceitam expressões: `found_x + 10`, `contador < 5 e achou`, `"Volta " + i`, `random(1, 6)`, `len(nome)`, `upper(texto)`. Em textos, use `{nome}`. O avaliador é próprio e seguro: não executa código Python.

Variáveis prontas:
- `repeticao`: número da repetição atual;
- `found_x`, `found_y` e `similaridade`: resultado da última busca;
- `cor_pixel`: cor lida por *Verificar cor de pixel*;
- `ultima_captura`: caminho do último screenshot salvo.

Os valores iniciais ficam em *Ferramentas > Variáveis iniciais*. Durante a execução, a aba *Variáveis* do painel inferior mostra os valores atuais.

### Log e depuração

O *Log de execução* registra:
- horário, repetição, etapa e comando;
- mensagem;
- similaridade e coordenadas encontradas;
- tempo de cada etapa.

Dá para filtrar só avisos e erros e exportar em CSV. Clicar numa linha seleciona a etapa. Se houver erro, a etapa fica marcada e a macro para com a causa escrita por extenso. Blocos sem fim, Else sem If, rótulos ou funções inexistentes e Break fora de loop aparecem em vermelho antes de executar.

## Arquivos `.shiftmacro`

São um ZIP com:
- `macro.json`: nome, descrição, etapas, variáveis, configurações de execução e atalhos;
- `images/*.png`: as imagens dos Smart Clicks.

A gravação é atômica: um arquivo temporário substitui o original, que nunca fica corrompido no meio. Outros recursos:
- **Salvamento automático:** a cada 60 s, configurável. Se o app fechar sem salvar, a próxima abertura oferece recuperar.
- **Arquivos recentes:** em *Arquivo > Abrir recente*.
- **Onde ficam os dados do app:** configurações e recuperação ficam em `%APPDATA%\ShiftMacro`.

## Linha de comando

```powershell
ShiftMacro.exe minha.shiftmacro                    # abre o arquivo
python main.py --run minha.shiftmacro              # executa sem janela (F7/F8 continuam valendo); código 0 = concluída
```

## Exemplos

Ficam na pasta `examples/` (no pacote, em `Exemplos/`):

| Arquivo | O que mostra |
|---|---|
| `01-bloco-de-notas` | Abrir programa, aguardar janela, digitar com acentos, loop e combinação de teclas |
| `02-variaveis-e-condicoes` | Loop, While, If/Else If/Else, Continue, Break, Go To, funções e variáveis, sem mexer no mouse |
| `03-smart-click` | Abre `smartclick-teste.html`, aguarda o alvo, clica 5 vezes enquanto ele muda de lugar e guarda as coordenadas |
| `04-executar-outra-macro` | Chama o exemplo 02 duas vezes |

Para gerar de novo: `python tools\make_examples.py`.

## Estrutura do projeto

```
main.py                 inicialização (interface ou --run)
shiftmacro/
  core/                 motor de execução: modelo, estrutura de blocos, expressões, contexto
  actions/              registro de comandos, catálogo, condições e backend de mouse e teclado
  vision/               captura (MSS), template matching e cor (OpenCV/NumPy), regiões de busca
  recorder/             gravação (pynput) e conversão de eventos em etapas
  storage/              arquivos .shiftmacro, configurações, recentes e salvamento automático
  ui/                   janela, tabela, formulários, Smart Click, sobreposições de tela, tema e ícones
  utils/                Windows: DPI, janelas e atalhos globais (RegisterHotKey)
assets/                 ícone e informações de versão do .exe
tests/                  testes automatizados
tools/                  geração de exemplos e ícone
scripts/                instalar dependências e compilar
installer/              instalador (PowerShell e Inno Setup)
```

Os módulos ficam dentro do pacote `shiftmacro/` para não colidir com pacotes de mesmo nome (`core`, `utils`…) no Python e no executável.

**Motor independente da interface:** `core/engine.py` não importa Qt e roda numa thread própria. Toda espera passa por `RunContext.sleep`, que verifica parada e pausa a cada 10 ms, e é isso que garante a parada imediata. Ao parar, o motor solta qualquer tecla ou botão que tenha ficado pressionado.

**Comando novo:** é um `CommandSpec` registrado em `actions/commands.py`, com campos (o formulário é gerado sozinho), descrição e função `run(ctx, cmd)`.

## Testes

```powershell
.venv\Scripts\python.exe -m pytest                                  # 70 testes, sem mexer no mouse
$env:SHIFTMACRO_REAL_INPUT="1"; .venv\Scripts\python.exe -m pytest tests\test_real_input.py
```

A suíte padrão usa uma tela em memória e uma entrada falsa. Ela cobre:
- **fluxo:** If/Else If/Else aninhados, loops com Break e Continue, While, Go To, funções, etapas desativadas, repetições por contagem e por tempo, velocidade, a partir da etapa e só as selecionadas;
- **parada de emergência:** em delay, loop infinito, While, tecla segurada e busca de imagem sem limite, sempre em menos de 0,3 s;
- **visão:** exata, com limiar, em várias escalas (125%), por monitor, região e janela, cor e pixel;
- **gravação:** clique, clique duplo, arraste, texto, combinações e tecla segurada;
- **arquivos:** formato `.shiftmacro`, incluindo caminhos maliciosos no ZIP, configurações e recuperação;
- **expressões:** inclusive bloqueio de código perigoso;
- **interface:** desfazer/refazer, arrastar, envolver em bloco, copiar e colar com imagens, painel de propriedades e salvar;
- **atualizador:** comparação de versões, escolha do pacote, recusa de download adulterado (SHA-256) e troca real dos arquivos por PowerShell.

`test_real_input.py` mexe no mouse por alguns segundos. Ele abre uma janela de teste e verifica, no sistema real:
- o Smart Click clicando na imagem;
- o texto com acentos chegando ao campo;
- um F8 de verdade parando um loop infinito;
- a gravação pelo pynput.

## Compilar o executável

```powershell
powershell -ExecutionPolicy Bypass -File scripts\compilar.ps1
```

O script roda os testes, gera ícone e exemplos e compila com PyInstaller (`ShiftMacro.spec`). O resultado fica em `dist\ShiftMacro\ShiftMacro.exe` e `dist\ShiftMacro-1.0.0-win64.zip`. Com o Inno Setup 6 instalado, também sai o `setup.exe`.

## Publicar uma versão

1. Suba `__version__` em `shiftmacro/__init__.py` e a versão em `assets/version.txt`.
2. Rode `scripts\compilar.ps1`.
3. Crie a release com a tag `vX.Y.Z` e anexe `ShiftMacro-X.Y.Z-win64.zip` e `ShiftMacro-X.Y.Z-win64.zip.sha256`.

O atualizador procura exatamente esses nomes.

## Apoie

O Shift Macro é gratuito. Se ele te poupa tempo, considere [apoiar no Ko-fi](https://ko-fi.com/ericklucena). O botão *Apoiar* fica na barra de ferramentas e em *Ajuda*.

## Limitações conhecidas

- **Programas como administrador:** o Windows não deixa um programa comum enviar cliques ou teclas para janelas abertas como administrador. Abra o Shift Macro como administrador nesses casos.
- **Jogos e tela bloqueada:** jogos com antitrapaça ou que leem o hardware diretamente podem ignorar entrada simulada. A tela de bloqueio e a de UAC também não aceitam.
- **Janela minimizada:** a busca de imagem só enxerga o que está na tela. Uma janela minimizada não pode ser pesquisada, e o app avisa.
- **Repetir por tempo:** o tempo é conferido entre uma repetição e outra. A repetição em andamento termina antes de parar.
- **Recorte de imagem:** a seleção fica dentro de um monitor por vez.
