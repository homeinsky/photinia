#!/usr/bin/env python3

"""
@author: xi
@since: 2016-11-11
"""

import math
import threading

import numpy as np
import tensorflow as tf

from . import initializers
from . import operations
from . import settings


def variable(name,
             initial_value,
             trainable=True):
    """Create a variable.
    Shortcut to "tf.Variable()".

    Args:
        name (str): Variable name.
        initial_value: A `Tensor`, or Python object convertible to a `Tensor`,
            which is the initial value for the Variable.
        trainable (bool): If `True`, the default, also adds the variable to the graph collection
            `GraphKeys.TRAINABLE_VARIABLES`.

    Returns:
        tf.Variable: The variable object.

    Raises:
        ValueError: If both `variable_def` and initial_value are specified.
        ValueError: If the initial value is not specified, or does not have a shape and `validate_shape` is `True`.
        RuntimeError: If eager execution is enabled.

    """
    return tf.Variable(
        name=name,
        initial_value=initial_value,
        trainable=trainable,
        dtype=settings.D_TYPE
    )


def placeholder(name,
                shape,
                dtype=settings.D_TYPE):
    """Create a placeholder.
    Shortcut to "tf.placeholder()".

    Args:
        name (str): Name of the placeholder.
        shape (tuple|list): The shape of the tensor to be fed (optional). If the shape is not specified,
            you can feed a tensor of any shape.
        dtype (tf.DType): The type of elements in the tensor to be fed.

    Returns:
        tf.Tensor: The placeholder tensor.

    """
    return tf.placeholder(name=name, shape=shape, dtype=dtype)


class Widget(object):
    """Widget
    The basic component to form a model.
    This an abstract class which can only be inherited.
    """

    LOCK = threading.Semaphore(1)
    INSTANCES = dict()

    def __init__(self,
                 name=None,
                 build=True):
        """Construct a widget.

        Args:
            name (str): Widget name.
            build (bool): If the widget will be built during the xonstruction.
        """
        if name is not None:
            if not isinstance(name, str):
                raise ValueError('Widget name must be specified with string.')
            if len(name.strip()) != len(name) or name == '':
                raise ValueError('Widget name cannot be empty or contain space characters.')
        self._name = name
        self._scope = ''
        self._full_name = None
        self._prefix = None
        self._built = False
        if build:
            self.build()

    @property
    def name(self):
        return self._name

    @property
    def built(self):
        return self._built

    def build(self):
        """Build the widget.
        The main purpose of this function is to create the trainable variables (parameters) for the widget.

        """
        if self._built:
            return self
        # if self._name is None:
        #     #
        #     # Build WITHOUT scope.
        #     self._build()
        #     self._built = True
        #     return self
        # else:
        #
        # Build WITH scope.
        self._scope = tf.get_variable_scope().name
        if self._scope == '':
            self._full_name = self._name
        else:
            if self._scope.endswith('/'):
                self._full_name = self._scope + self._name
            else:
                self._full_name = '%s/%s' % (self._scope, self._name)
        self._prefix = self._full_name + '/'
        with tf.variable_scope(self._name):
            self._build()
            self._built = True
        with Widget.LOCK:
            if self._full_name in Widget.INSTANCES:
                raise ValueError('Duplicated widget name %s.' % self._full_name)
            Widget.INSTANCES[self._full_name] = self
        return self

    def _build(self):
        """Build the widget.
        Abstract method.
        All subclass must implement this method.

        There is one task to be done in this method:
        1) Create the parameters (trainable variables) for the widget.

        """
        raise NotImplementedError()

    def setup(self, *args, **kwargs):
        """Setup the widget.
        "Setup" means to create a new series of operator in the TF graph, which can be called a "path".
        No matter how many paths be created, the number of trainable variables is (and of course cannot) be changed.
        They share the same parameters of the widget.

        """
        if not self._built:
            raise RuntimeError('This widget has not been built. Please build first.')
        if self._name is None:
            #
            # Setup only WITHOUT scope.
            return self._setup(*args, **kwargs)
        else:
            #
            # Setup only WITH scope.
            with tf.variable_scope(self._prefix):
                return self._setup(*args, **kwargs)

    def _setup(self, *args, **kwargs):
        """Setup the widget.
        Abstract method.
        All subclass must implement this method.

        There is one task to be done in this method:
        1) Construct the model's graph structure with TF.

        In this method, you CANNOT create any trainable variables.

        """
        raise NotImplementedError()

    def __call__(self, *args, **kwargs):
        return self.setup(*args, **kwargs)

    def get_variables(self):
        """Get variables(tensors) of the widget.

        Returns:
            list[tf.Tensor]: List of variables.

        """
        if self._name is None:
            return list()
        prefix = self._prefix
        global_vars = tf.global_variables()
        return [var for var in global_vars if var.name.startswith(prefix)]

    def get_trainable_variables(self):
        """Get variables(tensors that marked as "trainable") of the widget.

        Returns:
            list[tf.Tensor]: List of variables.

        """
        if self._name is None:
            return list()
        trainable_vars = tf.trainable_variables()
        return [var for var in trainable_vars if var.name.startswith(self._prefix)]

    @property
    def full_name(self):
        """Get the full name of the widget.
        E.g., model/layers/layer1
        The full name does not contain "/" character.

        Returns:
            str: Full name of the widget.

        """
        return self._full_name

    @property
    def prefix(self):
        """Get the prefix of the widget.
        E.g., model/layers/layer1/
        The prefix always ends with a "/" character.

        Returns:
            str: Prefix of the widget.

        """
        return self._prefix

    def get_parameters(self):
        """Get parameter values of the widget.

        Returns:
            dict[str, np.ndarray]: Name to value dictionary of the parameters.

        """
        var_list = self.get_trainable_variables()
        param_dict = {var.name: var for var in var_list}
        param_dict = settings.get_session().run(param_dict)
        return param_dict

    def set_parameters(self, param_dict, strict=True):
        """Set values to the parameters.

        Args:
            param_dict (dict[str, np.ndarray]): Name to value dictionary.
            strict (bool): If strict is True, all values in the dictionary must be used to assigned to the
                associated parameter, or an error will be risen.

        Raises:
            ValueError: If strict is True and there are some values in the dictionary unused.

        """
        var_list = self.get_trainable_variables()
        var_dict = {var.name: var for var in var_list}
        session = settings.get_session()
        for name, value in param_dict.items():
            if name not in var_dict:
                if strict:
                    raise ValueError('%s is not in this model.' % name)
            var = var_dict[name]
            var.load(value, session=session)

    def get_operation(self, name):
        name = self._prefix + name
        try:
            return tf.get_default_graph().get_operation_by_name(name)
        except KeyError:
            return None

    def get_tensor(self, name):
        if name.rfind(':') == -1:
            name = '%s%s:0' % (self._prefix, name)
        else:
            name = self._prefix + name
        try:
            return tf.get_default_graph().get_tensor_by_name(name)
        except KeyError:
            return None

    def get_variable(self, name):
        if name.rfind(':') == -1:
            name = '%s%s:0' % (self._prefix, name)
        else:
            name = self._prefix + name
        for var in tf.global_variables():
            if name == var.name:
                return var
        return None

    def __getattr__(self, name):
        name = self._prefix + name
        with Widget.LOCK:
            if name in Widget.INSTANCES:
                return Widget.INSTANCES[name]
        if name.rfind(':') == -1:
            name += ':0'
        try:
            return tf.get_default_graph().get_tensor_by_name(name)
        except KeyError:
            return None

    def __getitem__(self, name):
        return self.__getattr__(name)


class Linear(Widget):
    """Linear layer.
    y = wx + b
    """

    def __init__(self,
                 name,
                 input_size,
                 output_size,
                 with_bias=True,
                 w_init=initializers.GlorotUniform(),
                 b_init=initializers.Zeros()):
        """Linear layer.

        y = Wx + b

        Args:
            name (str): Widget name.
            input_size (int): Input size.
            output_size (int): Output size.
            with_bias (bool): If the layer contains bias.
            w_init (initializers.Initializer): Weight initializer.
            b_init (initializers.Initializer): Bias initializer.

        """
        self._input_size = input_size
        self._output_size = output_size
        self._with_bias = with_bias
        self._w_init = w_init
        self._b_init = b_init
        super(Linear, self).__init__(name)

    @property
    def input_size(self):
        return self._input_size

    @property
    def output_size(self):
        return self._output_size

    @property
    def with_bias(self):
        return self._with_bias

    def _build(self):
        """Build the linear layer.
        Two parameters: weight and bias.

        """
        self._w = tf.Variable(
            self._w_init.build(
                shape=(self._input_size, self._output_size)
            ),
            dtype=settings.D_TYPE,
            name='w'
        )
        self._b = tf.Variable(
            self._b_init.build(
                shape=(self._output_size,)
            ),
            dtype=settings.D_TYPE,
            name='b'
        ) if self._with_bias else None

    @property
    def w(self):
        return self._w

    @property
    def b(self):
        return self._b

    def _setup(self, x, axes=None):
        """Setup the layer.

        Args:
            x (tf.Tensor): Input tensor.
            axes (tuple[int]|list[int]): If x is a tensor, the layer will perform tensor dot.

        Returns:
            tf.Tensor: Output tensor.

        """
        y = tf.matmul(x, self._w) if axes is None else tf.tensordot(x, self._w, axes=axes)
        if self._with_bias:
            y += self._b
        return y


class Dropout(Widget):

    def __init__(self, name, keep_prob=None):
        """Dropout

        Args:
            name (str): Widget name.
            keep_prob (float|tf.Tensor): Keep probability.

        """
        self._keep_prob = keep_prob
        super(Dropout, self).__init__(name)

    @property
    def keep_prob(self):
        return self._keep_prob

    def _build(self):
        if self._keep_prob is None:
            self._keep_prob = tf.placeholder(
                shape=(),
                dtype=settings.D_TYPE
            )

    def _setup(self, x):
        """Setup dropout.

        Args:
            x (tf.Tensor): Input tensor.

        Returns:
            tf.Tensor: Output tensor.

        """
        return tf.nn.dropout(x, self._keep_prob)


class Conv2D(Widget):

    def __init__(self,
                 name,
                 input_size,
                 output_channels,
                 filter_height=3,
                 filter_width=3,
                 stride_height=1,
                 stride_width=1,
                 padding='SAME',
                 w_init=initializers.TruncatedNormal(),
                 b_init=initializers.Zeros(),
                 flat_output=False):
        """2D convolutional layer

        Args:
            name (str): Widget name.
            input_size (tuple[int]): Input size.
            output_channels (int): Numbers of output channels.
            filter_height (int): Filter height.
            filter_width (int): Filter width.
            stride_height (int): Stride height.
            stride_width (int): Stride width.
            padding (str): Padding type. Should be one of {"SAME", "VALID"}. Default is "SAME".
            w_init (initializers.Initializer): Weight(Kernel) initializer.
            b_init (initializers.Initializer): Bias initializer.
            flat_output (bool): If True, the output will be converted into flat vector(with shape batch_size * dim).

        """
        if not (isinstance(input_size, (tuple, list)) and len(input_size) == 3):
            raise ValueError('input_size should be tuple or list with 3 elements.')
        self._input_height = input_size[0]
        self._input_width = input_size[1]
        self._input_channels = input_size[2]
        self._output_channels = output_channels
        self._filter_height = filter_height
        self._filter_width = filter_width
        self._stride_height = stride_height
        self._stride_width = stride_width
        self._padding = padding
        self._w_init = w_init
        self._b_init = b_init
        self._flat_output = flat_output
        #
        if self._padding == 'SAME':
            self._output_height = math.ceil(self._input_height / stride_height)
            self._output_width = math.ceil(self._input_width / stride_width)
        else:
            self._output_height = math.ceil((self._input_height - filter_height + 1) / stride_height)
            self._output_width = math.ceil((self._input_width - filter_width + 1) / stride_width)
        self._flat_size = self._output_height * self._output_width * output_channels
        super(Conv2D, self).__init__(name)

    @property
    def input_size(self):
        return self._input_height, self._input_width

    @property
    def input_height(self):
        return self._input_height

    @property
    def input_width(self):
        return self._input_width

    @property
    def input_channels(self):
        return self._input_channels

    @property
    def output_height(self):
        return self._output_height

    @property
    def output_width(self):
        return self._output_width

    @property
    def output_size(self):
        return self._output_height, self._output_width, self._output_channels

    @property
    def output_channels(self):
        return self._output_channels

    @property
    def filter_height(self):
        return self._filter_height

    @property
    def filter_width(self):
        return self._filter_width

    @property
    def stride_height(self):
        return self._stride_height

    @property
    def stride_width(self):
        return self._stride_width

    @property
    def flat_output(self):
        return self._flat_output

    @flat_output.setter
    def flat_output(self, flat_output):
        self._flat_output = flat_output

    @property
    def flat_size(self):
        return self._flat_size

    def _build(self):
        self._w = tf.Variable(
            self._w_init.build(
                shape=(
                    self._filter_height,
                    self._filter_width,
                    self._input_channels,
                    self._output_channels
                )
            ),
            dtype=settings.D_TYPE,
            name='w'
        )
        self._b = tf.Variable(
            self._b_init.build(
                shape=(self._output_channels,)
            ),
            dtype=settings.D_TYPE,
            name='b'
        )

    @property
    def w(self):
        return self._w

    @property
    def b(self):
        return self._b

    def _setup(self, x):
        """Setup 2D convolutional layer.

        Args:
            x (tf.Tensor): Input tensor.

        Returns:
            tf.Tensor: Output tensor.

        """
        y = tf.nn.conv2d(
            input=x,
            filter=self._w,
            strides=[1, self._stride_height, self._stride_width, 1],
            padding=self._padding,
            data_format='NHWC'
        ) + self._b
        if self._flat_output:
            y = tf.reshape(y, (-1, self._flat_size))
        return y


class Pool2D(Widget):

    def __init__(self,
                 name,
                 input_size,
                 filter_height=3,
                 filter_width=3,
                 stride_height=2,
                 stride_width=2,
                 padding='SAME',
                 pool_type='max'):
        """Pooling layer for 2D.

        Args:
            name (str): Widget name.
            input_size (tuple[int]): Input size.
            filter_height (int): Filter height.
            filter_width (int): Filter width.
            stride_height (int): Stride height.
            stride_width (int): Stride width.
            padding (str): Padding type. Should be one of {"SAME", "VALID"}. Default is "SAME".
            pool_type (str): Pooling type. Should be one of {"max", "mean"}. Default is "max".

        """
        self._input_size = input_size
        self._filter_height = filter_height
        self._filter_width = filter_width
        self._stride_height = stride_height
        self._stride_width = stride_width
        self._padding = padding
        pool_type = pool_type.lower()
        if pool_type not in {'max', 'avg'}:
            raise ValueError('pool_type should be one of {"max", "avg"}, '
                             'but got %s' % pool_type)
        self._pool_type = pool_type
        #
        self._input_height = input_size[0]
        self._input_width = input_size[1]
        self._input_channels = input_size[2]
        if self._padding == 'SAME':
            self._output_height = math.ceil(self._input_height / stride_height)
            self._output_width = math.ceil(self._input_width / stride_width)
        else:
            self._output_height = math.ceil((self._input_height - filter_height + 1) / stride_height)
            self._output_width = math.ceil((self._input_width - filter_width + 1) / stride_width)
        self._flat_size = self._output_height * self._output_width * self._input_channels
        super(Pool2D, self).__init__(name)

    @property
    def input_size(self):
        return self._input_size

    @property
    def input_height(self):
        return self._input_height

    @property
    def input_width(self):
        return self._input_width

    @property
    def input_channels(self):
        return self._input_channels

    @property
    def output_size(self):
        return self._output_height, self._output_width, self._input_channels

    @property
    def output_height(self):
        return self._output_height

    @property
    def output_width(self):
        return self._output_width

    @property
    def flat_size(self):
        return self._flat_size

    def _build(self):
        pass

    def _setup(self, x):
        """Setup pooling layer for 2D.

        Args:
            x (tf.Tensor): Input tensor.

        Returns:
            tf.Tensor: Output tensor.

        """
        if self._pool_type == 'max':
            y = tf.nn.max_pool(
                value=x,
                ksize=[1, self._filter_height, self._filter_width, 1],
                strides=[1, self._stride_height, self._stride_width, 1],
                padding=self._padding,
                data_format='NHWC'
            )
            return y
        elif self._pool_type == 'avg':
            y = tf.nn.avg_pool(
                value=x,
                ksize=[1, self._filter_height, self._filter_width, 1],
                strides=[1, self._stride_height, self._stride_width, 1],
                padding=self._padding,
                data_format='NHWC'
            )
            return y


class GroupConv2D(Widget):
    """Group 2D convolutional layer.
    """

    def __init__(self,
                 name,
                 input_size,
                 output_channels,
                 num_groups,
                 filter_height=3,
                 filter_width=3,
                 stride_height=1,
                 stride_width=1,
                 padding='SAME',
                 data_format='NHWC',
                 w_init=initializers.TruncatedNormal(),
                 b_init=initializers.Zeros(),
                 flat_output=False):
        if not (isinstance(input_size, (tuple, list)) and len(input_size) == 3):
            raise ValueError('input_size should be tuple or list with 3 elements.')
        self._input_height = input_size[0]
        self._input_width = input_size[1]
        self._input_channels = input_size[2]
        self._output_channels = output_channels
        self._num_groups = num_groups
        self._filter_height = filter_height
        self._filter_width = filter_width
        self._stride_height = stride_height
        self._stride_width = stride_width
        self._data_format = data_format
        self._padding = padding
        self._w_init = w_init
        self._b_init = b_init
        self._flat_output = flat_output
        #
        if self._padding == 'SAME':
            self._output_height = math.ceil(self._input_height / stride_height)
            self._output_width = math.ceil(self._input_width / stride_width)
        else:
            self._output_height = math.ceil((self._input_height - filter_height + 1) / stride_height)
            self._output_width = math.ceil((self._input_width - filter_width + 1) / stride_width)
        self._flat_size = self._output_height * self._output_width * output_channels
        super(GroupConv2D, self).__init__(name)

    @property
    def input_size(self):
        return self._input_height, self._input_width

    @property
    def input_height(self):
        return self._input_height

    @property
    def input_width(self):
        return self._input_width

    @property
    def input_channels(self):
        return self._input_channels

    @property
    def output_height(self):
        return self._output_height

    @property
    def output_width(self):
        return self._output_width

    @property
    def output_size(self):
        return self._output_height, self._output_width, self._output_channels

    @property
    def output_channels(self):
        return self._output_channels

    @property
    def num_groups(self):
        return self._num_groups

    @property
    def filter_height(self):
        return self._filter_height

    @property
    def filter_width(self):
        return self._filter_width

    @property
    def stride_height(self):
        return self._stride_height

    @property
    def stride_width(self):
        return self._stride_width

    @property
    def flat_output(self):
        return self._flat_output

    @flat_output.setter
    def flat_output(self, flat_output):
        self._flat_output = flat_output

    @property
    def flat_size(self):
        return self._flat_size

    def _build(self):
        self._w = tf.Variable(
            self._w_init.build(
                shape=(
                    self._filter_height,
                    self._filter_width,
                    math.floor(self._input_channels / self._num_groups),
                    self._output_channels
                )
            ),
            dtype=settings.D_TYPE,
            name='w'
        )
        self._b = tf.Variable(
            self._b_init.build(
                shape=(self._output_channels,)
            ),
            dtype=settings.D_TYPE,
            name='b'
        )

    @property
    def w(self):
        return self._w

    @property
    def b(self):
        return self._b

    def _setup(self, x):
        x_list = tf.split(value=x, num_or_size_splits=self._num_groups, axis=3)
        w_list = tf.split(value=self._w, num_or_size_splits=self._num_groups, axis=3)
        y_list = [
            tf.nn.conv2d(
                input=x,
                filter=w,
                strides=[1, self._stride_height, self._stride_width, 1],
                padding=self._padding,
                data_format=self._data_format
            )
            for x, w in zip(x_list, w_list)
        ]
        y = tf.concat(values=y_list, axis=3) + self._b
        if self._flat_output:
            y = tf.reshape(y, (-1, self._flat_size))
        return y


class Conv2DTrans(Widget):

    def __init__(self,
                 name,
                 output_size,
                 input_channels,
                 filter_height=3,
                 filter_width=3,
                 stride_height=2,
                 stride_width=2,
                 data_format='NHWC',
                 w_init=initializers.TruncatedNormal(),
                 b_init=initializers.Zeros(),
                 flat_input=False):
        """Transpose convolutional layer for 2D.

        Args:
            name (str): Widget name.
            output_size (tuple[int]): Output size.
            input_channels (int): Input size.
            filter_height (int): Filter height.
            filter_width (int): Filter width.
            stride_height (int): Stride height.
            stride_width (int): Stride width.
            data_format (str): Data format. 'NHWC' and 'NCHW' are supported.
            w_init (initializers.Initializer): Weight(Kernel) initializer.
            b_init (initializers.Initializer): Bias initializer.
            flat_input (bool): If True, the output will be converted into flat vector(with shape batch_size * dim).

        """
        if not (isinstance(output_size, (tuple, list)) and len(output_size) == 3):
            raise ValueError('output_size should be tuple or list with 3 elements.')
        self._output_height = output_size[0]
        self._output_width = output_size[1]
        self._output_channels = output_size[2]
        self._input_channels = input_channels
        self._filter_height = filter_height
        self._filter_width = filter_width
        self._stride_height = stride_height
        self._stride_width = stride_width
        self._data_format = data_format
        self._w_init = w_init
        self._b_init = b_init
        self._flat_input = flat_input
        #
        self._input_height = math.ceil(self._output_height / stride_height)
        self._input_width = math.ceil(self._output_width / stride_width)
        self._flat_size = self._input_height * self._input_width * input_channels
        super(Conv2DTrans, self).__init__(name)

    @property
    def input_size(self):
        return self._input_height, self._input_width, self._input_channels

    @property
    def input_height(self):
        return self._input_height

    @property
    def input_width(self):
        return self._input_width

    @property
    def input_channels(self):
        return self._input_channels

    @property
    def flat_size(self):
        return self._flat_size

    @property
    def output_size(self):
        return self._output_height, self._output_width, self._output_channels

    @property
    def output_height(self):
        return self._output_height

    @property
    def output_width(self):
        return self._output_width

    @property
    def output_channels(self):
        return self._output_channels

    @property
    def filter_height(self):
        return self._filter_height

    @property
    def filter_width(self):
        return self._filter_width

    @property
    def stride_height(self):
        return self._stride_height

    @property
    def stride_width(self):
        return self._stride_width

    def _build(self):
        self._w = tf.Variable(
            self._w_init.build(
                shape=(
                    self._filter_height,
                    self._filter_width,
                    self._output_channels,
                    self._input_channels
                )
            ),
            dtype=settings.D_TYPE,
            name='w'
        )
        self._b = tf.Variable(
            self._b_init.build(
                shape=(self._output_channels,)
            ),
            dtype=settings.D_TYPE,
            name='b'
        )

    @property
    def w(self):
        return self._w

    @property
    def b(self):
        return self._b

    def _setup(self, x):
        """Setup transpose convolutional layer.

        Args:
            x (tf.Tensor): Input tensor.

        Returns:
            tf.Tensor: Output tensor.

        """
        input_shape = tf.shape(x)
        batch_size, input_height, input_width = input_shape[0], input_shape[1], input_shape[2]
        output_shape = (
            batch_size,
            input_height * self._stride_height,
            input_width * self._stride_width,
            self._output_channels
        )
        y = tf.nn.conv2d_transpose(
            value=x,
            filter=self._w,
            output_shape=output_shape,
            strides=[1, self._stride_height, self._stride_width, 1],
            padding='SAME',
            data_format='NHWC'
        ) + self._b
        return y


class GRUCell(Widget):
    """GRUCell
    """

    def __init__(self,
                 name,
                 input_size,
                 state_size,
                 with_bias=False,
                 activation=tf.nn.tanh,
                 w_init=initializers.TruncatedNormal(0, 1e-3),
                 u_init=initializers.TruncatedNormal(0, 1e-3),
                 b_init=initializers.Zeros()):
        """Construct a cell.
        Does not create the parameters' tensors.

        :param name: Name.
        :param input_size: Input size.
        :param state_size: State size.
        """
        self._input_size = input_size
        self._state_size = state_size
        self._with_bias = with_bias
        self._activation = activation
        self._w_init = w_init
        self._u_init = u_init
        self._b_init = b_init
        super(GRUCell, self).__init__(name)

    @property
    def input_size(self):
        return self._input_size

    @property
    def state_size(self):
        return self._state_size

    @property
    def output_size(self):
        return self._state_size

    @property
    def with_bias(self):
        return self._with_bias

    def _build(self):
        """Build the cell.
        The GRU cell is consists of 3 kinds of parameters:
        1) Update gate parameters (wz, uz, bz).
        2) Reset gate parameters (wr, ur, br).
        3) Activation parameters (wh, uh, bh).

        :return: None
        """
        self._wz = tf.Variable(
            self._w_init.build(
                shape=(self._input_size, self._state_size)
            ),
            dtype=settings.D_TYPE,
            name='wz'
        )
        self._wr = tf.Variable(
            self._w_init.build(
                shape=(self._input_size, self._state_size)
            ),
            dtype=settings.D_TYPE,
            name='wr'
        )
        self._wh = tf.Variable(
            self._w_init.build(
                shape=(self._input_size, self._state_size)
            ),
            dtype=settings.D_TYPE,
            name='wh'
        )
        #
        self._uz = tf.Variable(
            self._u_init.build(
                shape=(self._state_size, self._state_size)
            ),
            dtype=settings.D_TYPE,
            name='uz'
        )
        self._ur = tf.Variable(
            self._u_init.build(
                shape=(self._state_size, self._state_size)
            ),
            dtype=settings.D_TYPE,
            name='ur'
        )
        self._uh = tf.Variable(
            self._u_init.build(
                shape=(self._state_size, self._state_size)
            ),
            dtype=settings.D_TYPE,
            name='uh'
        )
        if self._with_bias:
            self._bz = tf.Variable(
                self._b_init.build(
                    shape=(self._state_size,)
                ),
                dtype=settings.D_TYPE,
                name='bz'
            )
            self._br = tf.Variable(
                self._b_init.build(
                    shape=(self._state_size,)
                ),
                dtype=settings.D_TYPE,
                name='br'
            )
            self._bh = tf.Variable(
                self._b_init.build(
                    shape=(self._state_size,)
                ),
                dtype=settings.D_TYPE,
                name='bh'
            )

    @property
    def wz(self):
        return self._wz

    @property
    def wr(self):
        return self._wr

    @property
    def wh(self):
        return self._wh

    @property
    def uz(self):
        return self._uz

    @property
    def ur(self):
        return self._ur

    @property
    def uh(self):
        return self._uh

    @property
    def bz(self):
        return self._bz if self._with_bias else None

    @property
    def br(self):
        return self._br if self._with_bias else None

    @property
    def bh(self):
        return self._bh if self._with_bias else None

    def _setup(self, x, h_):
        """Setup the cell.

        :param x: The input tensor.
        :param h_: Previous state tensor.
        :return: State tensor.
        """
        if self._with_bias:
            z = tf.sigmoid(
                tf.matmul(x, self._wz) + tf.matmul(h_, self._uz) + self._bz,
                name='update_gate'
            )
            r = tf.sigmoid(
                tf.matmul(x, self._wr) + tf.matmul(h_, self._ur) + self._br,
                name='reset_gate'
            )
            h = tf.matmul(x, self._wh) + tf.matmul(r * h_, self._uh) + self._bh
        else:
            z = tf.sigmoid(
                tf.matmul(x, self._wz) + tf.matmul(h_, self._uz),
                name='update_gate'
            )
            r = tf.sigmoid(
                tf.matmul(x, self._wr) + tf.matmul(h_, self._ur),
                name='reset_gate'
            )
            h = tf.matmul(x, self._wh) + tf.matmul(r * h_, self._uh)
        h = self._activation(h) if self._activation is not None else h
        h = z * h_ + (1.0 - z) * h
        return h

    def setup_sequence(self,
                       seq,
                       input_widgets=None,
                       output_widgets=None,
                       init_state=None):
        """Setup this cell as an RNN for the given sequence.

        :param seq: Sequence tensor.
        :param input_widgets: Widgets to setup before input to cell.
        :param output_widgets: Widgets to setup after cell state.
        :param init_state: Initial state tensor.
        :return: Output States.
        """
        seq = operations.transpose_sequence(seq)
        if init_state is None:
            batch_size = tf.shape(seq)[1]
            init_state = tf.zeros(
                shape=(batch_size, self.state_size),
                dtype=settings.D_TYPE,
                name='init_state'
            )

        def fn(acc, elem):
            cell_input = operations.setup(elem, input_widgets)
            state = self.setup(cell_input, acc)
            if output_widgets is None:
                return state
            else:
                output = operations.setup(state, output_widgets)
                return state, output

        states_outputs = tf.scan(
            fn=fn,
            elems=seq,
            initializer=init_state
        )

        if output_widgets is None:
            states = operations.transpose_sequence(states_outputs, name='states')
            return states
        else:
            states = operations.transpose_sequence(states_outputs[0], name='states')
            outputs = operations.transpose_sequence(states_outputs[1], name='outputs')
            return states, outputs

    def setup_recursive(self,
                        max_len,
                        input_widgets=None,
                        output_widgets=None,
                        init_state=None,
                        init_input=None):
        """Setup the cell as a RNN in a recursive manner.

        :param max_len: Max length. (int or Tensor)
        :param input_widgets: Widgets to setup before input to cell.
        :param output_widgets: Widgets to setup after cell state.
        :param init_state: Initial state.
        :param init_input: Initial input.
        :return: States and outputs.
        """
        if init_state is None and init_input is None:
            raise ValueError('init_state and init_input should not be None at the same time.')

        if init_state is None:
            batch_size = tf.shape(init_input)[0]
            init_state = tf.zeros(
                shape=(batch_size, self.state_size),
                dtype=settings.D_TYPE,
                name='init_state'
            )
        if init_input is None:
            batch_size = tf.shape(init_state)[0]
            init_input = tf.zeros(
                shape=(batch_size, self._input_size),
                dtype=settings.D_TYPE,
                name='init_input'
            )

        def fn_recursive(acc, _):
            prev_state, prev_output = acc
            cell_input = operations.setup(prev_output, input_widgets)
            state = self.setup(cell_input, prev_state)
            output = operations.setup(state, output_widgets)
            return state, output

        states, outputs = tf.scan(
            fn=fn_recursive,
            elems=tf.zeros((max_len,), dtype=tf.int8),
            initializer=(init_state, init_input)
        )

        states = operations.transpose_sequence(states, name='states')
        outputs = operations.transpose_sequence(outputs, name='outputs')
        return states, outputs


class LSTMCell(Widget):

    def __init__(self,
                 name,
                 input_size,
                 state_size,
                 with_bias=True,
                 activation=tf.nn.tanh,
                 w_init=initializers.TruncatedNormal(0, 1e-3),
                 u_init=initializers.TruncatedNormal(0, 1e-3),
                 b_init=initializers.Zeros()):
        """LSTM cell.

        Args:
            name (str): Widget name.
            input_size (int): Input size.
            state_size (int): State size.
            with_bias (bool): If True, the cell will involve biases.
            activation: Activation function.
            w_init (initializers.Initializer): Input weight initializer.
            u_init (initializers.Initializer): Recurrent weight initializer.
            b_init (initializers.Initializer): Bias initializer.

        """
        self._input_size = input_size
        self._state_size = state_size
        self._with_bias = with_bias
        self._activation = activation
        self._w_init = w_init
        self._u_init = u_init
        self._b_init = b_init
        super(LSTMCell, self).__init__(name)

    @property
    def input_size(self):
        return self._input_size

    @property
    def state_size(self):
        return self._state_size

    @property
    def output_size(self):
        return self._state_size

    def _build(self):
        """Build the cell.
        The LSTM cell is consists of 4 kinds of parameters:
        1) Input gate parameters (wi, ui, bi).
        2) Forget gate parameters (wf, uf, bf).
        3) Output gate parameters (wo, uo, bo).
        4) Activation parameters (wc, uc, bc).

        """
        self._wi = tf.Variable(
            self._w_init.build(
                shape=(self._input_size, self._state_size)
            ),
            dtype=settings.D_TYPE,
            name='wi'
        )
        self._wf = tf.Variable(
            self._w_init.build(
                shape=(self._input_size, self._state_size)
            ),
            dtype=settings.D_TYPE,
            name='wf'
        )
        self._wo = tf.Variable(
            self._w_init.build(
                shape=(self._input_size, self._state_size)
            ),
            dtype=settings.D_TYPE,
            name='wo'
        )
        self._wc = tf.Variable(
            self._w_init.build(
                shape=(self._input_size, self._state_size)
            ),
            dtype=settings.D_TYPE,
            name='wc'
        )
        #
        self._ui = tf.Variable(
            self._u_init.build(
                shape=(self._state_size, self._state_size)
            ),
            dtype=settings.D_TYPE,
            name='ui'
        )
        self._uf = tf.Variable(
            self._u_init.build(
                shape=(self._state_size, self._state_size)
            ),
            dtype=settings.D_TYPE,
            name='uf'
        )
        self._uo = tf.Variable(
            self._u_init.build(
                shape=(self._state_size, self._state_size)
            ),
            dtype=settings.D_TYPE,
            name='uo'
        )
        self._uc = tf.Variable(
            self._u_init.build(
                shape=(self._state_size, self._state_size)
            ),
            dtype=settings.D_TYPE,
            name='uc'
        )
        #
        if self._with_bias:
            self._bi = tf.Variable(
                self._b_init.build(
                    shape=(self._state_size,)
                ),
                dtype=settings.D_TYPE,
                name='bi'
            )
            self._bf = tf.Variable(
                self._b_init.build(
                    shape=(self._state_size,)
                ),
                dtype=settings.D_TYPE,
                name='bf'
            )
            self._bo = tf.Variable(
                self._b_init.build(
                    shape=(self._state_size,)
                ),
                dtype=settings.D_TYPE,
                name='bo'
            )
            self._bc = tf.Variable(
                self._b_init.build(
                    shape=(self._state_size,)
                ),
                dtype=settings.D_TYPE,
                name='bc'
            )

    @property
    def wi(self):
        return self._wi

    @property
    def wf(self):
        return self._wf

    @property
    def wo(self):
        return self._wo

    @property
    def wc(self):
        return self._wc

    @property
    def ui(self):
        return self._ui

    @property
    def uf(self):
        return self._uf

    @property
    def uo(self):
        return self._uo

    @property
    def uc(self):
        return self._uc

    @property
    def bi(self):
        return self._bi if self._with_bias else None

    @property
    def bf(self):
        return self._bf if self._with_bias else None

    @property
    def bo(self):
        return self._bo if self._with_bias else None

    @property
    def bc(self):
        return self._bc if self._with_bias else None

    def _setup(self, x, prev_cell_state, prev_state):
        """Setup the cell.

        Args:
            x (tf.Tensor): Input tensor.
                (batch_size, input_size)
            prev_cell_state (tf.Tensor): Previous cell state.
                (batch_size, state_size)
            prev_state (tf.Tensor): Previous state.
                (batch_size, state_size)

        Returns:
            tuple[tf.Tensor]: Tuple of cell states and states.
                (batch_size, seq_length, state_size)
                (batch_size, seq_length, state_size)

        """
        if self._with_bias:
            input_gate = tf.nn.sigmoid(
                tf.matmul(x, self._wi) + tf.matmul(prev_state, self._ui) + self._bi,
                name='input_gate'
            )
            forget_gate = tf.nn.sigmoid(
                tf.matmul(x, self._wf) + tf.matmul(prev_state, self._uf) + self._bf,
                name='forget_gate'
            )
            output_gate = tf.nn.sigmoid(
                tf.matmul(x, self._wo) + tf.matmul(prev_state, self._uo) + self._bo,
                name='output_gate'
            )
            cell_state = tf.matmul(x, self._wc) + tf.matmul(prev_state, self._uc) + self._bc
        else:
            input_gate = tf.nn.sigmoid(
                tf.matmul(x, self._wi) + tf.matmul(prev_state, self._ui),
                name='input_gate'
            )
            forget_gate = tf.nn.sigmoid(
                tf.matmul(x, self._wf) + tf.matmul(prev_state, self._uf),
                name='forget_gate'
            )
            output_gate = tf.nn.sigmoid(
                tf.matmul(x, self._wo) + tf.matmul(prev_state, self._uo),
                name='output_gate'
            )
            cell_state = tf.matmul(x, self._wc) + tf.matmul(prev_state, self._uc)
        if self._activation is not None:
            cell_state = self._activation(cell_state)
        cell_state = tf.add(forget_gate * prev_cell_state, input_gate * cell_state, name='cell_state')
        if self._activation is not None:
            cell_state = self._activation(cell_state)
        state = tf.multiply(output_gate, cell_state, name='state')
        return cell_state, state

    def setup_sequence(self,
                       seq,
                       widgets=None,
                       init_cell_state=None,
                       init_state=None):
        """Setup this cell as an RNN for the given sequence.

        Args:
            seq (tf.Tensor): Sequence tensor.
                (batch_size, seq_length, input_size)
            widgets (tuple|list): List of widgets before the cell.
            init_cell_state (tf.Tensor: Initial cell state.
                (batch_size, state_size)
            init_state (tf.Tensor: Initial state.
                (batch_size, state_size)

        Returns:
            tf.Tensor: States.
                (batch_size, seq_length, output_size)

        """
        seq = operations.transpose_sequence(seq)
        if init_cell_state is None:
            batch_size = tf.shape(seq)[1]
            init_cell_state = tf.zeros(
                shape=(batch_size, self.state_size),
                dtype=settings.D_TYPE,
                name='init_cell_state'
            )
        if init_state is None:
            batch_size = tf.shape(seq)[1]
            init_state = tf.zeros(
                shape=(batch_size, self.state_size),
                dtype=settings.D_TYPE,
                name='init_state'
            )
        _, states = tf.scan(
            fn=lambda acc, elem: self.setup(operations.setup(elem, widgets), acc[0], acc[1]),
            elems=seq,
            initializer=(init_cell_state, init_state)
        )
        # cell_states = operations.transpose_sequence(cell_states, name='cell_states')
        states = operations.transpose_sequence(states, name='states')
        return states

    def setup_recursive(self,
                        max_len,
                        input_widgets=None,
                        output_widgets=None,
                        init_cell_state=None,
                        init_state=None,
                        init_input=None):
        """Setup the cell in a recursive way.

        Args:
            max_len (int|tf.Tensor): Max sequence length.
            input_widgets (tuple|list): Widgets to setup before the cell.
            output_widgets (tuple|list): Widgets to setup after the cell.
            init_cell_state (tf.Tensor): Initial cell state.
                (batch_size, state_size)
            init_state (tf.Tensor): Initial state.
                (batch_size, state_size)
            init_input (tf.Tensor): Initial input.
                (batch_size, input _size)

        Returns:
            tuple[tf.Tensor]: States and outputs.
                (batch_size, seq_length, state_size)
                (batch_size, seq_length, output_size)

        """
        if init_state is None and init_input is None:
            raise ValueError('init_state and init_input should not be None at the same time.')

        batch_size = tf.shape(init_input)[0]
        if init_cell_state is None:
            init_cell_state = tf.zeros(
                shape=(batch_size, self.state_size),
                dtype=settings.D_TYPE,
                name='init_cell_state'
            )
        if init_state is None:
            init_state = tf.zeros(
                shape=(batch_size, self.state_size),
                dtype=settings.D_TYPE,
                name='init_state'
            )
        if init_input is None:
            init_input = tf.zeros(
                shape=(batch_size, self._input_size),
                dtype=settings.D_TYPE,
                name='init_input'
            )

        def fn_recursive(acc, _):
            prev_cell_state, prev_state, prev_output = acc
            cell_input = operations.setup(prev_output, input_widgets)
            cell_state, state = self.setup(cell_input, prev_cell_state, prev_state)
            output = operations.setup(state, output_widgets)
            return cell_state, state, output

        _, states, outputs = tf.scan(
            fn=fn_recursive,
            elems=tf.zeros((max_len,), dtype=tf.int8),
            initializer=(init_cell_state, init_state, init_input)
        )

        # cell_states = operations.transpose_sequence(cell_states, name='cell_states')
        states = operations.transpose_sequence(states, name='states')
        outputs = operations.transpose_sequence(outputs, name='outputs')
        return states, outputs


class BatchNorm(Widget):
    """BatchNorm
    This class is incomplete. The usage for prediction stage is actually different. Be careful!
    """

    def __init__(self,
                 name,
                 size,
                 epsilon=1e-5):
        self._size = size
        self._epsilon = epsilon
        super(BatchNorm, self).__init__(name)

    @property
    def size(self):
        return self._size

    @property
    def input_size(self):
        return self._size

    @property
    def output_size(self):
        return self._size

    @property
    def epsilon(self):
        return self._epsilon

    def _build(self):
        beta_init = tf.zeros(
            shape=self._size,
            dtype=settings.D_TYPE
        )
        gamma_init = tf.ones(
            shape=self._size,
            dtype=settings.D_TYPE
        )
        self._beta = tf.Variable(
            name='beta',
            initial_value=beta_init,
            dtype=settings.D_TYPE
        )
        self._gamma = tf.Variable(
            name='gamma',
            initial_value=gamma_init,
            dtype=settings.D_TYPE
        )

    def _setup(self, x):
        axes = tuple(range(len(x.get_shape()) - 1))
        mean, variance = tf.nn.moments(x=x, axes=axes)
        y = tf.nn.batch_normalization(
            x=x,
            mean=mean,
            variance=variance,
            offset=self._beta,
            scale=self._gamma,
            variance_epsilon=self._epsilon
        )
        return y

    @property
    def beta(self):
        return self._beta

    @property
    def gamma(self):
        return self._gamma


class SoftAttention(Widget):
    """Soft attention.

    The algorithm is described below:

        Sequence: S = {s_1, s_2, ..., s_n'}, in which s_i in R^n.
        Vector: v in R^m.
        Sequence weight: W, a k by n matrix.
        Vector weight: U, a k by m matrix.
        Omega, a k dimension vector.

        Attention sequence: A = {a_1, a_2, ..., a_n'}, in which a_i in R. A is computed as follow:
            a'_i = tanh(W @ c_i + U @ S)
            A = softmax(omega @ A')
        Attention context: AC = sum(A * C)
    """

    def __init__(self,
                 name,
                 seq_elem_size,
                 vec_size,
                 common_size,
                 seq_weight_initializer=initializers.GlorotUniform(),
                 context_weight_initializer=initializers.GlorotUniform(),
                 omega_initializer=initializers.GlorotUniform()):
        self._seq_elem_size = seq_elem_size
        self._vec_size = vec_size
        self._common_size = common_size
        self._seq_weight_initializer = seq_weight_initializer
        self._context_weight_initializer = context_weight_initializer
        self._omega_initializer = omega_initializer
        super(SoftAttention, self).__init__(name)

    @property
    def seq_elem_size(self):
        return self._seq_elem_size

    @property
    def vec_size(self):
        return self._vec_size

    @property
    def common_size(self):
        return self._common_size

    def _build(self):
        self._w = tf.Variable(
            self._seq_weight_initializer.build(
                shape=(self._seq_elem_size, self._common_size)
            ),
            dtype=settings.D_TYPE,
            name='w'
        )
        self._u = tf.Variable(
            self._context_weight_initializer.build(
                shape=(self._vec_size, self._common_size)
            ),
            dtype=settings.D_TYPE,
            name='u'
        )
        self._omega = tf.Variable(
            self._omega_initializer.build(
                shape=(self._common_size, 1)
            ),
            dtype=settings.D_TYPE,
            name='omega'
        )

    @property
    def w(self):
        return self._w

    @property
    def u(self):
        return self._u

    @property
    def omega(self):
        return self._omega

    def _setup(self, seq, vec, seq_length=None, activation=tf.nn.tanh):
        """Setup a soft attention mechanism for the given context sequence and state.
        The result is an attention context for the state.

        :param seq: The sequence tensor.
            Its shape is defined as (seq_length, batch_size, seq_elem_size).
        :param vec: The vector tensor.
            Its shape is defined as (batch_size, vec_size).
        :param seq_length: Sequence length tensor.
            Shape is define as (batch_size,)
        :param activation: The activation function.
            Default is tf.nn.tanh.
        :return: An attention context with shape (batch_size, seq_elem_size).
        """
        #
        # (batch_size, seq_length, seq_elem_size) -> (seq_length, batch_size, seq_elem_size)
        seq = operations.transpose_sequence(seq)
        #
        # (seq_length, batch_size, seq_elem_size) @ (seq_elem_size, common_size)
        # -> (seq_length, batch_size, common_size)
        a = tf.tensordot(seq, self._w, ((2,), (0,)))
        #
        # (batch_size, vec_size) @ (vec_size, common_size)
        # -> (batch_size, common_size)
        # -> (1, batch_size, common_size)
        b = tf.matmul(vec, self._u)
        b = tf.reshape(b, (1, -1, self._common_size))
        #
        # -> (seq_length, batch_size, common_size)
        # (seq_length, batch_size, common_size) @ (common_size, 1)
        # -> (seq_length, batch_size, 1)
        a = activation(a + b) if activation is not None else a + b
        a = tf.tensordot(a, self._omega, ((2,), (0,)))
        if seq_length is None:
            a = tf.nn.softmax(a, dim=0)
        else:
            m = tf.sequence_mask(seq_length, dtype=settings.D_TYPE)  # (batch_size, seq_length)
            m_shape = tf.shape(m)
            m = tf.reshape(tf.transpose(m), (m_shape[1], m_shape[0], 1))
            s = tf.exp(a)
            a = s / tf.reduce_sum(s * m, axis=0, keep_dims=True)
        #
        # (seq_length, batch_size, 1) * (seq_length, batch_size, seq_elem_size)
        # -> (seq_length, batch_size, seq_elem_size)
        # -> (batch_size, seq_elem_size)
        att_context = tf.reduce_sum(a * seq, 0)
        return att_context


class Gate(Widget):

    def __init__(self,
                 name,
                 input_sizes,
                 output_size,
                 w_init=initializers.TruncatedNormal(0.0, 1e-3),
                 b_init=initializers.Zeros()):
        if not isinstance(input_sizes, (tuple, list)):
            input_sizes = (input_sizes,)
        self._input_sizes = input_sizes
        self._output_size = output_size
        self._w_init = w_init
        self._b_init = b_init
        super(Gate, self).__init__(name)

    def _build(self):
        self._w_list = list()
        for i, input_size in enumerate(self._input_sizes):
            w_init = self._w_init.build((input_size, self._output_size), name='w_%d_init' % i)
            w = variable('w_%d' % i, w_init)
            self._w_list.append(w)
        self._b = variable('b', self._b_init.build((self._output_size,), name='b_init'))

    def _setup(self, *x_list):
        if len(x_list) != len(self._w_list):
            raise ValueError()
        y = None
        for i, x in enumerate(x_list):
            if y is None:
                y = tf.matmul(x, self._w_list[i])
            else:
                y += tf.matmul(x, self._w_list[i])
        y += self._b
        y = tf.nn.sigmoid(y)
        return y
