"""Tools for creating and running the model."""
from __future__ import print_function, division

import numpy as np

from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.cross_validation import train_test_split
from sklearn.grid_search import GridSearchCV
from sklearn.neighbors import KernelDensity
from sklearn.pipeline import Pipeline

import preprocessing
import utilities

class WPModel(object):
    """The object that computes win probabilities.


    """

    def __init__(self,
                 home_score_colname="curr_home_score",
                 away_score_colname="curr_away_score",
                 quarter_colname="quarter",
                 time_colname = "seconds_elapsed",
                 down_colname="down",
                 yards_to_go_colname="yards_to_go",
                 yardline_colname="yardline",
                 offense_team_colname="offense_team",
                 home_team_colname = "home_team",
                 copy=True,
                 model_class=LogisticRegression,
                 model_kwargs={},
                 parameter_search_grid=None):
        self.home_score_colname = home_score_colname
        self.away_score_colname = away_score_colname
        self.quarter_colname = quarter_colname
        self.time_colname = time_colname
        self.down_colname = down_colname
        self.yards_to_go_colname = yards_to_go_colname
        self.yardline_colname = yardline_colname
        self.offense_team_colname = offense_team_colname
        self.home_team_colname = home_team_colname
        self.copy = copy
        self.model_class = model_class
        self.model_kwargs = model_kwargs
        self.parameter_search_grid = parameter_search_grid

        self.model = self.create_pipeline()


    def create_pipeline(self):
        """Create the win probability estimation pipeline.


        Returns
        -------
        sklearn.pipeline.Pipeline
            A pipeline object containing all the steps in the model.
        """

        steps = []

        is_offense_home = preprocessing.ComputeIfOffenseIsHome(self.offense_team_colname,
                                                               self.home_team_colname,
                                                               copy=self.copy)
        steps.append(("compute_offense_home", is_offense_home))
        score_differential = preprocessing.CreateScoreDifferential(self.home_score_colname,
                                                                   self.away_score_colname,
                                                                   is_offense_home.offense_home_team_colname,
                                                                   copy=self.copy)
        steps.append(("create_score_differential", score_differential))
        steps.append(("map_downs_to_int", preprocessing.MapToInt(self.down_colname, copy=self.copy)))
        total_time_elapsed = preprocessing.ComputeElapsedTime(self.quarter_colname, self.time_colname, copy=self.copy)
        steps.append(("compute_total_time_elapsed", total_time_elapsed))
        steps.append(("remove_unnecessary_columns", preprocessing.CheckColumnNames(
            column_names=[is_offense_home.offense_home_team_colname,
                          score_differential.score_differential_colname,
                          total_time_elapsed.total_time_colname,
                          self.yardline_colname,
                          self.yards_to_go_colname,
                          self.down_colname],
            copy=self.copy)))
        steps.append(("encode_categorical_columns", preprocessing.OneHotEncoderFromDataFrame(
            categorical_feature_names=[self.down_colname],
            copy=self.copy)))

        learning_model = self.model_class(**self.model_kwargs)
        if self.parameter_search_grid is not None:
            model = GridSearchCV(learning_model, self.parameter_search_grid)
        else:
            model = learning_model
        model = CalibratedClassifierCV(model, cv=2, method="isotonic")
        steps.append(("compute_model", model))

        pipe = Pipeline(steps)
        return pipe


if __name__ == "__main__":
    import time
    start = time.time()
    play_df = utilities.get_nfldb_play_data(season_years=[2009, 2010, 2011, 2012, 2013, 2014])
    target_col = play_df["offense_won"]
    play_df.drop("offense_won", axis=1, inplace=True)
    play_df_train, play_df_test, target_col_train, target_col_test = (
       train_test_split(play_df, target_col, test_size=0.2, random_state=891))
    
    print("Took {0:.2f}s to query data".format(time.time() - start))
    start = time.time()
    win_probability_model = WPModel()#parameter_search_grid={'penalty': ['l1', 'l2'], 'C': [0.1, 1, 10, 100]})
    pipe = win_probability_model.model
    print("Took {0:.2f}s to create pipeline".format(time.time() - start))

    start = time.time()
    pipe.fit(play_df_train, target_col_train)
    print("Took {0:.2f}s to fit pipeline".format(time.time() - start))

    predicted_win_probabilities = pipe.predict_proba(play_df_test)[:,1]

    kde_offense_won = KernelDensity(kernel='gaussian', bandwidth=0.01).fit(
        (predicted_win_probabilities[(target_col_test.values == 1)])[:, np.newaxis])
    kde_total = KernelDensity(kernel='gaussian', bandwidth=0.01).fit(
        predicted_win_probabilities[:, np.newaxis])
    sample_probabilities = np.linspace(0, 1, 101)[:, np.newaxis]
    number_offense_won = np.exp(kde_offense_won.score_samples(sample_probabilities)) * np.sum((target_col_test))
    number_total = np.exp(kde_total.score_samples(sample_probabilities)) * len(target_col_test) #actually number density
    predicted_win_percents = number_offense_won / number_total
    max_deviation = np.max(np.abs(predicted_win_percents - sample_probabilities[:, 0]))
    print("Max deviation: {0:.2f}%".format(max_deviation * 100))
    print("DEBUG: ", len(target_col_test))
    
    import matplotlib.pyplot as plt
    ax = plt.figure().add_subplot(111)
    ax.plot([0, 1], [0, 1], ls="--", lw=2, color="black")
    ax.plot(sample_probabilities[:, 0], predicted_win_percents, ls="-", lw=3, color="green",
            label="Max Deviation = {0:.2f}%".format(max_deviation * 100))
    ax.set_xlabel("Predicted WP")
    ax.set_ylabel("Actual WP")
    ax.legend(loc="lower right")
    ax2 = ax.twinx()
    ax2.fill_between(sample_probabilities[:, 0], number_total,
                     facecolor="gray", alpha=0.25, interpolate=True)
    ax2.set_ylabel("Number of Plays")
    # ax.fill_between(sample_probabilities[:,0], number_total,
    #                 facecolor="blue", alpha=0.25, interpolate=True, label="all_probabilities")
    # ax.fill_between(sample_probabilities[:,0], number_offense_won,
    #                 facecolor="red", alpha=0.25, interpolate=True, label="offense_won")
    # ax.legend(loc="upper right")
    ax.figure.savefig("test.png")

    
    # for i in range(len(sample_probabilities)):
    #     print(sample_probabilities[i], predicted_win_percents[i])

    
    #pipe.transform(play_df[nrows:nrows+20])
    # start = time.time()
    # predicted_probabilities = pipe.predict_proba(play_df_test)[:, 0]
    # print("Took {0:.2f}s to make predictions".format(time.time() - start))
    # print(len(predicted_probabilities), predicted_probabilities.max())

    # pipe_sigmoid = CalibratedClassifierCV(pipe, cv=3, method='sigmoid')
    # pipe_sigmoid.fit(play_df_train, target_col_train)
    # predicted_probabilities_sigmoid = pipe_sigmoid.predict_proba(play_df_test)[:, 0]
    # print(len(predicted_probabilities), predicted_probabilities.max())
    # # for i in range(len(play_df)):
    #     print(play_df.ix[i], predictions[i])
