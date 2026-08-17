"""Gradient-boosted decision tree classifier.

The non-LLM comparison. Model risk review reasonably asks why a task needs a
language model, and "because we didn't try anything else" is not an answer.
This is the conventional alternative - TF-IDF features into gradient-boosted
trees, one head for impact and one for urgency, severity derived from the
rubric exactly as everywhere else in this project.

Same Classifier contract, same gates, same metrics. The only difference is
that this one has to be trained first, which is itself the interesting part -
it needs thousands of labelled examples where the LLM needed none.

Confidence is the product of the two heads' predicted probabilities. That is a
real probability estimate rather than a self-report, which makes it better
calibrated than an LLM's stated confidence and worth noting when comparing
Gate B behaviour across classifiers.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..rubric import derive_severity
from ..schemas import Category, Impact, TriageDecision, Urgency
from .base import ClassifierError


class GBDTClassifier:
    """TF-IDF into gradient-boosted trees. Requires training data."""

    def __init__(
        self,
        train_path: str | Path,
        max_features: int = 4000,
        n_estimators: int = 300,
        max_depth: int = 6,
        seed: int = 20260817,
    ) -> None:
        try:
            import numpy as np
            from sklearn.feature_extraction.text import TfidfVectorizer
            from xgboost import XGBClassifier
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ClassifierError(
                "gbdt classifier needs extras. pip install '.[gbdt]'"
            ) from exc

        self._np = np
        path = Path(train_path)
        if not path.exists():
            raise ClassifierError(
                f"training data not found at {path}. "
                "Run: python evals/generate_incidents.py"
            )

        rows = [
            json.loads(line)
            for line in path.read_text().splitlines()
            if line.strip()
        ]
        if len(rows) < 200:
            raise ClassifierError(
                f"only {len(rows)} training rows. Gradient boosting on text needs "
                "thousands; generate more before drawing conclusions."
            )

        texts = [r["text"] for r in rows]
        self._impacts = sorted({r["impact"] for r in rows})
        self._urgencies = sorted({r["urgency"] for r in rows})
        self._categories = sorted({r["category"] for r in rows})

        self._vectorizer = TfidfVectorizer(
            ngram_range=(1, 2), max_features=max_features, sublinear_tf=True
        )
        features = self._vectorizer.fit_transform(texts)

        def fit(labels, classes):
            model = XGBClassifier(
                n_estimators=n_estimators,
                max_depth=max_depth,
                learning_rate=0.15,
                subsample=0.9,
                colsample_bytree=0.9,
                objective="multi:softprob",
                num_class=len(classes),
                random_state=seed,
                verbosity=0,
                tree_method="hist",
            )
            index = {c: i for i, c in enumerate(classes)}
            model.fit(features, np.array([index[label] for label in labels]))
            return model

        self._impact_model = fit([r["impact"] for r in rows], self._impacts)
        self._urgency_model = fit([r["urgency"] for r in rows], self._urgencies)
        self._category_model = fit([r["category"] for r in rows], self._categories)

        self.n_training_rows = len(rows)
        self.name = f"gbdt-tfidf-n{len(rows)}"

    def classify(
        self,
        incident_id: str,
        text: str,
        feedback: str | None = None,
    ) -> TriageDecision:
        # Feedback is ignored. A trained model cannot revise on being told it
        # failed a gate, which means the retry in the agent loop is wasted on
        # it - worth stating rather than hiding.
        features = self._vectorizer.transform([text])

        impact_probs = self._impact_model.predict_proba(features)[0]
        urgency_probs = self._urgency_model.predict_proba(features)[0]
        category_probs = self._category_model.predict_proba(features)[0]

        impact = Impact(self._impacts[int(self._np.argmax(impact_probs))])
        urgency = Urgency(self._urgencies[int(self._np.argmax(urgency_probs))])
        category = Category(self._categories[int(self._np.argmax(category_probs))])

        confidence = float(impact_probs.max() * urgency_probs.max())

        return TriageDecision(
            incident_id=incident_id,
            category=category,
            impact=impact,
            urgency=urgency,
            severity=derive_severity(impact, urgency),
            confidence=round(min(max(confidence, 0.0), 1.0), 3),
            rationale=(
                f"Gradient-boosted model over TF-IDF features assessed impact as "
                f"{impact.value} (p={impact_probs.max():.2f}) and urgency as "
                f"{urgency.value} (p={urgency_probs.max():.2f}). Trained on "
                f"{self.n_training_rows} synthetic incidents."
            ),
            indicators=[
                f"p_impact={impact_probs.max():.2f}",
                f"p_urgency={urgency_probs.max():.2f}",
            ],
        )
