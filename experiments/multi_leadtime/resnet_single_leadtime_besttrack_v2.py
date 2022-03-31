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

# +
from tc_formation import plot
from tc_formation.data import data
import tc_formation.models.layers
import tc_formation.models.resnet as resnet
import tc_formation.tf_metrics as tfm
import tensorflow.keras as keras
import tensorflow as tf
from tensorflow.keras.layers.experimental import preprocessing
import tensorflow_addons as tfa
from datetime import datetime

gpu_devices = tf.config.experimental.list_physical_devices('GPU')
tf.config.experimental.set_memory_growth(gpu_devices[0], True)
# -

# # ResNet for Single Lead Time

# The data that we're using will have the following shape.
# Should change it to whatever the shape of the data we're going to use down there.

# +
exp_name = 'baseline_resnet_single_leadtime_besttrack_v2'
runtime = datetime.now().strftime('%Y_%b_%d_%H_%M')
# data_path = '/N/project/pfec_climo/qmnguyen/tc_prediction/extracted_test/6h_700mb'
#data_path = '/N/project/pfec_climo/qmnguyen/tc_prediction/extracted_features/alllevels_ABSV_CAPE_RH_TMP_HGT_VVEL_UGRD_VGRD/6h_700mb'
# data_path = '/N/project/pfec_climo/qmnguyen/tc_prediction/extracted_features/wp_ep_alllevels_ABSV_CAPE_RH_TMP_HGT_VVEL_UGRD_VGRD_100_260/12h_700mb'
# data_path = '/N/project/pfec_climo/qmnguyen/tc_prediction/extracted_features/multilevels_ABSV_CAPE_RH_TMP_HGT_VVEL_UGRD_VGRD/6h_700mb'
# data_path = 'data/nolabels_wp_ep_alllevels_ABSV_CAPE_RH_TMP_HGT_VVEL_UGRD_VGRD_100_260/12h/tc_ibtracs_6h_12h_18h_24h_30h_36h_42h_48h.csv'
data_path = 'data/nolabels_wp_ep_alllevels_ABSV_CAPE_RH_TMP_HGT_VVEL_UGRD_VGRD_100_260/12h/tc_ibtracs_12h_WP_EP_v2.csv'
train_path = data_path.replace('.csv', '_train.csv')
val_path = data_path.replace('.csv', '_val.csv')
test_path = data_path.replace('.csv', '_test.csv')
subset = dict(
    absvprs=[900, 750],
    rhprs=[750],
    tmpprs=[900, 500],
    hgtprs=[500],
    vvelprs=[500],
    ugrdprs=[800, 200],
    vgrdprs=[800, 200],
)
data_shape = (41, 161, 13)
leadtime = 12

# subset = None
# data_shape = (41, 161, 135)

# From Feature Importance - 3 features: capesfc, ugrdprs @ 800, vgrdprs @ 800
# subset = dict(
#     absvprs=None,
#     rhprs=None,
#     tmpprs=None,
#     hgtprs=None,
#     vvelprs=None,
#     ugrdprs=[800],
#     vgrdprs=[800],
#     # capesfc=None,
#     tmpsfc=None
# )
# data_shape = (41, 161, 3)
# -

model = resnet.ResNet18v2(
    input_shape=data_shape,
    #weights=None,
    include_top=True,
    classes=1,
    classifier_activation=None,)
model.summary()

trained_model = keras.models.load_model('outputs/baseline_resnet_multileadtime_2022_Feb_08_21_22_1st_ckp/', compile=False)
model.set_weights(trained_model.get_weights())

# Build the model using BinaryCrossentropy loss

model.compile(
    optimizer='adam',
    loss=tf.keras.losses.BinaryCrossentropy(from_logits=True),
    #loss=tfa.losses.SigmoidFocalCrossEntropy(from_logits=True),
    metrics=[
        'binary_accuracy',
        tfm.RecallScore(from_logits=True),
        tfm.PrecisionScore(from_logits=True),
        tfm.F1Score(num_classes=1, from_logits=True, threshold=0.5),
    ]
)

# Load our training and validation data.

full_training = data.load_data_v1(
    train_path,
    data_shape=data_shape,
    batch_size=64,
    shuffle=True,
    subset=subset,
    leadtime=leadtime,
    group_same_observations=False,
)
downsampled_training = data.load_data_v1(
    train_path,
    data_shape=data_shape,
    batch_size=64,
    shuffle=True,
    subset=subset,
    negative_samples_ratio=1)
validation = data.load_data_v1(
    val_path,
    data_shape=data_shape,
    subset=subset,
    leadtime=leadtime,
    group_same_observations=True,
)

normalizer = preprocessing.Normalization(axis=-1)
for X, y in iter(full_training):
    normalizer.adapt(X)
normalizer


# +
def normalize_data(x, y):
    return normalizer(x), y

full_training = full_training.map(normalize_data)
downsampled_training = downsampled_training.map(normalize_data)
validation = validation.map(normalize_data)
# -

# # First stage
#
# train the model on the down-sampled data.

# +
epochs = 350
first_stage_history = model.fit(
    downsampled_training,
#     full_training,
    epochs=epochs,
    validation_data=validation,
    class_weight={1: 1., 0: 1.},
    shuffle=True,
    callbacks=[
        keras.callbacks.EarlyStopping(
            monitor='val_f1_score',
            mode='max',
            verbose=1,
            patience=20,
            restore_best_weights=True),
        keras.callbacks.ModelCheckpoint(
            filepath=f"outputs/{exp_name}_{runtime}_1st_ckp",
            monitor='val_f1_score',
            mode='max',
            save_best_only=True,
        ),
        keras.callbacks.TensorBoard(
            log_dir=f'outputs/{exp_name}_{runtime}_1st_board',
        ),
    ]
)

plot.plot_training_history(first_stage_history, "First stage training")
# -

testing = data.load_data_v1(
    test_path,
    data_shape=data_shape,
    subset=subset,
    leadtime=leadtime,
    group_same_observations=True,
)
testing = testing.map(normalize_data)
print(f'\n**** LEAD TIME: {leadtime}')
model.evaluate(testing)

# # Second stage
#
# train the model on full dataset.

# +
second_stage_history = model.fit(
    full_training,
    epochs=epochs,
    validation_data=validation,
    class_weight={1: 10., 0: 1.},
    shuffle=True,
    callbacks=[
        keras.callbacks.EarlyStopping(
            monitor='val_f1_score',
            mode='max',
            verbose=1,
            patience=20,
            restore_best_weights=True),
        keras.callbacks.ModelCheckpoint(
            filepath=f"outputs/{exp_name}_{runtime}_2nd_ckp",
            monitor='val_f1_score',
            mode='max',
            save_best_only=True,
        ),
    ])


plot.plot_training_history(second_stage_history, "Second stage training")
# -

# After the model is trained, we will test it on test data.

model.evaluate(testing)
