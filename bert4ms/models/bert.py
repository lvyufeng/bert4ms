import mindspore.nn as nn
import mindspore.ops as P
import mindspore.numpy as mnp
import mindspore.common.dtype as mstype
from ..common.activations import MultiHeadAttention, activation_map
from ..common.cell import Cell, PretrainedCell
from ..common.layers import Dense, Embedding

def get_attn_pad_mask(seq_q, seq_k):
    batch_size, len_q = seq_q.shape
    batch_size, len_k = seq_k.shape

    pad_attn_mask = P.ExpandDims()(P.Equal()(seq_k, 0), 1)
    pad_attn_mask = P.Cast()(pad_attn_mask, mstype.int32)
    pad_attn_mask = P.BroadcastTo((batch_size, len_q, len_k))(pad_attn_mask)
    # pad_attn_mask = P.Cast()(pad_attn_mask, mstype.bool_)
    return pad_attn_mask

class BertConfig:
    def __init__(self,
                seq_length=128,
                vocab_size=32000,
                hidden_size=768,
                num_hidden_layers=12,
                num_attention_heads=12,
                intermediate_size=3072,
                hidden_act="gelu",
                hidden_dropout_prob=0.1,
                attention_probs_dropout_prob=0.1,
                max_position_embeddings=512,
                type_vocab_size=2):
        self.seq_length = seq_length
        self.vocab_size = vocab_size
        self.hidden_size = hidden_size
        self.num_hidden_layers = num_hidden_layers
        self.num_attention_heads = num_attention_heads
        self.hidden_act = hidden_act
        self.intermediate_size = intermediate_size
        self.hidden_dropout_prob = hidden_dropout_prob
        self.attention_probs_dropout_prob = attention_probs_dropout_prob
        self.max_position_embeddings = max_position_embeddings
        self.type_vocab_size = type_vocab_size

class PoswiseFeedForwardNet(Cell):
    def __init__(self, d_model, d_ff, activation:str='gelu'):
        super().__init__()
        self.fc1 = Dense(d_model, d_ff)
        self.fc2 = Dense(d_ff, d_model)
        self.activation = activation_map.get(activation, nn.GELU())
        self.layer_norm = nn.LayerNorm((d_model,), epsilon=1e-5)

    def construct(self, inputs):
        residual = inputs
        outputs = self.fc1(inputs)
        outputs = self.activation(outputs)
        outputs = self.fc2(outputs)
        return self.layer_norm(outputs + residual)

class BertEmbeddings(Cell):
    def __init__(self, config):
        super().__init__()
        self.tok_embed = Embedding(config.vocab_size, config.hidden_size)
        self.pos_embed = Embedding(config.seq_length, config.hidden_size)
        self.seg_embed = Embedding(config.type_vocab_size, config.hidden_size)
        self.norm = nn.LayerNorm((config.hidden_size,))

        self.expand_dims = P.ExpandDims()

    def construct(self, x, seg):
        seq_len = x.shape[1]
        pos = mnp.arange(seq_len)
        pos = P.BroadcastTo(x.shape)(self.expand_dims(pos, 0))
        embedding = self.tok_embed(x) + self.pos_embed(pos) + self.seg_embed(seg)
        return self.norm(embedding)

class BertEncoderLayer(Cell):
    def __init__(self, d_model, n_heads, d_ff, activation, dropout):
        super().__init__()
        self.enc_self_attn = MultiHeadAttention(d_model, n_heads, dropout)
        self.pos_ffn = PoswiseFeedForwardNet(d_model, d_ff, activation)

    def construct(self, enc_inputs, enc_self_attn_mask):
        enc_outputs, attn = self.enc_self_attn(enc_inputs, enc_inputs, enc_inputs, enc_self_attn_mask)
        enc_outputs = self.pos_ffn(enc_outputs)
        return enc_outputs, attn

class BertEncoder(Cell):
    def __init__(self, config):
        super().__init__()
        self.layers = nn.CellList([BertEncoderLayer(config.hidden_size, config.num_attention_heads, config.intermediate_size, config.hidden_act, config.hidden_dropout_prob) for _ in range(config.num_hidden_layers)])

    def construct(self, inputs, enc_self_attn_mask):
        outputs = inputs
        for layer in self.layers:
            outputs, enc_self_attn = layer(outputs, enc_self_attn_mask)
        return outputs

class BertModel(PretrainedCell):
    def __init__(self, config):
        super().__init__(config)
        self.embeddings = BertEmbeddings(config)
        self.encoder = BertEncoder(config)
        self.pooler = Dense(config.hidden_size, config.hidden_size, activation='tanh')
        
    def construct(self, input_ids, segment_ids):
        outputs = self.embeddings(input_ids, segment_ids)
        enc_self_attn_mask = get_attn_pad_mask(input_ids, input_ids)
        outputs = self.encoder(outputs, enc_self_attn_mask)
        h_pooled = self.pooler(outputs[:, 0]) 
        return outputs, h_pooled

class BertForPretraining(Cell):
    def __init__(self, auto_prefix, flags):
        super().__init__(auto_prefix=auto_prefix, flags=flags)

    def construct(self, *inputs, **kwargs):
        return super().construct(*inputs, **kwargs)