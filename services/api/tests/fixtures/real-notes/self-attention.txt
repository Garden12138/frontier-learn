## 实现自注意力

### 长序列建模的问题

* 在研究长序列建模问题之前，我们要从刚开始的模型架构说起，以语言翻译的翻译模型为例：

  ![](https://raw.githubusercontent.com/Garden12138/picbed-cloud/main/ai/ballm16.png)

  翻译时，不可能逐词翻译，实际上翻译过程中是需要上下文的理解和语法的对齐。为了解决这一局限性，模型包含了两个子模块的深度神经网络，即所谓的编码器（```encoder```）和解码器（```decoder```）。编码器的任务是先读取并处理整个文本，然后解码器生成翻译后的文本，即```RNN```模型：

  ![](https://raw.githubusercontent.com/Garden12138/picbed-cloud/main/ai/ballm17.png)

  编码器部分将整个输入文本处理为一个隐藏状态（记忆单元）。解码器随后使用最终隐藏状态生成输出。这个架构有个重大问题和限制在于在解码阶段 ```RNN``` 无法直接访问编码器的早期隐藏状态。因此，它只能依赖当前隐藏状态来封装所有相关信息。这种设计可能导致上下文信息的丢失，特别是在依赖关系较长的复杂句子中，这一问题尤为突出。如有一个长句子：```“The cat, who was sitting on the windowsill, jumped down because it saw a bird flying outside the window.”```要理解```“it”```指的是```“the cat”```而不是```“the windowsill”```或其他内容。对于 ```RNN``` 来说，这个任务是有难度的，因为：

    * 长距离依赖问题：在 ```RNN``` 中，每个新输入的词会被依次传递到下一个时间步。随着句子长度增加，模型的隐状态会不断被更新，但早期信息（如```“the cat”```）会在层层传播中逐渐消失。因此，模型可能无法在```“it”```出现时有效地记住```“the cat”```是```“it”```的指代对象。
    * 梯度消失问题：```RNN``` 在反向传播（根据损失值计算梯度的过程）中的梯度会随着时间步的增加逐渐减小，这种“梯度消失”（```RNN``` 的链式结构导致反向传播要跨很多时间步传递梯度；如果每一步梯度都被缩小，传到前面时就几乎没了，这就是梯度消失）使得模型很难在长句中保持信息的准确传播，从而难以捕捉到长距离的语义关联。

  为了弥补 ```RNN``` 的这些不足，注意力机制被引入。它的关键思想是在处理每个词时，不仅依赖于最后的隐藏状态，而是允许模型直接关注序列中的所有词。这样，即使是较远的词也能在模型计算当前词的语义时直接参与。假设使用一个简单的注意力矩阵，模型在处理```“it”```时，给每个词的权重可能如下：

    ![](https://raw.githubusercontent.com/Garden12138/picbed-cloud/main/ai/ballm18.png)

  在这个注意力矩阵中，可以看到```“it”```对```“the cat”```有较高的关注权重（0.3），而对其他词的关注权重较低。这种直接的关注能力让模型能够高效捕捉长距离依赖关系，理解```“it”```与```“the cat”```的语义关联。
    
    ![](https://raw.githubusercontent.com/Garden12138/picbed-cloud/main/ai/ballm19.png)

### 通过注意力机制捕捉数据依赖关系

* ```RNN```模型在长序列中存在消息覆盖或丢失的建模问题，通过引入注意力机制对编码器-解码器架构的 ```RNN``` 进行了改进，使得解码器在每个解码步骤可以选择性地访问输入序列的不同部分：

  ![](https://raw.githubusercontent.com/Garden12138/picbed-cloud/main/ai/ballm20.png)

  后续研究发现构建用于自然语言处理的深度神经网络并不需要 ```RNN``` 结构，随后提出了基于自注意力机制的原始 ```Transformer``` 架构。自注意力机制是一种允许输入序列中的每个位置在计算序列表示时关注同一序列中所有位置的机制。自注意力机制是基```Transformer```架构的当代大语言模型（如```GPT```系列模型）的关键组成部分。

### 通过自注意力机制关注输入的不同部分

* 在自注意力机制中，```“self”```指的是该机制通过关联同一输入序列中的不同位置来计算注意力权重的能力。它评估并学习输入内部各部分之间的关系和依赖性。

* 不含可训练权重的简化自注意力机制。实现没有包含任何可训练的权重简化自注意力机制，目标是为输入序列每个元素计算一个上下文向量（代表该元素与其他元素的关联关系）：

  ![](https://raw.githubusercontent.com/Garden12138/picbed-cloud/main/ai/ballm21.png)

  以输入序列```Your journey starts with one step```为例：

  ```python
  import torch
  inputs = torch.tensor(
    [[0.43, 0.15, 0.89], # Your     (x^1)
     [0.55, 0.87, 0.66], # journey  (x^2)
     [0.57, 0.85, 0.64], # starts   (x^3)
     [0.22, 0.58, 0.33], # with     (x^4)
     [0.77, 0.25, 0.10], # one      (x^5)
     [0.05, 0.80, 0.55]] # step     (x^6)
  print('初始化输入嵌入层:')
  print(inputs.shape)
  ```

  首先，计算注意力得分ω，通过计算查询 ```x(2)``` 与每个其他输入 ```token``` 的点积（点积运算本质上是一种将两个向量按元素相乘后再求和的简单方式）：

  ![](https://raw.githubusercontent.com/Garden12138/picbed-cloud/main/ai/ballm22.png)

  ```python
  # 计算输入序列第二个元素的注意力得分
  query = inputs[1]
  attn_scores_2 = torch.empty(inputs.shape[0])
  for i, x_i in enumerate(inputs):
      attn_scores_2[i] = torch.dot(x_i, query)
  print(attn_scores_2) 
  ```

  接下来，对计算的每个注意力得分进行归一化（注意力权重之和为 1，有助于解释和保持LLM训练稳定性）：

  ![](https://raw.githubusercontent.com/Garden12138/picbed-cloud/main/ai/ballm23.png)

  ```python
  # 输入序列第二个元素的注意力得分归一，方式1：直接除法
  attn_weights_2_tmp = attn_scores_2 / attn_scores_2.sum()
  print("输入序列第二个元素的注意力得分归一，方式1：直接除法")
  print("Attention weights:", attn_weights_2_tmp)
  print("Sum:", attn_weights_2_tmp.sum())
  # 输入序列第二个元素的注意力得分归一，方式2：自定义softmax算法
  def softmax_naive(x):
      return torch.exp(x) / torch.exp(x).sum(dim=0)
  attn_weights_2_naive = softmax_naive(attn_scores_2)
  print("输入序列第二个元素的注意力得分归一，方式2：自定义softmax算法")
  print("Attention weights:", attn_weights_2_naive)
  print("Sum:", attn_weights_2_naive.sum())
  # 输入序列第二个元素的注意力得分归一，方式2：torch.softmax函数
  attn_weights_2 = torch.softmax(attn_scores_2, dim=0)
  print("输入序列第二个元素的注意力得分归一，方式2：torch.softmax函数")
  print("Attention weights:", attn_weights_2)
  print("Sum:", attn_weights_2.sum())
  ```

  使用```softmax```好处：
    * 归一化输出为概率：```Softmax``` 将输出转换为 0 到 1 之间的概率，且所有类别的概率之和为 1，方便解释结果。例如，在分类任务中，输出可以直接表示模型对各类别的信心。
    * 平滑和放大效果：```Softmax``` 不仅能归一化，还具有平滑和放大效果。较大的输入值会被放大，较小的输入值会被抑制，从而增强模型对最优类别的区分。
    * 支持多分类问题：与 ```sigmoid``` 不同，```Softmax``` 适用于多类别分类问题。它可以输出每个类别的概率，使得模型可以处理多分类任务。

  最后，通过加权和（将每个输入向量与对应的归一后的注意力得分相乘后相加）计算输入元素的上下文向量：

  ![](https://raw.githubusercontent.com/Garden12138/picbed-cloud/main/ai/ballm24.png)

  ```python
  # 使用加权和计算输入序列第二个元素的的上下文向量
  context_vec_2 = torch.zeros(query.shape)
  for i,x_i in enumerate(inputs):
      context_vec_2 += attn_weights_2[i]*x_i
  print("输入序列第二个元素的的上下文向量")
  print(context_vec_2)
  ```

* 为所有输入的 ```token``` 计算注意力权重。在上一步我们实现了计算输入序列第二个元素的上下文向量，在这基础上，我们可实现所有输入对的上下问向量计算，流程和上一步一致：

  ![](https://raw.githubusercontent.com/Garden12138/picbed-cloud/main/ai/ballm25.png)

  首先，初始化定义所有输入对的注意力的得分张量：

  ```python
  attn_scores = torch.empty(inputs.shape[0], inputs.shape[0])
  ```

  接下来，计算所有输入对的点积：

  ```python
  # 使用嵌套for循环计算点积
  for i, x_i in enumerate(inputs):
      for j, x_j in enumerate(inputs):
          attn_scores[i, j] = torch.dot(x_i, x_j)
  print("使用嵌套for循环计算点积:")
  print(attn_scores)
  # 使用矩阵乘法计算点积
  attn_scores = inputs @ inputs.T
  print("使用矩阵乘法计算点积:")
  print(attn_scores)
  ```

  继续计算所有输入对的注意力权重

  ```python
  # 计算所有输入对的注意力权重（归一）
  attn_weights = torch.softmax(attn_scores, dim=-1)
  print("计算所有输入对的注意力权重（归一）:")
  print(attn_weights)
  ```

  最后计算所有输入对的上下文向量：

  ```python
  # 计算所有输入对的上下文向量，使用矩阵乘法
  all_context_vecs = attn_weights @ inputs
  print("计算所有输入对的上下文向量，使用矩阵乘法：:")
  print(all_context_vecs)
  ```

  符号```@```表示矩阵乘法运算；```.T```表示矩阵转置运算；```dim=-1```表示沿着最后一维进行运算，当前张量是二维，-1表示列，即沿着列方向（水平方向归一）。

### 实现带有可训练权重的自注意力机制

* 与简化自注意力机制相比，不是直接使用嵌入向量来计算上下文向量，而是使用可训练的权重参数矩阵来计算上下文向量。

  ![](https://raw.githubusercontent.com/Garden12138/picbed-cloud/main/ai/ballm30.png)

* 逐步计算注意力权重

  * 计算查询向量 ```q``` 、键向量 ```k``` 以及值向量 ```v``` ：

    ![](https://raw.githubusercontent.com/Garden12138/picbed-cloud/main/ai/ballm26.png)

    以输入序列第二个元素为例子：

    ```python
    # 初始化权重参数矩阵
    d_in = inputs.shape[1]                                          
    d_out = 2   
    torch.manual_seed(123)
    W_query = torch.nn.Parameter(torch.rand(d_in, d_out), requires_grad=False)
    W_key   = torch.nn.Parameter(torch.rand(d_in, d_out), requires_grad=False)
    W_value = torch.nn.Parameter(torch.rand(d_in, d_out), requires_grad=False)
    print("初始化权重参数矩阵:")
    print(W_query)
    print(W_key)
    print(W_value)
    # 计算输入序列第二个元素的query、key 和 value 向量
    x_2 = inputs[1]
    query_2 = x_2 @ W_query
    key_2 = x_2 @ W_key
    value_2 = x_2 @ W_value
    print("计算输入序列第二个元素的query、key 和 value 向量:")
    print(query_2)
    print(key_2)
    print(value_2)
    ```

    ```d_out``` 表示输出维度，一般由实际训练时定义，它可将输入维度转化为指定输出维度；这里将```requires_grad```设置为```False```，以便在输出结果中减少不必要的信息，从而使演示更加清晰。但如果要将这些权重矩阵用于模型训练，则需要将```requires_grad```设置为```True```，以便在模型训练过程中更新这些矩阵。

  * 计算注意力得分：
    
    ![](https://raw.githubusercontent.com/Garden12138/picbed-cloud/main/ai/ballm27.png)

    以输入序列第二个元素对所有输入元素的注意力得分为例：

    ```python
    # 计算输入序列所有元素的query、key 向量
    querys = inputs @ W_query
    keys = inputs @ W_key
    # 计算输入序列第二个元素对所有输入元素的注意力得分
    print("计算输入序列第二个元素对所有输入元素的注意力得分：")
    attn_scores_2 = querys[1] @ keys.T
    print(attn_scores_2)
    ```

  * 计算注意力权重：

    ![](https://raw.githubusercontent.com/Garden12138/picbed-cloud/main/ai/ballm28.png)

    以输入序列第二个元素对所有输入元素的注意力权重为例：

    ```python
    # 计算输入序列第二个元素对所有输入元素的注意力权重（得分归一）
    print("计算输入序列第二个元素对所有输入元素的注意力权重（得分归一）：")
    d_k = keys.shape[-1]
    attn_weights_2 = torch.softmax(attn_scores_2 / d_k**0.5, dim=-1) # 先进行点积缩放，防止点积结果过大导致梯度丢失
    print(attn_weights_2)
    ```

    使用```sqrt(d_k)```是因为点积结果的大小，通常会随着维度```d_k```增大而变大；更准确地说，它的标准差大约会按```sqrt(d_k)```增大。所以用```sqrt(d_k)```缩放，是为了把点积结果拉回到一个比较稳定的范围。

  * 计算上下文向量：

    ```python
    # 计算输入序列所有元素的向量
    values = inputs @ W_value
    # 计算输入序列第二个元素对所有输入元素的上下文向量
    print("计算输入序列第二个元素对所有输入元素的上下文向量：")
    context_vec_2 = attn_weights_2 @ values
    print(context_vec_2)
    ```

* 实现一个简洁的自注意力机制 Python 类

  * 在上面分步骤展示从嵌入向量到上下文向量每个环节的细节后，我们需要进行整合封装，实现一个简洁的自注意力机制 Python 类。

  * 实现一个简洁的自注意力机制V1类：

    ```python
    class SelfAttention_v1(nn.Module):
        def __init__(self, d_in, d_out):
            super().__init__()
            self.d_out = d_out
            # 手动初始化权重参数矩阵：W_query、W_key、W_value
            self.W_query = nn.Parameter(torch.rand(d_in, d_out))
            self.W_key   = nn.Parameter(torch.rand(d_in, d_out))
            self.W_value = nn.Parameter(torch.rand(d_in, d_out))

        def forward(self, x):
            # 计算权重向量：queries、keys、values
            keys = x @ self.W_key
            queries = x @ self.W_query
            values = x @ self.W_value
            # 计算注意力得分
            attn_scores = queries @ keys.T
            # 计算注意力权重
            attn_weights = torch.softmax(attn_scores / keys.shape[-1]**0.5, dim=-1)
            # 计算上下文向量
            context_vec = attn_weights @ values
            return context_vec
    print("实现一个简洁的自注意力机制V1类：")
    torch.manual_seed(123)
    sa_v1 = SelfAttention_v1(d_in, d_out)
    print(sa_v1(inputs))
    ```

  * 实现一个简洁的自注意力机制V2类：

    ```python
    class SelfAttention_v2(nn.Module):
        def __init__(self, d_in, d_out, qkv_bias=False):
            super().__init__()
            self.d_out = d_out
            # 自动初始化权重参数矩阵：W_query、W_key、W_value
            self.W_query = nn.Linear(d_in, d_out, bias=qkv_bias)
            self.W_key   = nn.Linear(d_in, d_out, bias=qkv_bias)
            self.W_value = nn.Linear(d_in, d_out, bias=qkv_bias)

        def forward(self, x):
            # 计算权重向量：queries、keys、values
            keys = self.W_key(x)
            queries = self.W_query(x)
            values = self.W_value(x)
            # 计算注意力得分
            attn_scores = queries @ keys.T
            # 计算注意力权重
            attn_weights = torch.softmax(
                attn_scores / keys.shape[-1]**0.5, dim=-1)
            # 计算上下文向量
            context_vec = attn_weights @ values
            return context_vec
    print("实现一个简洁的自注意力机制V2类：")
    torch.manual_seed(789)
    sa_v2 = SelfAttention_v2(d_in, d_out)
    print(sa_v2(inputs))
    ```

    ```v2```与```v1```的区别在于当禁用偏置单元时，```nn.Linear``` 层可以有效地执行矩阵乘法。此外，使用 ```nn.Linear``` 替代手动实现的 ```nn.Parameter(torch.rand(...))``` 的一个显著优势在于，```nn.Linear``` 具有优化的权重初始化方案，从而有助于实现更稳定和更高效的模型训练。

### 使用因果注意力机制来屏蔽后续词

* 因果注意力（也称为掩蔽注意力）是一种特殊的自注意力形式。它限制模型在处理任何给定的 ```token``` 时，只考虑当前以及之前 ```token```，而不能看到后续内容，因此需要对每个处理的 ```token``` 屏蔽其后续 ```token```。

* 对注意力权重的对角线上方部分进行了掩码操作，并对未掩码的注意力权重进行归一化，使得每一行的注意力权重之和为 1：

  ![](https://raw.githubusercontent.com/Garden12138/picbed-cloud/main/ai/ballm31.png)

  ```python
  # 实现因果注意力掩码V1
  print("实现因果注意力掩码V1：")
  queries = sa_v2.W_query(inputs)
  print("当前q向量：")
  print(queries)
  keys = sa_v2.W_key(inputs)
  print("当前k向量：")
  print(keys)
  attn_scores = queries @ keys.T
  print("当前注意力得分：")
  print(attn_scores)
  attn_weights = torch.softmax(attn_scores / keys.shape[-1]**0.5, dim=-1)
  print("当前注意力权重：")
  print(attn_weights)
  # 生成对角线以下为1的掩码矩阵
  print("生成对角线以下为1的掩码矩阵：")
  context_length = attn_scores.shape[0]
  mask_simple = torch.tril(torch.ones(context_length, context_length))
  print(mask_simple)
  # 将当前注意力权重对角线以上的值置零
  print("将当前注意力权重对角线以上的值置零：")
  masked_simple = attn_weights*mask_simple
  print(masked_simple)
  # 重新归一计算注意力权重
  print("重新归一计算注意力权重：")
  row_sums = masked_simple.sum(dim=-1, keepdim=True)
  masked_simple_norm = masked_simple / row_sums
  print(masked_simple_norm)
  ```

  ```torch.ones```表示生成一个全为 1 的张量；```torch.tril```表示生成一个下三角矩阵，其中下三角矩阵的对角线以下的元素为 1（包含对角线），其余元素为 0。

  还可以利用 ```softmax``` 函数的数学特性（当一行中存在负无穷值（```-∞```）时，```Softmax``` 函数会将这些值视为零概率。），更高效地计算掩码后的注意力权重，减少计算步骤：

  ![](https://raw.githubusercontent.com/Garden12138/picbed-cloud/main/ai/ballm32.png)

  ```python
  # 实现因果注意力掩码V2
  print("实现因果注意力掩码V2：")
  # 生成对角线以上为1（不包含对角线）的掩码矩阵
  print("生成对角线以上为1（不包含对角线）的掩码矩阵：")
  mask = torch.triu(torch.ones(context_length, context_length), diagonal=1)
  print(mask)
  attn_scores_masked = attn_scores.masked_fill(mask.bool(), -torch.inf) # 先将0-1掩码矩阵转换为false-true掩码矩阵，然后将注意力得分矩阵在遇到true的时候替换为-inf，false时保留原值
  print(attn_scores_masked)
  # 归一计算注意力权重
  print("归一计算注意力权重：")
  attn_weights_masked = torch.softmax(attn_scores_masked / keys.shape[-1]**0.5, dim=-1)
  print(attn_weights_masked)
  ```

  ```torch.triu```表示生成上三角矩阵，其中上三角矩阵的对角线以上元素为 1（```diagonal=1```，不包含对角线），其余元素为 0；```torch.bool```表示将掩码矩阵转换为布尔类型，布尔类型中0表示```false```，1表示```true```；```torch.masked_fill```表示将注意力得分矩阵在遇到```true```的时候替换为```-inf```，```false```时保留原值。

* 使用 ```dropout``` 遮掩额外的注意力权重防止过拟合，确保模型不会过于依赖任何特定的隐藏层单元组合，提高模型的泛化能力。需要注意的是，仅在训练过程中使用，训练结束后则会禁用：

  ![](https://raw.githubusercontent.com/Garden12138/picbed-cloud/main/ai/ballm33.png)

  ```python
  # 应用dropout掩码，减少在训练时过拟合
  print("应用dropout掩码，减少在训练时过拟合：")
  dropout = torch.nn.Dropout(0.5) # 每个元素都有 50% 的概率被置为 0
  print(dropout(attn_weights_masked))
  ```
  
  当对注意力权重矩阵应用 50% 的 ```dropout``` 时，矩阵中一半的元素会被随机设置为零。为了补偿有效元素的减少，矩阵中剩余元素的值会被放大 ```1/0.5 = 2``` 倍，公式如下：

  ![](https://raw.githubusercontent.com/Garden12138/picbed-cloud/main/ai/ballm34.png)

  缩放操作的作用：

    * 增大未遮盖值的相对差异：放大剩余权重后，它们的数值相对于被置零的权重增大，从而拉大了非零元素之间的相对差异。这使得在 ```Softmax``` 计算中（输入值的差异越大，输出分布就会越尖锐；而输入值差异越小，输出分布就会越平滑），剩下的值之间的对比更明显，从而影响 ```Softmax``` 输出的分布形态。
    * 增强模型的选择性关注：在训练中，模型会在每个步骤中随机选择不同的 ```token``` 进行更高的关注，这使模型在学习时不会依赖特定 ```token``` 的注意力。

### 从单头注意力扩展到多头注意力

* 多头注意力机制就是让模型从多个不同角度同时关注输入内容，从而更全面地理解上下文关系。“多头”一词指的是将注意力机制划分为多个“头”，每个头独立运作，在这种情况下，单个因果注意力模块可以视为单头注意力。

* 通过堆叠实现多头注意力机制，创建多个自注意力机制的实例，每个实例都具有独立的权重，然后将它们的输出合并：

  ![](https://raw.githubusercontent.com/Garden12138/picbed-cloud/main/ai/ballm35.png)
  
  ```python
  # 通过堆叠实现多头注意力机制
  print("通过堆叠实现多头注意力机制：")
  class MultiHeadAttentionWrapper(nn.Module):
      def __init__(self, d_in, d_out, context_length,
                 dropout, num_heads, qkv_bias=False):
          super().__init__()
          self.heads = nn.ModuleList(
              [CausalAttention(d_in, d_out, context_length, dropout, qkv_bias)
               for _ in range(num_heads)]
          )
      def forward(self, x):
          return torch.cat([head(x) for head in self.heads], dim=-1) # 循环进行使用因果注意力机制计算上下文向量，按最后一个维度进行拼接
  torch.manual_seed(123)
  mha = MultiHeadAttentionWrapper(d_in, d_out, context_length, 0.0, num_heads=2)
  context_vecs = mha(batch)
  print(context_vecs)
  ```

  这段代码通过“堆叠多个注意力头”的方式实现了一个简单的多头注意力机制。它的核心思想是：创建多个独立的 `CausalAttention` 因果注意力模块，让它们分别对同一份输入进行注意力计算，然后将多个注意力头的输出结果拼接在一起。

  在初始化方法中，`MultiHeadAttentionWrapper` 使用 `nn.ModuleList` 保存多个 `CausalAttention` 模块。这里通过列表推导式创建了 `num_heads` 个注意力头，每个注意力头都会接收相同的参数配置，例如输入维度 `d_in`、输出维度 `d_out`、上下文长度 `context_length`、dropout 比例以及是否使用 QKV 偏置。

  虽然这些注意力头的结构是一样的，但它们是彼此独立的模块，每个头都有自己独立的 `W_query`、`W_key` 和 `W_value` 等可训练参数。因此，即使输入数据相同，不同注意力头也可以从不同角度学习 token 之间的关系。

  在 `forward` 方法中，代码会遍历 `self.heads` 中的每一个注意力头，并将输入 `x` 分别传入每个 `head` 进行计算。每个注意力头都会输出一组上下文向量，表示该头根据因果注意力机制得到的上下文信息。

  最后，代码使用 `torch.cat([head(x) for head in self.heads], dim=-1)` 将所有注意力头的输出在最后一个维度上进行拼接。这里的 `dim=-1` 表示沿着特征维度拼接，而不是沿着 batch 或 token 数量维度拼接。

  需要注意的是，这种实现方式中，每个注意力头的输出维度都是 `d_out`，所以最终输出的维度会变成 `num_heads * d_out`。例如当 `num_heads=2` 时，两个头的结果拼接后，最后一维会变成原来的 2 倍。

  `torch.manual_seed(123)` 用于固定随机种子，保证每次运行时模型参数的随机初始化结果一致，方便复现实验结果。整体来看，这种方式比较直观，容易理解多头注意力的基本思想，但由于每个头都是单独的注意力模块，计算和参数组织方式不如后面“权重分割”的实现高效。


* 通过权重分割实现多头注意力机制：

  ![](https://raw.githubusercontent.com/Garden12138/picbed-cloud/main/ai/ballm36.png)

  ```python
  # 通过权重分割实现多头注意力机制
  print("通过权重分割实现多头注意力机制：")
  class MultiHeadAttention(nn.Module):
      def __init__(self, d_in, d_out,
                 context_length, dropout, num_heads, qkv_bias=False):
          super().__init__()
          # 检查总维度是否可平均分给多个注意力头
          assert d_out % num_heads == 0, "d_out must be divisible by num_heads"
          # 多头的总维度
          self.d_out = d_out
          # 注意力头数量
          self.num_heads = num_heads
          # 每个注意力头的维度
          self.head_dim = d_out // num_heads
          # 自动初始化权重参数矩阵：W_query、W_key、W_value
          self.W_query = nn.Linear(d_in, d_out, bias=qkv_bias)
          self.W_key = nn.Linear(d_in, d_out, bias=qkv_bias)
          self.W_value = nn.Linear(d_in, d_out, bias=qkv_bias)
          # 输出线性层，把多个注意力头拼接后的结果再做一次线性变换，让模型学习如何融合不同头的信息，得到最终的多头注意力输出
          self.out_proj = nn.Linear(d_out, d_out)
          self.dropout = nn.Dropout(dropout)
          self.register_buffer(
              'mask',
               torch.triu(torch.ones(context_length, context_length), diagonal=1)
          )


      def forward(self, x):
          b, num_tokens, d_in = x.shape
          # 计算权重向量：queries、keys、values : (b, num_tokens, d_out)
          keys = self.W_key(x)                                  
          queries = self.W_query(x)                             
          values = self.W_value(x)
          # 添加 num_heads 维度来隐式地拆分矩阵 : (b, num_tokens, d_out) -> (b, num_tokens, num_heads, head_dim)
          keys = keys.view(b, num_tokens, self.num_heads, self.head_dim)
          values = values.view(b, num_tokens, self.num_heads, self.head_dim)
          queries = queries.view(b, num_tokens, self.num_heads, self.head_dim)
          # 转置token数量和注意力头数，使每个head单独计算注意力 : (b, num_tokens, num_heads, head_dim) -> (b, num_heads, num_tokens, head_dim)
          keys = keys.transpose(1, 2)                               
          queries = queries.transpose(1, 2)                         
          values = values.transpose(1, 2)                           
          # 使用点积计算注意力得分，点积公式：Q @ K.T
          attn_scores = queries @ keys.transpose(2, 3)
          # 使用掩码填充注意力得分，遮住未来得分
          mask_bool = self.mask.bool()[:num_tokens, :num_tokens]
          attn_scores.masked_fill_(mask_bool, -torch.inf)
          # 使用归一（先点积缩放）计算注意力权重
          attn_weights = torch.softmax(
              attn_scores / keys.shape[-1]**0.5, dim=-1)
          # 随机丢弃一部分注意力权重，减少过拟合（训练时启用）
          attn_weights = self.dropout(attn_weights)
          # 计算上下文向量，转置转置注意力头数和token数量 : (b, num_heads, num_tokens, head_dim) -> (b, num_tokens, num_heads, head_dim) 
          context_vec = (attn_weights @ values).transpose(1, 2)
          # 先把上下文向量整理成连续内存布局（转置会改变张量的维度顺序，但底层内存可能不是连续排列的），后重新变形合并多个head
          context_vec = context_vec.contiguous().view(b, num_tokens, self.d_out)
          # 对合并后的多头结果再做一次线性变换
          context_vec = self.out_proj(context_vec)
          return context_vec

  torch.manual_seed(123)
  batch_size, context_length, d_in = batch.shape
  d_out = 2
  mha = MultiHeadAttention(d_in, d_out, context_length, 0.0, num_heads=2)
  context_vecs = mha(batch)
  print(context_vecs)
  print("context_vecs.shape:", context_vecs.shape)
  ```

  这段代码通过“权重分割”的方式实现了更标准、更高效的多头注意力机制。它不像前一种“堆叠多个注意力模块”的方式那样创建多个独立的 `CausalAttention`，而是使用一组大的线性层，一次性计算出所有注意力头需要的 `queries`、`keys` 和 `values`。

  在初始化方法中，`d_out` 表示多头注意力最终输出的总维度，`num_heads` 表示注意力头的数量。代码要求 `d_out` 必须能够被 `num_heads` 整除，这样才能将总维度平均分配给每个注意力头。每个头的维度由 `head_dim = d_out // num_heads` 计算得到。

  `W_query`、`W_key` 和 `W_value` 是三个线性层，分别用于将输入 `x` 映射成查询向量、键向量和值向量。它们的输出形状都是 `(batch_size, num_tokens, d_out)`，也就是说，此时还没有真正分成多个头，只是先把所有头需要的向量统一计算出来。

  接着，代码通过 `view` 将最后一维 `d_out` 拆分成 `num_heads` 和 `head_dim` 两个维度，形状从 `(batch_size, num_tokens, d_out)` 变成 `(batch_size, num_tokens, num_heads, head_dim)`。然后再通过 `transpose(1, 2)` 调整维度顺序，变成 `(batch_size, num_heads, num_tokens, head_dim)`，这样每个注意力头就可以独立地对所有 token 进行注意力计算。

  在注意力计算阶段，代码使用 `queries @ keys.transpose(2, 3)` 计算注意力得分，也就是每个 token 的 query 与其他 token 的 key 做点积。随后使用上三角因果掩码 `mask` 遮住当前位置之后的 token，防止模型在生成当前 token 时看到未来信息。

  注意力得分会先除以 `head_dim` 的平方根进行缩放，然后通过 `softmax` 转换成注意力权重。这个缩放操作可以避免点积结果过大，从而让 `softmax` 的结果更加稳定。之后再使用 `dropout` 随机丢弃一部分注意力权重，用于减少训练过程中的过拟合。

  得到注意力权重后，代码将其与 `values` 相乘，计算出每个注意力头对应的上下文向量。随后通过 `transpose` 和 `view` 将多个头的结果重新拼接回 `d_out` 维度，形状变回 `(batch_size, num_tokens, d_out)`。

  最后，`out_proj` 输出投影层会对拼接后的多头结果再做一次线性变换，用来学习如何融合不同注意力头的信息，得到最终的多头注意力输出。相比简单堆叠多个注意力模块，这种写法参数组织更紧凑，计算效率更高，也更接近 Transformer 中实际使用的多头注意力实现方式。

### 本节实践代码(整合版)

```python
"""
multi_head_attention.py

基于《Build a Large Language Model (From Scratch)》注意力机制章节的学习代码，
整理出的多头注意力机制实现示例。

包含：
1. CausalAttention：单头因果注意力
2. MultiHeadAttentionWrapper：通过堆叠多个单头注意力实现多头注意力
3. MultiHeadAttention：通过权重分割实现高效多头注意力
"""

import torch
import torch.nn as nn


class CausalAttention(nn.Module):
    """单头因果注意力机制。

    作用：
    - 计算 Query、Key、Value
    - 使用因果 mask 遮住未来 token
    - 得到每个 token 对历史 token 的上下文向量
    """

    def __init__(
        self,
        d_in: int,
        d_out: int,
        context_length: int,
        dropout: float,
        qkv_bias: bool = False,
    ):
        super().__init__()
        self.d_out = d_out

        # 自动初始化 W_query、W_key、W_value 三组可训练参数
        self.W_query = nn.Linear(d_in, d_out, bias=qkv_bias)
        self.W_key = nn.Linear(d_in, d_out, bias=qkv_bias)
        self.W_value = nn.Linear(d_in, d_out, bias=qkv_bias)

        self.dropout = nn.Dropout(dropout)

        # 注册因果注意力 mask：
        # 上三角为 1，表示这些位置属于“未来 token”，需要被遮住
        self.register_buffer(
            "mask",
            torch.triu(torch.ones(context_length, context_length), diagonal=1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """前向传播。

        Args:
            x: 输入张量，形状为 (batch_size, num_tokens, d_in)

        Returns:
            context_vec: 上下文向量，形状为 (batch_size, num_tokens, d_out)
        """
        batch_size, num_tokens, _ = x.shape

        keys = self.W_key(x)
        queries = self.W_query(x)
        values = self.W_value(x)

        # 注意力得分：Q @ K^T
        # queries: (batch_size, num_tokens, d_out)
        # keys.transpose(1, 2): (batch_size, d_out, num_tokens)
        # attn_scores: (batch_size, num_tokens, num_tokens)
        attn_scores = queries @ keys.transpose(1, 2)

        # 只取当前序列长度对应的 mask 区域
        mask_bool = self.mask.bool()[:num_tokens, :num_tokens]

        # 将未来 token 的注意力得分替换为 -inf，
        # 这样经过 softmax 后，这些位置的注意力权重会变成 0
        attn_scores.masked_fill_(mask_bool, -torch.inf)

        # 缩放点积注意力：除以 key 向量维度的平方根，避免点积结果过大
        attn_weights = torch.softmax(
            attn_scores / keys.shape[-1] ** 0.5,
            dim=-1,
        )

        # 训练时随机丢弃一部分注意力权重，减少过拟合
        attn_weights = self.dropout(attn_weights)

        # 使用注意力权重对 value 加权求和
        context_vec = attn_weights @ values
        return context_vec


class MultiHeadAttentionWrapper(nn.Module):
    """通过堆叠多个 CausalAttention 实现多头注意力。

    这种写法直观、适合学习：
    - 每个 head 都是一个独立的 CausalAttention
    - 最后把所有 head 的输出在最后一个维度上拼接起来
    """

    def __init__(
        self,
        d_in: int,
        d_out: int,
        context_length: int,
        dropout: float,
        num_heads: int,
        qkv_bias: bool = False,
    ):
        super().__init__()

        self.heads = nn.ModuleList(
            [
                CausalAttention(
                    d_in=d_in,
                    d_out=d_out,
                    context_length=context_length,
                    dropout=dropout,
                    qkv_bias=qkv_bias,
                )
                for _ in range(num_heads)
            ]
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # 每个 head 单独计算上下文向量，然后按最后一个维度拼接
        # 如果每个 head 输出 d_out，num_heads 个 head 拼接后就是 d_out * num_heads
        return torch.cat([head(x) for head in self.heads], dim=-1)


class MultiHeadAttention(nn.Module):
    """通过权重分割实现的高效多头注意力机制。

    这是更接近 Transformer / GPT 实际使用方式的实现：
    - 先一次性计算所有 head 的 Query、Key、Value
    - 再把 d_out 拆成 num_heads 个 head_dim
    - 每个 head 并行计算注意力
    - 最后拼接多个 head 的结果，并通过 out_proj 融合
    """

    def __init__(
        self,
        d_in: int,
        d_out: int,
        context_length: int,
        dropout: float,
        num_heads: int,
        qkv_bias: bool = False,
    ):
        super().__init__()

        # d_out 必须能被 num_heads 整除，才能平均分给每个注意力头
        assert d_out % num_heads == 0, "d_out must be divisible by num_heads"

        self.d_out = d_out
        self.num_heads = num_heads
        self.head_dim = d_out // num_heads

        # 一次性生成所有 head 的 Q、K、V
        self.W_query = nn.Linear(d_in, d_out, bias=qkv_bias)
        self.W_key = nn.Linear(d_in, d_out, bias=qkv_bias)
        self.W_value = nn.Linear(d_in, d_out, bias=qkv_bias)

        # 输出投影层：
        # 多个 head 拼接后，再通过这个线性层学习如何融合不同 head 的信息
        self.out_proj = nn.Linear(d_out, d_out)

        self.dropout = nn.Dropout(dropout)

        # 因果 mask：遮住未来 token
        self.register_buffer(
            "mask",
            torch.triu(torch.ones(context_length, context_length), diagonal=1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """前向传播。

        Args:
            x: 输入张量，形状为 (batch_size, num_tokens, d_in)

        Returns:
            context_vec: 多头注意力输出，形状为 (batch_size, num_tokens, d_out)
        """
        batch_size, num_tokens, _ = x.shape

        # 1. 计算 Q、K、V
        # 形状都是：(batch_size, num_tokens, d_out)
        keys = self.W_key(x)
        queries = self.W_query(x)
        values = self.W_value(x)

        # 2. 把 d_out 拆成 num_heads 个 head_dim
        # (batch_size, num_tokens, d_out)
        # -> (batch_size, num_tokens, num_heads, head_dim)
        keys = keys.view(batch_size, num_tokens, self.num_heads, self.head_dim)
        queries = queries.view(batch_size, num_tokens, self.num_heads, self.head_dim)
        values = values.view(batch_size, num_tokens, self.num_heads, self.head_dim)

        # 3. 调整维度顺序，让每个 head 可以单独计算注意力
        # -> (batch_size, num_heads, num_tokens, head_dim)
        keys = keys.transpose(1, 2)
        queries = queries.transpose(1, 2)
        values = values.transpose(1, 2)

        # 4. 每个 head 内部计算注意力得分：Q @ K^T
        # attn_scores: (batch_size, num_heads, num_tokens, num_tokens)
        attn_scores = queries @ keys.transpose(2, 3)

        # 5. 应用因果 mask，遮住未来 token
        mask_bool = self.mask.bool()[:num_tokens, :num_tokens]
        attn_scores.masked_fill_(mask_bool, -torch.inf)

        # 6. 缩放 + softmax，得到注意力权重
        attn_weights = torch.softmax(
            attn_scores / self.head_dim ** 0.5,
            dim=-1,
        )

        # 7. dropout
        attn_weights = self.dropout(attn_weights)

        # 8. 使用注意力权重对 values 加权求和
        # context_vec: (batch_size, num_heads, num_tokens, head_dim)
        context_vec = attn_weights @ values

        # 9. 把多个 head 的结果重新拼接起来
        # (batch_size, num_heads, num_tokens, head_dim)
        # -> (batch_size, num_tokens, num_heads, head_dim)
        context_vec = context_vec.transpose(1, 2)

        # transpose 后内存可能不连续，所以先 contiguous，再 view
        # -> (batch_size, num_tokens, d_out)
        context_vec = context_vec.contiguous().view(
            batch_size,
            num_tokens,
            self.d_out,
        )

        # 10. 输出投影，融合多个 head 的信息
        context_vec = self.out_proj(context_vec)

        return context_vec


def build_demo_inputs() -> torch.Tensor:
    """构造书中示例使用的输入嵌入。"""
    inputs = torch.tensor(
        [
            [0.43, 0.15, 0.89],  # Your
            [0.55, 0.87, 0.66],  # journey
            [0.57, 0.85, 0.64],  # starts
            [0.22, 0.58, 0.33],  # with
            [0.77, 0.25, 0.10],  # one
            [0.05, 0.80, 0.55],  # step
        ]
    )

    # 增加 batch 维度：
    # 原始 inputs: (num_tokens, d_in)
    # batch: (batch_size, num_tokens, d_in)
    batch = torch.stack((inputs, inputs), dim=0)
    return batch


def demo_multi_head_attention() -> None:
    """运行多头注意力示例。"""
    torch.manual_seed(123)

    batch = build_demo_inputs()
    batch_size, context_length, d_in = batch.shape

    print("输入 batch 形状:", batch.shape)
    print("batch_size:", batch_size)
    print("context_length:", context_length)
    print("d_in:", d_in)

    # ------------------------------------------------------------------
    # 方法一：通过堆叠多个单头因果注意力实现多头注意力
    # ------------------------------------------------------------------
    print("\n方法一：通过堆叠实现多头注意力")
    wrapper_mha = MultiHeadAttentionWrapper(
        d_in=d_in,
        d_out=2,
        context_length=context_length,
        dropout=0.0,
        num_heads=2,
    )

    wrapper_context_vecs = wrapper_mha(batch)

    print("输出结果:")
    print(wrapper_context_vecs)
    print("输出形状:", wrapper_context_vecs.shape)
    print("说明：每个 head 输出 2 维，2 个 head 拼接后输出 4 维")

    # ------------------------------------------------------------------
    # 方法二：通过权重分割实现更高效的多头注意力
    # ------------------------------------------------------------------
    print("\n方法二：通过权重分割实现多头注意力")
    efficient_mha = MultiHeadAttention(
        d_in=d_in,
        d_out=2,
        context_length=context_length,
        dropout=0.0,
        num_heads=2,
    )

    efficient_context_vecs = efficient_mha(batch)

    print("输出结果:")
    print(efficient_context_vecs)
    print("输出形状:", efficient_context_vecs.shape)
    print("说明：d_out=2，num_heads=2，所以每个 head 的维度 head_dim=1")


if __name__ == "__main__":
    demo_multi_head_attention()
```