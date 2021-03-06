"""Module for loading, manipulating, and searching card embedding vector spaces.

NOTE: This is rough work, and not actually part of the final project. See the project report
for more details.
"""
from __future__ import annotations
import re
import time
import math
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Tuple, Set, List, Dict, Union, Optional

import numpy as np
import gensim.downloader
from num2words import num2words
from nltk.corpus import stopwords
from gensim.utils import simple_preprocess
from sklearn import decomposition, neighbors
from gensim.models import Word2Vec, KeyedVectors

from logger import logger


_DEFAULT_WORD2VEC_MODEL = 'glove-wiki-gigaword-50'


@dataclass
class Card:
    """A representation of any card in the game."""
    name: str
    text: Optional[str] = None
    race: Optional[str] = None
    card_class: Optional[str] = None
    rarity: Optional[str] = None
    tier: Optional[int] = None
    attack: Optional[int] = None
    health: Optional[int] = None
    cost: Optional[int] = None
    is_golden: bool = False

    @staticmethod
    def from_dict(data: dict, gold_prefix: str = 'golden') -> Card:
        """Return the card represented by the given dict.
        Raise a ValueError if the given dict does not have a name key.
        """
        name = data.get('name', None)
        if name is None:
            raise ValueError('card data does not have a name key!')

        # Add golden prefix
        is_golden = data.get('is_golden', False)
        if is_golden:
            name = f'{gold_prefix} {name}'

        card = Card(name)
        card.text = data.get('text', None)
        card.is_golden = is_golden
        card.race = data.get('race', None)
        card.card_class = data.get('cardClass', None)
        card.rarity = data.get('rarity', None)

        if (tier := data.get('tier', None)) is not None:
            card.tier = int(tier)
        if (attack := data.get('attack', None)) is not None:
            card.attack = int(attack)
        if (health := data.get('health', None)) is not None:
            card.health = int(health)
        if (cost := data.get('cost', None)) is not None:
            card.cost = int(cost)

        return card


class CardEmbeddings:
    """Represents vector representations of Hearthstone cards as a discretized vector space."""
    # Private Instance Attribute:
    #   - _weights: A matrix with shape (vocab_size, n) where n is the dimensionality of the
    #               embedding vectors (i.e. the number of components). The i-th row of the
    #               matrix should correspond to the embedding vector for card i.
    #   - _card_names: A list of strings, where the i-th element of the list corresponds
    #                  to the name of the card with encoded index i. This is in lowercase.
    #   - _vocabulary: A dict mapping each card name to its index.
    #   - _nearest_neighbours: A nearest neighbours model for finding most similar embeddings.
    #   - _word2vec: Full-dimensionality word embeddings from a word2vec model.
    #   - _word_embeddings: Active (potentially reduced) word embeddings from a word2vec model.
    #   - _card_data: A dict mapping each card name to its json object.
    #   - _stop_words: A set of commonly used English words.
    _vocabulary: Dict[str, int]
    _nearest_neighbours: Optional[neighbors.NearestNeighbors]
    _word2vec: Optional[KeyedVectors]
    _word_embeddings: Optional[KeyedVectors]
    _card_data: Dict[str, dict]
    _stop_words: Set[str]

    def __init__(self, card_data_filepath: Path,
                 use_nearest_neighbours: bool = True,
                 word2vec_model: Optional[Union[str, Path]] = _DEFAULT_WORD2VEC_MODEL,
                 embedding_size: Optional[int] = None) -> None:
        """Initialise this CardEmbeddings.

        Args:
            card_data_filepath: Filepath to a json file containing a list of card objects in the
                                format given by the HearthstoneJSON data api. Embedding vectors are
                                built from the textual descriptions and card attributes given in
                                this file.
            use_nearest_neighbours: Whether to build the nearest neighbours model.
            word2vec_model: Filepath to a word2vec model checkpoint or the name of a pre-trained
                            model corresponding to the gensim-data models available from
                            https://github.com/RaRe-Technologies/gensim-data/.
                            If not specified, then defaults to the ``glove-wiki-gigaword-50`` model.
            embedding_size: The dimensionality of each embedding. If this does not match the
                            dimensionality of the given word2vec, then PCA is used to reduce
                            the dimensionality of the vectors to the desired size.
        """
        # Load card data and construct embeddings
        model_keys = list(gensim.downloader.info()['models'].keys())
        # Load model vectors as a KeyedVectors object
        if isinstance(word2vec_model, str) and word2vec_model in model_keys:
            # word2vec_model is the name of a pre-trained model
            self._word2vec = gensim.downloader.load(word2vec_model)
        else:
            # word2vec_model is a path to a model checkpoint
            self._word2vec = Word2Vec.load(str(word2vec_model)).wv

        self._init_special_embeddings()
        if embedding_size is not None:
            self._reduce_dimensionality(embedding_size)
        else:
            self._word_embeddings = self._word2vec

        self._weights = np.empty((0,))
        self._card_names = []
        self._vocabulary = {}
        self._nearest_neighbours = None
        self._card_data = {}
        self._stop_words = set(stopwords.words('english'))
        self._load_card_data(card_data_filepath)

        if use_nearest_neighbours:
            self._build_nearest_neighbours()

    def _load_card_data(self, card_data_filepath: Path) -> None:
        """Load card data from the given file and create the embedding vectors for each card.
        Note that this does NOT update the nearest neighbour searcher!
        """
        with open(card_data_filepath, encoding='utf-8') as fp:
            card_data = json.load(fp)

        for card_dict in card_data:
            name = card_dict.get('name', None)
            if name is None:
                continue

            self._card_data[name] = card_dict
            card = Card.from_dict(card_dict)
            vector = self._vectorize_card(card)
            # Update weights
            if len(self._weights) == 0:
                self._weights = [vector]
            else:
                self._weights = np.vstack((self._weights, vector))
            # Update card names
            self._card_names.append(card.name.lower())
            self._vocabulary[self._card_names[-1]] = len(self._card_names) - 1

    def _build_nearest_neighbours(self) -> None:
        """Build a nearest neighbour searcher from the embedding vectors."""
        logger.info('Building nearest neighbours for embeddings')
        start_time = time.time()
        # We use a KNN model to perform embedding similarity search quickly.
        # The goal is to find the most similar embedding vectors based on their cosine similarity.
        # However, while KNN does not support the cosine metric, by normalizing the embedding
        # vectors, we can use a KNN on Euclidean distance to find the most similar vectors, and
        # we will get the same ordering as we would if we used cosine similarity.
        self._nearest_neighbours = neighbors.NearestNeighbors(n_neighbors=10)
        # Normalized the weights to have unit norm
        normalized_weights = self._weights / np.linalg.norm(self._weights, axis=-1, keepdims=True)
        self._nearest_neighbours.fit(normalized_weights)
        elapsed = time.time() - start_time
        logger.info(f'Finished building nearest neighbours ({elapsed:.2f} seconds)!')

    def _reduce_dimensionality(self, target_dimensionality: int) -> None:
        """Reduce the dimensionality of the word embeddings.

        Preconditions:
            - target_dimensionality < self._word2vec.vector_size
        """
        # Embed word vectors into lower-dimensional space
        pca = decomposition.PCA(n_components=target_dimensionality)
        fit_embeddings = pca.fit_transform(self._word2vec.vectors)
        word_embeddings = KeyedVectors(target_dimensionality)
        keys, vectors = [], []
        for index, key in enumerate(self._word2vec.index_to_key):
            keys.append(key)
            vectors.append(fit_embeddings[index])
        word_embeddings.add_vectors(keys, vectors)
        self._word_embeddings = word_embeddings

    def _init_special_embeddings(self) -> None:
        """Initialise embeddings for special Hearthstone words such as "Deathrattle" and "Murloc."
        """
        if 'deathrattle' not in self._word2vec:
            # Use the average of the vectors for "death" and "rattle" as a proxy
            v = (self._word2vec.get_vector('death') + self._word2vec.get_vector('rattle')) / 2
            self._word2vec.add_vector('deathrattle', v)

        if 'deathrattles' not in self._word2vec:
            # Use the vector for "battlecry" as a proxy
            v = self._word2vec.get_vector('deathrattle')
            self._word2vec.add_vector('deathrattles', v)

        if 'battlecry' not in self._word2vec:
            # Use the average of the vectors for "battle" and "cry" as a proxy
            v = (self._word2vec.get_vector('battle') + self._word2vec.get_vector('cry')) / 2
            self._word2vec.add_vector('battlecry', v)

        if 'battlecries' not in self._word2vec:
            # Use the vector for "battlecry" as a proxy
            v = self._word2vec.get_vector('battlecry')
            self._word2vec.add_vector('battlecries', v)

        if 'windfury' not in self._word2vec:
            # Use the average of the vectors for "wind" and "fury" as a proxy
            v = (self._word2vec.get_vector('wind') + self._word2vec.get_vector('fury')) / 2
            self._word2vec.add_vector('windfury', v)

        if 'windfuries' not in self._word2vec:
            # Use the vector for "windfury" as a proxy
            v = self._word2vec.get_vector('windfury')
            self._word2vec.add_vector('windfuries', v)

        if 'murloc' not in self._word2vec:
            # Use the vector for "fish" as a proxy
            v = self._word2vec.get_vector('fish')
            self._word2vec.add_vector('murloc', v)

        if 'murlocs' not in self._word2vec:
            # Use the vector for "fishes" as a proxy
            v = self._word2vec.get_vector('fishes')
            self._word2vec.add_vector('murlocs', v)

    def get_vector(self, card_name: str) -> np.ndarray:
        """Return the embedding vector for the card with the given name.
        Raise a ValueError if there is no embedding vector for the card with the given name.
        """
        card_name = card_name.lower()
        if card_name in self._vocabulary:
            return self._weights[self._vocabulary[card_name]]
        else:
            raise ValueError(f'no embedding vector for the card with name \'{card_name}\'')

    def _vectorize_card(self, card: Card) -> np.ndarray:
        """Vectorize a card with the given attributes. Return the corresponding card embedding."""
        # Weight scheme:
        #   - 30% text vector
        #   - 30% race vector
        #   - 15% attack vector
        #   - 15% health vector
        #   - 10% remaining
        TEXT_VECTOR_WEIGHT = 0.3
        RACE_VECTOR_WEIGHT = 0.3
        ATTACK_VECTOR_WEIGHT = 0.15
        HEALTH_VECTOR_WEIGHT = 0.15
        REMAINING_VECTOR_WEIGHT = 1 - (TEXT_VECTOR_WEIGHT + RACE_VECTOR_WEIGHT + \
            ATTACK_VECTOR_WEIGHT + HEALTH_VECTOR_WEIGHT)

        features = []
        if card.text is not None:
            text_tokens = tokenize(clean_card_text(card.text))
            features.append((self._aggregrate_embeddings(text_tokens), TEXT_VECTOR_WEIGHT))

        if card.race is not None:
            features.append((self._aggregrate_embeddings(card.race.lower()), RACE_VECTOR_WEIGHT))

        if card.attack is not None:
            attack_tokens = tokenize(f'attack {num2words(card.attack)}')
            features.append((self._aggregrate_embeddings(attack_tokens), ATTACK_VECTOR_WEIGHT))

        if card.health is not None:
            health_tokens = tokenize(f'health {num2words(card.health)}')
            features.append((self._aggregrate_embeddings(health_tokens), HEALTH_VECTOR_WEIGHT))

        if card.tier is not None:
            tier_tokens = tokenize(f'tier {num2words(card.tier)}')
            features.append((self._aggregrate_embeddings(tier_tokens), REMAINING_VECTOR_WEIGHT))

        total_weight = sum(weight for _, weight in features)
        return sum((weight / total_weight) * vector for vector, weight in features)
        # Add tavern tier feature vector
        # if card.tier is not None:
            # tier_vector = self._word_embeddings.get_vector('tier', norm=True)
            # features.append(tier_vector * card.tier)

        # Add attack feature vector
        # if card.attack is not None:
            # attack_vector = self._word_embeddings.get_vector('attack', norm=True)
            # features.append(attack_vector * card.attack)
            # features.append(self._aggregrate_embeddings(attack_tokens, sum))
        # Add health feature vector
        # if card.health is not None:
            # health_vector = self._word_embeddings.get_vector('health', norm=True)
            # features.append(health_vector * card.health)
            # features.append(self._aggregrate_embeddings(health_tokens, sum))

    def _aggregrate_embeddings(self, tokens: List[str], func: callable = sum, norm: bool = True) \
            -> np.ndarray:
        """Return the aggregate of the embedding vectors for the given list of words.
        If a word doesn't have an embedding word, then the zero vector is used instead.

        Args:
            tokens: A list of tokens.
            func: The aggregation function to use. This takes in a list of vectors
                    (np.ndarray objects) and returns a single vector, of the same dimensionality
                    as a np.ndarray object.
            norm: Whether to use unit-norm word embeddings, or raw word embedding vectors.
        """
        for x in tokens:
            if x not in self._word_embeddings:
                logger.warning(f'No word embedding exists for \'{x}\'')

        return func(
            self._word_embeddings.get_vector(x, norm=norm)
            for x in tokens if x in self._word_embeddings
        )

    def _make_named_feature_vector(self, attribute: str, value: str, norm: bool = True) \
            -> np.ndarray:
        """Return the named feature vector for the given attribute.

        Args:
            attribute: The name of the attribute. Used as a context in the feature vector.
            value: The value of the attribute.
            norm: Whether to use unit-norm word embeddings, or raw word embedding vectors.
        """
        tokens = tokenize(f'{attribute} {value}')
        return self._aggregrate_embeddings(tokens, sum, norm=norm)

    def most_similar(self, card_name: str, k: Optional[int] = 10) -> List[Tuple[str, float]]:
        """Finds the most similar cards to the given card, based on the cosine similarity.
        Return a list of 2-element tuple of the word and similarity, sorted in decreasing order
        of the similarity.

        If the given card is not in the card name vocabulary, an empty list is returned.

        Args:
            card_name: The name of the card to search. This is not case sensitive.
            k: The number of most similar card names to return. If unspecified, the whole card
               name vocabulary is returned.
        """
        card_name = card_name.lower()
        if card_name not in self._vocabulary:
            return []

        # Default to the vocab size
        # Clamp the given value of k to be in the range [0, vocab_size].
        vocab_size = len(self._card_names)
        # We get the k + 1 nearest neighbours since the model gives back the input as well.
        k = max(min((k or vocab_size) + 1, vocab_size), 0)

        # Lookup the embedding vector
        card_index = self._vocabulary[card_name]
        vector = self._weights[card_index]
        # Get the nearest neighbours
        # The KNN returns a numpy array with shape (batch_size, vector_size),
        # but in our case the batch size is just 1 (the single embedding vector input).
        _, indices = self._nearest_neighbours.kneighbors([vector], n_neighbors=k)

        most_similar = [(
            self._card_names[index],
            # Recompute the distance, but using cosine similarity.
            cosine_similarity(vector, self._weights[index])
        ) for index in indices[0] if index != card_index]

        return most_similar

    def save_as_tsv(self, filepath: Union[str, Path]) -> None:
        """Save these card embeddings as a tsv file at the given filepath."""
        # Ensure filepath is a Path-like object
        filepath = Path(filepath)
        # Build metdata filepath
        extension = filepath.suffix
        metadata_filename = filepath.with_suffix('').name + '_metadata' + extension
        metadata_filepath = filepath.parent / metadata_filename
        with open(filepath, 'w+') as output_fp, open(metadata_filepath, 'w+') as metadata_fp:
            # Write data
            for index in range(len(self._weights)):
                line = '\t'.join(str(x) for x in self._weights[index])
                output_fp.write(line + '\n')
                metadata_fp.write(self._card_names[index] + '\n')

    @property
    def embedding_size(self) -> int:
        """Return the dimensionality of the embedding vectors."""
        return self._weights.shape[-1]

    def __getitem__(self, card_name: str) -> np.ndarray:
        """Return the embedding vector for the card with the given name."""
        return self.get_vector(card_name)


def cosine_similarity(u: np.ndarray, v: np.ndarray) -> float:
    """Return the cosine similarity of the two given vectors.

    Preconditions
        - u.shape == v.shape and u.ndim == 1
    """
    return np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v))


def tokenize(text: str) -> List[str]:
    """Return a list of tokens from the given text."""
    return simple_preprocess(text, min_len=0, max_len=float('inf'))

def clean_card_text(text: str) -> str:
    """Clean a card description."""
    text = text.replace('[x]', '')
    # Remove html tags
    text = re.sub(r'<.*?>', '', text)
    # Replace "+X/+Y" with "X attack and Y health"
    replace_func = lambda x: '{} attack and {} health'.format(x.group(1), x.group(2))
    text = re.sub(r'\+(\d*)\/\+(\d*)', replace_func, text)
    # Replace numbers with word representation
    text = re.sub(r'(\d+)', lambda x: num2words(int(x.group(0))), text)
    return text


if __name__ == '__main__':
    import doctest
    doctest.testmod()
