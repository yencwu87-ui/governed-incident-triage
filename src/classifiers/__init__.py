"""Classifier implementations sharing one contract."""

from .base import Classifier, ClassifierError
from .baseline import BaselineClassifier

__all__ = ["BaselineClassifier", "Classifier", "ClassifierError"]
