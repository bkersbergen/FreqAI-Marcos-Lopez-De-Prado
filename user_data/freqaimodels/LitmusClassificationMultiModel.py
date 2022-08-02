import logging
from typing import Any, Dict, Tuple

from catboost import CatBoostClassifier
from freqtrade.freqai.data_kitchen import FreqaiDataKitchen
from freqtrade.freqai.freqai_interface import IFreqaiModel
from pandas import DataFrame
# from sklearn.multioutput import MultiOutputClassifier

logger = logging.getLogger(__name__)


class LitmusClassificationMultiModel(IFreqaiModel):
    """
    User created prediction model. The class needs to override three necessary
    functions, predict(), train(), fit(). The class inherits ModelHandler which
    has its own DataHandler where data is held, saved, loaded, and managed.
    """

    def return_values(self, dataframe: DataFrame) -> DataFrame:
        """
        User uses this function to add any additional return values to the dataframe.
        e.g.
        dataframe['volatility'] = dk.volatility_values
        """

        return dataframe

    def train(
            self, unfiltered_dataframe: DataFrame, pair: str, dk: FreqaiDataKitchen
    ) -> Tuple[DataFrame, DataFrame]:
        """
        Filter the training data and train a model to it. Train makes heavy use of the datahkitchen
        for storing, saving, loading, and analyzing the data.
        :params:
        :unfiltered_dataframe: Full dataframe for the current training period
        :metadata: pair metadata from strategy.
        :returns:
        :model: Trained model which can be used to inference (self.predict)
        """

        logger.info("--------------------Starting training " f"{pair} --------------------")

        # unfiltered_labels = self.make_labels(unfiltered_dataframe, dk)
        # filter the features requested by user in the configuration file and elegantly handle NaNs
        features_filtered, labels_filtered = dk.filter_features(
            unfiltered_dataframe,
            dk.training_features_list,
            dk.label_list,
            training_filter=True,
        )

        # split data into train/test data.
        data_dictionary = dk.make_train_test_datasets(features_filtered, labels_filtered)

        data_dictionary = self.normalize_data(data_dictionary, dk)

        # optional additional data cleaning/analysis
        self.data_cleaning_train(dk)

        logger.info(
            f'Training model on {len(dk.data_dictionary["train_features"].columns)}' " features"
        )
        logger.info(f'Training model on {len(data_dictionary["train_features"])} data points')

        model = self.fit(data_dictionary)

        logger.info(f"--------------------done training {pair}--------------------")

        return model

    def fit(self, data_dictionary: Dict) -> Any:
        """
        User sets up the training and test data to fit their desired model here
        :params:
        :data_dictionary: the dictionary constructed by DataHandler to hold
        all the training and test data/labels.
        """

        """TODO
        - Add separate classifiers to be trained in parallel
        - Add feature selection
        - Add model performance diagnostics
        - """

        # Test on observations furthest in past
        X_test = data_dictionary["train_features"]
        y_test = data_dictionary["train_labels"]
        # Train on most recent observations
        X_train = data_dictionary["test_features"]
        y_train = data_dictionary["test_labels"]
        sample_weight = data_dictionary["test_weights"]

        # Define multi output classifier pipeline with feature selection
        """estimator = CatBoostClassifier(allow_writing_files=False, n_estimators=1000,
                                       verbose=2, task_type="CPU",
                                       early_stopping_rounds=10)
        mo_clf = MultiOutputClassifier(estimator, n_jobs=-1)"""

        clf = CatBoostClassifier(
            allow_writing_files=False,
            loss_function='MultiClass',
            early_stopping_rounds=10
        )
        clf.fit(X=X_train, y=y_train, sample_weight=sample_weight, eval_set=(X_test, y_test))

        """mo_clf.fit(X=X_train, Y=y_train, sample_weight=sample_weight,
                   eval_set=(X_test, y_test))"""

        return clf

    def predict(
            self, unfiltered_dataframe: DataFrame, dk: FreqaiDataKitchen, first: bool = False
    ) -> Tuple[DataFrame, DataFrame]:
        """
        Filter the prediction features data and predict with it.
        :param: unfiltered_dataframe: Full dataframe for the current backtest period.
        :return:
        :pred_df: dataframe containing the predictions
        :do_predict: np.array of 1s and 0s to indicate places where freqai needed to remove
        data (NaNs) or felt uncertain about data (PCA and DI index)
        """

        dk.find_features(unfiltered_dataframe)
        filtered_dataframe, _ = dk.filter_features(
            unfiltered_dataframe, dk.training_features_list, training_filter=False
        )
        filtered_dataframe = dk.normalize_data_from_metadata(filtered_dataframe)
        dk.data_dictionary["prediction_features"] = filtered_dataframe

        # optional additional data cleaning/analysis
        self.data_cleaning_predict(dk, filtered_dataframe)

        predictions = self.model.predict_proba(dk.data_dictionary["prediction_features"])

        pred_df = DataFrame(predictions, columns=self.model.classes_)
        print(pred_df)

        return (pred_df, dk.do_predict)

    def normalize_data(self, data_dictionary: Dict, dk) -> Dict[Any, Any]:
        """
        Normalize all data in the data_dictionary according to the training dataset
        :params:
        :data_dictionary: dictionary containing the cleaned and split training/test data/labels
        :returns:
        :data_dictionary: updated dictionary with standardized values.
        """
        # standardize the data by training stats
        train_max = data_dictionary["train_features"].max()
        train_min = data_dictionary["train_features"].min()
        data_dictionary["train_features"] = (
                2 * (data_dictionary["train_features"] - train_min) / (train_max - train_min) - 1
        )
        data_dictionary["test_features"] = (
                2 * (data_dictionary["test_features"] - train_min) / (train_max - train_min) - 1
        )

        for item in train_max.keys():
            dk.data[item + "_max"] = train_max[item]
            dk.data[item + "_min"] = train_min[item]

        return data_dictionary
