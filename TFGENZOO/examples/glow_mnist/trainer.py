"""
Note: does tfp serve correct distribution?
I think tfp can calculate log probability as same as PyTorch
ref:
https://colab.research.google.com/gist/MokkeMeguru/cec2fd9acfdca6ba7173b0e0cf2a86f7/torch-log_prob.ipynb
https://colab.research.google.com/gist/MokkeMeguru/1de367931dc690bcfdf7bc9e76fe9a95/tensorflow-log_prob.ipynb
"""
from examples.glow_mnist import model
from examples.utils import load_mnist, load_cifar10
from examples.glow_mnist import args
import tensorflow_probability as tfp
from tensorflow.keras import Model
from functools import reduce
import tensorflow as tf
from tensorflow.keras import optimizers, metrics
from pathlib import Path
from tqdm import tqdm
import numpy as np
import datetime

Mean = metrics.Mean
Adam = optimizers.Adam
tfd = tfp.distributions
Glow = model.Glow


class CustomSchedule(tf.keras.optimizers.schedules.LearningRateSchedule):
    """for warmup learning rate
    ref:
    https://www.tensorflow.org/tutorials/text/transformer
    """

    def __init__(self, d_model, warmup_steps=4000):
        super(CustomSchedule, self).__init__()
        self.d_model = d_model
        self.d_model = tf.cast(self.d_model, tf.float32)
        self.warmup_steps = warmup_steps

    def __call__(self, step):
        arg1 = tf.math.rsqrt(step)
        arg2 = step * (self.warmup_steps**-1.5)
        return tf.math.rsqrt(self.d_model) * tf.math.minimum(arg1, arg2)


def bits_per_dims(log_prob, pixels):
    return ((log_prob / pixels) - np.log(128.)) / np.log(2.)


class Glow_trainer:
    def __init__(self, args=args.args, training=True):
        self.args = args
        self.glow = Glow(self.args)
        self.glow.build(tuple([None] + self.args['input_shape']))
        self.glow.summary()
        self.pixels = reduce(lambda x, y: x * y, args['input_shape'])
        self.target_distribution = tfd.MultivariateNormalDiag(
            loc=tf.zeros([self.pixels], dtype=tf.float32),
            scale_diag=tf.ones([self.pixels], dtype=tf.float32))
        self.learning_rate_schedule = CustomSchedule(d_model=self.pixels)
        self.optimizer = Adam(self.learning_rate_schedule)

        self.log_prob_loss = Mean(name='log_prob[train]', dtype=tf.float32)
        self.log_det_jacobian_loss = Mean(
            name='log_det_jacobian[train]', dtype=tf.float32)
        self.loss = Mean(name='loss[train]', dtype=tf.float32)

        self.val_log_prob_loss = Mean(name='log_prob[val]', dtype=tf.float32)
        self.val_log_det_jacobian_loss = Mean(
            name='log_det_jacobian[val]', dtype=tf.float32)
        self.val_loss = Mean(name='loss[val]', dtype=tf.float32)

        # self.train_dataset, self.test_dataset = load_mnist.load_dataset(
        #     BATCH_SIZE=self.args['batch_size'])
        self.train_dataset, self.test_dataset = load_cifar10.load_dataset(
            BATCH_SIZE=self.args['batch_size'])
        checkpoint_path = args.get(
            'checkpoint_path', Path('../checkpoints/glow'))
        for sample in self.train_dataset.take(1):
            print('init loss (log_prob bits/dims) {}'.format(
                bits_per_dims(-(tf.reduce_mean(self.val_step(sample['img']))), self.pixels)))
        self.setup_checkpoint(checkpoint_path)
        if training:
            self.writer = tf.summary.create_file_writer(
                logdir="glow_log/" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
            self.writer.set_as_default()

    def setup_checkpoint(self, checkpoint_path):
        ckpt = tf.train.Checkpoint(model=self.glow, optimizer=self.optimizer)
        ckpt_manager = tf.train.CheckpointManager(
            ckpt, checkpoint_path, max_to_keep=3)
        if ckpt_manager.latest_checkpoint:
            ckpt.restore(ckpt_manager.latest_checkpoint)
            print('[Flow] Latest checkpoint restored!!')
            for sample in self.train_dataset.take(1):
                print('restored loss (log_prob bits/dims) {}'.format(
                    bits_per_dims(-(tf.reduce_mean(self.val_step(sample['img']))), self.pixels)))
        self.ckpt = ckpt
        self.ckpt_manager = ckpt_manager

    @tf.function
    def val_step(self, x):
        z, log_det_jacobian = self.glow(x, training=False)
        z = tf.reshape(z, [-1, self.pixels])
        lp = self.target_distribution.log_prob(z)
        loss = - (lp + log_det_jacobian)
        self.val_log_prob_loss(lp)
        self.val_log_det_jacobian_loss(log_det_jacobian)
        self.val_loss(loss)
        return loss

    # @tf.function
    def train_step(self, x):
        with tf.GradientTape() as tape:
            z, log_det_jacobian = self.glow(x, training=False)
            z = tf.reshape(z, [-1, self.pixels])
            lp = self.target_distribution.log_prob(z)
            loss = - (lp + log_det_jacobian)
        grads = tape.gradient(loss, self.glow.trainable_variables)
        self.optimizer.apply_gradients(
            zip(grads, self.glow.trainable_variables))
        self.log_prob_loss(lp)
        self.log_det_jacobian_loss(log_det_jacobian)
        self.loss(loss)

    def train(self):
        for epoch in range(self.args['epochs']):
            for x in tqdm(self.train_dataset):
                self.train_step(x['img'])
            for x in tqdm(self.test_dataset):
                self.val_step(x['img'])
            ckpt_save_path = self.ckpt_manager.save()
            print('epoch {}: train_loss={}, val_loss={}, bits per dims={}, saved at {}'.format(
                epoch, self.loss.result().numpy(), self.val_loss.result().numpy(),
                bits_per_dims(-self.val_loss.result().numpy(), self.pixels), ckpt_save_path))
            print('log_prob {} + ldj {}'.format(self.val_log_prob_loss.result(), self.val_log_det_jacobian_loss.result()))
            tf.summary.scalar('loss[train]', self.loss.result(), step=epoch)
            tf.summary.scalar('log_prob[train]', self.log_prob_loss.result(), step=epoch)
            tf.summary.scalar('log_det_jacobian[train]', self.log_det_jacobian_loss.result(), step=epoch)
            tf.summary.scalar('loss[val]', self.val_loss.result(), step=epoch)
            tf.summary.scalar('log_prob[val]', self.val_log_prob_loss.result(), step=epoch)
            tf.summary.scalar('log_det_jacobian[val]', self.val_log_det_jacobian_loss.result(), step=epoch)
            self.loss.reset_states()
            self.log_prob_loss.reset_states()
            self.log_det_jacobian_loss.reset_states()
            self.val_loss.reset_states()
            self.val_log_prob_loss.reset_states()
            self.val_log_det_jacobian_loss.reset_states()
    


# glow_trainer = Glow_trainer()
# >>>
# Model: "Glow"
# _________________________________________________________________
# Layer (type)                 Output Shape              Param #   
# =================================================================
# flow_list_71 (FlowList)      multiple                  303296    
# =================================================================
# Total params: 303,296
# Trainable params: 302,912
# Non-trainable params: 384
# _________________________________________________________________
# init loss (log_prob bits/dims) -8.988224029541016
#
# glow_trainer.train()