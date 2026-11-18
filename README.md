# Compactador de Arquivos — Huffman e LZ77

Sistema desktop em Python para compactar e descompactar arquivos de texto com o
algoritmo de Huffman e com a combinação LZ77 + Huffman. A interface foi feita
com CustomTkinter e permite arrastar e soltar arquivos, comparar estratégias,
visualizar a árvore de Huffman e conferir a integridade do conteúdo recuperado.

Os algoritmos foram implementados manualmente, usando apenas a biblioteca padrão
do Python (`heapq`, `collections.Counter`, `struct`, `hashlib`, etc.). Nenhuma
biblioteca de compressão (`zlib`, `gzip`, `bz2`, `lzma`, `zipfile`) ou de grafos
(`networkx`) é utilizada.

---

## 1. Requisitos

- Python 3.10 ou superior
- CustomTkinter
- tkinterdnd2 (arrastar e soltar; opcional em tempo de execução)

Instalação:

```bash
python -m pip install -r requirements.txt
```

Execução:

```bash
python main.py
```

Testes automatizados:

```bash
python -m unittest discover -s tests -v
```

---

## 2. Estrutura do projeto

```text
TrabalhoHuffman/
├── main.py               # ponto de entrada
├── huffman.py            # nós, árvore, códigos, codificação/decodificação
├── lz77.py               # janela deslizante, tokens, serialização, reversão
├── compressor.py         # integração dos algoritmos e geração do .huff
├── decompressor.py       # leitura do .huff, reconstrução e verificação
├── file_format.py        # formato binário, cabeçalho e validações
├── tree_view.py          # janela da árvore de Huffman (Canvas)
├── interface.py          # interface gráfica principal
├── requirements.txt
├── README.md
├── exemplos/
│   ├── exemplo_simples.txt
│   ├── exemplo_repetitivo.txt
│   └── exemplo_grande.txt
└── tests/
    └── test_algorithms.py
```

---

## 3. Como usar a interface

1. Selecione ou arraste um arquivo `.txt` para a área indicada.
2. Escolha uma das estratégias:
   - **Huffman** — usa apenas Huffman;
   - **LZ77 + Huffman** — aplica LZ77 e depois Huffman;
   - **Automático** — testa as duas e grava a menor saída completa.
3. Clique em **COMPACTAR ARQUIVO**. O resultado é salvo como
   `nome_original.huff` na mesma pasta do arquivo de entrada. A extensão `.txt`
   é substituída, não acumulada: `arquivo.txt` gera `arquivo.huff`.
4. Para descompactar, selecione ou arraste um `.huff` e clique em
   **DESCOMPACTAR ARQUIVO**. A janela de salvamento já sugere
   `nome_original_descompactado.txt`.
5. Use os botões inferiores para abrir a pasta do resultado, visualizar a
   árvore de Huffman e ver as informações detalhadas dos algoritmos.

O arquivo original nunca é modificado ou removido. Se o `.huff` de saída já
existir, o programa pede confirmação antes de sobrescrever.

---

## 4. Algoritmo de Huffman

### 4.1 Frequências

O arquivo é lido como bytes (`bytes`), não como texto. Isso preserva
exatamente o conteúdo original, incluindo acentos, quebras de linha e
tabulações. A contagem usa `collections.Counter`.

Exemplo com `ABRACADABRA`:

```text
A: 5
B: 2
R: 2
C: 1
D: 1
```

### 4.2 Nós e árvore

Cada símbolo distinto vira uma folha com seu peso. Uma fila de prioridade
(`heapq`) mantém os nós ordenados por frequência. Repetidamente:

1. removem-se os dois nós de menor peso;
2. cria-se um nó interno com a soma dos pesos;
3. o primeiro nó vira filho esquerdo e o segundo vira filho direito;
4. o nó interno volta para a fila.

O último nó é a raiz. O desempate é determinístico:

- folhas são criadas em ordem crescente do valor do byte;
- nós com a mesma frequência são retirados na ordem em que foram criados.

Assim, a árvore pode ser reconstruída apenas com as frequências armazenadas no
arquivo `.huff`.

### 4.3 Códigos

O percurso da raiz até cada folha define o código:

- aresta esquerda = `0`;
- aresta direita = `1`.

Como todos os símbolos ficam em folhas, nenhum código é prefixo de outro. Isso
garante decodificação inequívoca.

### 4.4 Empacotamento

Os códigos são concatenados em uma sequência de bits e convertidos para bytes
reais. O último byte pode ter bits de preenchimento; por isso o cabeçalho guarda
a quantidade exata de bits codificados. Nenhuma representação textual de zeros e
uns é gravada.

### 4.5 Casos especiais

- Arquivo vazio: não há árvore, `bits_len = 0` e nenhum byte de dados.
- Um único símbolo distinto: a raiz é uma folha e o código atribuído é `0`.
- Símbolos com a mesma frequência: o desempate determinístico mantém a
  reconstrução estável.

---

## 5. Algoritmo LZ77

O LZ77 percorre os dados mantendo uma janela deslizante sobre o que já foi
processado. Para cada posição, procura a maior sequência que coincida com um
trecho anterior. Se a coincidência tiver comprimento suficiente, emite uma
referência `(distância, comprimento)`; caso contrário, emite o byte literal.

Parâmetros padrão (configuráveis em `compressor.LZ77Parameters`):

| Parâmetro | Valor padrão | Significado |
|---|---:|---|
| `window` | 32768 bytes | tamanho máximo da janela de busca |
| `min_match` | 3 | comprimento mínimo para virar referência |
| `max_match` | 258 | comprimento máximo de uma correspondência |
| `max_chain` | 64 | limite de candidatos examinados por posição |

A busca usa correntes de hash sobre trigramas para evitar varrer a janela
inteira em cada posição. Referências sobrepostas são permitidas: na
descompactação os bytes são copiados um a um, então uma referência pode apontar
para bytes que estão sendo produzidos naquele momento.

Exemplo conceitual:

```text
Entrada:  ABCABCABCABC
Tokens:   A  B  C  (3, 9)
```

### 5.1 Representação intermediária

Para o modo híbrido, os tokens são serializados em bytes antes de passar pelo
Huffman. Os tokens são agrupados de 8 em 8:

- 1 byte de controle, onde o bit `i` indica se o token `i` é referência;
- para cada literal: 1 byte com o símbolo;
- para cada referência: `varint(distância)` seguido de `varint(comprimento)`.

Essa representação é compacta, reversível e preserva a distribuição dos bytes
literais, o que melhora o desempenho do Huffman na etapa seguinte.

---

## 6. Combinação LZ77 + Huffman

Compactação:

```text
Arquivo original
      |
      v
   LZ77  ->  tokens
      |
      v
Serialização intermediária (bytes)
      |
      v
   Huffman  ->  árvore + códigos
      |
      v
Empacotamento dos bits
      |
      v
Arquivo .huff
```

Descompactação:

```text
Arquivo .huff
      |
      v
Decodificação Huffman  ->  bytes intermediários
      |
      v
Interpretação dos tokens LZ77
      |
      v
Descompactação LZ77
      |
      v
Arquivo original
```

O cabeçalho indica a estratégia usada. No modo híbrido, a árvore mostrada na
interface é exatamente a árvore construída sobre os bytes da representação
intermediária, e não uma árvore ilustrativa.

### 6.1 Estratégia automática

O modo automático:

1. gera o arquivo completo com Huffman puro;
2. gera o arquivo completo com LZ77 + Huffman;
3. compara os tamanhos reais dos dois arquivos, incluindo cabeçalho, metadados,
   tabela de frequências e preenchimento do último byte;
4. grava apenas a menor saída;
5. informa na interface qual estratégia venceu e os tamanhos de cada uma.

A combinação não é sempre melhor. Ela tende a vencer em dados com muitas
sequências repetidas; em textos variados e pequenos, o custo dos metadados pode
fazer o Huffman puro ganhar.

---

## 7. Formato binário `.huff`

Todos os inteiros são little-endian.

| Campo | Tipo / tamanho |
|---|---|
| Assinatura | 4 bytes: `HUFF` |
| Versão | uint8 (atualmente 1) |
| Estratégia | uint8: `0` = Huffman, `1` = LZ77 + Huffman |
| Reservado | uint16 |
| Janela LZ77 | uint32 |
| Comprimento máximo LZ77 | uint32 |
| Comprimento mínimo LZ77 | uint16 |
| Tamanho original | uint64 (bytes do `.txt`) |
| Tamanho intermediário | uint64 (bytes após LZ77; `0` no modo Huffman) |
| Bits codificados | uint64 (bits reais, sem preenchimento) |
| Número de símbolos | uint32 |
| Tamanho do nome original | uint16 |
| Nome original | `name_len` bytes em UTF-8 |
| Hash SHA-256 | 32 bytes |
| Tabela de frequências | `symbol_count` × (uint8 símbolo + varint frequência) |
| Dados empacotados | `ceil(bits_len / 8)` bytes |

O varint é LEB128: cada byte usa 7 bits de dados e o bit mais significativo
indica continuação. Ele reduz o cabeçalho quando há muitos símbolos distintos,
situação comum no modo híbrido.

A árvore não é gravada. Ela é reconstruída a partir das frequências com o mesmo
critério determinístico usado na compactação.

### 7.1 Validações feitas na leitura

- assinatura `HUFF` e versão suportada;
- estratégia conhecida;
- nome original em UTF-8;
- tabela de frequências completa e sem símbolos duplicados;
- soma das frequências compatível com o tamanho original (Huffman) ou com o
  tamanho intermediário (híbrido);
- quantidade de bytes empacotados compatível com `bits_len`;
- referências LZ77 dentro dos limites dos dados já produzidos;
- tamanho final e SHA-256 do conteúdo recuperado.

Se qualquer verificação falhar, a descompactação é recusada e o programa exibe
uma mensagem de erro em vez de informar sucesso.

---

## 8. Fórmulas apresentadas na interface

```text
Espaço economizado = tamanho original - tamanho compactado
Percentual de redução = ((original - compactado) / original) * 100
Taxa de compactação = tamanho original / tamanho compactado
```

Arquivos vazios não provocam divisão por zero: a interface mostra `n/d`. Quando
o `.huff` fica maior que o original, o programa avisa explicitamente que houve
aumento de tamanho.

---

## 9. Visualização da árvore

A janela da árvore usa somente o `Canvas` do Tkinter:

- folhas verdes mostram o símbolo e a frequência;
- nós internos azuis mostram a soma dos pesos;
- a raiz é destacada em laranja;
- arestas esquerdas são rotuladas com `0` e direitas com `1`;
- há rolagem horizontal e vertical e a visualização abre centralizada na raiz;
- `Ctrl + scroll` aumenta ou diminui o zoom mantendo o ponto sob o cursor;
- o rodapé mostra o nível de zoom atual.

Os bytes são apresentados de forma legível:

| Byte | Rótulo |
|---|---|
| espaço | `ESPAÇO` |
| `\n` | `\n` |
| `\t` | `\t` |
| `\r` | `\r` |
| imprimível (33–126) | o próprio caractere |
| demais | hexadecimal, por exemplo `0xFF` |

No modo híbrido, a janela informa que as frequências foram calculadas sobre os
bytes da representação intermediária produzida pelo LZ77.

---

## 10. Relação com a disciplina de Grafos

### 10.1 Huffman

- Um grafo é formado por vértices e arestas.
- Uma árvore é um grafo conexo e acíclico.
- A árvore de Huffman é binária: cada nó interno tem no máximo dois filhos.
- As folhas representam símbolos; os nós internos representam a soma dos pesos.
- A fila de prioridade escolhe sempre os dois menores pesos: estratégia gulosa.
- Os caminhos da raiz às folhas definem códigos binários livres de prefixo.

### 10.2 LZ77

- A janela deslizante é uma região do fluxo já processado.
- A busca por sequências anteriores produz referências `(distância, comprimento)`.
- Literais e referências alternam-se na saída.
- O processo inverso reconstrói os dados copiando bytes já produzidos.

### 10.3 Combinação

- LZ77 reduz a redundância de sequências repetidas.
- Huffman reduz o número de bits dos símbolos mais frequentes.
- Juntas, as técnicas exploram dois tipos diferentes de redundância.
- O resultado depende do conteúdo: por isso existe o modo automático, que mede
  os arquivos completos em vez de supor que a combinação sempre vence.

---

## 11. Situações especiais tratadas

- arquivo vazio;
- arquivo com um único símbolo;
- arquivo com muitos caracteres repetidos;
- caracteres acentuados e UTF-8;
- textos em Windows-1252/Latin-1 (detecção automática com aviso do encoding);
- espaços, quebras de linha e tabulações;
- arquivos muito pequenos e arquivos grandes;
- extensão inválida ou conteúdo que não é texto reconhecível;
- falha ao ler ou salvar;
- confirmação antes de sobrescrever;
- árvore com muitos nós;
- `.huff` corrompido, truncado ou com assinatura/versão inválidas;
- metadados inconsistentes;
- referências LZ77 inválidas;
- sequência de bits incompleta;
- falha de SHA-256;
- arquivo compactado maior que o original;
- estratégia diferente da esperada.

---

## 12. Testes

Os testes usam `unittest` e cobrem:

- contagem de frequências;
- construção determinística da árvore;
- existência de código para todos os símbolos;
- propriedade de código livre de prefixo;
- ida e volta de codificação/decodificação Huffman;
- arquivo vazio e arquivo com um único símbolo;
- ida e volta do LZ77, incluindo referências sobrepostas;
- serialização e interpretação dos tokens;
- varints;
- validação do formato `.huff`;
- assinatura, truncamento e payload inconsistente;
- compactação e descompactação nas três estratégias;
- escolha do menor arquivo no modo automático;
- verificação de SHA-256;
- detecção de arquivo corrompido;
- geração de nome de saída sem sobrescrita.

Execução:

```bash
python -m unittest discover -s tests -v
```

---

## 13. Observações para a apresentação

- A árvore exibida é a árvore realmente usada na compactação (ou reconstruída
  do `.huff` na descompactação).
- O arquivo `.huff` é autossuficiente: não é necessário manter o `.txt`
  original para descompactar.
- O modo automático compara o tamanho completo dos arquivos, não apenas a
  quantidade de bits da codificação.
- A interface mostra as estatísticas do LZ77 (tokens, literais, referências) e
  a tabela de frequências/códigos do Huffman para facilitar a explicação.
- O hash SHA-256 garante que o conteúdo recuperado é idêntico ao original.
