from langchain_core.embeddings import Embeddings
from sentence_transformers import SentenceTransformer
from config import settings
from typing import List


class SentenceTransformerEmbeddings(Embeddings):
    def __init__(self, model_name: str):
        self.model = SentenceTransformer(model_name)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.model.encode(texts, show_progress_bar=False).tolist()

    def embed_query(self, text: str) -> List[float]:
        return self.model.encode(text, show_progress_bar=False).tolist()
    def get_sentence_embedding_dimension(self) -> int:
        return self.model.get_sentence_embedding_dimension()
    def encode(self, texts: List[str], show_progress_bar=False, batch_size=16, convert_to_numpy=True) -> List[List[float]]:
        return self.model.encode(texts, show_progress_bar=show_progress_bar, batch_size=batch_size, convert_to_numpy=convert_to_numpy)
    
sentence_transformer_embeddings = SentenceTransformerEmbeddings(settings.embed_model)