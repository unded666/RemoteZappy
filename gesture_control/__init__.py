"""GestureControl package

This module provides the primary interface for the GestureControl package,
which includes functionality for gesture recognition and studio visualization.

Public API:
- MLPClassifier, GestureDataset, load_model, save_model from .mlp
- train_meta_classifier, load_meta_classifier from .meta
- GestureRecognizer from .recognizer
- studio from .studio
"""

from .mlp import MLPClassifier, GestureDataset, load_model, save_model
from .meta import train_meta_classifier, load_meta_classifier
from .recognizer import GestureRecognizer
from .studio import studio

__all__ = [
    # From mlp
    'MLPClassifier',
    'GestureDataset',
    'load_model',
    'save_model',

    # From meta
    'train_meta_classifier',
    'load_meta_classifier',

    # From recognizer
    'GestureRecognizer',

    # From studio
    'studio',
]
