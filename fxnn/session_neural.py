"""Exact-update trainer reused from the preregistered Adam budget experiment."""
import warnings

import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler


class BudgetReached(Exception):
    """Internal sentinel raised before any extra backprop or Adam update."""


class BudgetClassifier(MLPClassifier):
    def _backprop(self, X, y, sample_weight, *args):
        if self._optimizer.t == self.update_budget:
            raise BudgetReached
        result = super()._backprop(X, y, sample_weight, *args)
        if not np.isfinite(result[0]):
            raise ValueError('Non-finite minibatch loss')
        self.batch_losses.append(float(result[0]))
        self.batch_sizes.append(len(X))
        return result


class FixedUpdates:
    def fit(self, X, y, weights, parameters, updates):
        if type(updates) is not int or updates <= 0:
            raise ValueError('Positive integer update budget required')
        self.scaler = StandardScaler().fit(X, sample_weight=weights)
        transformed = self.scaler.transform(X)
        self.model = BudgetClassifier(**parameters)
        self.model.update_budget = updates
        self.model.batch_losses, self.model.batch_sizes = [], []
        self.calls = 0
        optimizer = None
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            while optimizer is None or optimizer.t < updates:
                self.calls += 1
                try:
                    self.model.partial_fit(transformed, y, classes=[0, 1], sample_weight=weights)
                except UserWarning as error:
                    if str(error) == 'Training interrupted by user.':
                        raise KeyboardInterrupt from error
                    raise
                except BudgetReached:
                    if self.model._optimizer.t != updates:
                        raise ValueError('Premature budget sentinel')
                if optimizer is not None and self.model._optimizer is not optimizer:
                    raise ValueError('Adam optimizer reset across calls')
                optimizer = self.model._optimizer
                if not all(np.isfinite(a).all() for a in
                           self.model.coefs_ + self.model.intercepts_ + optimizer.ms + optimizer.vs):
                    raise ValueError('Non-finite neural coefficients or Adam state')
        if optimizer.t != updates or len(self.model.batch_losses) != updates:
            raise ValueError('Effective Adam update count mismatch')
        return self

    def predict(self, X):
        return self.model.predict_proba(self.scaler.transform(X))[:, 1] if len(X) else np.empty(0)
