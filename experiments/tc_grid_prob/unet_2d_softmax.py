# ---
# jupyter:
#   jupytext:
#     formats: py:light,ipynb
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.13.4
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %cd ../..

from datetime import datetime
from tc_formation.models import unet
from tc_formation import tf_metrics as tfm
from tc_formation.metrics.bb import BBoxesIoUMetric
import tc_formation.data.time_series as ts_data
from tc_formation.losses.hard_negative_mining import hard_negative_mining
import tensorflow as tf
import tensorflow.keras as keras
from tensorflow.keras.layers.experimental import preprocessing
import tensorflow_addons as tfa
import xarray as xr

# # Predict TC Formation using Grid Probability 2D Softmax

# Configurations to run for this experiment.

exp_name = 'tc_grid_prob_unet_2d_softmax'
runtime = datetime.now().strftime('%Y_%b_%d_%H_%M')
data_path = 'data/nolabels_wp_ep_alllevels_ABSV_CAPE_RH_TMP_HGT_VVEL_UGRD_VGRD_100_260/12h/tc_ibtracs_6h_12h_18h_24h_30h_36h_42h_48h.csv'
train_path = data_path.replace('.csv', '_train.csv')
val_path = data_path.replace('.csv', '_val.csv')
test_path = data_path.replace('.csv', '_test.csv')
# subset = dict(
#     absvprs=[900, 750],
#     rhprs=[750],
#     tmpprs=[900, 500],
#     hgtprs=[500],
#     vvelprs=[500],
#     ugrdprs=[800, 200],
#     vgrdprs=[800, 200],
#     #capesfc=None,
#     #tmpsfc=None,
# )
# data_shape = (41, 161, 13)
subset = dict(
    # absvprs=None, # [900, 750],
    # rhprs=None, # [750],
    # tmpprs=None, # [900, 500],
    hgtprs=None, # [500],
    # vvelprs=None, # [500],
    # ugrdprs=[800, 200],
    # vgrdprs=[800, 200],
    capesfc=None,
    tmpsfc=None,
)
data_shape = (41, 161, 114)
# subset = dict(
#     absvprs=[900, 800, 750, 500, 200],
#     rhprs=[900, 800, 750, 500, 200],
#     tmpprs=[900, 800, 750, 500, 200],
#     hgtprs=[900, 800, 750, 500, 200],
#     vvelprs=[900, 800, 750, 500, 200],
#     ugrdprs=[900, 800, 750, 500, 200],
#     vgrdprs=[900, 800, 750, 500, 200],
# )
# data_shape = (41, 161, 37)
# subset = None
# data_shape = (41, 161, 135)

# Create U-Net model with normalization layer.

# +
input_layer = keras.Input(data_shape)
normalization_layer = preprocessing.Normalization()
model = unet.Unet(
    input_tensor=normalization_layer(input_layer),
    model_name='unet',
    classifier_activation=None,
    output_classes=1,
    decoder_shortcut_mode='add',
    filters_block=[64, 128, 256, 512, 1024])

outputs = model.outputs

# Make outputs become probability distribution using Softmax.
nominator = tf.squeeze(tf.exp(outputs), axis=0)
denominator = tf.reduce_sum(nominator, axis=[1, 2, 3], keepdims=True)
outputs = nominator / denominator

# Make final model.
model = keras.Model(inputs=model.inputs, outputs=outputs)
model.summary()
# -

# Then, we load the training and validation dataset.

tc_avg_radius_lat_deg = 3
data_loader = ts_data.TropicalCycloneWithGridProbabilityDataLoader(
    data_shape=data_shape,
    tc_avg_radius_lat_deg=tc_avg_radius_lat_deg,
    subset=subset,
    softmax_output=False,
    smooth_gt=True,
)
training = data_loader.load_dataset(
    train_path,
    batch_size=128,
    leadtimes=12,
    shuffle=True)
validation = data_loader.load_dataset(val_path, leadtimes=12, batch_size=128)

# After that, we will initialize the normalization layer,
# and compile the model.

features = training.map(lambda feature, _: feature)
normalization_layer.adapt(features)


# +
@hard_negative_mining
def hard_negative_mined_sigmoid_focal_loss(y_true, y_pred):
    fl = tfa.losses.SigmoidFocalCrossEntropy()
    return fl(y_true, y_pred)

@hard_negative_mining
def hard_negative_mined_binary_crossentropy_loss(y_true, y_pred):
    l = tf.keras.losses.BinaryCrossentropy(reduction=tf.keras.losses.Reduction.NONE)
    return l(y_true, y_pred)

def dice_loss(y_true, y_pred):
    y_true = tf.cast(y_true, tf.float32)
    # y_pred = tf.math.sigmoid(y_pred)
    numerator = 2 * tf.reduce_sum(y_true * y_pred)
    denominator = tf.reduce_sum(y_true + y_pred)

    return 1 - numerator / denominator

def combine_loss_funcs(*fns):
    def combined_loss(y_true, y_pred):
        return sum(f(y_true, y_pred) for f in fns)
    
    return combined_loss

model.compile(
    optimizer='adam',
    # loss=tf.keras.losses.BinaryCrossentropy(from_logits=True),
    # loss=combine_loss_funcs(hard_negative_mined_sigmoid_focal_loss, dice_loss),
    # loss=dice_loss,
    loss=tf.losses.KLDivergence(),
    # loss=hard_negative_mined_sigmoid_focal_loss,
    # loss=hard_negative_mined_binary_crossentropy_loss,
    metrics=[
        #'binary_accuracy',
        #keras.metrics.Recall(name='recall', class_id=1 if use_softmax else None),
        #keras.metrics.Precision(name='precision', class_id=1 if use_softmax else None),
        #tfm.CustomF1Score(name='f1', class_id=1 if use_softmax else None),
        #BBoxesIoUMetric(name='IoU', iou_threshold=0.2),
        #tfa.metrics.F1Score(num_classes=1, threshold=0.5),
        #tfm.PrecisionScore(from_logits=True),
        #tfm.F1Score(num_classes=1, from_logits=True, threshold=0.5),
    ])
# -

# Finally, we can train the model!

epochs = 150
model.fit(
    training,
    epochs=epochs,
    validation_data=validation,
    shuffle=True,
    callbacks=[
        keras.callbacks.TensorBoard(
            log_dir=f'outputs/{exp_name}_{runtime}_1st_board',
        ),
        keras.callbacks.EarlyStopping(
            monitor='val_loss',
            mode='min',
            verbose=1,
            patience=50,
            restore_best_weights=True
        ),
    ]
)

for leadtime in [12]: # [6, 12, 18, 24, 30, 36, 42, 48]:
    testing = data_loader.load_dataset(
        test_path,
        leadtimes=leadtime,
        batch_size=128
    )
    print(f'\n**** LEAD TIME: {leadtime}')
    model.evaluate(testing)

# # Some Predictions

# +
import matplotlib.pyplot as plt # noqa
from mpl_toolkits.basemap import Basemap # noqa
import numpy as np # noqa
import pandas as pd # noqa
from tc_formation.data.data import load_observation_data_with_tc_probability # noqa
from tc_formation.plots import decorators, observations as plt_obs # noqa

@decorators._with_axes
@decorators._with_basemap
def plot_tc_occurence_prob(
        dataset: xr.Dataset,
        prob: np.ndarray,
        basemap: Basemap = None,
        *args, **kwargs):
    lats, longs = np.meshgrid(dataset['lon'], dataset['lat'])
    cs = basemap.contourf(lats, longs, prob, cmap='OrRd')
    basemap.colorbar(cs, "right", size="5%", pad="2%")

def plot_groundtruth_and_prediction(tc_df):
    for _, row in tc_df.iterrows():
        print("=====\n=====\n====\n")
        
        dataset = xr.open_dataset(row['Path'])
        data, groundtruth = data_loader.load_single_data(row)

        prediction = model.predict([data])[0]
        
        fig, ax = plt.subplots(nrows=2, figsize=(30, 18))
        plot_tc_occurence_prob(dataset=dataset, prob=np.squeeze(groundtruth), ax=ax[0])
        plt_obs.plot_wind(dataset=dataset, pressure_level=800, skip=4, ax=ax[0])
        ax[0].set_title('Groundtruth')

        plot_tc_occurence_prob(dataset=dataset, prob=np.squeeze(prediction), ax=ax[1])
        plt_obs.plot_wind(dataset=dataset, pressure_level=800, skip=4, ax=ax[1])
        ax[1].set_title('Prediction')
        
        if row['TC']:
            title = f"""Prediction on date {row['Date']}
                        for tropical cyclone appearing on {row['First Observed']}"""
        else:
            title = f"Prediction on date {row['Date']}"
        fig.suptitle(title)
        fig.tight_layout()
        display(fig)
        plt.close(fig)


# -

# ## Train with TC

train_df = pd.read_csv(train_path)
train_with_tc_df = train_df[train_df['TC']].sample(5)
plot_groundtruth_and_prediction(train_with_tc_df)

# ## With TC

test_df = pd.read_csv(test_path)
test_with_tc_df = test_df[test_df['TC']].sample(5)
plot_groundtruth_and_prediction(test_with_tc_df)

# ## Without TC

test_without_tc_df = test_df[~test_df['TC']].sample(5)
plot_groundtruth_and_prediction(test_without_tc_df)
