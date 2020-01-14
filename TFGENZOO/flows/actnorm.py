import tensorflow as tf
from flows import flows
from tensorflow.keras import layers
import numpy as np
Flow = flows.Flow
Layer = layers.Layer


class Actnorm(Flow):
    """Actnorm bijector
    ref.
    https://arxiv.org/pdf/1807.03039.pdf
    https://github.com/y0ast/Glow-PyTorch/blob/master/modules.py
    """

    def build(self, input_shape):
        super(Actnorm, self).build(input_shape)
        input_shape = input_shape.as_list()
        shapes = [1 for i in range(len(input_shape))]
        shapes[self.normaxis] = input_shape[self.normaxis]
        self.log_scale = self.add_weight(
            "log_scale",
            shape=shapes,
            dtype=tf.float32,
            initializer='zeros',
            )
        self.bias = self.add_weight(
            "bias",
            shape=shapes,
            dtype=tf.float32,
            initializer='zeros'
        )
        axis = [i for i in range(len(input_shape))]
        axis.pop(self.normaxis)
        self.reduce_axis = axis
        reduce_pixel = input_shape
        reduce_pixel.pop(self.normaxis)
        reduce_pixel.pop(0)
        self.reduce_pixel = np.prod(reduce_pixel)
        self.built = True

    def __init__(self, normaxis: int = -1,
                 log_scale_factor: float = 1.0,
                 with_debug: bool = False):
        """
        args:
        - normaxis: int
        normalization's axis
        ex. if HWC, -1
        - log_scale_factor: float
        scaling factor avoiding zero devision
        default 1.0
        - with_debug: bool
        debugging assertion flag
        """
        super(Actnorm, self).__init__(with_debug=with_debug)
        self.normaxis = normaxis
        self.log_scale_factor = log_scale_factor
        self.initialized = False

    def setStat(self, x: tf.Tensor):
        """Actnorm's initialization of first batch
        - x: tf.Tensor
        the first batch
        note:
        bias = - mean(x)
        scale = 1/ stddev(x)
        """
        print('Set stat is called')
        mean = - tf.reduce_mean(x, axis=self.reduce_axis, keepdims=True)
        var = tf.reduce_mean((x + mean) ** 2,
                             axis=self.reduce_axis, keepdims=True)
        stdvar = tf.math.sqrt(var) + 1e-6
        log_scale = tf.math.log(1. / stdvar /
                                self.log_scale_factor) * self.log_scale_factor
        bias_update = self.bias.assign(mean)
        log_scale_update = self.log_scale.assign(log_scale)
        self.add_update(bias_update)
        self.add_update(log_scale_update)

    def call(self, x: tf.Tensor, **kwargs):
        """forward
        formula:
        z = (x +bias) * scale
        log_det_jacobian = h * w * sum(log(scale))
        """
        bias = tf.broadcast_to(self.bias, tf.shape(x))
        log_scale = tf.broadcast_to(self.log_scale, tf.shape(x))
        z = (x + bias) * tf.exp(log_scale)
        log_det_jacobian = self.reduce_pixel * tf.reduce_sum(self.log_scale)
        return z, log_det_jacobian

    def inverse(self, z: tf.Tensor, **kwargs):
        """
        formula:
        x = z / scale - bias
        inverse_log_det_jacobian = - h * w * sum(log(scale))
        """
        bias = tf.broadcast_to(self.bias, tf.shape(z))
        log_scale = tf.broadcast_to(self.log_scale, tf.shape(z))
        x = (z / tf.exp(- log_scale)) - bias
        inverse_log_det_jacobian = - \
            (self.reduce_pixel * tf.reduce_sum(self.log_scale))
        return x, inverse_log_det_jacobian


def test_actnorm():
    actnorm = Actnorm(-1)
    x = tf.keras.Input([16, 16, 4])
    model = tf.keras.Model(x, actnorm(x))
    x = tf.random.normal([100, 16, 16, 4]) + 100
    actnorm.setStat(x)
    z, log_det_jacobian = model(x)
    _x, inverse_log_det_jacobian = actnorm.inverse(z)
    print('input: x', tf.reduce_mean(x).numpy())
    print('output: z', tf.reduce_mean(z).numpy())
    print('inverse: z', tf.reduce_mean(_x).numpy())
    print('diff: {}'.format(tf.reduce_mean(x - _x)))
    print('log_det_diff: {}'.format(log_det_jacobian +
                                    inverse_log_det_jacobian))
    # print('log_det_jacobian: ',
    #       actnorm.forward_log_det_jacobian(y, event_ndims=3).numpy())