"""Tools to get raw data ready for modeling."""
from __future__ import print_function, division

import numpy as np
import pandas as pd
import patsy

from sklearn import metrics
from sklearn.base import BaseEstimator
from sklearn.model_selection import train_test_split
from sklearn.utils.validation import NotFittedError


class CalculateDerivedVariable(BaseEstimator):

    def __init__(self, new_colname, formula):
        self.new_colname = new_colname
        self.formula = formula

    def fit(self, X, y=None):
        return self

    def transform(self, X, y=None):
        dm = patsy.dmatrix(
            "I({0}) - 1".format(self.formula), X
        )
        X[self.new_colname] = np.asarray(dm)[:, -1]
        return X


class DataFrameToNumpy(BaseEstimator):

    def __init__(self, dtype=np.float):
        self.dtype = dtype

    def fit(self, X, y=None):
        self.columns_ = X.columns
        return self

    def transform(self, X, y=None):
        X_np = X[self.columns_].values.astype(self.dtype)
        return X_np


class OneHotEncode(BaseEstimator):
    def __init__(self, colname):
        self.colname = colname

    def fit(self, X, y=None):
        self.unique_values_ = X[self.colname].unique()
        return self

    def transform(self, X, y=None):
        # Encode variables
        dummy_variables = pd.get_dummies(
            X, prefix=self.colname, prefix_sep="_"
        )
        unique_colnames_with_prefix = [
            "{0}{1}{2}".format(self.colname, "_", column)
            for column in self.unique_values_
        ]
        # Confirm that none of the encoded variables are previously unseen:
        if not set(dummy_variables.columns).issubset(set(unique_colnames_with_prefix)):
            raise KeyError(
                "One or more variable {0} not in fitted column ({1})".format(
                    dummy_variables.columns, unique_colnames_with_prefix
                )
            )
        # Reindex the dummy dataframe to have all columns in it:
        dummy_variables = dummy_variables.reindex(
            columns=unique_colnames_with_prefix, fill_value=0
        )

        # Drop the last column because it's superfluous:
        dummy_variables.drop(
            unique_colnames_with_prefix[-1], axis=1, inplace=True
        )

        # Add dummy columns to dataframe
        X[dummy_variables.columns] = dummy_variables
        return X


class GenerateFeatures(BaseEstimator):
    def _init__(self, linear_model, tree_model, n_iters):
        self.linear_model = linear_model
        self.tree_model = tree_model
        self.n_iters = n_iters

    def _add_features(self, *datasets):
        added_columns_data = []
        for dataset in datasets:
            extra_columns = np.zeros([dataset.shape[0], len(self.added_features_)])
            for i, feature_info in enumerate(self.added_features_):
                

    def fit(self, X, y):
        train_X, test_X, train_y, test_y = train_test_split(X, y)
        self.train_performance_ = []
        self.test_performance_ = []
        self.added_features_ = set()
        for i in range(self.n_iters):
            derived_added_train_X, derived_added_test_X = self._add_features(
                train_X, test_X
            )
            train_predictions, train_roc_auc, test_roc_auc = self._fit_linear_model(
                train_X, test_X, train_y, test_y
            )
            self.train_performance_.append(train_roc_auc)
            self.test_performance_.append(test_roc_auc)
            residuals = (
                train_predictions - train_y
            ) / np.sqrt(train_predictions * (1 - train_predictions))

            self.tree_model.fit(train_X, residuals)
            best_features, best_thresholds, best_directions = self._get_best_path(
                self.tree_model.tree_
            )
            self.added_features_.add(
                tuple(zip(best_features, best_directions, best_thresholds))
            )

    def _fit_linear_model(self, train_X, test_X, train_y, test_y):
        self.linear_model.fit(train_X,  train_y)
        train_predictions = self.linear_model.predict_proba(train_X)
        test_predictions = self.linear_model.predict_proba(test_X)
        train_roc_auc = metrics.roc_auc_score(train_y, train_predictions)
        test_roc_auc = metrics.roc_auc_score(test_y, test_predictions)
        return train_predictions, train_roc_auc, test_roc_auc

    def _get_best_path(self, tree_obj):
        # identify the parent of each node
        parents = np.zeros(len(tree_obj.impurity), dtype=np.int) - 1
        for node in range(len(tree_obj.impurity)):
            if tree_obj.children_left[node] >= 0:
                parents[tree_obj.children_left[node]] = node
            if tree_obj.children_right[node] >= 0:
                parents[tree_obj.children_right[node]] = node

        # starting with the best node, work up the tree
        curr_node = tree_obj.impurity.argmin()
        parent_node = parents[curr_node]
        split_nodes = []
        split_directions = []
        while curr_node >= 0:
            split_nodes.append(parent_node)
            split_directions.append(
                "<="
                if tree_obj.children_left[parent_node] == curr_node
                else ">"
            )
            parent_node = parents[parent_node]
            curr_node = parents[curr_node]

        nodes = split_nodes[-2::-1]
        features = tree_obj.feature[nodes]
        thresholds = tree_obj.threshold[nodes]
        directions = split_directions[-2::-1]
        return features, thresholds, directions


    def _get_path_splits(self, path, directions, tree_obj):
        features = tree_obj.features[path]
        thresholds = tree_obj.thresholds[path]
        return zip(features, directions, thresholds)




class CheckColumnNames(BaseEstimator):
    """Make sure user has the right column names, in the right order.

    This is a useful first step to make sure that nothing
    is going to break downstream, but can also be used effectively
    to drop columns that are no longer necessary.

    Parameters
    ----------
    column_names : ``None``, or list of strings
        A list of column names that need to be present in the scoring
        data. All other columns will be stripped out. The order of the
        columns will be applied to any scoring
        data as well, in order to handle the fact that pandas lets
        you play fast and loose with column order. If ``None``,
        will obtain every column in the DataFrame passed to the
        ``fit`` method.
    copy : boolean (default=``True``)
        If ``False``, add the score differential in place.
       
    """
    def __init__(self, column_names=None, copy=True):
        self.column_names = column_names
        self.copy = copy
        self._fit = True
        self.user_specified_columns = False
        if self.column_names is None:
            self._fit = False
        else:
            self.user_specified_columns = True
            

    def fit(self, X, y=None):
        """Grab the column names from a Pandas DataFrame.

        Parameters
        ----------
        X : Pandas DataFrame, of shape(number of plays, number of features)
            NFL play data.
        y : Numpy array, with length = number of plays, or None
            1 if the home team won, 0 if not.
            (Used as part of Scikit-learn's ``Pipeline``)

        Returns
        -------
        self : For compatibility with Scikit-learn's ``Pipeline``. 
        """
        if not self.user_specified_columns:
            self.column_names = X.columns
            self._fit = True

        return self

    def transform(self, X, y=None):
        """Apply the column ordering to the data.

        Parameters
        ----------
        X : Pandas DataFrame, of shape(number of plays, number of features)
            NFL play data.
        y : Numpy array, with length = number of plays, or None
            1 if the home team won, 0 if not.
            (Used as part of Scikit-learn's ``Pipeline``)

        Returns
        -------
        X : Pandas DataFrame, of shape(number of plays, ``len(column_names)``)
            The input DataFrame, properly ordered and with extraneous
            columns dropped

        Raises
        ------
        KeyError
            If the input data frame doesn't have all the columns specified
            by ``column_names``.
        NotFittedError
            If ``transform`` is called before ``fit``.
        """
        if not self._fit:
            raise NotFittedError("CheckColumnName: Call 'fit' before 'transform")
        
        if self.copy:
            X = X.copy()

        try:
                
            return X[self.column_names]
        except KeyError:
            raise KeyError("CheckColumnName: DataFrame does not have required columns. "
                           "Must contain at least {0}".format(self.column_names))
