"""Tools for creating and running the model."""
from __future__ import print_function, division

import os

import numpy as np
from scipy import stats

from sklearn.ensemble import RandomForestClassifier
from sklearn.externals import joblib
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.cross_validation import train_test_split
from sklearn.grid_search import GridSearchCV
from sklearn.metrics import brier_score_loss
from sklearn.neighbors import KernelDensity
from sklearn.pipeline import Pipeline
from sklearn.utils.validation import NotFittedError

import preprocessing
import utilities

class WPModel(object):
    """The object that computes win probabilities.

    In addition to holding the model itself, it defines some columns names likely to be
    used in the model as parameters to allow other users to more easily figure out which
    columns go into the model.

    Parameters
    ----------
    home_score_colname : string (default="curr_home_score")
        The name of the column containing the current home score at the start of a play.
    away_score_colname : string (default="curr_away_score")
        The name of the column containing the current away score at the start of a play.
    quarter_colname : string (default="quarter")
        The name of the column containing the quarter the play took place in.
    time_colname : string (default="seconds_elapsed")
        The name of the column containing the time elapsed (in seconds) from the start
        of the quarter when the play began.
    down_colname : string (default="down")
        The name of the column containing the current down number, with zeros for plays like
        kickoffs and extra points.
    yards_to_go_colname : string (default="yards_to_go")
        The name of the column containing the number of yards to go in order to get a first down.
    offense_team_colname : string (default="offense_team")
        The name of the column containing the abbreviation for the team currently on offense.
    home_team_colname : string (default="home_team")
        The name of the column containing the abbreviation for the home team.
    offense_won_colname : string (default="offense_won")
        The name of the column containing whether or not the offense ended up winning the game.
    copy_data : boolean (default=``True``)
        Whether or not to copy data when fitting and applying the model. Running the model
        in-place (``copy_data=False``) will be faster and have a smaller memory footprint,
        but if not done carefully can lead to data integrity issues.

    Attributes
    ----------
    model : A Scikit-learn pipeline (or equivalent)
        The actual model used to compute WP. Upon initialization it will be set to
        a default model, but can be overridden by the user.
    training_seasons : A list of ints, or ``None`` (default=``None``)
        If the model was trained using data downloaded from nfldb, a list of the seasons
        used to train the model. If nfldb was **not** used, an empty list. If no model
        has been trained yet, ``None``.
    training_season_types : A list of strings or ``None`` (default=``None``)
        Same as ``training_seasons``, except for the portions of the seasons used in training the
        model ("Preseason", "Regular", and/or "Postseason").
    validation_seasons : same as ``training_seasons``, but for validation data.
    validation_season_types : same as ``training_season_types``, but for validation data.
    sample_probabilities : A numpy array of floats or ``None`` (default=``None``)
        After the model has been validated, contains the sampled predicted probabilities used to
        compute the validation statistic.
    predicted_win_percents : A numpy array of floats or ``None`` (default=``None``)
        After the model has been validated, contains the actual probabilities in the test
        set at each probability in ``sample_probabilities``.
    num_plays_used : A numpy array of floats or ``None`` (default=``None``)
        After the model has been validated, contains the number of plays used to compute each
        element of ``predicted_win_percents``.
    model_directory : string
        The directory where all models will be saved to or loaded from.

    """
    model_directory = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
    _default_model_filename = "default_model.nflwin"

    def __init__(self,
                 home_score_colname="curr_home_score",
                 away_score_colname="curr_away_score",
                 quarter_colname="quarter",
                 time_colname = "seconds_elapsed",
                 down_colname="down",
                 yards_to_go_colname="yards_to_go",
                 yardline_colname="yardline",
                 offense_team_colname="offense_team",
                 home_team_colname="home_team",
                 offense_won_colname="offense_won",
                 copy_data=True
                ):
        self.home_score_colname = home_score_colname
        self.away_score_colname = away_score_colname
        self.quarter_colname = quarter_colname
        self.time_colname = time_colname
        self.down_colname = down_colname
        self.yards_to_go_colname = yards_to_go_colname
        self.yardline_colname = yardline_colname
        self.offense_team_colname = offense_team_colname
        self.home_team_colname = home_team_colname
        self.offense_won_colname = offense_won_colname
        self.copy_data = copy_data

        self.model = self.create_default_pipeline()
        self._training_seasons = None
        self._training_season_types = None
        self._validation_seasons = None
        self._validation_season_types = None

        self._sample_probabilities = None
        self._predicted_win_percents = None
        self._num_plays_used = None


    @property
    def training_seasons(self):
        return self._training_seasons
    @property
    def training_seasons_types(self):
        return self._training_season_types
    @property
    def validation_seasons(self):
        return self._validation_seasons
    @property
    def validation_seasons_types(self):
        return self._validation_season_types

    @property
    def sample_probabilities(self):
        return self._sample_probabilities
    @property
    def predicted_win_percents(self):
        return self._predicted_win_percents
    @property
    def num_plays_used(self):
        return self._num_plays_used

    def train_model(self,
                    source_data="nfldb",
                    training_seasons=[2009, 2010, 2011, 2012, 2013, 2014],
                    training_season_types=["Regular", "Postseason"]):
        """Train the model.

        Once a modeling pipeline is set up (either the default or something
        custom-generated), historical data needs to be fed into it in order to
        "fit" the model so that it can then be used to predict future results.
        This method implements a simple wrapper around the core Scikit-learn functionality
        which does this.

        The default is to use data from the nfldb database, however that can be changed
        to a simple Pandas DataFrame if desired (for instance if you wish to use data
        from another source).

        There is no particular output from this function, rather the parameters governing
        the fit of the model are saved inside the model object itself. If you want to get an
        estimate of the quality of the fit, use the ``validate_model`` method after running
        this method.

        Notes
        -----
        If you are loading in the default model, **there is no need to re-run this method**.
        In fact, doing so will likely result in weird errors and could corrupt the model if you
        were to try to save it back to disk.

        Parameters
        ----------
        source_data : the string ``"nfldb"`` or a Pandas DataFrame (default=``"nfldb"``)
            The data to be used to train the model. If ``"nfldb"``, will query the nfldb
            database for the training data (note that this requires a correctly configured
            installation of nfldb's database).
        training_seasons : list of ints (default=``[2009, 2010, 2011, 2012, 2013, 2014]``)
            What seasons to use to train the model if getting data from the nfldb database.
            If ``source_data`` is not ``"nfldb"``, this argument will be ignored.
            **NOTE:** it is critical not to use all possible data in order to train the
            model - some will need to be reserved for a final validation (see the
            ``validate_model`` method). A good dataset to reserve
            for validation is the most recent one or two NFL seasons.
        training_season_types : list of strings (default=``["Regular", "Postseason"]``)
            If querying from the nfldb database, what parts of the seasons to use.
            Options are "Preseason", "Regular", and "Postseason". If ``source_data`` is not
            ``"nfldb"``, this argument will be ignored.

        Returns
        -------
        ``None``
        """
        self._training_seasons = []
        self._training_season_types = []
        if source_data == "nfldb":
            source_data = utilities.get_nfldb_play_data(season_years=training_seasons,
                                                        season_types=training_season_types)
            self._training_seasons = training_seasons
            self._training_season_types = training_season_types
        target_col = source_data[self.offense_won_colname]
        feature_cols = source_data.drop(self.offense_won_colname, axis=1)
        self.model.fit(feature_cols, target_col)

    def validate_model(self,
                       source_data="nfldb",
                       validation_seasons=[2015],
                       validation_season_types=["Regular", "Postseason"]):
        """Validate the model.

        Once a modeling pipeline is trained, a different dataset must be fed into the trained model
        to validate the quality of the fit.
        This method implements a simple wrapper around the core Scikit-learn functionality
        which does this.

        The default is to use data from the nfldb database, however that can be changed
        to a simple Pandas DataFrame if desired (for instance if you wish to use data
        from another source).

        The output of this method is a p value which represents the confidence at which
        we can reject the null hypothesis that the model predicts the appropriate win
        probabilities. This number is computed by first smoothing the predicted win probabilities of both all test data and
        just the data where the offense won with a gaussian `kernel density
        estimate <http://scikit-learn.org/stable/modules/generated/sklearn.neighbors.KernelDensity.html#sklearn.neighbors.KernelDensity>`_
        with standard deviation = 0.01. Once the data is smooth, ratios at each percentage point from 1% to 99% are computed (i.e.
        what fraction of the time did the offense win when the model says they have a 1% chance of winning, 2% chance, etc.). Each of
        these ratios should be well approximated by the binomial distribution, since they are essentially independent (not perfectly
        but hopefully close enough) weighted coin flips, giving a p value. From there `Fisher's method <https://en.wikipedia.org/wiki/Fisher%27s_method>`_
        is used to combine the p values into a global p value. A p value close to zero means that the model is unlikely to be
        properly predicting the correct win probabilities. A p value close to one, **while not proof that the model is correct**,
        means that the model is at least not inconsistent with the hypothesis that it predicts good win probabilities.

        Parameters
        ----------
        source_data : the string ``"nfldb"`` or a Pandas DataFrame (default=``"nfldb"``)
            The data to be used to train the model. If ``"nfldb"``, will query the nfldb
            database for the training data (note that this requires a correctly configured
            installation of nfldb's database).
        training_seasons : list of ints (default=``[2015]``)
            What seasons to use to validate the model if getting data from the nfldb database.
            If ``source_data`` is not ``"nfldb"``, this argument will be ignored.
            **NOTE:** it is critical not to use the same data to validate the model as was used
            in the fit. Generally a good data set to use for validation is one from a time
            period more recent than was used to train the model. For instance, if the model was trained
            on data from 2009-2014, data from the 2015 season would be a sensible choice to validate the model.
        training_season_types : list of strings (default=``["Regular", "Postseason"]``)
            If querying from the nfldb database, what parts of the seasons to use.
            Options are "Preseason", "Regular", and "Postseason". If ``source_data`` is not
            ``"nfldb"``, this argument will be ignored.

        Returns
        -------
        float, between 0 and 1
            The combined p value, where smaller values indicate that the model is not accurately predicting win
            probabilities.
            
        Raises
        ------
        NotFittedError
            If the model hasn't been fit.

        Notes
        -----
        Probabilities are computed between 1 and 99 percent because a single incorrect prediction at 100% or 0% automatically drives
        the global p value to zero. Since the model is being smoothed this situation can occur even when there are no model predictions
        at those extreme values, and therefore leads to erroneous p values.

        While it seems reasonable (to me at least), I am not totally certain that this approach is entirely correct.
        It's certainly sub-optimal in that you would ideally reject the null hypothesis that the model predictions
        **aren't** appropriate, but that seems to be a much harder problem (and one that would need much more test
        data to beat down the uncertainties involved). I'm also not sure if using Fisher's method is appropriate here,
        and I wonder if it might be necessary to Monte Carlo this. I would welcome input from others on better ways to do this.
        
        """

        if self.training_seasons is None:
            raise NotFittedError("Must fit model before validating.")
        
        self._validation_seasons = []
        self._validation_season_types = []
        if source_data == "nfldb":
            source_data = utilities.get_nfldb_play_data(season_years=validation_seasons,
                                                        season_types=validation_season_types)
            self._validation_seasons = validation_seasons
            self._validation_season_types = validation_season_types
            
        target_col = source_data[self.offense_won_colname]
        feature_cols = source_data.drop(self.offense_won_colname, axis=1)
        predicted_probabilities = self.model.predict_proba(feature_cols)[:,1]

        self._sample_probabilities, self._predicted_win_percents, self._num_plays_used = (
            WPModel._compute_predicted_percentages(target_col.values, predicted_probabilities))

        #Compute p-values for each where null hypothesis is that distributions are same, then combine
        #them all to make sure data is not inconsistent with accurate predictions.
        combined_pvalue = self._test_distribution(self.sample_probabilities,
                                                  self.predicted_win_percents,
                                                  self.num_plays_used)
        
        return combined_pvalue

    def predict_wp(self, plays):
        """Estimate the win probability for a set of plays.

        Basically a simple wrapper around ``WPModel.model.predict_proba``,
        takes in a DataFrame and then spits out an array of predicted
        win probabilities.

        Parameters
        ----------
        plays : Pandas DataFrame
            The input data to use to make the predictions.

        Returns
        -------
        Numpy array, of length ``len(plays)``
            Predicted probability that the offensive team in each play
            will go on to win the game.

        Raises
        ------
        NotFittedError
            If the model hasn't been fit.
        """
        if self.training_seasons is None:
            raise NotFittedError("Must fit model before predicting WP.")

        return self.model.predict_proba(plays)[:,1]


    def plot_validation(self, axis=None, **kwargs):
        """Plot the validation data.

        Parameters
        ----------
        axis : matplotlib.pyplot.axis object or ``None`` (default=``None``)
            If provided, the validation line will be overlaid on ``axis``.
            Otherwise, a new figure and axis will be generated and plotted on.
        **kwargs
            Arguments to ``axis.plot``.

        Returns
        -------
        matplotlib.pylot.axis
            The axis the plot was made on.

        Raises
        ------
        NotFittedError
            If the model hasn't been fit **and** validated.
        """

        if self.sample_probabilities is None:
            raise NotFittedError("Must validate model before plotting.")
        
        import matplotlib.pyplot as plt
        if axis is None:
            axis = plt.figure().add_subplot(111)
            axis.plot([0, 1], [0, 1], ls="--", lw=2, color="black")
            axis.set_xlabel("Predicted WP")
            axis.set_ylabel("Actual WP")
        axis.plot(self.sample_probabilities,
                  self.predicted_win_percents,
                  **kwargs)

        return axis
            

    @staticmethod
    def _test_distribution(sample_probabilities, predicted_win_percents, num_plays_used):
        """Based off assuming the data at each probability is a Bernoulli distribution."""

        #Get the p-values:
        p_values = [stats.binom_test(np.round(predicted_win_percents[i] * num_plays_used[i]),
                                     np.round(num_plays_used[i]),
                                     p=sample_probabilities[i]) for i in range(len(sample_probabilities))]
        combined_p_value = stats.combine_pvalues(p_values)[1]
        return(combined_p_value)

    @staticmethod
    def _compute_predicted_percentages(actual_results, predicted_win_probabilities):
        """Compute the sample percentages from a validation data set.
        """
        kde_offense_won = KernelDensity(kernel='gaussian', bandwidth=0.01).fit(
            (predicted_win_probabilities[(actual_results == 1)])[:, np.newaxis])
        kde_total = KernelDensity(kernel='gaussian', bandwidth=0.01).fit(
            predicted_win_probabilities[:, np.newaxis])
        sample_probabilities = np.linspace(0.01, 0.99, 99)
        number_density_offense_won = np.exp(kde_offense_won.score_samples(sample_probabilities[:, np.newaxis])) * np.sum((actual_results))
        number_density_total = np.exp(kde_total.score_samples(sample_probabilities[:, np.newaxis])) * len(actual_results)
        number_offense_won = number_density_offense_won * np.sum(actual_results) / np.sum(number_density_offense_won)
        number_total = number_density_total * len(actual_results) / np.sum(number_density_total)
        predicted_win_percents = number_offense_won / number_total

        return sample_probabilities, predicted_win_percents, number_total
    
    def create_default_pipeline(self):
        """Create the default win probability estimation pipeline.


        Returns
        -------
        Scikit-learn pipeline
            The default pipeline, suitable for computing win probabilities
            but by no means the best possible model.

        This can be run any time a new default pipeline is required,
        and either set to the ``model`` attribute or used independently.
        """

        steps = []

        is_offense_home = preprocessing.ComputeIfOffenseIsHome(self.offense_team_colname,
                                                               self.home_team_colname,
                                                               copy=self.copy_data)
        steps.append(("compute_offense_home", is_offense_home))
        score_differential = preprocessing.CreateScoreDifferential(self.home_score_colname,
                                                                   self.away_score_colname,
                                                                   is_offense_home.offense_home_team_colname,
                                                                   copy=self.copy_data)
        steps.append(("create_score_differential", score_differential))
        steps.append(("map_downs_to_int", preprocessing.MapToInt(self.down_colname, copy=self.copy_data)))
        total_time_elapsed = preprocessing.ComputeElapsedTime(self.quarter_colname, self.time_colname, copy=self.copy_data)
        steps.append(("compute_total_time_elapsed", total_time_elapsed))
        steps.append(("remove_unnecessary_columns", preprocessing.CheckColumnNames(
            column_names=[is_offense_home.offense_home_team_colname,
                          score_differential.score_differential_colname,
                          total_time_elapsed.total_time_colname,
                          self.yardline_colname,
                          self.yards_to_go_colname,
                          self.down_colname],
            copy=self.copy_data)))
        steps.append(("encode_categorical_columns", preprocessing.OneHotEncoderFromDataFrame(
            categorical_feature_names=[self.down_colname],
            copy=self.copy_data)))

        search_grid = {'base_estimator__penalty': ['l1', 'l2'],
                       'base_estimator__C': [0.01, 0.1, 1, 10, 100]
                      }
        base_model = LogisticRegression()
        calibrated_model = CalibratedClassifierCV(base_model, cv=2, method="isotonic")
        grid_search_model = GridSearchCV(calibrated_model, search_grid,
                             scoring=self._brier_loss_scorer)
        #steps.append(("compute_model", grid_search_model))
        steps.append(("compute_model", calibrated_model))

        pipe = Pipeline(steps)
        return pipe

    def save_model(self, filename=None):
        """Save the WPModel instance to disk.

        All models are saved to the same place, with the installed
        NFLWin library (given by ``WPModel.model_directory``). 

        Parameters
        ----------
        filename : string (default=None):
            The filename to use for the saved model. If this parameter
            is not specified, save to the default filename. Note that if a model
            already lists with this filename, it will be overwritten. Note also that
            this is a filename only, **not** a full path. If a full path is specified
            it is likely (albeit not guaranteed) to cause errors.

        Returns
        -------
        ``None``
        """

        if filename is None:
            filename = self._default_model_filename
        joblib.dump(self, os.path.join(self.model_directory, filename))

    @classmethod
    def load_model(cls, filename=None):
        """Load a saved WPModel.

        Parameters
        ----------
        Same as ``save_model``.

        Returns
        -------
        ``nflwin.WPModel`` instance.
        """
        if filename is None:
            filename = cls._default_model_filename
            
        return joblib.load(os.path.join(cls.model_directory, filename))

    @staticmethod
    def _brier_loss_scorer(estimator, X, y):
        """Use the Brier loss to estimate model score.

        For use in GridSearchCV, instead of accuracy.
        """
        predicted_positive_probabilities = estimator.predict_proba(X)[:, 1]
        return 1. - brier_score_loss(y, predicted_positive_probabilities)


if __name__ == "__main__":
    import time
    start = time.time()
    win_probability_model = WPModel()
    win_probability_model.train_model(training_seasons=[2009, 2010, 2011, 2012, 2013])
    print("Took {0:.2f}s to build model".format(time.time() - start))
    start = time.time()
    combined_pvalue = win_probability_model.validate_model(validation_seasons=[2014])
    print("Took {0:.2f}s to validate model, with combined p_value of {1:.2f}".format(time.time() - start, combined_pvalue))

    test_data = utilities.get_nfldb_play_data(season_years=[2015])
    win_probability_model.predict_wp(test_data)
    
    import matplotlib.pyplot as plt
    plt.style.use('ggplot')
    ax = win_probability_model.plot_validation(ls="-", color="blue", label="p value = {0:.2f}".format(combined_pvalue))
    ax.legend(loc="lower right")
    ax.figure.savefig("test.png")

    # kde_offense_won = KernelDensity(kernel='gaussian', bandwidth=0.01).fit(
    #     (predicted_win_probabilities[(target_col_test.values == 1)])[:, np.newaxis])
    # kde_total = KernelDensity(kernel='gaussian', bandwidth=0.01).fit(
    #     predicted_win_probabilities[:, np.newaxis])
    # sample_probabilities = np.linspace(0, 1, 101)[:, np.newaxis]
    # number_density_offense_won = np.exp(kde_offense_won.score_samples(sample_probabilities)) * np.sum((target_col_test))
    # number_density_total = np.exp(kde_total.score_samples(sample_probabilities)) * len(target_col_test)
    # number_offense_won = number_density_offense_won * np.sum(target_col_test) / np.sum(number_density_offense_won)
    # number_total = number_density_total * len(target_col_test) / np.sum(number_density_total)
    # predicted_win_percents = number_offense_won / number_total
    # from statsmodels.stats.proportion import proportion_confint
    # win_pct_errors = np.array([proportion_confint(sample_probabilities[i,0]*number_total[i], number_total[i], method="jeffrey", alpha=0.333) for i in range(len(number_total))])
    # max_deviation = np.max(np.abs(predicted_win_percents - sample_probabilities[:, 0]))
    # print("Max deviation: {0:.2f}%".format(max_deviation * 100))
    
    # import matplotlib.pyplot as plt
    # plt.style.use('ggplot')
    # ax = plt.figure().add_subplot(111)
    # ax.plot([0, 1], [0, 1], ls="--", lw=2, color="black")
    # ax.fill_between(sample_probabilities[:, 0],
    #                 win_pct_errors[:,0],
    #                 win_pct_errors[:,1],
    #                 facecolor="blue", alpha=0.25)
    # ax.plot(sample_probabilities[:, 0], predicted_win_percents, ls="-", color="blue",
    #         label="Max Deviation = {0:.2f}%".format(max_deviation * 100))
    # ax.set_xlabel("Predicted WP")
    # ax.set_ylabel("Actual WP")
    # ax.legend(loc="lower right")
    # ax2 = ax.twinx()
    # ax2.fill_between(sample_probabilities[:, 0], number_total,
    #                  facecolor="gray", alpha=0.25, interpolate=True)
    # ax2.set_ylabel("Number of Plays in Test Set")
    # ax.figure.savefig("test.png")
