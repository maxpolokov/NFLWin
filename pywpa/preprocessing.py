"""Tools to get raw data ready for modeling."""
from __future__ import print_function, division

import numpy as np
import pandas as pd

from sklearn.base import BaseEstimator
from sklearn.preprocessing import OneHotEncoder
from sklearn.utils.validation import NotFittedError

class OneHotEncoderFromDataFrame(BaseEstimator):
    """One-hot encode a DataFrame.

    This cleaner wraps the standard scikit-learn OneHotEncoder,
    handling the transfer between column name and column index.

    Parameters
    ----------
    categorical_feature_names : "all" or array of column names.
        Specify what features are treated as categorical.
        * "all" (default): All features are treated as categorical.
        * array of column names: Array of categorical feature names.
    dtype : number type, default=np.float.
        Desired dtype of output.
    handle_unknown : str, "error" (default) or "ignore".
        Whether to raise an error or ignore if an unknown categorical feature
        is present during transform.
    copy : boolean (default=True)
        If ``False``, apply the encoding in-place.
    """

    @property
    def dtype(self):
        return self._dtype
    @dtype.setter
    def dtype(self, dtype):
        self._dtype = dtype
        self.onehot.dtype = self._dtype

    @property
    def handle_unknown(self):
        return self._handle_unknown
    @handle_unknown.setter
    def handle_unknown(self, handle_unknown):
        self._handle_unknown = handle_unknown
        self.onehot.handle_unknown = self._handle_unknown
        
    def __init__(self,
                 categorical_feature_names="all",
                 dtype=np.float,
                 handle_unknown="error",
                 copy=True):
        self.onehot = OneHotEncoder(sparse=False, n_values="auto",
                                    categorical_features="all") #We'll subset the DF
        self.categorical_feature_names = categorical_feature_names
        self.dtype = dtype
        self.handle_unknown = handle_unknown
        self.copy = copy

    def fit(self, X, y=None):
        """Convert the column names to indices, then compute the one hot encoding.

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

        if self.categorical_feature_names == "all":
            self.categorical_feature_names = X.columns

        #Get all columns that need to be encoded:
        data_to_encode = X[self.categorical_feature_names]
            

        self.onehot.fit(data_to_encode)

        return self

    def transform(self, X, y=None):
        if self.copy:
            X = X.copy()
        
        data_to_transform = X[self.categorical_feature_names]
        transformed_data = self.onehot.transform(data_to_transform)

        #TODO (AndrewRook): Find good column names for the encoded columns.
        colnames = ["onehot_col{0}".format(i+1) for i in range(transformed_data.shape[1])]
        transformed_df = pd.DataFrame(transformed_data, columns=colnames)
        
        X.drop(self.categorical_feature_names, axis=1, inplace=True)

        return pd.concat([X, transformed_df], axis=1)
            
    

class CreateScoreDifferential(BaseEstimator):
    """Convert home and away scores into a differential (home - away).

    Parameters
    ----------
    home_score_colname : string
        The name of the column containing the score of the home team.
    away_score_colname : string
        The name of the column containing the score of the away team.
    score_differential_colname : string (default=``"score_differential"``)
        The name of column containing the score differential. Must not already
        exist in the DataFrame.
    copy : boolean (default = ``True``)
        If ``False``, add the score differential in place.
    """
    def __init__(self, home_score_colname,
                 away_score_colname,
                 score_differential_colname="score_differential",
                 copy=True):
        self.home_score_colname = home_score_colname
        self.away_score_colname = away_score_colname
        self.score_differential_colname = score_differential_colname
        self.copy = copy

    def fit(self, X, y=None):
        return self

    def transform(self, X, y=None):
        """Create the score differential column.

        Parameters
        ----------
        X : Pandas DataFrame, of shape(number of plays, number of features)
            NFL play data.
        y : Numpy array, with length = number of plays, or None
            1 if the home team won, 0 if not.
            (Used as part of Scikit-learn's ``Pipeline``)

        Returns
        -------
        X : Pandas DataFrame, of shape(number of plays, number of features + 1)
            The input DataFrame, with the score differential column added.
        """
        try:
            score_differential = X[self.home_score_colname] - X[self.away_score_colname]
        except KeyError:
            raise KeyError("CreateScoreDifferential: data missing required column. Must "
                           "include columns named {0} and {1}".format(self.home_score_colname,
                                                                      self.away_score_colname))
        if self.score_differential_colname in X.columns:
            raise KeyError("CreateScoreDifferential: column {0} already in DataFrame, and can't "
                           "be used for the score differential".format(self.score_differential_colname))
        if self.copy:
            X = X.copy()

        X[self.score_differential_colname] = score_differential

        return X
        


class CheckColumnNames(BaseEstimator):
    """Make sure user has the right column names, in the right order.

    This is a useful first step to make sure that nothing
    is going to break downstream.

    Attributes
    ----------
    column_names : list of strings
        A list of column names that need to be present in the scoring
        data. All other columns will be stripped out. The order of the
        columns will be applied to any scoring
        data as well, in order to handle the fact that pandas lets
        you play fast and loose with column order.
    """
    def __init__(self):
        self.column_names = None
        self._fit = False

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
        try:
            return X[self.column_names]
        except KeyError:
            raise KeyError("CheckColumnName: DataFrame does not have required columns. "
                           "Must contain at least {0}".format(self.column_names))
        
if __name__ == "__main__":
    import pandas as pd
    input_df = pd.DataFrame({"one": [0, 1, 2, 1, 0],
                             "two": ["a", "b", "c", "d", "e"],
                             "three": [0.5, 1, 2.5, 4, 10],
                             "four": [10, 10, 10, 5, 1]})
    transform_df = pd.DataFrame({"one": [0, 1, 2, 1, 0],
                                 "two": ["a", "b", "c", "d", "e"],
                                 "three": [0.5, 1, 2.5, 4, 10],
                                 "four": [7, 2, 10, 5, 1]})

    onehot = OneHotEncoderFromDataFrame(categorical_feature_names = ["one","four"])
    onehot.fit(input_df)
    print(onehot.transform(input_df))
    print(onehot.transform(transform_df))
